"""Forward-only migrations of hub.db and workspace files (design.md §8.3).

Files in viewer_hub/migrations/:
  NNNN_name.sql  run in one transaction
  NNNN_name.py   define ``migrate(db, paths)``; run in one transaction

Startup outcomes:
  user_version == HUB_SCHEMA  -> normal
  user_version <  HUB_SCHEMA  -> backup, migrate one by one, normal
  user_version >  HUB_SCHEMA  -> data written by a newer app: read-only, nothing is written
  a migration fails           -> roll back, restore the backup, read-only with the error
"""
from __future__ import annotations

import importlib
import logging
import re
import sqlite3
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from viewer_hub import __version__
from viewer_hub.core import backup
from viewer_hub.core.db import HubDB
from viewer_hub.core.paths import HubPaths

logger = logging.getLogger(__name__)
_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.(sql|py)$")


@dataclass(frozen=True)
class Migration:
    number: int
    name: str
    kind: str  # "sql" | "py"


def available() -> list[Migration]:
    found = []
    for entry in resources.files("viewer_hub.migrations").iterdir():
        match = _NAME.match(entry.name)
        if match:
            found.append(Migration(int(match.group(1)), entry.name, match.group(2)))
    found.sort(key=lambda m: m.number)
    numbers = [m.number for m in found]
    if numbers != list(range(1, len(numbers) + 1)):
        raise RuntimeError(f"Migrations must be numbered 0001.. without gaps: {numbers}")
    return found


def hub_schema() -> int:
    """The schema this app writes: the last migration's number."""
    return available()[-1].number


@dataclass
class StartupState:
    db: HubDB
    readonly: bool = False
    reason: str | None = None  # shown as a banner when read-only
    migrated_from: int | None = None
    backup_path: Path | None = None


def _run(db: sqlite3.Connection, migration: Migration, paths: HubPaths) -> None:
    package = resources.files("viewer_hub.migrations")
    db.execute("BEGIN IMMEDIATE")
    try:
        if migration.kind == "sql":
            for statement in _split_sql(package.joinpath(migration.name).read_text(encoding="utf-8")):
                db.execute(statement)
        else:
            module = importlib.import_module(f"viewer_hub.migrations.{migration.name[:-3]}")
            module.migrate(db, paths)
        db.execute(f"PRAGMA user_version = {migration.number}")
        db.execute("COMMIT")
    except BaseException:
        db.execute("ROLLBACK")
        raise


def _split_sql(text: str) -> list[str]:
    lines = [line for line in text.splitlines() if not line.strip().startswith("--")]
    return [part.strip() for part in "\n".join(lines).split(";") if part.strip()]


def open_hub(paths: HubPaths) -> StartupState:
    paths.ensure()
    target = hub_schema()
    db = HubDB(paths.db)
    current = db.schema_version

    if current > target:
        db.close()
        return StartupState(
            HubDB(paths.db, readonly=True),
            readonly=True,
            reason=f"Dữ liệu được tạo bởi phiên bản mới hơn (schema {current} > {target}). Đang mở chỉ đọc.",
        )
    if current == target:
        return StartupState(db)

    saved = backup.create(paths, f"from-schema-{current}", __version__) if current > 0 else None
    try:
        for migration in available():
            if migration.number > current:
                logger.info("migration %s", migration.name)
                _run(db.raw(), migration, paths)
    except Exception as exc:  # restore and open read-only, never leave data half migrated
        logger.exception("migration failed")
        db.close()
        if saved:
            backup.restore(paths, saved, __version__)
        return StartupState(
            HubDB(paths.db, readonly=True),
            readonly=True,
            reason=f"Nâng cấp dữ liệu thất bại: {exc}. Đã khôi phục bản sao lưu {saved.name if saved else ''}; đang mở chỉ đọc.",
            backup_path=saved,
        )
    return StartupState(db, migrated_from=current, backup_path=saved)
