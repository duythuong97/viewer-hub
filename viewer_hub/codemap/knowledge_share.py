"""Share what people wrote about a code-map pack: one JSON file out, merged into someone else's knowledge db.

Exported: business tree edits, flow documents, rules, decisions, questions, node notes, term mappings and
hand-made links. Not exported: MCP call logs and AI export ids (local history), knowledge_meta.

Import never deletes. Rows the receiver does not have are added; for rows both sides have and that differ,
``mode`` decides:

* ``newer`` (default) — the one changed last wins (``updated_at``);
* ``mine`` — keep the receiver's row, only add what is new;
* ``theirs`` — take the file's row.

The receiver's knowledge db is copied to ``backups/`` next to it before anything is written.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from viewer_hub.codemap.business import BusinessError, GraphIndex, apply_links

FORMAT = "viewer-hub/codemap-knowledge"
VERSION = 1
MODES = ("newer", "mine", "theirs")
MAX_ROWS = 200_000
KEEP_BACKUPS = 10


class Table:
    def __init__(self, name: str, key: tuple[str, ...], stamp: tuple[str, ...], label: str, title: str, *,
                 drop: tuple[str, ...] = (), local: tuple[str, ...] = ()) -> None:
        # key: what identifies "the same row" on two machines; stamp: when it last changed (first non-empty);
        # drop: local ids never copied (autoincrement); local: ids copied for a new row but never compared or updated.
        self.name, self.key, self.stamp, self.label, self.title = name, key, stamp, label, title
        self.drop, self.local = drop, local

    def changed_at(self, row: dict[str, Any]) -> str:
        return next((str(row[column]) for column in self.stamp if row.get(column)), "")


TABLES = (
    Table("biz_items", ("item_id",), ("updated_at",), "Tên / mô tả menu và tính năng", "name"),
    Table("biz_flows", ("flow_id",), ("updated_at",), "Tài liệu luồng", "flow_id"),
    Table("biz_rules", ("rule_id",), ("updated_at",), "Quy tắc nghiệp vụ", "title"),
    Table("biz_decisions", ("decision_id",), ("updated_at",), "Quyết định", "title"),
    Table("biz_questions", ("question_id",), ("answered_at", "created_at"), "Câu hỏi", "text"),
    Table("graph_knowledge", ("target_id", "body"), ("updated_at",), "Ghi chú trên node", "target_id", drop=("knowledge_id",)),
    Table("semantic_mappings", ("target_id",), ("updated_at",), "Gán thuật ngữ", "target_id"),
    Table("biz_links", ("source_id", "target_id", "edge_type"), ("updated_at",), "Liên kết tay", "source_ref", local=("link_id",)),
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _columns(db: sqlite3.Connection, table: str) -> list[str]:
    return [row[1] for row in db.execute(f"PRAGMA kn.table_info({table})")]


def export_knowledge(db: sqlite3.Connection, pack: dict[str, str], graph_hash: str, who: str) -> dict[str, Any]:
    tables: dict[str, list[dict[str, Any]]] = {}
    for table in TABLES:
        columns = [column for column in _columns(db, table.name) if column not in table.drop]
        rows = db.execute(f"SELECT {','.join(columns)} FROM kn.{table.name} ORDER BY {','.join(table.key)}").fetchall()
        tables[table.name] = [dict(zip(columns, row)) for row in rows]
    return {
        "format": FORMAT, "version": VERSION, "pack": pack, "graph_hash": graph_hash,
        "exported_at": _now(), "exported_by": who,
        "counts": {name: len(rows) for name, rows in tables.items()},
        "tables": tables,
    }


def _parse(data: Any) -> dict[str, Any]:
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError as exc:
            raise BusinessError("invalid_knowledge", "File không phải JSON hợp lệ") from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise BusinessError("invalid_knowledge", "Không phải file knowledge của Code Map (.codemap-knowledge.json)")
    if data.get("version") != VERSION:
        raise BusinessError("invalid_knowledge", f"File knowledge phiên bản {data.get('version')!r}; bản này đọc được phiên bản {VERSION}")
    tables = data.get("tables")
    if not isinstance(tables, dict):
        raise BusinessError("invalid_knowledge", "File thiếu phần tables")
    if sum(len(rows) for rows in tables.values() if isinstance(rows, list)) > MAX_ROWS:
        raise BusinessError("invalid_knowledge", f"File có hơn {MAX_ROWS} dòng")
    return data


def _clean(row: Any, columns: set[str]) -> dict[str, Any] | None:
    """Only known columns and plain values; anything else in the file is ignored."""
    if not isinstance(row, dict):
        return None
    out = {key: value for key, value in row.items()
           if key in columns and (value is None or isinstance(value, (str, int, float)) and not isinstance(value, bool))}
    return out


def _plan(db: sqlite3.Connection, data: dict[str, Any], mode: str) -> tuple[dict[str, dict[str, Any]], dict[str, list]]:
    """What an import would do, per table: counts, a few names of each kind, and the rows to write."""
    summary: dict[str, dict[str, Any]] = {}
    writes: dict[str, list] = {}
    for table in TABLES:
        columns = [column for column in _columns(db, table.name) if column not in table.drop]
        allowed = set(columns)
        incoming = data["tables"].get(table.name)
        incoming = incoming if isinstance(incoming, list) else []
        stats = {"label": table.label, "new": 0, "same": 0, "changed": 0, "take": 0, "keep": 0, "invalid": 0, "examples": []}
        rows_to_write = []
        for raw in incoming:
            row = _clean(raw, allowed)
            if not row or any(row.get(key) in (None, "") for key in table.key):
                stats["invalid"] += 1
                continue
            where = " AND ".join(f"{key}=?" for key in table.key)
            local = db.execute(f"SELECT {','.join(columns)} FROM kn.{table.name} WHERE {where}",
                               [row[key] for key in table.key]).fetchone()
            if local is None:
                stats["new"] += 1
                rows_to_write.append(("insert", row))
                continue
            local = dict(zip(columns, local))
            if all(local.get(key) == row.get(key) for key in row if key not in table.local):
                stats["same"] += 1
                continue
            stats["changed"] += 1
            take = mode == "theirs" or (mode == "newer" and table.changed_at(row) > table.changed_at(local))
            if take:
                stats["take"] += 1
                rows_to_write.append(("update", row))
            else:
                stats["keep"] += 1
            if len(stats["examples"]) < 5:
                stats["examples"].append({"name": str(row.get(table.title) or "")[:120], "take": take,
                                          "mine": table.changed_at(local), "theirs": table.changed_at(row)})
        summary[table.name] = stats
        writes[table.name] = rows_to_write
    return summary, writes


def check_import(db: sqlite3.Connection, data: Any, mode: str, pack_id: str) -> dict[str, Any]:
    if mode not in MODES:
        raise BusinessError("invalid_knowledge", f"mode phải là một trong {', '.join(MODES)}")
    data = _parse(data)
    summary, _ = _plan(db, data, mode)
    warnings = []
    source = data.get("pack") if isinstance(data.get("pack"), dict) else {}
    if source.get("id") and source.get("id") != pack_id:
        warnings.append(f"File xuất từ pack “{source.get('id')}”, đang nhập vào pack “{pack_id}”. Chỉ những node có cùng id mới khớp.")
    writes = sum(stats["new"] + stats["take"] for stats in summary.values())
    return {"ok": writes > 0, "from": {"pack": source, "exported_at": data.get("exported_at"), "exported_by": data.get("exported_by")},
            "tables": summary, "writes": writes, "warnings": warnings}


def backup(knowledge: Path) -> Path:
    folder = knowledge.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"knowledge-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.sqlite"
    # A separate connection: VACUUM INTO on the request's connection trips over its temp views of the same names.
    with closing(sqlite3.connect(knowledge)) as source, closing(sqlite3.connect(target)) as copy:
        source.backup(copy)
    for old in sorted(folder.glob("knowledge-*.sqlite"))[:-KEEP_BACKUPS]:
        old.unlink(missing_ok=True)
    return target


def apply_import(db: sqlite3.Connection, index: GraphIndex | None, data: Any, mode: str, pack_id: str,
                 knowledge: Path) -> dict[str, Any]:
    result = check_import(db, data, mode, pack_id)
    if not result["ok"]:
        raise BusinessError("invalid_knowledge", "File không có gì mới so với knowledge hiện tại")
    saved = backup(knowledge)
    _summary, writes = _plan(db, _parse(data), mode)
    db.execute("BEGIN IMMEDIATE")
    try:
        for table in TABLES:
            for action, row in writes[table.name]:
                keys = list(row)
                if action == "insert":
                    db.execute(f"INSERT INTO kn.{table.name}({','.join(keys)}) VALUES({','.join('?' * len(keys))})",
                               [row[key] for key in keys])
                else:
                    sets = [key for key in keys if key not in table.key and key not in table.local]
                    if sets:
                        db.execute(f"UPDATE kn.{table.name} SET {','.join(f'{key}=?' for key in sets)} "
                                   f"WHERE {' AND '.join(f'{key}=?' for key in table.key)}",
                                   [row[key] for key in sets] + [row[key] for key in table.key])
        db.execute("INSERT OR REPLACE INTO kn.knowledge_meta(key,value) VALUES('last_import',?)",
                   (json.dumps({"at": _now(), "from": result["from"], "mode": mode}, ensure_ascii=False),))
        db.commit()
    except sqlite3.Error:
        db.rollback()
        raise
    if index is not None:
        apply_links(db, index)
    return {**result, "backup": saved.name}
