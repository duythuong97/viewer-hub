"""Import a .sapack safely: no zip slip, no zip bomb, only data file types, checksums verified."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import time
import zipfile
from pathlib import Path, PurePosixPath

from viewer_hub.core.db import HubDB
from viewer_hub.core.paths import HubPaths

FORMATS = {1}
ALLOWED_SUFFIXES = {".json", ".sqlite", ".csv", ".md", ".markdown", ".html", ".css", ".js", ".png", ".jpg", ".jpeg",
                    ".gif", ".svg", ".webp", ".woff", ".woff2", ".txt", ".yml", ".yaml", ".map", ".xml", ".ico", ".pdf"}
MAX_TOTAL = 20 * 1024 ** 3
MAX_RATIO = 200
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_VERSION = re.compile(r"^[0-9A-Za-z.\-_]{1,40}$")
RESERVED_IDS = {"local"}  # "local" is the dev folder <home>/codemap in the code-map viewer


class PackError(ValueError):
    pass


def _check_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    total, members = 0, []
    for info in archive.infolist():
        name = info.filename
        parts = PurePosixPath(name).parts
        if name.startswith(("/", "\\")) or "\\" in name or any(p in ("..", "") for p in parts) or ":" in name:
            raise PackError(f"Đường dẫn không hợp lệ trong pack: {name}")
        if info.is_dir():
            continue
        if PurePosixPath(name).suffix.lower() not in ALLOWED_SUFFIXES:
            raise PackError(f"Pack chứa loại file không cho phép: {name}")
        total += info.file_size
        if total > MAX_TOTAL:
            raise PackError("Pack quá lớn sau khi giải nén.")
        if info.compress_size and info.file_size / info.compress_size > MAX_RATIO and info.file_size > 50 * 1024 * 1024:
            raise PackError(f"Tỉ lệ nén bất thường: {name}")
        members.append(info)
    return members


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_manifest(manifest: dict) -> None:
    if manifest.get("format") not in FORMATS:
        raise PackError(f"Định dạng pack {manifest.get('format')} không được hỗ trợ (cần {sorted(FORMATS)}).")
    if not _ID.match(str(manifest.get("id", ""))):
        raise PackError("pack.json: id không hợp lệ")
    if "--" in manifest["id"]:
        raise PackError("pack.json: id không được chứa '--'")
    if manifest["id"] in RESERVED_IDS:
        raise PackError(f"pack.json: id '{manifest['id']}' được dành riêng, hãy đặt id khác")
    if not _VERSION.match(str(manifest.get("version", ""))):
        raise PackError("pack.json: version không hợp lệ")
    if not isinstance(manifest.get("components"), dict):
        raise PackError("pack.json: thiếu components")


def version_key(version: str) -> tuple:
    """Natural order: 2026.11.13-fk < 2026.11.14 < 2026.12.1, 1.10 > 1.9."""
    return tuple((0, int(part), "") if part.isdigit() else (1, 0, part) for part in re.findall(r"\d+|[A-Za-z]+", version))


def active_version(db: HubDB, pack_id: str) -> str | None:
    row = db.one("SELECT version FROM packs WHERE id = ? AND active = 1", (pack_id,))
    return row["version"] if row else None


def import_pack(paths: HubPaths, db: HubDB, file: Path, activate: bool | str = "auto") -> dict:
    """Unpack a .sapack into packs/<id>/<version>/ and register it.

    Never touches user data (workspace/, user/, config): a pack only adds a new version folder.
    ``activate``: True / False, or "auto" = only when it is not older than the version in use,
    so an old pack (for example one bundled in an older release) never replaces newer data.
    The result has ``activated`` and, when it was kept inactive, ``reason``.
    """
    if db.readonly:
        raise PackError("Dữ liệu đang ở chế độ chỉ đọc, chưa import được pack.")
    paths.ensure()
    with zipfile.ZipFile(file) as archive:
        members = _check_members(archive)
        try:
            manifest = json.loads(archive.read("pack.json").decode("utf-8"))
        except KeyError:
            raise PackError("Thiếu pack.json") from None
        validate_manifest(manifest)
        pack_id, version = manifest["id"], manifest["version"]
        if db.one("SELECT 1 FROM packs WHERE id = ? AND version = ?", (pack_id, version)):
            raise PackError(f"Đã có {pack_id} {version}")
        target = paths.packs / pack_id / version
        if target.exists():
            # Left by an import that stopped before registering: pack data only, safe to replace.
            shutil.rmtree(target, ignore_errors=True)
        work = paths.tmp / f"pack-{pack_id}-{int(time.time() * 1000)}"
        work.mkdir(parents=True)
        try:
            for info in members:
                destination = work.joinpath(*PurePosixPath(info.filename).parts)
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, open(destination, "wb") as out:
                    shutil.copyfileobj(source, out, 1024 * 1024)
            for relative, expected in (manifest.get("sha256") or {}).items():
                member = work.joinpath(*PurePosixPath(relative).parts)
                if not member.is_file() or _sha256(member) != expected:
                    raise PackError(f"Sai checksum: {relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            work.rename(target)
        except BaseException:
            shutil.rmtree(work, ignore_errors=True)
            raise
    current = active_version(db, pack_id)
    reason = None
    if activate == "auto":
        activate = current is None or version_key(version) >= version_key(current)
        if not activate:
            reason = f"Bản {version} cũ hơn bản đang dùng {current}: đã nạp nhưng chưa bật."
    try:
        register(db, manifest, bool(activate))
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)  # never leave an unregistered version behind
        raise
    return {**manifest, "activated": bool(activate), "previous": current, "reason": reason}


def register(db: HubDB, manifest: dict, activate: bool) -> None:
    with db.write() as conn:
        if activate:
            conn.execute("UPDATE packs SET active = 0 WHERE id = ?", (manifest["id"],))
        conn.execute(
            """INSERT OR REPLACE INTO packs (id, version, title, format, components, imported_at, active)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (manifest["id"], manifest["version"], manifest.get("title") or manifest["id"], manifest["format"],
             json.dumps(manifest["components"], ensure_ascii=False), time.strftime("%Y-%m-%dT%H:%M:%S%z"), 1 if activate else 0),
        )


def set_active(db: HubDB, paths: HubPaths, pack_id: str, version: str) -> None:
    """Switch which version of a pack is used (roll back or forward). User data is not touched."""
    if not db.one("SELECT 1 FROM packs WHERE id = ? AND version = ?", (pack_id, version)):
        raise PackError(f"Không có {pack_id} {version}")
    if not (paths.packs / pack_id / version).is_dir():
        raise PackError(f"Thiếu thư mục dữ liệu của {pack_id} {version}; hãy import lại file .sapack.")
    with db.write() as conn:
        conn.execute("UPDATE packs SET active = 0 WHERE id = ?", (pack_id,))
        conn.execute("UPDATE packs SET active = 1 WHERE id = ? AND version = ?", (pack_id, version))
