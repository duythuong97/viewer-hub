"""Single instance per data dir (design.md §7.6).

An old and a new version must never write the same data dir at once, so the
lock covers every version. The lock itself is ``hub.lock``; who holds it
(pid, version, url) goes to ``hub.instance.json`` next to it, because Windows
cannot read a byte range another process has locked.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import IO

from viewer_hub.core.atomic import read_json, write_json


class AlreadyRunning(RuntimeError):
    def __init__(self, info: dict):
        super().__init__(f"Viewer Hub is already running (pid {info.get('pid', '?')}, {info.get('url', '')})")
        self.info = info


class InstanceLock:
    def __init__(self, path: Path):
        self.path = path
        self.info_path = path.with_name(path.stem + ".instance.json")
        self._handle: IO[bytes] | None = None

    def acquire(self, info: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")
        try:
            _lock(handle)
        except OSError:
            handle.close()
            raise AlreadyRunning(self.read()) from None
        self._handle = handle
        write_json(self.info_path, {**info, "pid": os.getpid(), "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z")})

    def update(self, **info) -> None:
        if self._handle:
            write_json(self.info_path, {**self.read(), **info})

    def read(self) -> dict:
        try:
            return read_json(self.info_path, {}) or {}
        except (OSError, ValueError):
            return {}

    def release(self) -> None:
        if not self._handle:
            return
        try:
            _unlock(self._handle)
        finally:
            self._handle.close()
            self._handle = None
            self.info_path.unlink(missing_ok=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.release()


if sys.platform == "win32":
    import msvcrt

    def _lock(handle) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)

    def _unlock(handle) -> None:
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _lock(handle) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(handle) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
