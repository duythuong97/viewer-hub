"""Hand-made links between graph nodes (kn.biz_links).

The extract misses some edges: a call through a dynamic name, a job started from a config table, a screen that
reaches its API through a helper the parser does not follow. People add those links here; AI may propose them
in an imported file (``status='proposed'``) and a person approves them. Approved links are walked like
extracted edges (``GraphIndex.set_links``), so flows, the AI export and MCP (trace / impact via storage.manual_links) see them, marked ``manual``.
"""
from __future__ import annotations

import sqlite3
import uuid
from typing import Any, Iterable

from .common import DATA_TYPES, LINK_DATA_TYPES, LINK_STATUSES, LINK_TYPES, BusinessError, _now
from .graph import GraphIndex, apply_links, ref_of

MAX_NOTE = 2000
MAX_LINKS = 20_000


def _row(index: GraphIndex, row: sqlite3.Row) -> dict[str, Any]:
    def side(node_id: str, ref: str) -> dict[str, Any]:
        node = index.nodes.get(node_id)
        return {"node_id": node_id, "ref": ref_of(node) if node else ref, "node_type": node["node_type"] if node else "",
                "missing": node is None}
    return {
        "link_id": row["link_id"], "source": side(row["source_id"], row["source_ref"]),
        "target": side(row["target_id"], row["target_ref"]), "edge_type": row["edge_type"], "note": row["note"],
        "status": row["status"], "origin": row["origin"], "created_by": row["created_by"],
        "approved_by": row["approved_by"], "created_at": row["created_at"], "updated_at": row["updated_at"],
    }


def list_links(db: sqlite3.Connection, index: GraphIndex, node_ids: Iterable[str] | None = None,
               status: str | None = None) -> list[dict[str, Any]]:
    """Links touching any of ``node_ids`` (all links when None), newest first."""
    sql, params = "SELECT * FROM kn.biz_links", []
    where = []
    if status:
        where.append("status=?"); params.append(status)
    rows = db.execute(f"{sql}{' WHERE ' + ' AND '.join(where) if where else ''} ORDER BY updated_at DESC LIMIT ?",
                      [*params, MAX_LINKS]).fetchall()
    members = set(node_ids) if node_ids is not None else None
    return [_row(index, row) for row in rows
            if members is None or row["source_id"] in members or row["target_id"] in members]


def check_link(index: GraphIndex, source: str, target: str, edge_type: str) -> None:
    if source not in index.nodes:
        raise BusinessError("invalid_link", f"Không có node nguồn {source!r} trong graph")
    if target not in index.nodes:
        raise BusinessError("invalid_link", f"Không có node đích {target!r} trong graph")
    if source == target:
        raise BusinessError("invalid_link", "Node nguồn và node đích trùng nhau")
    if edge_type not in LINK_TYPES:
        raise BusinessError("invalid_link", f"Loại cạnh phải là một trong: {', '.join(LINK_TYPES)}")
    if edge_type in LINK_DATA_TYPES and index.nodes[target]["node_type"] not in DATA_TYPES:
        raise BusinessError("invalid_link", f"{edge_type} chỉ nối tới bảng / view / dữ liệu")


def _existing(db: sqlite3.Connection, source: str, target: str, edge_type: str):
    return db.execute("SELECT * FROM kn.biz_links WHERE source_id=? AND target_id=? AND edge_type=?",
                      (source, target, edge_type)).fetchone()


def create_link(db: sqlite3.Connection, index: GraphIndex, body: dict[str, Any], who: str, *,
                origin: str = "user", status: str = "approved", commit: bool = True) -> dict[str, Any]:
    source, target = str(body.get("source") or ""), str(body.get("target") or "")
    edge_type = str(body.get("edge_type") or "CALLS").upper()
    check_link(index, source, target, edge_type)
    if any(t == target and kind == edge_type for t, kind, edge_id in index.out.get(source, ())):
        raise BusinessError("invalid_link", "Graph đã có cạnh này từ extract")
    note = str(body.get("note") or "").strip()[:MAX_NOTE]
    found = _existing(db, source, target, edge_type)
    now = _now()
    if found:
        # Adding again what exists: a person's approval promotes an AI proposal, a proposal never demotes.
        if found["status"] == "proposed" and status == "approved":
            db.execute("UPDATE kn.biz_links SET status='approved',approved_by=?,note=CASE WHEN ?='' THEN note ELSE ? END,"
                       "updated_at=? WHERE link_id=?", (who, note, note, now, found["link_id"]))
        link_id = found["link_id"]
    else:
        link_id = f"lnk-{uuid.uuid4().hex[:12]}"
        db.execute(
            "INSERT INTO kn.biz_links(link_id,source_id,target_id,edge_type,note,status,origin,source_ref,target_ref,"
            "created_by,approved_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (link_id, source, target, edge_type, note, status, origin, ref_of(index.nodes[source]),
             ref_of(index.nodes[target]), who, who if status == "approved" else "", now, now),
        )
    if commit:
        db.commit()
        apply_links(db, index)
    return _row(index, db.execute("SELECT * FROM kn.biz_links WHERE link_id=?", (link_id,)).fetchone())


def update_link(db: sqlite3.Connection, index: GraphIndex, link_id: str, body: dict[str, Any], who: str) -> dict[str, Any]:
    row = db.execute("SELECT * FROM kn.biz_links WHERE link_id=?", (link_id,)).fetchone()
    if not row:
        raise BusinessError("not_found", "Không có liên kết này", 404)
    status = body.get("status", row["status"])
    if status not in LINK_STATUSES:
        raise BusinessError("invalid_link", "status phải là approved hoặc proposed")
    note = str(body["note"]).strip()[:MAX_NOTE] if "note" in body else row["note"]
    db.execute("UPDATE kn.biz_links SET status=?,note=?,approved_by=?,updated_at=? WHERE link_id=?",
               (status, note, who if status == "approved" and row["status"] != "approved" else row["approved_by"],
                _now(), link_id))
    db.commit()
    apply_links(db, index)
    return _row(index, db.execute("SELECT * FROM kn.biz_links WHERE link_id=?", (link_id,)).fetchone())


def delete_link(db: sqlite3.Connection, index: GraphIndex, link_id: str) -> None:
    if not db.execute("DELETE FROM kn.biz_links WHERE link_id=?", (link_id,)).rowcount:
        raise BusinessError("not_found", "Không có liên kết này", 404)
    db.commit()
    apply_links(db, index)
