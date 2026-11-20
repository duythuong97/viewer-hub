"""Keep the Copilot skills of this Hub in the user's project folders (Settings → Dùng với GitHub Copilot).

The user lists folders (their repos); on every Hub start, and when the list is saved, each folder gets
``.github/skills/<server>/SKILL.md`` for every MCP server this machine runs (``mcp_export.skill``). Only skills the
Hub wrote are touched: a skill folder is the Hub's when its SKILL.md carries ``MARKER``. A skill that is no longer
offered (an addon removed, a premium feature locked again) is removed; the user's own skills are never read or changed.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

from viewer_hub.app import mcp_export
from viewer_hub.core import atomic

FOLDERS_KEY = "copilot_folders"
STATUS_KEY = "copilot_sync"
MAX_FOLDERS = 20
SKILLS_DIR = Path(".github") / "skills"
MARKER = mcp_export.MARKER


class FolderError(ValueError):
    pass


def folders(db) -> list[str]:
    try:
        value = json.loads(db.setting(FOLDERS_KEY, "[]"))
    except ValueError:
        return []
    return [str(item) for item in value if isinstance(item, str)] if isinstance(value, list) else []


def statuses(db) -> dict[str, dict]:
    try:
        value = json.loads(db.setting(STATUS_KEY, "{}"))
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def clean(values) -> list[str]:
    """Absolute paths of existing folders, without duplicates; FolderError names the first bad one."""
    if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
        raise FolderError("Danh sách folder không hợp lệ")
    result: list[str] = []
    for raw in values:
        text = raw.strip().strip('"')
        if not text:
            continue
        path = Path(text).expanduser()
        if not path.is_absolute():
            raise FolderError(f"Cần đường dẫn đầy đủ: {text}")
        if not path.is_dir():
            raise FolderError(f"Không có folder: {text}")
        resolved = str(path.resolve())
        if resolved not in result:
            result.append(resolved)
    if len(result) > MAX_FOLDERS:
        raise FolderError(f"Tối đa {MAX_FOLDERS} folder")
    return result


def sync_folder(folder: Path, skills: dict[str, str]) -> dict:
    """Write ``skills`` (name → SKILL.md text) into ``folder/.github/skills``; remove the Hub's skills not in it."""
    target = folder / SKILLS_DIR
    written, removed = [], []
    for name, text in skills.items():
        path = target / name / "SKILL.md"
        try:
            current = path.read_text(encoding="utf-8")
        except OSError:
            current = None
        if current is not None and MARKER not in current:
            continue  # a skill of the same name the user wrote: theirs
        if current != text:
            atomic.write_text(path, text)
            written.append(name)
    if target.is_dir():
        for child in sorted(target.iterdir()):
            if child.name in skills or not child.is_dir():
                continue
            skill = child / "SKILL.md"
            try:
                ours = MARKER in skill.read_text(encoding="utf-8")
            except OSError:
                ours = False
            # Only a folder holding nothing but the Hub's SKILL.md goes.
            if ours and [item.name for item in child.iterdir()] == ["SKILL.md"]:
                shutil.rmtree(child)
                removed.append(child.name)
    return {"skills": len(skills), "written": written, "removed": removed}


def sync(db, modules, folder_list: list[str] | None = None) -> dict[str, dict]:
    """Sync every configured folder; the result per folder is also kept for the Settings page."""
    skills = mcp_export.skills(modules)
    now = datetime.now().isoformat(timespec="seconds")
    results: dict[str, dict] = {}
    for folder in folder_list if folder_list is not None else folders(db):
        path = Path(folder)
        if not path.is_dir():
            results[folder] = {"at": now, "error": "Không tìm thấy folder (đã xoá hoặc ổ đĩa chưa gắn)"}
            continue
        try:
            results[folder] = {"at": now, **sync_folder(path, skills)}
        except OSError as error:
            results[folder] = {"at": now, "error": f"Không ghi được: {error.strerror or error}"}
    if not db.readonly:
        db.set_setting(STATUS_KEY, json.dumps(results, ensure_ascii=False))
    return results


def sync_on_start(db, modules) -> None:
    """``sync`` for the start thread: a failure is logged, never raised into a dying thread."""
    import logging

    try:
        sync(db, modules)
    except Exception:  # noqa: BLE001 - the Hub runs on; the Settings page shows the last result
        logging.getLogger(__name__).exception("Copilot skills sync failed")
