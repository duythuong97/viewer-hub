"""Gaps in the graph a link can close: calls, reads and writes the extract could not follow.

One list for people (the "Chỗ hở" page: *Nối* / *Không phải*) and agents (``codemap_knowledge_gaps kind=link``):

* an extractor issue on a code node that a document can explain (``LINK_ISSUES``: an unresolved call, a dynamic URL
  or SQL, a route that matched nothing);
* a placeholder node (``UNRESOLVED_REFERENCE``) code calls, reads or writes.

Left out: what an admin fixes in the input (``INPUT_ISSUES``: a table missing from the catalog, an executable not
scanned), noise that is never a missing link (Oracle built-ins, local variables, column names), gaps a link already
closes (its note carries ``[gap <id>]``) and gaps a person marked "Không phải" (``kn.biz_gap_dismissed``).
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any, Callable, Iterable

from viewer_hub.codemap.knowledge import has_table

from .common import BusinessError, _now
from .graph import GraphIndex, ref_of

LINK_ISSUES = frozenset({
    "UNRESOLVED_REFERENCE", "UNRESOLVED_CALL", "URL_DYNAMIC", "SQL_DYNAMIC", "ROUTE_AMBIGUOUS",
    "ROUTE_PREFIX_MISMATCH", "EXTRACTOR_CALL_UNBOUND",
})
INPUT_ISSUES = frozenset({"TABLE_NOT_IMPORTED", "JOB_EXECUTABLE_NOT_FOUND", "EXECUTABLE_NOT_MAPPED", "EXTERNAL_OBJECT"})
# The edge a gap most likely misses, by issue type; a placeholder keeps the edge code has to it.
EDGE_GUESS = {"URL_DYNAMIC": "CALLS_API", "ROUTE_AMBIGUOUS": "CALLS_API", "ROUTE_PREFIX_MISMATCH": "CALLS_API",
              "SQL_DYNAMIC": "READS", "DYNAMIC_SQL": "READS", "DYNAMIC_URL": "CALLS_API"}

# Oracle system packages and SQL functions: a call to them is not a call into the system's own code.
_BUILTIN_PREFIXES = ("DBMS_", "UTL_", "APEX_", "OWA_", "CTX_", "SYS.", "SYSTEM.", "STANDARD.")
_BUILTIN_CALLS = frozenset({
    "ABS", "ADD_MONTHS", "AVG", "CAST", "CEIL", "CHR", "COALESCE", "CONCAT", "COUNT", "DECODE", "EXTRACT", "FLOOR",
    "GREATEST", "INSTR", "LAST_DAY", "LEAST", "LENGTH", "LOWER", "LPAD", "LTRIM", "MAX", "MIN", "MOD", "MONTHS_BETWEEN",
    "NVL", "NVL2", "REGEXP_LIKE", "REGEXP_REPLACE", "REGEXP_SUBSTR", "REPLACE", "ROUND", "RPAD", "RTRIM", "SUBSTR",
    "SUM", "SYSDATE", "SYSTIMESTAMP", "TO_CHAR", "TO_DATE", "TO_NUMBER", "TRIM", "TRUNC", "UPPER", "SQLCODE", "SQLERRM",
    "RAISE_APPLICATION_ERROR", "COMMIT", "ROLLBACK", "ROWNUM", "ROWID", "LEVEL", "XMLTYPE", "XMLELEMENT", "XMLAGG",
})
# PL/SQL locals and parameters by the usual prefixes: L_RESULT.OBJECTS.EXISTS, V_COUNT, P_ORDER_ID, G_CACHE.
_LOCAL = re.compile(r"^(?:L|V|P|G|LV|LN|LR|LT|O|IO)_[A-Z0-9_$#]+(?:\.|$)", re.IGNORECASE)


def is_noise(name: str, columns: set[str]) -> bool:
    """A placeholder that never means a missing link: a built-in, a local variable or a column name."""
    text = name.strip().upper()
    if not text:
        return True
    if text.startswith(_BUILTIN_PREFIXES) or text.split("(", 1)[0] in _BUILTIN_CALLS:
        return True
    if _LOCAL.match(text):
        return True
    return "." not in text and text in columns


def gap_mark(gap_id: str) -> str:
    return f"[gap {gap_id}]"


def closed_by(db: sqlite3.Connection, gap_id: str) -> list[str]:
    """Links whose note names this gap."""
    return [row[0] for row in db.execute("SELECT link_id FROM kn.biz_links WHERE instr(note, ?) > 0", (gap_mark(gap_id),))]


def dismissed(db: sqlite3.Connection) -> set[str]:
    if not has_table(db, "biz_gap_dismissed", "kn"):
        return set()
    return {row[0] for row in db.execute("SELECT gap_id FROM kn.biz_gap_dismissed")}


def dismiss(db: sqlite3.Connection, gap_id: str, who: str) -> None:
    """"Không phải": a person says this gap is not a missing link; it leaves both lists (web and agents)."""
    if not isinstance(gap_id, str) or not gap_id.strip() or len(gap_id) > 600:
        raise BusinessError("invalid_business", "gap id required")
    db.execute("INSERT OR REPLACE INTO kn.biz_gap_dismissed(gap_id,dismissed_by,created_at) VALUES(?,?,?)",
               (gap_id.strip(), who, _now()))
    db.commit()


def restore(db: sqlite3.Connection, gap_id: str) -> None:
    db.execute("DELETE FROM kn.biz_gap_dismissed WHERE gap_id=?", (gap_id,))
    db.commit()


def link_gaps(db: sqlite3.Connection, index: GraphIndex, keep_node: Callable[[str], bool] = lambda _node: True,
              *, limit: int = 50, offset: int = 0,
              candidates: Callable[[str, str], list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    """Open gaps, most severe first: ``{"items": [...], "total": n}``. Each item: ``id``, ``kind`` (issue |
    unresolved), ``type``, ``source`` (node_id, ref), ``sources`` (more callers of a placeholder), ``reference`` (the
    name the code wrote), ``message``, ``edge_type`` (the likely missing edge) and, when ``candidates`` is given,
    the nodes it may mean (``candidates(text, source_id)``)."""
    if not has_table(db, "graph_issues"):
        return {"items": [], "total": 0}
    explained = {(str(row[0]), str(row[1] or "").lower()) for row in db.execute(
        f"SELECT source_node_id, raw_reference FROM graph_issues WHERE issue_type IN ({','.join('?' * len(INPUT_ISSUES))})",
        sorted(INPUT_ISSUES))}
    columns = {row[0] for row in db.execute(
        "SELECT DISTINCT upper(technical_name) FROM graph_nodes WHERE node_type='COLUMN'")}
    hidden = dismissed(db)
    found: list[dict[str, Any]] = []
    for issue_id, issue_type, source, raw, message in db.execute(
        "SELECT issue_id, issue_type, source_node_id, raw_reference, message FROM graph_issues "
        "WHERE source_node_id IS NOT NULL AND source_node_id<>'' ORDER BY CASE severity WHEN 'ERROR' THEN 0 "
        "WHEN 'WARNING' THEN 1 ELSE 2 END, issue_type, issue_id"
    ):
        node = index.nodes.get(source)
        kind = str(issue_type)
        if not (kind in LINK_ISSUES or kind.startswith("DYNAMIC_")) or node is None \
                or node["node_type"] == "UNRESOLVED_REFERENCE" or not keep_node(source):
            continue
        if raw and is_noise(str(raw), columns):
            continue
        found.append({"id": f"issue:{issue_id}", "kind": "issue", "type": kind, "source": _end(index, source),
                      "sources": [], "reference": str(raw or ""), "message": str(message or ""),
                      "edge_type": EDGE_GUESS.get(kind, "CALLS"), "text": str(raw or node["technical_name"])})
    targets: dict[str, list[tuple[str, str]]] = {}
    for source, edge_type, target in db.execute(
        "SELECT e.source_node_id, e.edge_type, e.target_node_id FROM graph_edges e "
        "JOIN graph_nodes t ON t.node_id=e.target_node_id JOIN graph_nodes s ON s.node_id=e.source_node_id "
        "WHERE t.node_type='UNRESOLVED_REFERENCE' AND s.node_type<>'UNRESOLVED_REFERENCE' ORDER BY e.target_node_id"
    ):
        targets.setdefault(target, []).append((source, edge_type))
    for target, sources in targets.items():
        name = (index.nodes.get(target) or {}).get("technical_name") or target.rsplit(":", 1)[-1]
        if is_noise(name, columns):
            continue
        sources = [(source, kind) for source, kind in sources
                   if (source, name.lower()) not in explained and source in index.nodes and keep_node(source)]
        if not sources:
            continue
        found.append({"id": f"unresolved:{target}", "kind": "unresolved", "type": "UNRESOLVED_REFERENCE",
                      "source": _end(index, sources[0][0]), "sources": [_end(index, source) for source, _ in sources[1:6]],
                      "more_sources": max(0, len(sources) - 6), "reference": name, "message": "",
                      "edge_type": sources[0][1] or "CALLS", "text": name})
    items = [item for item in found if item["id"] not in hidden and not closed_by(db, item["id"])]
    page = items[offset:offset + limit]
    if candidates is not None:
        for item in page:
            item["candidates"] = candidates(item["text"], item["source"]["node_id"])
    return {"items": page, "total": len(items)}


def _end(index: GraphIndex, node_id: str) -> dict[str, str]:
    node = index.nodes[node_id]
    return {"node_id": node_id, "ref": ref_of(node), "system": node["system"], "node_type": node["node_type"]}


def items_text(items: Iterable[dict[str, Any]]) -> list[str]:
    """Lines for an agent (``codemap_knowledge_gaps``)."""
    lines = []
    for item in items:
        source = item["source"]
        if item["kind"] == "issue":
            detail = f" · reference `{item['reference']}`" if item["reference"] else ""
            lines.append(f"- [{item['id']}] link · {item['type']} on {source['ref']} (id `{source['node_id']}`){detail} · {item['message']}")
        else:
            callers = "; ".join(f"{end['ref']} (id `{end['node_id']}`)" for end in [source, *item["sources"][:2]])
            more = len(item["sources"]) - 2 + item.get("more_sources", 0)
            lines.append(f"- [{item['id']}] link · unresolved reference `{item['reference']}` from {callers}"
                         f"{f' and {more} more' if more > 0 else ''}: link each source to the real node "
                         f"(likely {item['edge_type']})")
        for candidate in item.get("candidates", []):
            lines.append(f"  - candidate: {candidate['line']}")
        if "candidates" in item and not item["candidates"]:
            lines.append("  - no candidate in the graph: the target may be outside the scanned sources")
    return lines
