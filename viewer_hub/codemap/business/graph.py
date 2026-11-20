"""The graph as the business layer sees it (GraphIndex), manual links applied, node naming."""
from __future__ import annotations

import hashlib
import re
import sqlite3
import threading
from collections import deque
from pathlib import Path
from typing import Any, Iterable


from viewer_hub.codemap.contract.vocabulary import FOLLOW_EDGES, READ_EDGES, WRITE_EDGES, follows
from .common import REF_KEYS, TERMINAL_TYPES, _json


class GraphIndex:
    """Nodes and outgoing edges of codemap.sqlite, loaded once per extract."""

    def __init__(self, db: sqlite3.Connection) -> None:
        # Columns are left out: a large schema has hundreds of thousands of them and no flow walks through them.
        # Only screens need their properties (the route), so other rows skip the JSON parse.
        self.nodes: dict[str, dict[str, Any]] = {}
        self.by_type: dict[str, list[str]] = {}
        for row in db.execute(
            "SELECT node_id,node_type,technical_name,qualified_name,default_display_name,"
            "CASE WHEN node_type='SCREEN' THEN properties_json ELSE NULL END,system_key,database_key,repository_key "
            "FROM graph_nodes WHERE node_type<>'COLUMN'"
        ):
            node = {
                "node_id": row[0], "node_type": row[1], "technical_name": row[2] or "", "qualified_name": row[3] or "",
                "display_name": row[4] or row[2] or row[0], "properties": _json(row[5], {}),
                "system": system_of(row[1], row[6], row[7], row[8], row[0]),
                # The system that owns the code (tree grouping): routines and SQL files sit with their repository.
                "owner": row[6] or row[8] or row[7] or ("Jobnet" if row[1] in JOB_TYPES else "Khác"),
            }
            self.nodes[row[0]] = node
            self.by_type.setdefault(row[1], []).append(row[0])
        # Only edges a walk can follow are kept, which drops the structural bulk (table → column, project → file).
        self.out: dict[str, list[tuple[str, str, str]]] = {}
        kinds = sorted(FOLLOW_EDGES | {"CONTAINS"})
        for edge_id, source, target, edge_type in db.execute(
            f"SELECT edge_id,source_node_id,target_node_id,edge_type FROM graph_edges "
            f"WHERE graph_layer<>'DATA_FLOW' AND edge_type IN ({','.join('?' * len(kinds))})", kinds,
        ):
            if source not in self.nodes or target not in self.nodes or not self.follows(target, edge_type):
                continue
            self.out.setdefault(source, []).append((target, edge_type, edge_id))
        self._reach: dict[tuple, list[str]] = {}
        # Hand-made links (kn.biz_links), replaced as a whole when the knowledge db changes.
        self.manual: dict[str, list[tuple[str, str, str]]] = {}
        self._manual_key: tuple = ()

    def set_links(self, rows: Iterable[tuple[str, str, str, str]]) -> None:
        """Use these hand-made links (link_id, source, target, edge_type) on top of the extracted edges."""
        rows = tuple(sorted(tuple(row) for row in rows))
        if rows == self._manual_key:
            return
        manual: dict[str, list[tuple[str, str, str]]] = {}
        for link_id, source, target, edge_type in rows:
            if source in self.nodes and target in self.nodes and source != target:
                manual.setdefault(source, []).append((target, edge_type, f"link:{link_id}"))
        # New objects, never mutated: a request still walking the old ones finishes on a consistent view.
        self.manual, self._reach, self._manual_key = manual, {}, rows

    def edges_from(self, node_id: str) -> list[tuple[str, str, str]]:
        extra = self.manual.get(node_id)
        return [*self.out.get(node_id, ()), *extra] if extra else self.out.get(node_id, [])

    def _ok(self, target: str, edge_type: str, edge_id: str) -> bool:
        # A hand-made link is followed as drawn; the extracted ones by the shared walk rule.
        return edge_id.startswith("link:") or self.follows(target, edge_type)

    def follows(self, target: str, edge_type: str) -> bool:
        # The rule every flow walk shares (contract/vocabulary.py, codemap/flows.py).
        return edge_type in READ_EDGES | WRITE_EDGES or follows(edge_type, self.nodes[target]["node_type"])

    def reach(self, entries: Iterable[str], limit: int) -> list[str]:
        """Breadth-first walk from the entries; data nodes end a path."""
        entries = tuple(entries)
        key = (entries, limit)
        if key not in self._reach:
            self._reach[key] = self._walk(entries, limit)
        return self._reach[key]

    def _walk(self, entries: tuple[str, ...], limit: int) -> list[str]:
        seen: dict[str, None] = {}
        queue = deque(node_id for node_id in entries if node_id in self.nodes)
        while queue and len(seen) < limit:
            node_id = queue.popleft()
            if node_id in seen:
                continue
            seen[node_id] = None
            if self.nodes[node_id]["node_type"] in TERMINAL_TYPES:
                continue
            for target, edge_type, edge_id in self.edges_from(node_id):
                if target not in seen and self._ok(target, edge_type, edge_id):
                    queue.append(target)
        return list(seen)

    def edges_within(self, node_ids: Iterable[str]) -> list[dict[str, str]]:
        members = set(node_ids)
        return [
            {"edge_id": edge_id, "source": source, "target": target, "edge_type": edge_type,
             **({"manual": True} if edge_id.startswith("link:") else {})}
            for source in members
            for target, edge_type, edge_id in self.edges_from(source)
            if target in members and self._ok(target, edge_type, edge_id)
        ]

    def children(self, node_id: str, edge_type: str, node_type: str) -> list[str]:
        return [t for t, kind, _ in self.edges_from(node_id) if kind == edge_type and self.nodes[t]["node_type"] == node_type]


