"""The data side of the business layer (docs/solutions/codemap-redesign-solution.md §5.2, §5.3).

* ``feature_data``: the tables a feature's flows read and write (approved hand-made links included, since the walk
  goes through GraphIndex.edges_from) and the CRUD matrix flow × table. Derived from edges only, no AI.
* ``table_usage``: the features (screens, APIs, jobs…) and the code that read or write one table.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Iterable

from viewer_hub.codemap.contract.vocabulary import READ_EDGES, WRITE_EDGES
from .common import BusinessError, MAX_FEATURE_NODES, MAX_FLOW_NODES, TERMINAL_TYPES
from .graph import GraphIndex, ref_name
from .tree import find_item

TABLE_TYPES = frozenset({"TABLE", "VIEW", "MATERIALIZED_VIEW"})
MAX_DATA_TABLES = 40
MAX_USAGE = 200
MAX_CALLERS = 20_000  # nodes a reverse walk from one table may visit
CRUD_ORDER = "CRUD"
# Which CRUD letter(s) an edge into a table is.
CRUD = {"INSERTS": "C", "LOADS_INTO": "C", "MERGES": "CU", "UPDATES": "U", "WRITES": "U", "DELETES": "D",
        "READS": "R", "REMOTE_READS": "R"}
FEATURE_KINDS = {"SCREEN": "screen", "JOB_NETWORK": "job", "EXECUTABLE": "job", "API_OPERATION": "api",
                 "PROCEDURE": "plsql", "FUNCTION": "plsql", "TRIGGER": "plsql", "SQL_FILE": "sql", "LOADER_CONTROL": "sql"}


def crud_text(letters: Iterable[str]) -> str:
    present = set("".join(letters))
    return "".join(letter for letter in CRUD_ORDER if letter in present)


def _touches(index: GraphIndex, node_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    """{table id: {"ops": set of letters, "manual": bool}} of the data edges leaving ``node_ids``."""
    found: dict[str, dict[str, Any]] = {}
    for source in node_ids:
        for target, edge_type, edge_id in index.edges_from(source):
            letters = CRUD.get(edge_type)
            if not letters or edge_type not in READ_EDGES | WRITE_EDGES:
                continue
            node = index.nodes.get(target)
            if node is None or node["node_type"] not in TABLE_TYPES:
                continue
            entry = found.setdefault(target, {"ops": set(), "manual": False})
            entry["ops"].update(letters)
            entry["manual"] = entry["manual"] or edge_id.startswith("link:")
    return found


def _table_fact(index: GraphIndex, table_id: str) -> dict[str, Any]:
    node = index.nodes[table_id]
    return {"id": table_id, "name": ref_name(node), "qualified_name": node["qualified_name"] or node["technical_name"],
            "node_type": node["node_type"], "system": node["system"]}


def feature_data(index: GraphIndex, tree: dict[str, Any], feature_id: str, limit: int = MAX_DATA_TABLES) -> dict[str, Any]:
    """Tables of one feature and its CRUD matrix: one row per flow (its own walk, as on the flow page), plus a row
    for the whole feature when the feature reaches tables no flow does. At most ``limit`` tables: written ones
    first, then those more flows touch."""
    item = find_item(tree, feature_id)
    if not item or item["kind"] != "feature":
        raise BusinessError("not_found", "Feature not found", 404)
    rows: list[dict[str, Any]] = []
    for flow in (child for child in item.get("children", []) if child["kind"] == "flow"):
        entry = flow.get("entry_node_id")
        touched = _touches(index, index.reach([entry], MAX_FLOW_NODES)) if entry in index.nodes else {}
        rows.append({"id": flow["id"], "name": flow["name"], "kind": "flow", "touched": touched})
    whole = _touches(index, index.reach([item["entry_node_id"], *item.get("extra_entries", [])], MAX_FEATURE_NODES))
    in_flows = {table_id for row in rows for table_id in row["touched"]}
    if not rows or set(whole) - in_flows:
        rows.append({"id": feature_id, "name": "Toàn tính năng" if rows else item["name"], "kind": "feature", "touched": whole})
    tables: dict[str, dict[str, Any]] = {}
    for row in rows:
        for table_id, touch in row["touched"].items():
            entry = tables.setdefault(table_id, {"ops": set(), "manual": False, "rows": 0})
            entry["ops"] |= touch["ops"]
            entry["manual"] = entry["manual"] or touch["manual"]
            entry["rows"] += 1
    ranked = sorted(tables, key=lambda table_id: (not (tables[table_id]["ops"] - {"R"}), -tables[table_id]["rows"],
                                                  ref_name(index.nodes[table_id])))
    limit = max(1, min(int(limit or MAX_DATA_TABLES), MAX_DATA_TABLES))
    kept = ranked[:limit]
    shown = set(kept)
    return {
        "feature": {"id": feature_id, "name": item["name"]},
        "tables": [{**_table_fact(index, table_id), "ops": crud_text(tables[table_id]["ops"]),
                    "manual": tables[table_id]["manual"]} for table_id in kept],
        "rows": [{"id": row["id"], "name": row["name"], "kind": row["kind"],
                  "cells": {table_id: crud_text(touch["ops"]) for table_id, touch in row["touched"].items() if table_id in shown}}
                 for row in rows],
        "total": len(tables), "truncated": len(ranked) > limit, "omitted": max(0, len(ranked) - limit), "limit": limit,
    }


def _callers(index: GraphIndex) -> dict[str, list[str]]:
    """Reverse adjacency of the walkable edges (kept on the index: it is rebuilt with it)."""
    cached = getattr(index, "_callers_cache", None)
    if cached is not None and cached[0] is index.manual:
        return cached[1]
    reverse: dict[str, list[str]] = {}
    for source in set(index.out) | set(index.manual):
        for target, edge_type, edge_id in index.edges_from(source):
            if index._ok(target, edge_type, edge_id):
                reverse.setdefault(target, []).append(source)
    index._callers_cache = (index.manual, reverse)
    return reverse


def _features(tree: dict[str, Any]) -> list[dict[str, Any]]:
    out, stack = [], list(tree["menus"])
    while stack:
        item = stack.pop()
        if item["kind"] == "feature":
            out.append(item)
        stack.extend(child for child in item.get("children", []) if child["kind"] in {"menu", "feature"})
    return out


def table_usage(index: GraphIndex, tree: dict[str, Any], table_id: str, limit: int = MAX_USAGE) -> dict[str, Any]:
    """Who reads or writes ``table_id``: the code with a data edge to it (``accessors``) and the features whose walk
    reaches one of them (``features``, with the CRUD letters of that walk). Features that are tables themselves
    (the "Dữ liệu" menu) are left out."""
    node = index.nodes.get(table_id)
    if node is None or node["node_type"] not in TABLE_TYPES:
        raise BusinessError("not_found", "Table not found", 404)
    reverse = _callers(index)
    accessors: dict[str, set[str]] = {}
    for source in reverse.get(table_id, []):
        for target, edge_type, _edge_id in index.edges_from(source):
            if target == table_id and edge_type in CRUD:
                accessors.setdefault(source, set()).update(CRUD[edge_type])
    seen: set[str] = set(accessors)
    queue = deque(accessors)
    while queue and len(seen) < MAX_CALLERS:
        here = queue.popleft()
        for caller in reverse.get(here, []):
            if caller not in seen and index.nodes[caller]["node_type"] not in TERMINAL_TYPES:
                seen.add(caller)
                queue.append(caller)
    limit = max(1, min(int(limit or MAX_USAGE), MAX_USAGE))
    features = []
    for item in _features(tree):
        if item["entry_type"] in TABLE_TYPES:
            continue
        entries = [item["entry_node_id"], *item.get("extra_entries", [])]
        if not any(entry in seen for entry in entries) and not any(entry in seen for entry in item.get("flow_entries", [])):
            continue
        reached = index.reach(entries, MAX_FEATURE_NODES)
        touch = _touches(index, reached).get(table_id)
        if touch is None:
            # Beyond the feature walk's node cap: still a user of the table, the letters from the flows' walks.
            letters = set()
            for flow in (child for child in item.get("children", []) if child["kind"] == "flow"):
                entry = flow.get("entry_node_id")
                if entry in index.nodes:
                    found = _touches(index, index.reach([entry], MAX_FLOW_NODES)).get(table_id)
                    letters |= found["ops"] if found else set()
            if not letters:
                continue
            touch = {"ops": letters, "manual": False}
        features.append({"id": item["id"], "name": item["name"], "route": item.get("route", ""),
                         "kind": FEATURE_KINDS.get(item["entry_type"], "other"), "entry_type": item["entry_type"],
                         "ops": crud_text(touch["ops"]), "manual": touch["manual"]})
    features.sort(key=lambda feature: (not (set(feature["ops"]) - {"R"}), feature["kind"], feature["name"]))
    code = sorted(({"id": node_id, "name": ref_name(index.nodes[node_id]), "node_type": index.nodes[node_id]["node_type"],
                    "system": index.nodes[node_id]["system"], "ops": crud_text(letters)} for node_id, letters in accessors.items()),
                  key=lambda entry: (not (set(entry["ops"]) - {"R"}), entry["name"]))
    return {"table": _table_fact(index, table_id), "ops": crud_text(set().union(*accessors.values()) if accessors else set()),
            "features": features[:limit], "accessors": code[:limit],
            "total_features": len(features), "total_accessors": len(code),
            "truncated": len(features) > limit or len(code) > limit}
