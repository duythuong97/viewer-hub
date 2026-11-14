"""Search over features, flows and nodes; which features reach a node."""
from __future__ import annotations

import sqlite3
from typing import Any


from .common import BusinessError, MAX_FEATURE_NODES, MAX_FLOW_NODES
from .flows import node_facts
from .graph import GraphIndex, ref_name
from .tree import _docs


_NODE_FLOWS: dict[str, Any] = {}


def node_flows(index: GraphIndex, tree: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    """node id -> the features and flows that reach it, built once per (graph, tree) instead of per request."""
    key = (id(index), id(tree))
    if _NODE_FLOWS.get("key") == key:
        return _NODE_FLOWS["value"]
    found: dict[str, list[dict[str, str]]] = {}
    # Features at any depth (system > group > section), screens and jobs first: they are what a person
    # looks for when asking where a piece of code is used.
    located: list[tuple[str, dict[str, Any]]] = []
    stack = [(menu, menu["name"]) for menu in tree["menus"]]
    while stack:
        item, path = stack.pop(0)
        for child in item.get("children", []):
            if child["kind"] == "feature":
                located.append((path, child))
            elif child["kind"] == "menu":
                stack.append((child, f"{path} / {child['name']}"))
    rank = {"SCREEN": 0, "JOB_NETWORK": 1, "EXECUTABLE": 2}
    located.sort(key=lambda pair: rank.get(pair[1].get("entry_type"), 3))
    for path, feature in located:
        for node_id in index.reach([feature["entry_node_id"], *feature.get("extra_entries", [])], MAX_FEATURE_NODES):
            found.setdefault(node_id, []).append({"kind": "feature", "id": feature["id"], "name": feature["name"], "path": path})
        for flow in feature["children"]:
            if not flow.get("entry_node_id"):
                continue
            for node_id in index.reach([flow["entry_node_id"]], MAX_FLOW_NODES):
                found.setdefault(node_id, []).append({"kind": "flow", "id": flow["id"], "name": flow["name"],
                                                      "path": f"{path} / {feature['name']}", "feature_id": feature["id"]})
    _NODE_FLOWS.update(key=key, value=found, tree=tree, index=index)  # keep both alive so their ids stay unique
    return found


def node_page(db: sqlite3.Connection, index: GraphIndex, tree: dict[str, Any], node_id: str) -> dict[str, Any]:
    """One code node: its display facts and every documented flow that reaches it."""
    if node_id not in index.nodes:
        raise BusinessError("not_found", "Node not found", 404)
    flows = [{key: hit[key] for key in ("id", "name", "path")} for hit in node_flows(index, tree).get(node_id, []) if hit["kind"] == "flow"]
    return {"node": node_facts(db, index, [node_id])[node_id], "flows": flows}


def search_nodes(db: sqlite3.Connection, index: GraphIndex, tree: dict[str, Any], query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Code nodes matching the query, each with the feature and flow that reach it (if any)."""
    if len(query.strip()) < 2:
        return []
    like = f"%{query.strip()}%"
    rows = db.execute(
        """SELECT node_id FROM graph_nodes WHERE node_type NOT IN ('COLUMN') AND (technical_name LIKE ? COLLATE NOCASE
             OR default_display_name LIKE ? COLLATE NOCASE OR qualified_name LIKE ? COLLATE NOCASE
             OR node_id IN (SELECT target_id FROM graph_localization WHERE value LIKE ? COLLATE NOCASE))
           ORDER BY CASE WHEN technical_name=? COLLATE NOCASE THEN 0 ELSE 1 END, length(technical_name), node_id LIMIT ?""",
        (like, like, like, like, query.strip(), limit),
    ).fetchall()
    reach = node_flows(index, tree)
    results = []
    for (node_id,) in rows:
        if node_id not in index.nodes:
            continue
        node = index.nodes[node_id]
        hit = {"kind": "node", "id": node_id, "label": ref_name(node), "node_type": node["node_type"], "feature_id": None, "flow_id": None}
        owners = reach.get(node_id, [])
        feature = next((owner for owner in owners if owner["kind"] == "feature"), None)
        if feature:
            hit["feature_id"], hit["path"] = feature["id"], feature["name"]
            flow = next((owner for owner in owners if owner["kind"] == "flow" and owner["feature_id"] == feature["id"]), None)
            if flow:
                hit["flow_id"], hit["path"] = flow["id"], f"{feature['name']} / {flow['name']}"
        results.append(hit)
    return results


def search(db: sqlite3.Connection, tree: dict[str, Any], query: str, limit: int = 30) -> list[dict[str, Any]]:
    tokens = [token for token in query.lower().split() if token]
    if not tokens:
        return []
    docs = _docs(db)
    results = []

    def hit(text: str) -> bool:
        lowered = text.lower()
        return all(token in lowered for token in tokens)

    stack = [(item, []) for item in tree["menus"]]
    while stack and len(results) < limit:
        item, trail = stack.pop(0)
        path = " / ".join(trail)
        if item["kind"] in {"menu", "feature"} and hit(f"{item['name']} {item.get('route', '')} {item.get('description', '')}"):
            results.append({"kind": item["kind"], "id": item["id"], "label": item["name"], "path": path, "route": item.get("route", "")})
        if item["kind"] == "flow":
            doc = docs.get(item["id"], {}).get("doc", {})
            if hit(f"{item['name']} {(doc.get('summary') or {}).get('text', '')}"):
                results.append({"kind": "flow", "id": item["id"], "label": item["name"], "path": path, "has_doc": item["has_doc"]})
            for step in doc.get("steps", []):
                if hit(f"{step.get('name', '')} {step.get('text', '')}"):
                    results.append({"kind": "step", "id": item["id"], "step_id": step["id"], "label": step.get("name") or step["id"],
                                    "path": f"{path} / {item['name']}"})
                for rule in step.get("rules", []):
                    if hit(f"{rule.get('title', '')} {rule.get('text', '')}"):
                        results.append({"kind": "rule", "id": item["id"], "step_id": step["id"], "label": rule.get("title", ""),
                                        "path": f"{path} / {item['name']}"})
        stack.extend((child, [*trail, item["name"]]) for child in item.get("children", []))
    return results[:limit]