def screen_actions(index: GraphIndex, screen_id: str) -> list[str]:
    """UI actions of a screen: its own, then those of every component its template renders, at any depth
    (a button inside a child component is a flow of the screen too)."""
    actions = list(index.children(screen_id, "CONTAINS", "UI_ACTION"))
    seen: set[str] = set()
    frontier = index.children(screen_id, "BELONGS_TO", "ANGULAR_COMPONENT")
    while frontier:
        component = frontier.pop(0)
        if component in seen:
            continue
        seen.add(component)
        actions.extend(index.children(component, "CONTAINS", "UI_ACTION"))
        frontier.extend(index.children(component, "RENDERS", "ANGULAR_COMPONENT"))
    return list(dict.fromkeys(actions))


_INDEX_CACHE: dict[str, tuple[tuple[int, int], GraphIndex]] = {}


_INDEX_LOCK = threading.Lock()
MAX_CACHED_INDEXES = 2  # a 1.2 GB extract's index holds ~300 MB of RAM


def graph_index(db: sqlite3.Connection, web_path: Path) -> GraphIndex:
    stat = web_path.stat()
    key = (stat.st_size, stat.st_mtime_ns)
    cached = _INDEX_CACHE.get(str(web_path))
    if cached and cached[0] == key:
        return cached[1]
    from viewer_hub.codemap.storage import clear_deadline, set_deadline  # storage imports this module's schema

    # One load at a time: concurrent calls after a pack update wait for it instead of each holding a copy.
    with _INDEX_LOCK:
        cached = _INDEX_CACHE.get(str(web_path))
        if cached and cached[0] == key:
            return cached[1]
        # Loaded once per extract, so it is not held to one request's query time.
        clear_deadline(db)
        index = GraphIndex(db)
        set_deadline(db)
        after = web_path.stat()
        if (after.st_size, after.st_mtime_ns) == key:  # not replaced by an extract while it was read
            # One entry per pack (several code-map packs can be active); an older copy of the same file goes.
            _INDEX_CACHE.pop(str(web_path), None)
            while len(_INDEX_CACHE) >= MAX_CACHED_INDEXES:
                _INDEX_CACHE.pop(next(iter(_INDEX_CACHE)))
            _INDEX_CACHE[str(web_path)] = (key, index)
    apply_links(db, index)
    return index


