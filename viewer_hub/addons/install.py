"""Install and remove addons (docs/addons.md §3, §7): a zip holding addon.json at its root or in its one top folder.

Install = check the zip (safe names, bounded size), unpack into tmp/, check addon.json, the signature and the
security rules (core/scan.py), then swap it into ``<data>/addons/<id>/`` in one rename. Its data
(``<data>/user/addons/<id>/``) is never touched, so an update or a reinstall keeps it. The caller stops a running
addon first (registry.py).
"""
from __future__ import annotations

import json
import logging
import re
import secrets
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable

from viewer_hub.addons import signature
from viewer_hub.addons.manifest import MANIFEST, Addon, AddonError, load, parse
from viewer_hub.core import atomic
from viewer_hub.core.paths import HubPaths
from viewer_hub.core.scan import scan_addon

logger = logging.getLogger(__name__)

MAX_UNPACKED = 512 * 1024 * 1024
MAX_FILES = 20000
MAX_RATIO = 200  # one member may not inflate more than this (zip bomb)
# Names Windows cannot hold (a device: CON, NUL… with any extension; trailing dot or space; these characters).
_WINDOWS_DEVICE = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$", re.IGNORECASE)
_WINDOWS_BAD = re.compile(r'[<>"|?*\x00-\x1f]')
# Pages and API of the Hub itself: an addon id may not take one (nor a builtin module's key, reserved_ids).
RESERVED_PAGES = {"premium", "settings", "help", "api", "sdk", "static", "x"}
BUILTIN_COMMANDS = {"codemap", "search", "csv", "monitor"}  # viewer-hub mcp <command> of builtin modules


def reserved_ids() -> set[str]:
    from viewer_hub.app.modules import all_modules

    return {m.key for m in all_modules()} | RESERVED_PAGES


@dataclass
class Installed:
    addon: Addon
    trust: str                       # "signed" | "unsigned"
    notes: list[str] = field(default_factory=list)
    replaced: str = ""               # version it replaced, if any


def version_key(version: str) -> tuple:
    return tuple(int(part) if part.isdigit() else 0 for part in version.replace("-", ".").split("."))


# Source folders of an addon project, never installed: a zip made by hand from the project folder (Explorer
# "Compressed folder", `zip -r`) carries them; dotfiles (.git, .DS_Store) too.
# Development files of an addon project (the SDK layout, kit/AGENTS.md §2): never installed, so the project folder
# itself can be zipped and uploaded. Keep in step with DEV_ROOT / DEV_ANY in kit/sdk/build.mjs (tests check).
DEV_ROOT = {"web", "src", "test", "tests", "dist", "node_modules", "AGENTS.md", "CLAUDE.md", "README.md",
            "package.json", "package-lock.json"}
DEV_ANY = {"node_modules", "__pycache__", "__MACOSX"}  # __MACOSX: Finder "Compress" metadata
SOURCE_DIRS = DEV_ROOT | DEV_ANY  # (older name, kept for callers)


def _source(rel: str) -> bool:
    """A development file (not installed): see DEV_ROOT / DEV_ANY; also dotfiles and .pyc anywhere."""
    parts = PurePosixPath(rel).parts
    if not parts:
        return False
    return (parts[0] in DEV_ROOT or any(part in DEV_ANY or part.startswith(".") for part in parts)
            or rel.endswith(".pyc"))


