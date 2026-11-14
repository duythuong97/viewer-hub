"""System / Application views of a graph: keep the nodes a level is about and join them through the rest.

Technical shows every node. Application keeps the MAIN nodes (screens, actions, APIs, routines, tables,
jobs); System keeps the entry points and the data. A kept node is joined to the next kept node a walk reaches
through hidden (technical) nodes, so a screen still connects to the table its API writes even though the
methods in between are hidden. Shared by the explorer (/flow) and the business flow page.
"""
from __future__ import annotations

import sqlite3
from collections import defaultdict
from typing import Any, Iterable

SYSTEM_TYPES = frozenset({
    "SCREEN", "UI_ACTION", "API_OPERATION", "JOB_NETWORK", "JOB", "EXECUTABLE", "COMMAND_MODE", "MESSAGE_TOPIC",
    "TABLE", "VIEW", "MATERIALIZED_VIEW", "EXTERNAL_SYSTEM", "EXTERNAL_API_OPERATION", "EXTERNAL_DATABASE_OBJECT",
    "API_CALL_REFERENCE",
})
# Technical nodes a level still needs: an HTTP call is where a frontend meets an API (the only node left when
# the backend is not in the graph), and a table missing from the catalog is still data.
APPLICATION_EXTRA_TYPES = frozenset({"API_CALL_REFERENCE"})
# Containment that is part of a flow (a screen's actions, a jobnet's jobs, a method's SQL, a package's routines).
FLOW_PART_TYPES = frozenset({"UI_ACTION", "JOB", "INLINE_SQL", "SQL_STATEMENT", "PROCEDURE", "FUNCTION", "LOCAL_ROUTINE"})


def keeps(level: str, node_type: str, graph_role: str, node_id: str = "") -> bool:
    if node_type == "UNRESOLVED_REFERENCE":
        return level == "TECHNICAL" or ":TABLE:" in node_id
    if level == "SYSTEM":
        return node_type in SYSTEM_TYPES
    if level == "APPLICATION":
        return graph_role == "MAIN" or node_type in APPLICATION_EXTRA_TYPES
    return True


def walkable(edge_type: str, graph_layer: str, target_type: str) -> bool:
    """Edges a flow walk follows: everything but structure, except containment of the parts that run."""
    if graph_layer != "STRUCTURAL":
        return True
    return edge_type == "CONTAINS" and target_type in FLOW_PART_TYPES


def bridge(kept: Iterable[str], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Edges between kept nodes: the direct ones, and one edge per kept pair joined through hidden nodes.

    ``edges`` hold ``edge_id``, ``source``, ``target``, ``edge_type`` (walkable edges only). A joined edge
    takes the type of its last hop (a write into a table stays a write) and records how many nodes it hides.
    """
    kept = set(kept)
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        out[edge["source"]].append(edge)
    result: dict[str, dict[str, Any]] = {}
    for start in sorted(kept):
        seen = {start}
        frontier = [(edge, 0) for edge in out.get(start, [])]
        while frontier:
            edge, hidden = frontier.pop()
            target = edge["target"]
            if target in kept:
                if target == start:
                    continue
                if hidden == 0:
                    result[edge["edge_id"]] = {**edge}
                else:
                    key = f"via:{start}>{target}:{edge['edge_type']}"
                    result.setdefault(key, {"edge_id": key, "source": start, "target": target,
                                            "edge_type": edge["edge_type"], "via": hidden})
                continue
            if target in seen:
                continue
            seen.add(target)
            frontier.extend((following, hidden + 1) for following in out.get(target, []))
    return [result[key] for key in sorted(result)]


# Lenses: which question the graph answers. The same edge matters for one and is noise for another, so nothing is
# dropped for good: what a lens leaves out is folded into a count on the node and opens on a click.
#   run  (Luồng chạy, default) calls, API calls, reads/writes; the types and injected services a method uses fold.
#   data (Dữ liệu)             Explore follows the paths to the data only (the W/R walk); the same folding.
#   deps (Phụ thuộc)           everything, USES included: what a change to a class or service reaches.
LENSES = ("run", "data", "deps")
# Edges to the things code uses rather than runs: a C# type, an injected service or repository, an ORM mapping.
FOLD_EDGES = frozenset({"USES", "MAPS_TO"})
# Nodes those edges point at. Standing on one of them (expanding the class itself) shows its USES edges in every
# lens: then "who uses this class" is the question.
DEPENDENCY_TYPES = frozenset({"CSHARP_TYPE", "SERVICE", "REPOSITORY", "ANGULAR_SERVICE"})


def folds(lens: str, edge_type: str, standing_type: str) -> bool:
    """True when the lens folds this edge at the node being expanded instead of drawing it."""
    return lens != "deps" and edge_type in FOLD_EDGES and standing_type not in DEPENDENCY_TYPES


def folded_counts(db: sqlite3.Connection, node_ids: Iterable[str], shown_edges: Iterable[str] = ()) -> dict[str, dict[str, Any]]:
    """Per node: how many USES/MAPS_TO edges leave it that are not drawn, by the type of what they reach."""
    ids = [node_id for node_id in dict.fromkeys(node_ids)]
    shown = set(shown_edges)
    result: dict[str, dict[str, Any]] = {}
    kinds = sorted(FOLD_EDGES)
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        rows = db.execute(
            f"SELECT e.edge_id,e.source_node_id,t.node_type,s.node_type FROM graph_edges e "
            f"JOIN graph_nodes t ON t.node_id=e.target_node_id JOIN graph_nodes s ON s.node_id=e.source_node_id "
            f"WHERE e.source_node_id IN ({','.join('?' * len(chunk))}) AND e.edge_type IN ({','.join('?' * len(kinds))})",
            [*chunk, *kinds])
        for edge_id, source, target_type, source_type in rows:
            if edge_id in shown or source_type in DEPENDENCY_TYPES:
                continue
            entry = result.setdefault(source, {"count": 0, "kinds": {}})
            entry["count"] += 1
            entry["kinds"][target_type] = entry["kinds"].get(target_type, 0) + 1
    return result
