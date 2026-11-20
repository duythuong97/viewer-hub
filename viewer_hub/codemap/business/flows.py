"""Node facts and flows: skeletons, stored flow documents, semantic and system levels, feature detail."""
from __future__ import annotations

import sqlite3
from typing import Any


from viewer_hub.codemap.contract.vocabulary import READ_EDGES, WRITE_EDGES
from viewer_hub.codemap.levels import bridge, folded_counts, keeps, walkable
from .common import BusinessError, MAX_FEATURE_NODES, MAX_FLOW_NODES, _json
from .graph import GraphIndex, ref_name, ref_of
from .tree import find_item


def node_facts(db: sqlite3.Connection, index: GraphIndex, node_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Display facts for nodes: document name, file and line, localized names, business term."""
    facts = {
        node_id: {
            "node_id": node_id, "node_type": index.nodes[node_id]["node_type"], "name": ref_name(index.nodes[node_id]),
            "ref": ref_of(index.nodes[node_id]), "technical_name": index.nodes[node_id]["technical_name"],
            "display_name": index.nodes[node_id]["display_name"], "system": index.nodes[node_id]["system"],
            "file": "", "line": None, "names": {}, "term": "",
        }
        for node_id in node_ids if node_id in index.nodes
    }
    ids = list(facts)
    for chunk in _chunks(ids, 400):
        marks = ",".join("?" * len(chunk))
        for row in db.execute(
            f"SELECT target_id,source_path,start_line FROM graph_evidence WHERE target_type='NODE' AND target_id IN ({marks}) "
            "ORDER BY evidence_id", chunk,
        ):
            fact = facts[row[0]]
            if not fact["file"]:
                fact["file"], fact["line"] = row[1], row[2]
        for row in db.execute(
            f"SELECT target_id,locale,value FROM graph_localization WHERE field_name='name' AND target_id IN ({marks}) "
            "AND UPPER(review_status)<>'REJECTED'", chunk,
        ):
            facts[row[0]]["names"][row[1]] = row[2]
        for row in db.execute(
            f"""SELECT m.target_id, COALESCE(vi.label, en.label, '') FROM graph_business_semantic_mappings m
                LEFT JOIN graph_business_semantics vi ON vi.semantic_id=m.semantic_id AND vi.locale='vi'
                LEFT JOIN graph_business_semantics en ON en.semantic_id=m.semantic_id AND en.locale='en'
                WHERE m.status='approved' AND m.target_id IN ({marks})""", chunk,
        ):
            facts[row[0]]["term"] = facts[row[0]]["term"] or row[1]
    return facts


def _chunks(values: list[str], size: int):
    for start in range(0, len(values), size):
        yield values[start:start + size]



def skeleton(index: GraphIndex, flow_id: str, entry: str | None, name: str = "") -> dict[str, Any]:
    """A flow document with one step per system the flow crosses, every text left for AI.

    The walk from the entry is breadth-first, so systems come in the order the flow reaches them
    (customer-web → order-api → ORDER_DB → …); each step then sits in one swimlane.
    """
    empty = {"id": flow_id, "name": name, "summary": {"text": "", "status": "ai"}, "facts": [], "steps": [],
             "edge_cases": {"items": [], "status": "ai"}}
    if not entry or entry not in index.nodes:
        return empty
    by_system: dict[str, list[str]] = {}
    for node_id in index.reach([entry], MAX_FLOW_NODES):
        by_system.setdefault(index.nodes[node_id]["system"], []).append(node_id)
    empty["steps"] = [
        {"id": f"s{position}", "system": system, "name": "", "actor": "", "text": "", "status": "ai", "nodes": members, "rules": []}
        for position, (system, members) in enumerate(by_system.items(), start=1)
    ]
    return empty


def load_flow(db: sqlite3.Connection, index: GraphIndex, tree: dict[str, Any], flow_id: str) -> dict[str, Any]:
    item = find_item(tree, flow_id)
    if not item or item["kind"] != "flow":
        raise BusinessError("not_found", "Flow not found", 404)
    row = db.execute("SELECT doc_json FROM kn.biz_flows WHERE flow_id=?", (flow_id,)).fetchone()
    doc = _json(row[0], {}) if row else skeleton(index, flow_id, item["entry_node_id"], item["name"])
    node_ids = list(dict.fromkeys(node_id for step in doc.get("steps", []) for node_id in step.get("nodes", [])))
    _mark_code_changed(db, doc, node_ids)
    if item["entry_node_id"] and item["entry_node_id"] in index.nodes:
        node_ids = list(dict.fromkeys([*node_ids, *index.reach([item["entry_node_id"]], MAX_FLOW_NODES)]))
    node_ids = [node_id for node_id in node_ids if node_id in index.nodes]
    feature = find_item(tree, item["feature_id"])
    return {
        "flow": {**doc, "id": flow_id, "name": doc.get("name") or item["name"]},
        "has_doc": bool(row), "feature_id": item["feature_id"], "feature_name": feature["name"] if feature else "",
        "path": _path(tree, flow_id), "nodes": list(node_facts(db, index, node_ids).values()),
        "edges": index.edges_within(node_ids), "entry_node_id": item["entry_node_id"],
        # The types and injected services each node uses: never part of the flow, shown as a count to open.
        "folded": folded_counts(db, node_ids),
        "levels": semantic_levels(db, node_ids, item["entry_node_id"], index),
    }


def _mark_code_changed(db: sqlite3.Connection, doc: dict[str, Any], flow_nodes: list[str]) -> None:
    """``code_changed`` on each part a person saved whose nodes behave differently in this extract."""
    from viewer_hub.codemap.knowledge import part_changed

    parts = [(doc.get("summary"), flow_nodes), (doc.get("edge_cases"), flow_nodes)]
    parts += [(step, step.get("nodes") or []) for step in doc.get("steps", [])]
    for part, nodes in parts:
        if isinstance(part, dict) and part_changed(db, part, nodes):
            part["code_changed"] = True


def semantic_levels(db: sqlite3.Connection, node_ids: list[str], entry: str | None,
                    index: GraphIndex | None = None) -> dict[str, dict[str, Any]]:
    """The flow graph at the System and Application levels (Technical is the flow itself).

    Application keeps the nodes codemap/levels.py keeps, joined through the hidden ones, so a screen still
    reaches the table its API writes. System draws one box per system the flow crosses (screen app, API,
    batch, database…, the swimlanes' systems) and one arrow per pair of systems that talk, labelled with what
    happens between them."""
    members = set(node_ids)
    info: dict[str, tuple[str, str]] = {}
    rows: list[dict[str, Any]] = []
    for start in range(0, len(node_ids), 500):
        chunk = node_ids[start:start + 500]
        marks = ",".join("?" * len(chunk))
        info.update({row[0]: (row[1], row[2]) for row in db.execute(
            f"SELECT node_id,node_type,graph_role FROM graph_nodes WHERE node_id IN ({marks})", chunk)})
        rows += [{"edge_id": e, "source": s, "target": t, "edge_type": k, "layer": layer} for e, s, t, k, layer in db.execute(
            f"SELECT edge_id,source_node_id,target_node_id,edge_type,graph_layer FROM graph_edges WHERE source_node_id IN ({marks}) ORDER BY edge_id",
            chunk) if t in members]
    walked = [row for row in rows if row["layer"] != "DATA_FLOW" and row["source"] != row["target"]
              and walkable(row["edge_type"], row["layer"], info.get(row["target"], ("", ""))[0])]
    result = {}
    if index is not None:
        manual = [{"edge_id": edge["edge_id"], "source": edge["source"], "target": edge["target"], "edge_type": edge["edge_type"]}
                  for edge in index.edges_within(node_ids) if edge.get("manual")]
        result["SYSTEM"] = system_level(index, node_ids, [*walked, *manual], entry)
    for level in ("APPLICATION",) if index is not None else ("SYSTEM", "APPLICATION"):
        kept = {node_id for node_id in node_ids if keeps(level, *info.get(node_id, ("", "")), node_id)}
        if entry in members:
            kept.add(entry)
        joined = bridge(kept, walked)
        result[level] = {
            "nodes": [node_id for node_id in node_ids if node_id in kept],
            "edges": [{"edge_id": edge["edge_id"], "source": edge["source"], "target": edge["target"], "edge_type": edge["edge_type"],
                       **({"via": edge["via"]} if "via" in edge else {})} for edge in joined],
        }
    return result


# What an arrow between two systems is called when several kinds of edge join them: the one that matters most.
_SYSTEM_EDGE_ORDER = ("INSERTS", "UPDATES", "MERGES", "DELETES", "WRITES", "LOADS_INTO", "READS", "REMOTE_READS",
                      "CALLS_API", "HANDLED_BY", "TRIGGERS_JOB", "TRIGGERS", "STARTS", "PUBLISHES", "CONSUMED_BY", "CALLS")


def system_level(index: GraphIndex, node_ids: list[str], edges: list[dict[str, Any]], entry: str | None) -> dict[str, Any]:
    """One node per system (``system:<key>``, with its member nodes) and one edge per ordered pair of systems."""
    system = {node_id: index.nodes[node_id]["system"] for node_id in node_ids if node_id in index.nodes}
    members: dict[str, list[str]] = {}
    for node_id in node_ids:
        if node_id in system:
            members.setdefault(system[node_id], []).append(node_id)
    nodes = []
    for key, ids in members.items():
        kinds: dict[str, int] = {}
        for node_id in ids:
            kinds[index.nodes[node_id]["node_type"]] = kinds.get(index.nodes[node_id]["node_type"], 0) + 1
        nodes.append({"node_id": f"system:{key}", "node_type": "SYSTEM", "name": key, "display_name": key, "system": key,
                      "members": ids, "kinds": dict(sorted(kinds.items(), key=lambda item: -item[1])), "synthetic": True})
    pairs: dict[tuple[str, str], dict[str, int]] = {}
    for edge in edges:
        source, target = system.get(edge["source"]), system.get(edge["target"])
        if source and target and source != target:
            kinds = pairs.setdefault((source, target), {})
            kinds[edge["edge_type"]] = kinds.get(edge["edge_type"], 0) + 1
    rank = {name: position for position, name in enumerate(_SYSTEM_EDGE_ORDER)}
    joined = []
    for (source, target), kinds in pairs.items():
        main = min(kinds, key=lambda kind: (rank.get(kind, len(rank)), kind))
        joined.append({"edge_id": f"sys:{source}>{target}", "source": f"system:{source}", "target": f"system:{target}",
                       "edge_type": main, "count": sum(kinds.values()), "kinds": kinds})
    return {"nodes": [node["node_id"] for node in nodes], "system_nodes": nodes, "edges": joined,
            "entry": f"system:{system[entry]}" if entry in system else (nodes[0]["node_id"] if nodes else None)}


def _path(tree: dict[str, Any], item_id: str) -> list[dict[str, str]]:
    def walk(items, trail):
        for item in items:
            here = [*trail, {"id": item["id"], "name": item["name"], "kind": item["kind"]}]
            if item["id"] == item_id:
                return here
            found = walk(item.get("children", []), here)
            if found:
                return found
        return None
    return walk(tree["menus"], []) or []


def feature_detail(db: sqlite3.Connection, index: GraphIndex, tree: dict[str, Any], feature_id: str) -> dict[str, Any]:
    item = find_item(tree, feature_id)
    if not item or item["kind"] not in {"feature", "menu"}:
        raise BusinessError("not_found", "Feature not found", 404)
    result = {**item, "path": _path(tree, feature_id)}
    if item["kind"] == "feature":
        node_ids = index.reach([item["entry_node_id"], *item.get("extra_entries", [])], MAX_FEATURE_NODES)
        writes, reads = set(), set()
        for source in node_ids:
            for target, edge_type, _ in index.edges_from(source):
                if edge_type in WRITE_EDGES:
                    writes.add(target)
                elif edge_type in READ_EDGES:
                    reads.add(target)
        name = lambda node_id: ref_name(index.nodes[node_id])  # noqa: E731
        result.update({
            "entry": {"node_id": item["entry_node_id"], "name": name(item["entry_node_id"]), "node_type": item["entry_type"]},
            "apis": sorted({name(n) for n in node_ids if index.nodes[n]["node_type"] == "API_OPERATION"}),
            "writes": sorted(name(n) for n in writes if n in index.nodes),
            "reads": sorted(name(n) for n in reads - writes if n in index.nodes),
            "node_count": len(node_ids),
            "last_export": _last_export(db, feature_id),
        })
    return result


def _last_export(db: sqlite3.Connection, feature_id: str) -> dict[str, str] | None:
    row = db.execute(
        "SELECT export_id,created_at FROM kn.biz_exports WHERE feature_id=? ORDER BY created_at DESC, export_id DESC LIMIT 1",
        (feature_id,),
    ).fetchone()
    return {"export_id": row[0], "created_at": row[1]} if row else None
