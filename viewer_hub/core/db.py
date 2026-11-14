"""hub.db: the registry of packs, CSV datasets and docs sites (design.md §7.2).

Every row here is also recorded in a JSON file next to its data
(dataset.json, site.json, pack.json) so ``repair`` can rebuild hub.db.
"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


def connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        db = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, check_same_thread=False, isolation_level=None)
    else:
        db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=NORMAL")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


class HubDB:
    """One connection, serialised: hub.db is small and written rarely."""

    def __init__(self, path: Path, *, readonly: bool = False):
        self.path = path
        self.readonly = readonly
        self._db = connect(path, readonly=readonly)
        self._lock = threading.RLock()

    @property
    def schema_version(self) -> int:
        return int(self._db.execute("PRAGMA user_version").fetchone()[0])

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._db.execute(sql, params).fetchone()

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        if self.readonly:
            raise ReadOnlyError("The data dir is open read-only (see the banner on the home page).")
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                yield self._db
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def setting(self, key: str, default: str = "") -> str:
        """A value from the settings table (key/value strings); ``default`` when unset or empty."""
        row = self.one("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row and row["value"] else default

    def set_setting(self, key: str, value: str) -> None:
        with self.write() as db:
            db.execute("INSERT INTO settings(key, value) VALUES (?, ?) "
                       "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))

    def raw(self) -> sqlite3.Connection:
        return self._db

    def close(self) -> None:
        with self._lock:
            self._db.close()


class ReadOnlyError(RuntimeError):
    pass
