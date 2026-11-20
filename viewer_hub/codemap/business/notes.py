"""Business notes on one code node (``kn.graph_knowledge``): what a screen, table or job means for the business.

A note is in use as soon as it is written. ``created_by`` names the agent that wrote it (empty for a person),
``edited_by`` the person who last saved it, and ``fingerprint`` the node's behaviour fingerprint at that moment, so
the page can say "Code đã đổi" after an extract changes the node. An agent never changes a note a person saved
(``mcp/doc_tools.propose_note`` only touches its own notes); a person editing or confirming an AI note makes it theirs.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable

from viewer_hub.codemap import knowledge
from viewer_hub.codemap.contract.fingerprints import combined

from .common import BusinessError

MAX_NOTES_PER_NODE = 50


def _row(row: sqlite3.Row, current: dict[str, str]) -> dict[str, Any]:
    keys = row.keys()
    stored = row["fingerprint"] if "fingerprint" in keys else ""
    node = row["target_id"]
    now = combined(current, [node]) if node in current else ""
    try:
        citations = json.loads(row["citations_json"] or "[]")
    except ValueError:
        citations = []
    return {
        "id": row["knowledge_id"], "node": row["target_id"], "text": row["body"],
        "by_ai": bool(row["created_by"]), "created_by": row["created_by"],
        "edited_by": row["edited_by"] if "edited_by" in keys else "",
        "updated_at": row["updated_at"], "citations": citations if isinstance(citations, list) else [],
        "changed": bool(stored and now and stored != now),
    }


def list_notes(db: sqlite3.Connection, node_ids: Iterable[str]) -> list[dict[str, Any]]:
    """Notes in use on these nodes, oldest first (rejected / draft rows from older versions are left out)."""
    values = list(dict.fromkeys(node_ids))
    if not values or not knowledge.has_table(db, "graph_knowledge", "kn"):
        return []
    rows = []
    for start in range(0, len(values), 400):
        chunk = values[start:start + 400]
        marks = ",".join("?" * len(chunk))
        rows += db.execute(f"SELECT * FROM kn.graph_knowledge WHERE target_id IN ({marks}) AND status='approved' "
                           "ORDER BY knowledge_id", chunk).fetchall()
    current = knowledge.fingerprints(db, {row["target_id"] for row in rows})
    return [_row(row, current) for row in rows]


def _get(db: sqlite3.Connection, note_id: int) -> sqlite3.Row:
    row = db.execute("SELECT * FROM kn.graph_knowledge WHERE knowledge_id=?", (note_id,)).fetchone()
    if not row:
        raise BusinessError("not_found", "Note not found", 404)
    return row


def _text(body: dict[str, Any]) -> str:
    text = body.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > knowledge.MAX_TEXT:
        raise BusinessError("invalid_business", f"text must be 1 to {knowledge.MAX_TEXT} characters")
    return text.strip()


def _citations(body: dict[str, Any], previous: str = "[]") -> str:
    if "citations" not in body:
        return previous
    try:
        return json.dumps(knowledge.citations(body["citations"], required=False), ensure_ascii=False)
    except knowledge.KnowledgeError as exc:
        raise BusinessError("invalid_business", exc.message) from exc


def create_note(db: sqlite3.Connection, node_id: str, body: dict[str, Any], who: str) -> dict[str, Any]:
    if not knowledge.existing_nodes(db, [node_id]):
        raise BusinessError("not_found", "Node not found", 404)
    count = db.execute("SELECT COUNT(*) FROM kn.graph_knowledge WHERE target_id=? AND status='approved'", (node_id,)).fetchone()[0]
    if count >= MAX_NOTES_PER_NODE:
        raise BusinessError("invalid_business", f"A node keeps at most {MAX_NOTES_PER_NODE} notes")
    note_id = db.execute(
        "INSERT INTO kn.graph_knowledge(target_id,body,status,citations_json,created_by,edited_by,fingerprint) "
        "VALUES(?,?,'approved',?,'',?,?)",
        (node_id, _text(body), _citations(body), who, knowledge.fingerprint_of(db, [node_id]))).lastrowid
    db.commit()
    return list_one(db, note_id)


def update_note(db: sqlite3.Connection, note_id: int, body: dict[str, Any], who: str) -> dict[str, Any]:
    """Save a person's text (or, without ``text``, confirm the note still matches the code): the note becomes theirs."""
    row = _get(db, note_id)
    text = _text(body) if "text" in body else row["body"]
    db.execute("UPDATE kn.graph_knowledge SET body=?,citations_json=?,created_by='',edited_by=?,fingerprint=?,updated_at=? "
               "WHERE knowledge_id=?",
               (text, _citations(body, row["citations_json"]), who, knowledge.fingerprint_of(db, [row["target_id"]]),
                knowledge.now(), note_id))
    db.commit()
    return list_one(db, note_id)


def delete_note(db: sqlite3.Connection, note_id: int) -> None:
    _get(db, note_id)
    db.execute("DELETE FROM kn.graph_knowledge WHERE knowledge_id=?", (note_id,))
    db.commit()


def list_one(db: sqlite3.Connection, note_id: int) -> dict[str, Any]:
    row = _get(db, note_id)
    return _row(row, knowledge.fingerprints(db, [row["target_id"]]))


def ai_note(db: sqlite3.Connection, node_id: str, text: str, who: str) -> str:
    """Write the note an AI file brings for one node; the caller commits.

    The AI's earlier note on the node is replaced (a re-import rewords it instead of piling up copies); a note a
    person saved is never touched. Returns ``created``, ``updated`` or ``same``.
    """
    rows = db.execute("SELECT knowledge_id, body, created_by FROM kn.graph_knowledge WHERE target_id=? AND status='approved' "
                      "ORDER BY knowledge_id", (node_id,)).fetchall()
    if any(row["body"] == text for row in rows):
        return "same"
    fingerprint = knowledge.fingerprint_of(db, [node_id])
    own = next((row for row in rows if row["created_by"]), None)
    if own:
        db.execute("UPDATE kn.graph_knowledge SET body=?,created_by=?,fingerprint=?,updated_at=? WHERE knowledge_id=?",
                   (text, who, fingerprint, knowledge.now(), own["knowledge_id"]))
        return "updated"
    db.execute("INSERT INTO kn.graph_knowledge(target_id,body,status,created_by,fingerprint) VALUES(?,?,'approved',?,?)",
               (node_id, text, who, fingerprint))
    return "created"
