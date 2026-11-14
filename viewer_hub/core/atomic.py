"""Atomic file writes (design.md §7.5): write to tmp/, fsync, then os.replace()."""
from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any


def write_bytes(target: Path, data: bytes, tmp_dir: Path | None = None) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    # Same folder as the target keeps os.replace() on one volume (atomic on Windows and POSIX).
    tmp = (tmp_dir or target.parent) / f".{target.name}.{secrets.token_hex(4)}.tmp"
    try:
        with open(tmp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    finally:
        tmp.unlink(missing_ok=True)


def write_text(target: Path, text: str) -> None:
    write_bytes(target, text.encode("utf-8"))


def write_json(target: Path, value: Any) -> None:
    write_text(target, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
