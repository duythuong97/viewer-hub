"""Install and remove addons (docs/addons.md §3, §7): a zip holding addon.json at its root or in its one top folder, laid
out as docs/addons.md §2 (the package root holds only addon.json, GUIDE.md, signature.json, ui/, app/, assets/, legal/).

Install = check the zip (safe names, bounded size), unpack into tmp/, check addon.json, the signature and the
security rules (core/scan.py), how it fits the addons already installed (deps.py: ``uses`` / ``exports``), then swap
it into ``<data>/addons/<id>/`` in one rename. Its data (``<data>/user/addons/<id>/``) is never touched, so an update
or a reinstall keeps it. The caller stops a running addon first (registry.py).

A compatibility warning (deps.Issue WARN) stops the install until the admin accepts it by its key (``accept``); a
BLOCK always stops it. ``stage`` keeps an uploaded zip for that second request (routes.py).
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

from viewer_hub.addons import deps, signature
from viewer_hub.addons.builtin import with_builtin
from viewer_hub.addons.manifest import MANIFEST, Addon, AddonError, load, parse
from viewer_hub.core import atomic
from viewer_hub.core.paths import HubPaths
from viewer_hub.core.scan import layout_errors, scan_addon

logger = logging.getLogger(__name__)

MAX_UNPACKED = 512 * 1024 * 1024
MAX_FILES = 20000
MAX_RATIO = 200  # one member may not inflate more than this (zip bomb)
# Names Windows cannot hold (a device: CON, NUL… with any extension; trailing dot or space; these characters).
_WINDOWS_DEVICE = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$", re.IGNORECASE)
_WINDOWS_BAD = re.compile(r'[<>"|?*\x00-\x1f]')
# Pages and API of the Hub itself: an addon id may not take one (nor a builtin module's key, reserved_ids).
# call / staged / contracts: /api/addons/<that>/… are the Hub's own routes (routes.py), not an addon's.
RESERVED_PAGES = {"premium", "settings", "help", "api", "sdk", "static", "x", "call", "staged", "contracts"}
BUILTIN_COMMANDS = {"codemap", "search", "csv", "monitor"}  # viewer-hub mcp <command> of builtin modules


def reserved_ids() -> set[str]:
    from viewer_hub.app.modules import all_modules

    return {m.key for m in all_modules()} | RESERVED_PAGES


STAGE_TTL = 15 * 60  # seconds an uploaded zip waits for the admin to accept its warnings


@dataclass
class Installed:
    addon: Addon
    trust: str                       # "signed" | "unsigned"
    notes: list[str] = field(default_factory=list)
    replaced: str = ""               # version it replaced, if any
    issues: list[deps.Issue] = field(default_factory=list)  # how it fits the other addons (deps.check_install)


class NeedsReview(AddonError):
    """The zip is fine on its own but conflicts with installed addons: ``issues`` lists what stops it."""

    def __init__(self, result: Installed, stopping: list[deps.Issue]) -> None:
        blocks = [i for i in stopping if i.level == deps.BLOCK]
        head = blocks or stopping
        super().__init__("; ".join(i.message for i in head[:3]) + (" …" if len(head) > 3 else ""))
        self.result = result
        self.stopping = stopping

    @property
    def blocked(self) -> bool:
        return any(i.level == deps.BLOCK for i in self.stopping)


def installed_addons(paths: HubPaths) -> dict[str, Addon]:
    """Every addon in ``<data>/addons`` whose addon.json loads (a broken one counts as not installed)."""
    found: dict[str, Addon] = {}
    for manifest in sorted(paths.addons.glob("*/" + MANIFEST)) if paths.addons.is_dir() else []:
        try:
            addon = load(manifest.parent)
        except (AddonError, OSError):
            continue
        found[addon.id] = addon
    return found


def version_key(version: str) -> tuple:
    return tuple(int(part) if part.isdigit() else 0 for part in version.replace("-", ".").split("."))


# Files that are not part of an addon wherever they appear (Finder / editor leftovers); everything else in the zip is the
# package and must follow its layout (core/scan.py layout_errors).
JUNK_ANY = {"__pycache__", "__MACOSX"}


def _junk(rel: str) -> bool:
    parts = PurePosixPath(rel).parts
    return any(part in JUNK_ANY or part.startswith(".") for part in parts) or rel.endswith(".pyc")


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
        tops = {name.split("/", 1)[0] for name in names if not _junk(name.split("/", 1)[0])}
        if len(tops) != 1 or f"{next(iter(tops))}/{MANIFEST}" not in names:
            if not any(name.rsplit("/", 1)[-1] == MANIFEST for name in names):
                raise AddonError(f"đây không phải zip addon (không có {MANIFEST}). Một zip chương trình thường phải được đóng "
                                 "thành addon trước (project addon: npm run zip)")
            raise AddonError(f"zip phải có {MANIFEST} ở gốc, hoặc đúng một thư mục gốc chứa {MANIFEST}")
        prefix = tops.pop() + "/"
    kept, total = [], 0
    for info in infos:
        if not info.filename.startswith(prefix) or info.is_dir():
            continue
        rel = info.filename[len(prefix):]
        if not rel or _junk(rel):
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
    layout = layout_errors(folder)
    if layout:
        raise AddonError("cấu trúc gói không đúng: " + "; ".join(layout[:8]) + (" …" if len(layout) > 8 else ""))
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


def _check_deps(paths: HubPaths, result: Installed, accept, premium_ok) -> None:
    result.issues = deps.check_install(result.addon, with_builtin(installed_addons(paths)), premium_ok)
    result.notes += [i.message for i in result.issues if i.level == deps.NOTE]
    stopping = [i for i in result.issues if i.level == deps.BLOCK] if accept is True \
        else deps.blocking(result.issues, accept or ())
    if stopping:
        raise NeedsReview(result, stopping)


def preview(paths: HubPaths, zip_path: Path, *, reserved: set[str] | None = None,
            premium_ok: Callable[[str], bool] = lambda _p: True) -> Installed:
    """Every check of install_zip, nothing installed: the result with its ``issues`` (AddonError: not installable)."""
    paths.tmp.mkdir(parents=True, exist_ok=True)
    work = paths.tmp / f"addon-{secrets.token_hex(6)}"
    try:
        result = check(unpack(zip_path, work))
        _check_place(paths, result, reserved_ids() if reserved is None else reserved)
        result.issues = deps.check_install(result.addon, with_builtin(installed_addons(paths)), premium_ok)
        return result
    finally:
        shutil.rmtree(work, ignore_errors=True)


def install_zip(paths: HubPaths, zip_path: Path, *, reserved: set[str] | None = None,
                before_swap: Callable[[Installed], None] | None = None, accept=(),
                premium_ok: Callable[[str], bool] = lambda _p: True) -> Installed:
    """Everything is checked before anything changes; ``before_swap`` (e.g. stop the running copy) runs only then,
    so a bad zip never stops the addon it would have replaced. ``accept``: keys of the compatibility warnings the
    admin accepted, or True for all of them (a BLOCK is never accepted); NeedsReview otherwise."""
    paths.tmp.mkdir(parents=True, exist_ok=True)
    work = paths.tmp / f"addon-{secrets.token_hex(6)}"
    try:
        folder = unpack(zip_path, work)
        result = check(folder)
        _check_place(paths, result, reserved_ids() if reserved is None else reserved)
        _check_deps(paths, result, accept, premium_ok)
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


def stage(paths: HubPaths, upload) -> tuple[str, Path]:
    """Keep an uploaded zip (``upload.save(path)``) under a random token for the second request; old ones expire."""
    import time

    paths.tmp.mkdir(parents=True, exist_ok=True)
    for old in paths.tmp.glob("addon-staged-*.zip"):
        try:
            if time.time() - old.stat().st_mtime > STAGE_TTL:
                old.unlink()
        except OSError:
            pass
    token = secrets.token_hex(12)
    path = paths.tmp / f"addon-staged-{token}.zip"
    upload.save(path)
    return token, path


def staged(paths: HubPaths, token: str) -> Path:
    import time

    if not re.fullmatch(r"[0-9a-f]{24}", token or ""):
        raise AddonError("mã tải lên không hợp lệ")
    path = paths.tmp / f"addon-staged-{token}.zip"
    try:
        fresh = time.time() - path.stat().st_mtime <= STAGE_TTL
    except OSError:
        fresh = False
    if not fresh:
        path.unlink(missing_ok=True)
        raise AddonError("file tải lên đã hết hạn (15 phút): chọn lại file .zip")
    return path


def uninstall(paths: HubPaths, addon_id: str, *, accept=True) -> None:
    """Remove the addon's code; its data (user/addons/<id>) stays for a later reinstall and in backups.
    ``accept``: keys of the warnings (deps.check_remove: addons that use it) accepted, or True."""
    target = paths.addons / addon_id
    if not target.is_dir() or target.parent != paths.addons:
        raise AddonError(f"không có addon {addon_id}")
    if accept is not True:
        others = {i: a for i, a in installed_addons(paths).items() if i != addon_id}
        stopping = deps.blocking(deps.check_remove(addon_id, others), accept)
        if stopping:
            raise AddonError("; ".join(i.message for i in stopping))
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


def _held_file(paths: HubPaths) -> Path:
    return paths.user / "addons-held.json"


def held_updates(paths: HubPaths) -> dict[str, str]:
    """Default addons not updated at the last start because the new copy would break others: {id: why}."""
    value = atomic.read_json(_held_file(paths), {})
    return {str(k): str(v) for k, v in value.items()} if isinstance(value, dict) else {}


def install_bundled(paths: HubPaths, folder: Path | None = None) -> list[str]:
    """Addon zips shipped in the release (<release>/addons/*.zip): installed on start when missing or newer than
    the installed one, so a new machine gets them from the release zip alone. One the user removed stays removed
    (removed_ids) until they install it by hand.

    Nobody is there to accept a warning, so (plan §4.3 O2): providers go first (deps.install_order); a zip that would
    break an installed addon that uses it is not installed and is named on the Settings page (held_updates); what it
    itself misses (a dependency not installed yet) does not hold it."""
    folder = folder or bundled_dir()
    removed = removed_ids(paths)
    done = []
    held: dict[str, str] = {}
    wanted_zips: dict[str, tuple[Addon, Path]] = {}
    for zip_path in sorted(folder.glob("*.zip")) if folder.is_dir() else []:
        try:
            wanted = peek(zip_path)
        except AddonError as exc:
            logger.error("bundled addon %s skipped: %s", zip_path.name, exc)
            continue
        wanted_zips[wanted.id] = (wanted, zip_path)
    for wanted in deps.install_order(a for a, _ in wanted_zips.values()):
        zip_path = wanted_zips[wanted.id][1]
        if wanted.id in removed:
            continue
        current = paths.addons / wanted.id
        try:
            if current.is_dir() and version_key(load(current).version) >= version_key(wanted.version):
                if (current / signature.FILE).is_file():
                    continue
                with zipfile.ZipFile(zip_path) as z:
                    if not any(PurePosixPath(name).name == signature.FILE for name in z.namelist()):
                        continue
        except AddonError:
            pass
        issues = deps.check_install(wanted, with_builtin(installed_addons(paths)))
        others = [i for i in issues if i.level == deps.WARN and i.code in ("dependent", "downgrade")]
        if others:
            held[wanted.id] = f"{wanted.name} {wanted.version}: " + "; ".join(i.message for i in others)
            logger.error("bundled addon %s held: %s", zip_path.name, held[wanted.id])
            continue
        try:
            result = install_zip(paths, zip_path, accept=True)
        except (AddonError, OSError) as exc:
            logger.error("bundled addon %s rejected: %s", zip_path.name, exc)
            continue
        done.append(f"{result.addon.name} {result.addon.version}")
    if held or _held_file(paths).is_file():
        paths.user.mkdir(parents=True, exist_ok=True)
        atomic.write_json(_held_file(paths), held)
    return done
