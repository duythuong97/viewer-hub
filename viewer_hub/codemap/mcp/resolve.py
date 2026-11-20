"""Names in a document (screen, API, table, job, Japanese / English logical names) to graph nodes.

One resolver for ``codemap_resolve`` and every write tool that takes node references, over the same search
index as ``codemap_search`` (search_nodes names and logical names, search_terms, the business dictionary).
A reference resolves only when exactly one node carries that name; otherwise the caller gets candidates and
must pick a node id, so nothing is ever written against a guessed node.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from viewer_hub.codemap.business.common import REF_KEYS
from viewer_hub.codemap.contract.search_tokens import compact
from viewer_hub.codemap.retriever import GraphNode, Retriever

MAX_NAMES = 20
MAX_CANDIDATES = 5
# Never what a document means by a name unless asked for by type: columns repeat across tables, unresolved
# references are the extractor's placeholders, files and folders are containers.
HIDDEN_TYPES = frozenset({"COLUMN", "UNRESOLVED_REFERENCE", "FILE", "DIRECTORY"})
_PREFIX = re.compile(r"^([a-z_]+):\s+(.+)$")
_TYPES_BY_KEY: dict[str, set[str]] = {}
for _type, _key in REF_KEYS.items():
    _TYPES_BY_KEY.setdefault(_key, set()).add(_type)


@dataclass
class Candidate:
    node_id: str
    type: str
    name: str
    logical: str
    system: str
    score: float

    def line(self) -> str:
        logical = f" ({self.logical})" if self.logical else ""
        where = f" · {self.system}" if self.system else ""
        return f"{self.type} {self.name}{logical}{where} · id `{self.node_id}` · score {self.score:.1f}"


@dataclass
class Resolution:
    query: str
    status: str  # exact | ambiguous | none
    candidates: list[Candidate] = field(default_factory=list)

    @property
    def node_id(self) -> str | None:
        return self.candidates[0].node_id if self.status == "exact" else None

    def lines(self) -> list[str]:
        if self.status == "exact":
            return [f"- `{self.query}` → exact: {self.candidates[0].line()}"]
        if self.status == "none":
            return [f"- `{self.query}` → none: no node carries this name (outside the scanned sources, or a "
                    "different name in the code; try codemap_search)"]
        lines = [f"- `{self.query}` → ambiguous: {len(self.candidates)} candidate(s); give the node id"]
        lines.extend(f"  - {candidate.line()}" for candidate in self.candidates)
        return lines


def node_types(value: str | None) -> set[str] | None:
    """``TABLE``, ``table`` or ``api`` (the short keys of node refs) as a set of node types."""
    text = (value or "").strip()
    if not text:
        return None
    types: set[str] = set()
    for part in re.split(r"[,|\s]+", text):
        if part:
            types |= _TYPES_BY_KEY.get(part.lower(), {part.upper()})
    return types


def _logical(names: str) -> list[str]:
    """search_nodes.names is ``ja:注文ID; en:Order ID``."""
    return [part.split(":", 1)[1].strip() if re.match(r"^[a-z]{2,3}:", part.strip()) else part.strip()
            for part in names.split(";") if part.strip()]


def _systems(retriever: Retriever, ids: list[int]) -> dict[int, tuple[str, ...]]:
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    return {int(row[0]): tuple(str(value) for value in row[1:] if value)
            for row in retriever.db.execute(
                f"SELECT id, system, repository, database FROM search_nodes WHERE id IN ({marks})", ids)}


def _exact(node: GraphNode, query: str) -> bool:
    whole = compact(query)
    if not whole:
        return False
    if whole in {compact(node.name), compact(node.qualified_name), *(compact(name) for name in _logical(node.names))}:
        return True
    if "." in query and " " not in query:
        owner, tail = query.rsplit(".", 1)
        return compact(tail) == compact(node.name) and compact(owner) in compact(node.qualified_name)
    return False


def resolve_name(retriever: Retriever, query: str, node_type: str | None = None, system: str | None = None) -> Resolution:
    query = query.strip()
    types = node_types(node_type)
    name = query
    prefixed = _PREFIX.match(query)
    if prefixed and prefixed.group(1) in _TYPES_BY_KEY:
        if types is None:  # "table: ORDER_HEADER", the ref form codemap_get_flow_doc uses
            types = set(_TYPES_BY_KEY[prefixed.group(1)])
        name = prefixed.group(2).strip()
    wanted_system = (system or "").strip().lower()

    def keep(node: GraphNode, where: tuple[str, ...]) -> bool:
        if types is not None and node.type not in types:
            return False
        if types is None and node.type in HIDDEN_TYPES:
            return False
        return not wanted_system or any(value.lower() == wanted_system for value in where)

    direct = retriever.db.execute("SELECT id FROM search_nodes WHERE stable_id=?", (query,)).fetchone()
    if direct:
        node = retriever.nodes([int(direct[0])])[0]
        where = _systems(retriever, [node.id]).get(node.id, ())
        return Resolution(query, "exact", [_candidate(node, where, 0.0)])

    scored = dict((node.id, (node, score)) for node, score in retriever.scored_nodes(name, 30))
    # The name index skips very common words; an exact technical or logical name is looked up directly too.
    tail = name.rsplit(".", 1)[-1] if " " not in name else name
    rows = retriever.db.execute(
        "SELECT id FROM search_nodes WHERE name = ? COLLATE NOCASE OR name = ? COLLATE NOCASE OR instr(names, ?) > 0 LIMIT 60",
        (name, tail, name),
    ).fetchall()
    extra = [int(row[0]) for row in rows if int(row[0]) not in scored]
    for node in retriever.nodes(extra):
        scored[node.id] = (node, 0.0)
    systems = _systems(retriever, list(scored))
    kept = [(node, score) for node, score in scored.values() if keep(node, systems.get(node.id, ()))]
    kept.sort(key=lambda item: -item[1])
    exact = [(node, score) for node, score in kept if _exact(node, name)]
    if len(exact) == 1:
        node, score = exact[0]
        return Resolution(query, "exact", [_candidate(node, systems.get(node.id, ()), score)])
    pool = exact or kept
    if not pool:
        return Resolution(query, "none")
    return Resolution(query, "ambiguous",
                      [_candidate(node, systems.get(node.id, ()), score) for node, score in pool[:MAX_CANDIDATES]])


def candidates(retriever: Retriever, text: str, *, exclude: set[str] = frozenset(), limit: int = MAX_CANDIDATES) -> list[Candidate]:
    """Best search hits for a free text (an unresolved name, a dynamic SQL snippet), hidden types left out."""
    found = []
    hits = [(node, score) for node, score in retriever.scored_nodes(text, 30)
            if node.type not in HIDDEN_TYPES and node.stable_id not in exclude]
    systems = _systems(retriever, [node.id for node, _ in hits[:limit]])
    for node, score in hits[:limit]:
        found.append(_candidate(node, systems.get(node.id, ()), score))
    return found


def _candidate(node: GraphNode, where: tuple[str, ...], score: float) -> Candidate:
    return Candidate(node.stable_id, node.type, node.name, " / ".join(_logical(node.names)[:3]),
                     where[0] if where else "", score)