def apply_links(db: sqlite3.Connection, index: GraphIndex) -> None:
    """Put the hand-made links of the attached knowledge db (``kn``) on the index; an end whose node is gone
    from this extract is first looked up again by the name the link stored (``relink``)."""
    try:
        rows = db.execute("SELECT link_id,source_id,target_id,edge_type FROM kn.biz_links").fetchall()
    except sqlite3.OperationalError:  # no knowledge db attached (search-only connections)
        rows = []
    if any(row[1] not in index.nodes or row[2] not in index.nodes for row in rows):
        from .links import relink  # links imports this module

        if relink(db, index):
            rows = db.execute("SELECT link_id,source_id,target_id,edge_type FROM kn.biz_links").fetchall()
    index.set_links(tuple(row) for row in rows)


def graph_hash(web_path: Path) -> str:
    stat = web_path.stat()
    return hashlib.sha1(f"{stat.st_size}:{stat.st_mtime_ns}".encode()).hexdigest()[:12]


DATABASE_TYPES = frozenset({"TABLE", "VIEW", "MATERIALIZED_VIEW", "COLUMN", "SEQUENCE", "SYNONYM", "PROCEDURE", "FUNCTION",
                            "TRIGGER", "PLSQL_PACKAGE", "DATABASE", "DATABASE_SCHEMA", "INLINE_SQL", "SQL_FILE"})
JOB_TYPES = frozenset({"JOB_NETWORK", "JOB"})


def system_of(node_type: str, system_key: str | None, database_key: str | None, repository_key: str | None, node_id: str) -> str:
    """The system a node runs in, for swimlanes: the database for DB objects, the repository for code."""
    if node_type in JOB_TYPES:
        return "Jobnet"
    if node_type in {"EXTERNAL_DATABASE_OBJECT", "DATABASE_LINK"}:
        return database_key or "Hệ thống ngoài"
    if node_type in {"EXTERNAL_API_OPERATION", "EXTERNAL_SYSTEM"}:
        return system_key or "Hệ thống ngoài"
    if node_type == "UNRESOLVED_REFERENCE":
        # A table or routine nobody resolved still lives in the database it was referenced from.
        return database_key if database_key and database_key not in {"DEFERRED", "UNKNOWN"} else "Chưa xác định"
    if node_type in DATABASE_TYPES and database_key:
        return database_key
    return repository_key or system_key or database_key or "Khác"


def ref_name(node: dict[str, Any]) -> str:
    """The name a document uses for a node: Class.method for code, the technical name otherwise."""
    technical = node["technical_name"]
    if node["node_type"] in {"METHOD", "LOCAL_ROUTINE", "UI_ACTION", "PROCEDURE", "FUNCTION"} and "." not in technical:
        parts = [part for part in re.split(r"[.:]", node["qualified_name"]) if part]
        if len(parts) >= 2 and parts[-1] == technical and not parts[-2].lower() in {"cs", "ts", "sql", "js"}:
            return f"{parts[-2]}.{technical}"
    return technical or node["display_name"]


def ref_of(node: dict[str, Any]) -> str:
    return f"{REF_KEYS.get(node['node_type'], node['node_type'].lower())}: {ref_name(node)}"


def feature_labels(index: GraphIndex, node_ids: Iterable[str]) -> dict[str, tuple[str, str]]:
    """(ref, name) for each node, unique within the set: two nodes with the same name (the same table in two
    databases) are told apart by their system, e.g. `table: DB2.ORDER_HEADER`."""
    ids = [node_id for node_id in dict.fromkeys(node_ids) if node_id in index.nodes]
    counts: dict[str, int] = {}
    for node_id in ids:
        counts[ref_name(index.nodes[node_id])] = counts.get(ref_name(index.nodes[node_id]), 0) + 1
    labels: dict[str, tuple[str, str]] = {}
    taken: set[str] = set()
    for node_id in ids:
        node = index.nodes[node_id]
        name = ref_name(node)
        if counts[name] > 1:
            name = f"{node['system']}.{name}" if node.get("system") else name
            if name in taken:
                name = f"{name}#{node_id.rsplit(':', 1)[-1][:12]}"
        taken.add(name)
        labels[node_id] = (f"{REF_KEYS.get(node['node_type'], node['node_type'].lower())}: {name}", name)
    return labels
