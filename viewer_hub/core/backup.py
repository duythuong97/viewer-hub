"""Backups of user source data (design.md §4).

Backed up: hub.db, every knowledge.sqlite under user/, config.yaml, every
dataset.json and site.json. Not backed up: uploaded source files (migrations
never rewrite them), derived data (rebuilt), packs (immutable, re-importable).
"""
from __future__ import annotations

import shutil
import sqlite3
import time
from pathlib import Path

from viewer_hub.core.atomic import write_json
from viewer_hub.core.paths import HubPaths

KEEP = 5
MANIFEST = "backup.json"


def _sqlite_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"{source.as_uri()}?mode=ro", uri=True)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)  # consistent copy even while the app has the file open
    finally:
        dst.close()
        src.close()


def _members(paths: HubPaths) -> list[tuple[Path, str]]:
    """(absolute file, kind) for everything a backup holds."""
    out: list[tuple[Path, str]] = []
    if paths.db.is_file():
        out.append((paths.db, "sqlite"))
    out.extend((p, "sqlite") for p in sorted(paths.user.rglob("*.sqlite")))
    if paths.config.is_file():
        out.append((paths.config, "file"))
    for name in ("dataset.json", "site.json"):
        out.extend((p, "file") for p in sorted(paths.workspace.rglob(name)))
    return out


def create(paths: HubPaths, reason: str, app_version: str) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    folder = paths.backups / f"{stamp}-{reason}"
    suffix = 1
    while folder.exists():
        suffix += 1
        folder = paths.backups / f"{stamp}-{reason}-{suffix}"
    work = paths.tmp / f"backup-{stamp}"
    work.mkdir(parents=True, exist_ok=True)
    files = []
    for source, kind in _members(paths):
        relative = source.relative_to(paths.home)
        target = work / relative
        if kind == "sqlite":
            _sqlite_copy(source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        files.append(relative.as_posix())
    write_json(work / MANIFEST, {"reason": reason, "appVersion": app_version, "createdAt": stamp, "files": files})
    folder.parent.mkdir(parents=True, exist_ok=True)
    work.rename(folder)
    prune(paths)
    return folder


def list_backups(paths: HubPaths) -> list[Path]:
    if not paths.backups.is_dir():
        return []
    return sorted((p for p in paths.backups.iterdir() if (p / MANIFEST).is_file()), reverse=True)


def prune(paths: HubPaths, keep: int = KEEP) -> None:
    for old in list_backups(paths)[keep:]:
        shutil.rmtree(old, ignore_errors=True)


def restore(paths: HubPaths, folder: Path, app_version: str) -> Path:
    """Put a backup back. The current state is backed up first, so restore can be undone."""
    import json

    manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    safety = create(paths, "before-restore", app_version)
    for relative in manifest["files"]:
        source = folder / relative
        target = paths.home / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.suffix in {".db", ".sqlite"}:
            for side in (target.with_name(target.name + "-wal"), target.with_name(target.name + "-shm")):
                side.unlink(missing_ok=True)
        shutil.copy2(source, target)
    return safety
