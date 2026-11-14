"""Edits people make: names, descriptions, review status, flow parts, answers to questions."""
from __future__ import annotations

import json
import sqlite3
from typing import Any


from viewer_hub.codemap.levels import keeps
from .common import BusinessError, RULE_STATUSES, STRANDED_MENU, UNSORTED_MENU, _json, _now
from .flows import skeleton
from .graph import GraphIndex
from .tree import find_item


def _text(value: Any, limit: int, field: str) -> str:
    if not isinstance(value, str) or len(value) > limit:
        raise BusinessError("invalid_business", f"{field} must be text up to {limit} characters")
    return value.strip()


def update_item(db: sqlite3.Connection, tree: dict[str, Any], item_id: str, body: dict[str, Any], who: str,
                index: GraphIndex | None = None) -> None:
    item = find_item(tree, item_id)
    if not item and index is not None and item_id.startswith("entry:") and item_id[6:] in index.nodes:
        # Entry points past the tree's first page (or currently attached to a feature) are still assignable.
        item = {"id": item_id, "kind": "entry"}
    if not item or item["kind"] not in {"menu", "feature", "entry"} or item_id in {UNSORTED_MENU, STRANDED_MENU}:
        raise BusinessError("not_found", "Menu, feature or entry point not found", 404)
    allowed = {"name", "description", "status", "parent_id"}
    if not body or set(body) - allowed:
        raise BusinessError("invalid_business", "Only name, description, status and parent_id can change")
    current = db.execute("SELECT * FROM kn.biz_items WHERE item_id=?", (item_id,)).fetchone()
    row = dict(current) if current else {"item_id": item_id}
    if "name" in body:
        row["name"] = _text(body["name"], 200, "name") or None
    if "description" in body:
        row["description"] = _text(body["description"], 20_000, "description")
    if "parent_id" in body:
        parent = find_item(tree, body["parent_id"]) if isinstance(body["parent_id"], str) else None
        wanted = "feature" if item["kind"] == "entry" else "menu"
        if item["kind"] == "menu" or not parent or parent["kind"] != wanted or parent["id"] in {UNSORTED_MENU, STRANDED_MENU}:
            raise BusinessError("invalid_business", f"parent_id must be a {wanted}")
        row["parent_id"] = parent["id"]
    if "status" in body:
        if body["status"] != "approved":
            raise BusinessError("invalid_business", "status can only be set to approved")
        row["status"], row["reviewed_by"] = "approved", who
    elif {"name", "description"} & set(body):
        row["status"], row["reviewed_by"] = "edited", who
    db.execute(
        """INSERT INTO kn.biz_items(item_id,parent_id,name,description,status,reviewed_by,sort_order,updated_at)
           VALUES(:item_id,:parent_id,:name,:description,:status,:reviewed_by,:sort_order,:updated_at)
           ON CONFLICT(item_id) DO UPDATE SET parent_id=excluded.parent_id,name=excluded.name,description=excluded.description,
             status=excluded.status,reviewed_by=excluded.reviewed_by,updated_at=excluded.updated_at""",
        {"parent_id": None, "name": None, "description": None, "status": None, "reviewed_by": None, "sort_order": None,
         **row, "updated_at": _now()},
    )
    db.commit()


def _save_flow(db: sqlite3.Connection, flow_id: str, feature_id: str, doc: dict[str, Any]) -> None:
    db.execute(
        """INSERT INTO kn.biz_flows(flow_id,feature_id,doc_json,updated_at) VALUES(?,?,?,?)
           ON CONFLICT(flow_id) DO UPDATE SET feature_id=excluded.feature_id,doc_json=excluded.doc_json,updated_at=excluded.updated_at""",
        (flow_id, feature_id, json.dumps(doc, ensure_ascii=False), _now()),
    )


def _begin(db: sqlite3.Connection) -> None:
    """Read-modify-write of a flow document under a write lock, so two edits (or an edit and an import)
    cannot overwrite each other."""
    if db.in_transaction:
        db.commit()
    db.execute("BEGIN IMMEDIATE")


def _stored_or_skeleton(db: sqlite3.Connection, index: GraphIndex, item: dict[str, Any]) -> dict[str, Any]:
    row = db.execute("SELECT doc_json FROM kn.biz_flows WHERE flow_id=?", (item["id"],)).fetchone()
    return _json(row[0], {}) if row else skeleton(index, item["id"], item["entry_node_id"], item["name"])


