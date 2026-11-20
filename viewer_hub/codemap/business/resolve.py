"""The names people and AI write for a node, to the node: one resolver for import files, MCP and links.

A node's **address** is ``<system> › <type> › <full name>``: ``order-api › method › Shop.Data.OrderRepository.Save``.
The full name is the name people use for the code (namespace, class, package), never its file, line or project;
the parameter list is added only when the name has overloads. A reference is looked up in levels and the first
level with exactly one node wins:

1. node id or the whole address;
2. ``type: name`` or the full name (the ``ref`` form documents and import files use);
3. the end of a full name: ``OrderRepository.Save``, ``Save``;
4. a logical name (Japanese / English name from the search index);
5. close spelling: case, ``_`` / ``-`` / spaces and one or two wrong letters.

Several nodes at a level: one of them among ``near`` (the flow's nodes, the other end of a link) wins, else the
caller gets the candidates and nothing is guessed.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Iterable

from viewer_hub.codemap.contract.addresses import SEPARATOR, assign, full_name, type_key  # noqa: F401
from viewer_hub.codemap.contract.search_tokens import compact

from .common import REF_KEYS
from .graph import GraphIndex, ref_name

MAX_CANDIDATES = 5
# Placeholders and containers are never what a written name means unless its type says so.
HIDDEN_TYPES = frozenset({"UNRESOLVED_REFERENCE", "FILE", "DIRECTORY", "SYSTEM"})
LEVEL_REASONS = {
    1: "đúng id / địa chỉ",
    2: "đúng tên đầy đủ",
    3: "khớp phần cuối tên",
    4: "khớp tên nghiệp vụ",
    5: "gần đúng chính tả",
}
_TYPE_PREFIX = re.compile(r"^([a-z_]+):\s*(.+)$")
_TYPES_BY_KEY: dict[str, set[str]] = {}
for _type, _key in REF_KEYS.items():
    _TYPES_BY_KEY.setdefault(_key, set()).add(_type)


@dataclass
class Candidate:
    node_id: str
    address: str
    ref: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {"node_id": self.node_id, "address": self.address, "ref": self.ref, "reason": self.reason}

    def line(self) -> str:
        return f"{self.address} (id `{self.node_id}`, {self.reason})"


@dataclass
class Resolution:
    query: str
    status: str  # match | ambiguous | none
    level: int = 0
    reason: str = ""
    candidates: list[Candidate] = field(default_factory=list)

    @property
    def node_id(self) -> str | None:
        return self.candidates[0].node_id if self.status == "match" else None

    def as_dict(self) -> dict[str, Any]:
        return {"query": self.query, "status": self.status, "level": self.level, "reason": self.reason,
                "candidates": [candidate.as_dict() for candidate in self.candidates]}

    def message(self) -> str:
        """One line for people and agents: why it matched, or what to pick."""
        if self.status == "match":
            return f"{self.query} → {self.candidates[0].address} ({self.reason})"
        if self.status == "none":
            return f"{self.query}: không có node nào mang tên này (ngoài phạm vi đã quét, hoặc code dùng tên khác)"
        return (f"{self.query}: {len(self.candidates)} node cùng tên, ghi địa chỉ hoặc id của một node: "
                + "; ".join(candidate.line() for candidate in self.candidates))


def _distance(a: str, b: str, limit: int) -> int:
    """Edit distance, stopping once it is above ``limit``."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, 1):
        current = [i]
        for j, char_b in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (char_a != char_b)))
        if min(current) > limit:
            return limit + 1
        previous = current
    return previous[-1]