def _members(archive: zipfile.ZipFile) -> tuple[str, list[tuple[str, zipfile.ZipInfo]]]:
    """(prefix of the addon inside the zip, [(path in the addon, member)]) of the files to install.

    The addon is either the zip's root (addon.json at the top) or its only top folder (<any name>/addon.json)."""
    infos = archive.infolist()
    if not infos:
        raise AddonError("zip rỗng")
    seen: dict[str, str] = {}
    for info in infos:
        name = info.filename
        if name.startswith("/") or "\\" in name or ".." in PurePosixPath(name).parts or ":" in name:
            raise AddonError(f"tên file không an toàn trong zip: {name}")
        for part in PurePosixPath(name).parts:
            if _WINDOWS_DEVICE.match(part) or _WINDOWS_BAD.search(part) or part.endswith((".", " ")):
                raise AddonError(f"tên file không dùng được trên Windows: {name}")
        folded = name.rstrip("/").casefold()
        if folded in seen and seen[folded] != name.rstrip("/"):
            raise AddonError(f"hai file chỉ khác chữ hoa / thường (Windows coi là một): {seen[folded]}, {name}")
        seen[folded] = name.rstrip("/")
    names = {info.filename for info in infos}
    if MANIFEST in names:
        prefix = ""
    else:
        tops = {name.split("/", 1)[0] for name in names if not _source(name.split("/", 1)[0])}
        if len(tops) != 1 or f"{next(iter(tops))}/{MANIFEST}" not in names:
            if not any(name.rsplit("/", 1)[-1] == MANIFEST for name in names):
                raise AddonError(f"đây không phải zip addon (không có {MANIFEST}). Zip chương trình (vd. McpBridge-x.y.z.zip) "
                                 "phải được đóng thành addon trước (vd. my-bridge: npm run release → mcp-bridge-x.y.z.zip), "
                                 "hoặc viewer-hub addon pack <thư mục addon> --include <zip chương trình>")
            raise AddonError(f"zip phải có {MANIFEST} ở gốc, hoặc đúng một thư mục gốc chứa {MANIFEST}")
        prefix = tops.pop() + "/"
    kept, total = [], 0
    for info in infos:
        if not info.filename.startswith(prefix) or info.is_dir():
            continue
        rel = info.filename[len(prefix):]
        if not rel or _source(rel):
            continue
        if info.external_attr >> 16 & 0o170000 == 0o120000:
            raise AddonError(f"symlink trong zip: {info.filename}")
        total += info.file_size
        if info.file_size > 1024 * 1024 and info.file_size > MAX_RATIO * max(info.compress_size, 1):
            raise AddonError(f"file nén bất thường (zip bomb?): {info.filename}")
        kept.append((rel, info))
    if len(kept) > MAX_FILES:
        raise AddonError(f"quá nhiều file (hơn {MAX_FILES}); đừng nén kèm node_modules")
    if total > MAX_UNPACKED:
        raise AddonError("zip giải nén ra quá lớn")
    return prefix, kept


def _manifest(archive: zipfile.ZipFile, prefix: str) -> dict:
    try:
        return json.loads(archive.read(f"{prefix}{MANIFEST}").decode("utf-8"))
    except KeyError:
        raise AddonError(f"thiếu {prefix}{MANIFEST}") from None
    except ValueError as exc:
        raise AddonError(f"{MANIFEST} không phải JSON: {exc}") from exc


def peek(zip_path: Path) -> Addon:
    """The addon a zip holds (its addon.json, checked), without unpacking it."""
    try:
        with zipfile.ZipFile(zip_path) as archive:
            prefix, _ = _members(archive)
            return parse(_manifest(archive, prefix))
    except (OSError, zipfile.BadZipFile) as exc:
        raise AddonError(f"không đọc được zip: {exc}") from exc


