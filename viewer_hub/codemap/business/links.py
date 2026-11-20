"""Hand-made links between graph nodes (kn.biz_links).

The extract misses some edges: a call through a dynamic name, a job started from a config table, a screen that
reaches its API through a helper the parser does not follow. People add those links here, AI adds them from an
imported file or MCP (``origin='ai'``). There is no approval: every link is walked like extracted edges (``GraphIndex.set_links``), so flows, the AI export and MCP (trace / impact via storage.manual_links) see them, marked ``manual``.
"""
from __future__ import annotations

import sqlite3
import uuid
from typing import Any, Iterable

from .common import DATA_TYPES, LINK_DATA_TYPES, LINK_TYPES, BusinessError, _now
from .graph import GraphIndex, apply_links, ref_of
from .resolve import names

MAX_NOTE = 2000
MAX_LINKS = 20_000


# A link end is found again only by a name that says which node it is (address, full name, end of the name);
# close spellings are offered to a person as candidates, never applied.
RELINK_LEVEL = 3
MAX_RELINKS = 2_000


def _moves(db: sqlite3.Connection, link_id: str) -> dict[str, dict[str, str]]:
    try:
        rows = db.execute("SELECT side,old_ref,reason FROM kn.biz_link_moves WHERE link_id=?", (link_id,)).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {row[0]: {"old_ref": row[1], "reason": row[2]} for row in rows}


def _row(index: GraphIndex, row: sqlite3.Row, db: sqlite3.Connection | None = None) -> dict[str, Any]:
    moves = _moves(db, row["link_id"]) if db is not None else {}
    lookup = names(index) if db is not None else None

    def side(name: str, node_id: str, ref: str) -> dict[str, Any]:
        node = index.nodes.get(node_id)
        found = {"node_id": node_id, "ref": ref_of(node) if node else ref, "node_type": node["node_type"] if node else "",
                 "address": lookup.address.get(node_id, "") if lookup else "", "missing": node is None}
        if name in moves:
            found["moved"] = moves[name]
        if node is None and lookup is not None and ref:
            # The person picks the node again: the closest names first.
            result = lookup.resolve(ref)
            found["candidates"] = [candidate.as_dict() for candidate in result.candidates]
        return found
    return {
        "link_id": row["link_id"], "source": side("source", row["source_id"], row["source_ref"]),
        "target": side("target", row["target_id"], row["target_ref"]), "edge_type": row["edge_type"], "note": row["note"],
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
    rows = db.execute(f"{sql}{' WHERE ' + ' AND '.join(where) if where else ''} ORDER BY created_at DESC, link_id LIMIT ?",
                      [*params, MAX_LINKS]).fetchall()
    members = set(node_ids) if node_ids is not None else None
    return [_row(index, row, db) for row in rows
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
                origin: str = "user", commit: bool = True) -> dict[str, Any]:
    source, target = str(body.get("source") or ""), str(body.get("target") or "")
    edge_type = str(body.get("edge_type") or "CALLS").upper()
    check_link(index, source, target, edge_type)
    if any(t == target and kind == edge_type for t, kind, edge_id in index.out.get(source, ())):
        raise BusinessError("invalid_link", "Graph đã có cạnh này từ extract")
    note = str(body.get("note") or "").strip()[:MAX_NOTE]
    found = _existing(db, source, target, edge_type)
    now = _now()
    if found:
        # Adding again what exists keeps the link; a new note replaces the old one.
        if note:
            db.execute("UPDATE kn.biz_links SET note=?,updated_at=? WHERE link_id=?", (note, now, found["link_id"]))
        link_id = found["link_id"]
    else:
        link_id = f"lnk-{uuid.uuid4().hex[:12]}"
        db.execute(
            "INSERT INTO kn.biz_links(link_id,source_id,target_id,edge_type,note,status,origin,source_ref,target_ref,"
            "created_by,approved_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (link_id, source, target, edge_type, note, "approved", origin, _ref(index, source), _ref(index, target),
             who, "", now, now),
        )
    if commit:
        db.commit()
        apply_links(db, index)
    return _row(index, db.execute("SELECT * FROM kn.biz_links WHERE link_id=?", (link_id,)).fetchone(), db)