class NameIndex:
    """Addresses and names of every node of one graph index, built once per index (see ``names``)."""

    def __init__(self, index: GraphIndex, logical: Iterable[tuple[str, str]] = ()) -> None:
        self.index = index
        self.full: dict[str, tuple[str, str]] = {node_id: full_name(node) for node_id, node in index.nodes.items()}
        # The same addresses the extract stores in graph_node_addresses (contract/addresses.py).
        self.address, _duplicates = assign(index.nodes.values())
        self.by_address = {address.lower(): node_id for node_id, address in self.address.items()}
        self.by_name: dict[str, list[str]] = {}
        self.by_tail: dict[str, list[str]] = {}
        self.by_compact: dict[str, list[str]] = {}
        for node_id, node in index.nodes.items():
            name, params = self.full[node_id]
            short = ref_name(node)
            for key in {name.lower(), (name + params).lower(), short.lower()}:
                self.by_name.setdefault(key, []).append(node_id)
            parts = name.split(".")
            for start in range(1, len(parts)):
                self.by_tail.setdefault(".".join(parts[start:]).lower(), []).append(node_id)
            for key in {compact(short), compact(".".join(parts[-2:]))}:
                if key:
                    self.by_compact.setdefault(key, []).append(node_id)
        self.by_logical: dict[str, list[str]] = {}
        for node_id, names in logical:
            if node_id in index.nodes:
                for part in str(names or "").split(";"):
                    text = part.split(":", 1)[1] if re.match(r"^\s*[a-z]{2,3}:", part) else part
                    if text.strip():
                        self.by_logical.setdefault(text.strip().lower(), []).append(node_id)

    # ----------------------------------------------------------------------------------------- lookup

    def candidate(self, node_id: str, reason: str) -> Candidate:
        node = self.index.nodes[node_id]
        return Candidate(node_id, self.address[node_id], f"{type_key(node['node_type'])}: {ref_name(node)}", reason)

    def resolve(self, value: Any, *, near: Iterable[str] = (), types: Iterable[str] | None = None,
                max_level: int = 5) -> Resolution:
        """``value`` is an id, address, ``type: name``, name or ``{type: name}``; ``near`` breaks ties."""
        if isinstance(value, dict) and len(value) == 1:
            key, name = next(iter(value.items()))
            value = f"{key}: {name}"
        query = str(value or "").strip()[:1000]
        if not query:
            return Resolution(query, "none")
        wanted_types = set(types) if types else None
        wanted_system = ""
        name = query
        if query in self.index.nodes:
            return Resolution(query, "match", 1, LEVEL_REASONS[1], [self.candidate(query, LEVEL_REASONS[1])])
        found = self.by_address.get(query.lower())
        if found:
            return Resolution(query, "match", 1, LEVEL_REASONS[1], [self.candidate(found, LEVEL_REASONS[1])])
        parts = [part.strip() for part in re.split(r"\s*[›>]\s*", query)] if "›" in query else []
        if len(parts) >= 3 and self._types(parts[1]):
            wanted_system, wanted_types, name = parts[0].lower(), wanted_types or self._types(parts[1]), \
                " › ".join(parts[2:])
        else:
            prefixed = _TYPE_PREFIX.match(query)
            if prefixed and self._types(prefixed.group(1)):
                wanted_types = wanted_types or self._types(prefixed.group(1))
                name = prefixed.group(2).strip()
        near_set = set(near)

        def keep(node_id: str) -> bool:
            node = self.index.nodes[node_id]
            if wanted_types is not None:
                if node["node_type"] not in wanted_types:
                    return False
            elif node["node_type"] in HIDDEN_TYPES:
                return False
            return not wanted_system or node["system"].lower() == wanted_system

        key = name.lower()
        steps = [
            (2, lambda: self.by_name.get(key, [])),
            (3, lambda: self.by_tail.get(key, [])),
            (4, lambda: self.by_logical.get(key, [])),
            (5, lambda: self._close(name)),
        ]
        for level, lookup in steps:
            if level > max_level:
                break
            ids = [node_id for node_id in dict.fromkeys(lookup()) if keep(node_id)]
            if not ids:
                continue
            reason = LEVEL_REASONS[level]
            if len(ids) == 1:
                return Resolution(query, "match", level, reason, [self.candidate(ids[0], reason)])
            close = [node_id for node_id in ids if node_id in near_set]
            if len(close) == 1:
                reason = f"{reason}, cùng luồng"
                return Resolution(query, "match", level, reason, [self.candidate(close[0], reason)])
            ordered = sorted(ids, key=lambda node_id: (node_id not in near_set, self.address[node_id]))
            return Resolution(query, "ambiguous", level, reason, [
                self.candidate(node_id, "cùng luồng" if node_id in near_set else self.index.nodes[node_id]["system"])
                for node_id in ordered[:MAX_CANDIDATES]
            ])
        return Resolution(query, "none")

    def _types(self, key: str) -> set[str] | None:
        """Node types of a type key: the short keys of refs (``api``, ``table``) or a node type in lower case
        (``sequence``, ``angular_component``), the form addresses use for types without a short key."""
        key = key.strip().lower()
        if key in _TYPES_BY_KEY:
            return set(_TYPES_BY_KEY[key])
        return {key.upper()} if key.upper() in self.index.by_type else None

    def _close(self, name: str) -> list[str]:
        """Names one or two letters away (two only for long names), closest first. A full name is compared by its
        last two parts (Class.method), the form the index keeps."""
        parts = name.split(":", 1)[-1].split(".")
        # Class.method first; the method name alone only when the class part matches nothing.
        for target in dict.fromkeys((compact(".".join(parts[-2:])), compact(parts[-1]))):
            found = self._close_to(target)
            if found:
                return found
        return []

    def _close_to(self, target: str) -> list[str]:
        best: dict[int, list[str]] = {}
        if len(target) >= 4:
            limit = 1 if len(target) < 10 else 2
            for key, ids in self.by_compact.items():
                if abs(len(key) - len(target)) > limit or key[:1] != target[:1]:
                    continue
                distance = _distance(key, target, limit)
                if distance <= limit:
                    best.setdefault(distance, []).extend(ids)
        return best[min(best)] if best else []


def names(index: GraphIndex, db: sqlite3.Connection | None = None) -> NameIndex:
    """The name index of a graph index, built on first use (logical names come from the search index, when the
    serving database has one)."""
    built = getattr(index, "_names", None)
    if built is None:
        logical: list[tuple[str, str]] = []
        if db is not None:
            try:
                logical = db.execute("SELECT stable_id, names FROM search_nodes WHERE names<>''").fetchall()
            except sqlite3.OperationalError:
                logical = []
        built = NameIndex(index, logical)
        index._names = built
    return built