def unpack(zip_path: Path, work: Path) -> Path:
    """The addon in the zip unpacked as ``work/<id>`` (source folders and dotfiles left out)."""
    try:
        archive = zipfile.ZipFile(zip_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise AddonError(f"không phải file zip: {exc}") from exc
    with archive:
        prefix, members = _members(archive)
        target = work / parse(_manifest(archive, prefix)).id
        for rel, info in members:
            dest = target.joinpath(*PurePosixPath(rel).parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, open(dest, "wb") as out:
                shutil.copyfileobj(source, out)
    return target


def check(folder: Path) -> Installed:
    """Manifest, signature and the security scan of an unpacked addon; AddonError lists what is wrong."""
    addon = load(folder)
    trust = signature.verify(folder, addon.id, addon.version)
    errors, notes = scan_addon(folder)
    if errors:
        raise AddonError("vi phạm quy tắc bảo mật: " + "; ".join(errors[:8]) + (" …" if len(errors) > 8 else ""))
    return Installed(addon, trust, notes + _guide_notes(folder, addon))


def _guide_notes(folder: Path, addon: Addon) -> list[str]:
    """What the user guide will miss (shown at install, not refused): GUIDE.md, a line for each MCP tool."""
    guide = folder / "GUIDE.md"
    if not guide.is_file():
        return ["thiếu GUIDE.md: trang Hướng dẫn không có phần của addon này"]
    text = guide.read_text(encoding="utf-8", errors="replace")
    missing = [t for t in (addon.mcp.tools if addon.mcp else ()) if f"`{t}`" not in text]
    return [f"GUIDE.md chưa mô tả tool: {', '.join(missing)}"] if missing else []


def _check_place(paths: HubPaths, result: Installed, reserved: set[str]) -> None:
    """Refuse what would clash with the Hub or weaken what is installed: a taken id or MCP command, a signed addon
    replaced by an unsigned zip (anyone can make one with the same id)."""
    addon = result.addon
    if addon.id in reserved:
        raise AddonError(f"id {addon.id} trùng một mục có sẵn của Viewer Hub; đổi id trong addon.json")
    if addon.mcp:
        taken = set(BUILTIN_COMMANDS)
        for other in paths.addons.glob("*/" + MANIFEST) if paths.addons.is_dir() else []:
            if other.parent.name == addon.id:
                continue
            try:
                command = (json.loads(other.read_text(encoding="utf-8")).get("mcp") or {}).get("command")
            except (OSError, ValueError, AttributeError):
                continue
            if command:
                taken.add(command)
        if addon.mcp.command in taken:
            raise AddonError(f"mcp.command {addon.mcp.command} đã được Viewer Hub hoặc addon khác dùng")
    current = paths.addons / addon.id
    if result.trust == "unsigned" and (current / signature.FILE).is_file():
        raise AddonError(f"bản {addon.id} đang cài có chữ ký, zip này chưa ký: không thay. Muốn dùng bản chưa ký thì gỡ "
                         "bản đang cài trước")


def install_zip(paths: HubPaths, zip_path: Path, *, reserved: set[str] | None = None,
                before_swap: Callable[[Installed], None] | None = None) -> Installed:
    """Everything is checked before anything changes; ``before_swap`` (e.g. stop the running copy) runs only then,
    so a bad zip never stops the addon it would have replaced."""
    paths.tmp.mkdir(parents=True, exist_ok=True)
    work = paths.tmp / f"addon-{secrets.token_hex(6)}"
    try:
        folder = unpack(zip_path, work)
        result = check(folder)
        _check_place(paths, result, reserved_ids() if reserved is None else reserved)
        if before_swap:
            before_swap(result)
        target = paths.addons / result.addon.id
        paths.addons.mkdir(parents=True, exist_ok=True)
        if target.exists():
            try:
                result.replaced = load(target).version
            except AddonError:
                result.replaced = "?"
            old = work / "old"
            target.rename(old)  # fails while a program still runs from it (Windows): the caller stops it first
        folder.rename(target)
        result.addon = load(target)
        paths.addon_data(result.addon.id).mkdir(parents=True, exist_ok=True)
        _mark_removed(paths, result.addon.id, False)  # installed by hand again: a default addon updates again
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)


def uninstall(paths: HubPaths, addon_id: str) -> None:
    """Remove the addon's code; its data (user/addons/<id>) stays for a later reinstall and in backups."""
    target = paths.addons / addon_id
    if not target.is_dir() or target.parent != paths.addons:
        raise AddonError(f"không có addon {addon_id}")
    trash = paths.tmp / f"removed-{addon_id}-{secrets.token_hex(4)}"
    paths.tmp.mkdir(parents=True, exist_ok=True)
    target.rename(trash)
    shutil.rmtree(trash, ignore_errors=True)
    _mark_removed(paths, addon_id, True)


def _removed_file(paths: HubPaths) -> Path:
    return paths.user / "addons-removed.json"


def removed_ids(paths: HubPaths) -> set[str]:
    """Addons the user removed: a default addon (install_bundled) is not put back on the next start."""
    value = atomic.read_json(_removed_file(paths), [])
    return {str(x) for x in value} if isinstance(value, list) else set()


def _mark_removed(paths: HubPaths, addon_id: str, removed: bool) -> None:
    ids = removed_ids(paths)
    if (addon_id in ids) == removed:
        return
    ids = ids | {addon_id} if removed else ids - {addon_id}
    paths.user.mkdir(parents=True, exist_ok=True)
    atomic.write_json(_removed_file(paths), sorted(ids))


def bundled_dir() -> Path:
    from viewer_hub.core.config import release_root

    return release_root() / "addons"


def install_bundled(paths: HubPaths, folder: Path | None = None) -> list[str]:
    """Addon zips shipped in the release (<release>/addons/*.zip): installed on start when missing or newer than
    the installed one, so a new machine gets them from the release zip alone. One the user removed stays removed
    (removed_ids) until they install it by hand."""
    folder = folder or bundled_dir()
    removed = removed_ids(paths)
    done = []
    for zip_path in sorted(folder.glob("*.zip")) if folder.is_dir() else []:
        try:
            wanted = peek(zip_path)
        except AddonError as exc:
            logger.error("bundled addon %s skipped: %s", zip_path.name, exc)
            continue
        if wanted.id in removed:
            continue
        current = paths.addons / wanted.id
        try:
            if current.is_dir() and version_key(load(current).version) >= version_key(wanted.version):
                continue
        except AddonError:
            pass
        try:
            result = install_zip(paths, zip_path)
        except (AddonError, OSError) as exc:
            logger.error("bundled addon %s rejected: %s", zip_path.name, exc)
            continue
        done.append(f"{result.addon.name} {result.addon.version}")
    return done