def update_part(db: sqlite3.Connection, index: GraphIndex, tree: dict[str, Any], flow_id: str, part: str,
                body: dict[str, Any], who: str) -> dict[str, Any]:
    item = find_item(tree, flow_id)
    if not item or item["kind"] != "flow":
        raise BusinessError("not_found", "Flow not found", 404)
    _begin(db)
    doc = _stored_or_skeleton(db, index, item)
    if part == "summary":
        target, fields = doc.setdefault("summary", {"text": "", "status": "ai"}), {"text": 50_000, "name": 200}
    elif part == "edge_cases":
        target, fields = doc.setdefault("edge_cases", {"items": [], "status": "ai"}), {"items": None}
    elif part.startswith("step:"):
        step_id = part[5:]
        target = next((step for step in doc.get("steps", []) if step.get("id") == step_id), None)
        if target is None:
            raise BusinessError("not_found", "Step not found", 404)
        fields = {"name": 200, "actor": 200, "text": 50_000, "nodes": None, "rules": None}
    else:
        raise BusinessError("invalid_business", "part must be summary, edge_cases or step:<id>")
    if not body or set(body) - {*fields, "status"}:
        raise BusinessError("invalid_business", f"Only {', '.join(sorted(fields))} or status can change")
    for key, limit in fields.items():
        if key not in body:
            continue
        if key == "name" and part == "summary":
            doc["name"] = _text(body[key], limit, key)
        elif key == "items":
            values = body[key]
            if not isinstance(values, list) or len(values) > 100:
                raise BusinessError("invalid_business", "items must be a list of up to 100 texts")
            target["items"] = [_text(value, 4000, "item") for value in values if isinstance(value, str) and value.strip()]
        elif key == "nodes":
            values = body[key]
            if not isinstance(values, list) or any(not isinstance(value, str) or value not in index.nodes for value in values):
                raise BusinessError("invalid_business", "nodes must be existing node ids")
            target["nodes"] = list(dict.fromkeys(values))
        elif key == "rules":
            target["rules"] = _clean_rules(body[key], target.get("rules", []))
        else:
            target[key] = _text(body[key], limit, key)
    if "status" in body:
        if body["status"] != "approved":
            raise BusinessError("invalid_business", "status can only be set to approved")
        target["status"], target["reviewed_by"] = "approved", who
        # Behaviour fingerprint of the nodes it describes: a later extract that changes them puts the part
        # back in the review queue (web/backend/knowledge.py).
        from viewer_hub.codemap.knowledge import fingerprint_of

        nodes = target.get("nodes") if part.startswith("step:") else [
            node for step in doc.get("steps", []) for node in step.get("nodes", [])
        ]
        target["fingerprint"] = fingerprint_of(db, nodes or [])
    else:
        target["status"], target["reviewed_by"] = "edited", who
        target.pop("fingerprint", None)
    _save_flow(db, flow_id, item["feature_id"], doc)
    db.commit()
    return doc


def _clean_rules(values: Any, previous: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not isinstance(values, list) or len(values) > 50:
        raise BusinessError("invalid_business", "rules must be a list of up to 50 rules")
    rules = []
    for position, value in enumerate(values):
        if not isinstance(value, dict):
            raise BusinessError("invalid_business", "each rule must be an object")
        # A rule keeps an omitted field only when the client sent the same rule (same title) back.
        old = previous[position] if position < len(previous) and previous[position].get("title") == value.get("title") else {}
        rules.append({
            "title": _text(value.get("title", old.get("title", "")), 400, "rule title"),
            "text": _text(value.get("text", old.get("text", "")), 8000, "rule text"),
            "at": _text(value.get("at", old.get("at", "")), 400, "rule at"),
            "evidence": _text(value.get("evidence", old.get("evidence", "")), 400, "rule evidence"),
            "status": value.get("status", old.get("status", "warn")) if value.get("status", old.get("status", "warn")) in RULE_STATUSES else "warn",
        })
    return rules


def answer_question(db: sqlite3.Connection, index: GraphIndex, tree: dict[str, Any], flow_id: str, question_id: str,
                    answer: Any, who: str) -> dict[str, Any]:
    item = find_item(tree, flow_id)
    if not item or item["kind"] != "flow":
        raise BusinessError("not_found", "Flow not found", 404)
    _begin(db)
    doc = _stored_or_skeleton(db, index, item)
    question = next((q for q in doc.get("questions", []) if q.get("id") == question_id), None)
    if question is None:
        raise BusinessError("not_found", "Question not found", 404)
    question["answer"], question["answered_by"] = _text(answer, 8000, "answer"), who
    if not question["answer"]:
        raise BusinessError("invalid_business", "answer must not be empty")
    _save_flow(db, flow_id, item["feature_id"], doc)
    db.commit()
    return doc
