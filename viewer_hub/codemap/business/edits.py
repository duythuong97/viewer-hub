"""Edits people make: names, descriptions, flow parts. Nothing is approved: an edit is in use."""
from __future__ import annotations

import json
import sqlite3
from typing import Any


from viewer_hub.codemap.knowledge import safe_citations
from viewer_hub.codemap.levels import keeps
from .common import BusinessError, RULE_STATUSES, STRANDED_MENU, UNSORTED_MENU, _json, _now
from .flows import skeleton
from .graph import GraphIndex
from .tree import children_sig, find_item


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
    allowed = {"name", "description", "parent_id", "confirm"}
    if not body or set(body) - allowed:
        raise BusinessError("invalid_business", "Only name, description and parent_id can change")
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
    if {"name", "description"} & set(body):
        row["status"], row["reviewed_by"] = "edited", who
    if {"name", "description", "confirm"} & set(body) and item["kind"] in {"menu", "feature"}:
        # Saved (or confirmed "still right") against what is below it now.
        row["children_sig"] = children_sig(item)
    db.execute(
        """INSERT INTO kn.biz_items(item_id,parent_id,name,description,status,reviewed_by,sort_order,updated_at,children_sig)
           VALUES(:item_id,:parent_id,:name,:description,:status,:reviewed_by,:sort_order,:updated_at,:children_sig)
           ON CONFLICT(item_id) DO UPDATE SET parent_id=excluded.parent_id,name=excluded.name,description=excluded.description,
             status=excluded.status,reviewed_by=excluded.reviewed_by,updated_at=excluded.updated_at,children_sig=excluded.children_sig""",
        {"parent_id": None, "name": None, "description": None, "status": None, "reviewed_by": None, "sort_order": None,
         "children_sig": "", **row, "updated_at": _now()},
    )
    db.commit()


# --------------------------------------------------------------------------- what AI writes about an item

ITEM_LOCKED = frozenset({"edited", "approved"})
MAX_ITEM_NAME = 200
MAX_ITEM_DESCRIPTION = 20_000


def documented_item(tree: dict[str, Any], item_id: str) -> dict[str, Any]:
    """A feature or a menu (system, group, section) an agent may name and describe; the generated lists are not."""
    item = find_item(tree, item_id)
    if not item or item["kind"] not in {"feature", "menu"} or item_id in {UNSORTED_MENU, STRANDED_MENU} or item.get("unsorted"):
        raise BusinessError("not_found", "Feature or menu not found", 404)
    return item


def item_document(db: sqlite3.Connection, tree: dict[str, Any], item_id: str) -> dict[str, Any]:
    """A feature's or menu's name and overview as an agent fills them: what is stored, and whether a person wrote it
    (then it is locked: an agent reads it, never changes it)."""
    item = documented_item(tree, item_id)
    row = db.execute("SELECT name,description,status FROM kn.biz_items WHERE item_id=?", (item_id,)).fetchone()
    row = dict(row) if row else {}
    locked = row.get("status") in ITEM_LOCKED
    return {
        "id": item_id, "graph_name": item["name"] if not row.get("name") else "",
        "name": row.get("name") or "", "description": row.get("description") or "",
        "status": row.get("status") or "", "locked": locked,
    }


def ai_item(db: sqlite3.Connection, tree: dict[str, Any], item_id: str, body: Any, *, commit: bool = True) -> str:
    """Write an agent's name / overview for a feature or menu, marked as written by AI (status 'ai').

    Returns 'locked' (a person wrote it: nothing changes), 'empty' (nothing to write), 'same' or 'written'.
    Only the fields sent are written; the item's place in the tree (parent, order) is kept."""
    item = documented_item(tree, item_id)
    if not isinstance(body, dict):
        raise BusinessError("invalid_business", "feature must be an object with name and description")
    current = db.execute("SELECT * FROM kn.biz_items WHERE item_id=?", (item_id,)).fetchone()
    row = dict(current) if current else {"item_id": item_id}
    if row.get("status") in ITEM_LOCKED:
        return "locked"
    name = body.get("name") if isinstance(body.get("name"), str) else ""
    description = body.get("description") if isinstance(body.get("description"), str) else ""
    name, description = name.strip()[:MAX_ITEM_NAME], description.strip()[:MAX_ITEM_DESCRIPTION]
    if not name and not description:
        return "empty"
    wanted = {**row, **({"name": name} if name else {}), **({"description": description} if description else {})}
    if (wanted.get("name"), wanted.get("description"), row.get("status")) == (row.get("name"), row.get("description"), "ai"):
        return "same"
    wanted["status"], wanted["reviewed_by"], wanted["children_sig"] = "ai", None, children_sig(item)
    db.execute(
        """INSERT INTO kn.biz_items(item_id,parent_id,name,description,status,reviewed_by,sort_order,updated_at,children_sig)
           VALUES(:item_id,:parent_id,:name,:description,:status,:reviewed_by,:sort_order,:updated_at,:children_sig)
           ON CONFLICT(item_id) DO UPDATE SET name=excluded.name,description=excluded.description,
             status=excluded.status,reviewed_by=excluded.reviewed_by,updated_at=excluded.updated_at,children_sig=excluded.children_sig""",
        {"parent_id": None, "name": None, "description": None, "sort_order": None, **wanted, "updated_at": _now()},
    )
    if commit:
        db.commit()
    return "written"


def refresh_sigs(db: sqlite3.Connection, index: GraphIndex, item_ids: list[str]) -> None:
    """After one import wrote both a text and what it summarises (flows then their feature, sub-menus then their
    menu), record each overview against the tree as it is now, so it does not show as out of date at once."""
    from .tree import build_tree

    if not item_ids:
        return
    tree = build_tree(db, index)
    for item_id in item_ids:
        item = find_item(tree, item_id)
        if item:
            db.execute("UPDATE kn.biz_items SET children_sig=? WHERE item_id=?", (children_sig(item), item_id))
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
    if not body or set(body) - set(fields):
        raise BusinessError("invalid_business", f"Only {', '.join(sorted(fields))} can change")
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
    # Edited by a person: AI never rewrites it, and it keeps the behaviour fingerprint of the nodes it describes,
    # so a later extract that changes them marks it "code changed" (knowledge.part_changed).
    from viewer_hub.codemap.knowledge import fingerprint_of

    nodes = target.get("nodes") if part.startswith("step:") else [
        node for step in doc.get("steps", []) for node in step.get("nodes", [])
    ]
    target["status"], target["reviewed_by"] = "edited", who
    target["fingerprint"] = fingerprint_of(db, nodes or [])
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
        # Document citations an agent attached (knowledge.citations); a person's edit keeps them.
        cited = safe_citations(value.get("citations", old.get("citations")))
        if cited:
            rules[-1]["citations"] = cited
    return rules