def update_link(db: sqlite3.Connection, index: GraphIndex, link_id: str, body: dict[str, Any], who: str) -> dict[str, Any]:
    """Change the note, point an end at another node (``source`` / ``target``: a lost node picked again), or
    confirm (``confirm: true``) that a link found again after a re-extract still holds."""
    row = db.execute("SELECT * FROM kn.biz_links WHERE link_id=?", (link_id,)).fetchone()
    if not row:
        raise BusinessError("not_found", "Không có liên kết này", 404)
    if set(body) - {"note", "source", "target", "confirm"}:
        raise BusinessError("invalid_link", "Chỉ sửa được ghi chú, node hai đầu, hoặc xác nhận liên kết vẫn đúng")
    note = str(body["note"]).strip()[:MAX_NOTE] if "note" in body else row["note"]
    source = str(body.get("source") or row["source_id"])
    target = str(body.get("target") or row["target_id"])
    if source != row["source_id"] or target != row["target_id"]:
        check_link(index, source, target, row["edge_type"])
    now = _now()
    db.execute("UPDATE kn.biz_links SET note=?,source_id=?,target_id=?,source_ref=?,target_ref=?,updated_at=? WHERE link_id=?",
               (note, source, target, _ref(index, source) if source in index.nodes else row["source_ref"],
                _ref(index, target) if target in index.nodes else row["target_ref"], now, link_id))
    picked = [side for side in ("source", "target") if side in body]
    if body.get("confirm") or picked:
        sides = ("source", "target") if body.get("confirm") else picked
        db.execute(f"DELETE FROM kn.biz_link_moves WHERE link_id=? AND side IN ({','.join('?' * len(sides))})",
                   (link_id, *sides))
    db.commit()
    apply_links(db, index)
    return _row(index, db.execute("SELECT * FROM kn.biz_links WHERE link_id=?", (link_id,)).fetchone(), db)


def _ref(index: GraphIndex, node_id: str) -> str:
    """What a link remembers of an end, to find it again: its address (system › type › full name)."""
    return names(index).address.get(node_id) or ref_of(index.nodes[node_id])


def relink(db: sqlite3.Connection, index: GraphIndex) -> int:
    """Point link ends whose node is gone at the node that now carries the stored name; returns how many moved.

    Tried once per graph index for each lost end. Read-only connections leave the rows as they are."""
    tried = index.__dict__.setdefault("_relink_tried", set())
    lookup = names(index, db)
    moved, attempted = 0, set()
    try:
        rows = db.execute("SELECT link_id,source_id,target_id,source_ref,target_ref FROM kn.biz_links").fetchall()
        for link_id, source, target, source_ref, target_ref in rows[:MAX_LINKS]:
            ends = {"source": (source, source_ref, target), "target": (target, target_ref, source)}
            for side, (node_id, ref, other) in ends.items():
                if node_id in index.nodes or (link_id, side) in tried or not ref or moved >= MAX_RELINKS:
                    continue
                attempted.add((link_id, side))
                tried.add((link_id, side))
                result = lookup.resolve(ref, near=[other], max_level=RELINK_LEVEL)
                if result.status != "match" or result.node_id == other:
                    continue
                new_id = result.node_id
                db.execute(f"UPDATE kn.biz_links SET {side}_id=?,{side}_ref=?,updated_at=? WHERE link_id=?",
                           (new_id, lookup.address[new_id], _now(), link_id))
                db.execute("INSERT INTO kn.biz_link_moves(link_id,side,old_id,old_ref,new_id,reason) VALUES(?,?,?,?,?,?) "
                           "ON CONFLICT(link_id,side) DO UPDATE SET new_id=excluded.new_id,reason=excluded.reason,"
                           "moved_at=CURRENT_TIMESTAMP", (link_id, side, node_id, ref, new_id, result.reason))
                moved += 1
        if moved:
            db.commit()
    except sqlite3.OperationalError:  # read-only knowledge db: a writable open moves them
        db.rollback()
        tried -= attempted
        return 0
    return moved


def delete_link(db: sqlite3.Connection, index: GraphIndex, link_id: str) -> None:
    if not db.execute("DELETE FROM kn.biz_links WHERE link_id=?", (link_id,)).rowcount:
        raise BusinessError("not_found", "Không có liên kết này", 404)
    db.execute("DELETE FROM kn.biz_link_moves WHERE link_id=?", (link_id,))
    db.commit()
    apply_links(db, index)
