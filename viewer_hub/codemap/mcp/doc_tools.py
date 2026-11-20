"""Tools for an agent that knows the business documents but not the code (Copilot Studio, GitHub Copilot, Claude).

Two reads tell it what to write and where:

* ``codemap_knowledge_gaps``  what is missing: flows without documentation, parts whose code changed since they were written,
  references the extract could not follow;
* ``codemap_resolve``         the names a document uses → graph nodes (exact / ambiguous / none).

The writes are in use at once and marked as written by AI (like every propose tool in write_tools.py), with
citations to the documents:

* ``codemap_propose_link``    a missing edge between two nodes (kn.biz_links, origin ai, walked at once);
* ``codemap_propose_note``    a business note on a node (kn.graph_knowledge).

A name that does not resolve to exactly one node writes nothing: the agent gets the candidates and retries with
a node id. Sending the same item again (same natural key) updates the agent's own item; what a person wrote never changes.
"""
from __future__ import annotations

import json
import math
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

from viewer_hub.codemap import business, knowledge
from viewer_hub.codemap.business.common import _json
from viewer_hub.codemap.business.links import MAX_NOTE, ai_link
from viewer_hub.codemap.storage import SERVING_DATABASE_NAME
from viewer_hub.codemap.workspace import Workspace

from .resolve import MAX_NAMES, Resolution, candidates, resolve_name
from .tools import TOOLS, Tool, ToolError, _text
from .write_tools import AI_HINT, _errors, _flows

MAX_ITEMS = 20
MAX_GAPS = 50
GAP_KINDS = ("flow_doc", "link", "all")
# Extractor issues a document can close: the code reaches something the parser could not name.
LINK_ISSUES = frozenset({
    "UNRESOLVED_REFERENCE", "UNRESOLVED_CALL", "URL_DYNAMIC", "SQL_DYNAMIC", "ROUTE_AMBIGUOUS",
    "ROUTE_PREFIX_MISMATCH", "EXTRACTOR_CALL_UNBOUND",
})
# Missing input (a table not in the catalog, a repository or executable not scanned): an admin fixes the input,
# a document cannot. An unresolved reference these issues explain is not offered as a link gap either.
INPUT_ISSUES = frozenset({"TABLE_NOT_IMPORTED", "JOB_EXECUTABLE_NOT_FOUND", "EXECUTABLE_NOT_MAPPED", "EXTERNAL_OBJECT"})
CITATIONS_SCHEMA = {
    "type": "array", "maxItems": knowledge.MAX_CITATIONS,
    "items": {"type": "object", "properties": {
        "doc": {"type": "string", "description": "Document name, e.g. 注文登録画面設計書.xlsx"},
        "section": {"type": "string", "description": "Section, sheet or heading, e.g. '3.2 イベント定義'"},
        "url": {"type": "string", "description": "Optional http(s) link to the document"},
        "quote": {"type": "string", "description": f"Optional exact quote, up to {knowledge.MAX_QUOTE} characters"},
    }, "required": ["doc", "section"]},
    "description": "Where in the business documents this comes from.",
}


def _is_link_issue(issue_type: str) -> bool:
    return issue_type in LINK_ISSUES or issue_type.startswith("DYNAMIC_")


def _items(arguments: dict[str, Any], name: str, *, most: int = MAX_ITEMS) -> list[Any]:
    """A list argument; a JSON text of the list is accepted for clients that cannot send arrays of objects."""
    value = arguments.get(name)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as exc:
            raise ToolError(f"{name} must be a list (or a JSON text of one)") from exc
    if not isinstance(value, list) or not value:
        raise ToolError(f"{name} must be a non-empty list")
    if len(value) > most:
        raise ToolError(f"{name} has {len(value)} items; send at most {most} per call")
    return value


def _cite(value: Any, *, required: bool) -> list[dict[str, str]]:
    try:
        return knowledge.citations(value, required=required)
    except knowledge.KnowledgeError as exc:
        raise ToolError(exc.message) from exc


@contextmanager
def _web(workspace: Workspace) -> Iterator[sqlite3.Connection]:
    with workspace.web() as db:
        if db is None:
            raise ToolError("the knowledge database is not configured for this server")
        yield db


def resolve_refs(workspace: Workspace, references: list[str]) -> tuple[dict[str, str], list[Resolution]]:
    """Node id per reference, and the references that did not name exactly one node."""
    found: dict[str, str] = {}
    failed: list[Resolution] = []
    with workspace.retriever() as retriever:
        for reference in dict.fromkeys(references):
            resolution = resolve_name(retriever, reference)
            if resolution.node_id:
                found[reference] = resolution.node_id
            else:
                failed.append(resolution)
    return found, failed


def unresolved_answer(failed: list[Resolution]) -> str:
    lines = [f"Nothing was written: {len(failed)} reference(s) do not name exactly one node. Send the node id "
             "(`id` below) instead of the name, or check the name with codemap_resolve."]
    for resolution in failed:
        lines.extend(resolution.lines())
    return "\n".join(lines)


# --------------------------------------------------------------------------- reads

def resolve(workspace: Workspace, arguments: dict[str, Any]) -> str:
    names = _items(arguments, "names", most=MAX_NAMES)
    if any(not isinstance(name, str) or not name.strip() or len(name) > 500 for name in names):
        raise ToolError("names must be texts of up to 500 characters")
    node_type = _text(arguments, "type", required=False, limit=100)
    system = _text(arguments, "system", required=False, limit=200)
    with workspace.retriever() as retriever:
        results = [resolve_name(retriever, name, node_type, system) for name in names]
    counts = {status: sum(1 for result in results if result.status == status) for status in ("exact", "ambiguous", "none")}
    lines = [f"> {workspace.status_line()}", "",
             f"## Resolved {len(results)} name(s): {counts['exact']} exact, {counts['ambiguous']} ambiguous, {counts['none']} none",
             "Use the `id` of an exact match in the propose tools. For an ambiguous name pick the candidate the "
             "document means (or narrow with type / system); never guess an id for a name with no match."]
    for result in results:
        lines.extend(result.lines())
    return "\n".join(lines)


def _code_changed(db: sqlite3.Connection, part: dict[str, Any], nodes: list[str]) -> bool:
    """A flow-document part whose nodes behave differently from when it was written (it stores their fingerprint)."""
    stored = part.get("fingerprint")
    if not stored or not nodes:
        return False
    current = knowledge.fingerprint_of(db, nodes)
    return bool(current) and current != stored


def _flow_gaps(db: sqlite3.Connection, index: business.GraphIndex, tree: dict[str, Any], keep_flow) -> list[tuple[int, str]]:
    docs = {row[0]: _json(row[1], {}) for row in db.execute("SELECT flow_id, doc_json FROM kn.biz_flows")}
    gaps = []
    for flow in _flows(tree):
        if not keep_flow(flow):
            continue
        entry = index.nodes.get(flow.get("entry_node_id") or "")
        what = f"{flow['name']}" + (f" (entry {business.ref_of(entry)})" if entry else "") + f" · flow_id `{flow['id']}`"
        doc = docs.get(flow["id"])
        if not doc:
            gaps.append((1, f"- [flow:{flow['id']}] flow_doc · {what} · no documentation yet"))
            continue
        stale, empty = [], []
        summary = doc.get("summary") or {}
        all_nodes = [node for step in doc.get("steps", []) for node in step.get("nodes", [])]
        if _code_changed(db, summary, all_nodes):
            stale.append("summary")
        elif not str(summary.get("text") or "").strip():
            empty.append("summary")
        for step in doc.get("steps", []):
            if _code_changed(db, step, step.get("nodes", [])):
                stale.append(f"step {step.get('id')}")
            elif not str(step.get("text") or "").strip():
                empty.append(f"step {step.get('id')}")
        if stale:
            gaps.append((0, f"- [flow:{flow['id']}] flow_doc · {what} · code changed since it was written in: {', '.join(stale)} (re-check them against the documents)"))
        elif empty:
            gaps.append((2, f"- [flow:{flow['id']}] flow_doc · {what} · parts with no text: {', '.join(empty)}"))
    return [(rank, line) for rank, line in sorted(gaps, key=lambda gap: gap[0])]


def _links_for_gap(db: sqlite3.Connection, gap_id: str) -> list[str]:
    return [row[0] for row in db.execute("SELECT link_id FROM kn.biz_links WHERE instr(note, ?) > 0", (_gap_mark(gap_id),))]


def _link_gaps(workspace: Workspace, db: sqlite3.Connection, index: business.GraphIndex, keep_node, limit: int) -> list[str]:
    if not knowledge.has_table(db, "graph_issues"):
        return []
    explained = {(str(row[0]), str(row[1] or "").lower()) for row in db.execute(
        f"SELECT source_node_id, raw_reference FROM graph_issues WHERE issue_type IN ({','.join('?' * len(INPUT_ISSUES))})",
        sorted(INPUT_ISSUES))}
    found: list[tuple[str, str, str, str]] = []  # gap id, line, search text, source node
    for issue_id, issue_type, source, raw, message in db.execute(
        "SELECT issue_id, issue_type, source_node_id, raw_reference, message FROM graph_issues "
        "WHERE source_node_id IS NOT NULL AND source_node_id<>'' ORDER BY CASE severity WHEN 'ERROR' THEN 0 "
        "WHEN 'WARNING' THEN 1 ELSE 2 END, issue_type, issue_id"
    ):
        node = index.nodes.get(source)
        if not _is_link_issue(str(issue_type)) or node is None or node["node_type"] == "UNRESOLVED_REFERENCE" or not keep_node(source):
            continue
        detail = f" · reference `{raw}`" if raw else ""
        found.append((f"issue:{issue_id}", f"link · {issue_type} on {business.ref_of(node)} (id `{source}`){detail} · {message}",
                      str(raw or node["technical_name"]), source))
    targets: dict[str, list[tuple[str, str]]] = {}
    for source, edge_type, target in db.execute(
        "SELECT e.source_node_id, e.edge_type, e.target_node_id FROM graph_edges e "
        "JOIN graph_nodes t ON t.node_id=e.target_node_id JOIN graph_nodes s ON s.node_id=e.source_node_id "
        "WHERE t.node_type='UNRESOLVED_REFERENCE' AND s.node_type<>'UNRESOLVED_REFERENCE' ORDER BY e.target_node_id"
    ):
        targets.setdefault(target, []).append((source, edge_type))
    for target, sources in targets.items():
        name = (index.nodes.get(target) or {}).get("technical_name") or target.rsplit(":", 1)[-1]
        sources = [(source, kind) for source, kind in sources
                   if (source, name.lower()) not in explained and source in index.nodes and keep_node(source)]
        if not sources:
            continue
        callers = "; ".join(f"{business.ref_of(index.nodes[source])} (id `{source}`) {kind}" for source, kind in sources[:3])
        more = f" and {len(sources) - 3} more" if len(sources) > 3 else ""
        found.append((f"unresolved:{target}", f"link · unresolved reference `{name}` from {callers}{more}: link each "
                      "source to the real node", name, sources[0][0]))
    lines: list[str] = []
    with workspace.retriever() as retriever:
        for gap_id, line, text, source in found:
            if _links_for_gap(db, gap_id):
                continue  # closed by a link (written by a person or an agent)
            if len(lines) >= limit:
                break
            lines.append(f"- [{gap_id}] {line}")
            options = candidates(retriever, text, exclude={source})
            lines.extend(f"  - candidate: {candidate.line()}" for candidate in options)
            if not options:
                lines.append("  - no candidate in the graph: the target may be outside the scanned sources")
    return lines


@_errors
def knowledge_gaps(workspace: Workspace, arguments: dict[str, Any]) -> str:
    kind = _text(arguments, "kind", required=False, limit=20) or "all"
    if kind not in GAP_KINDS:
        raise ToolError(f"kind must be one of {', '.join(GAP_KINDS)}")
    system = _text(arguments, "system", required=False, limit=200).lower()
    feature = _text(arguments, "feature", required=False, limit=500)
    limit = arguments.get("limit", 20)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_GAPS:
        raise ToolError(f"limit must be an integer from 1 to {MAX_GAPS}")
    share = limit if kind != "all" else max(1, math.ceil(limit / 2))
    with _web(workspace) as db:
        index = business.graph_index(db, workspace.output / SERVING_DATABASE_NAME)
        tree = business.build_tree(db, index)
        flows = _flows(tree)
        if feature:
            item = business.find_item(tree, feature)
            wanted = feature.lower()
            features = {flow["feature_id"] for flow in flows
                        if flow["feature_id"] == feature or (business.find_item(tree, flow["feature_id"]) or {}).get("name", "").lower() == wanted}
            if item and item.get("kind") == "feature":
                features.add(item["id"])
            if not features:
                raise ToolError(f"no feature matches {feature!r}; give a feature id or its name in the tree")
            flows = [flow for flow in flows if flow["feature_id"] in features]
            reach = set(index.reach([flow["entry_node_id"] for flow in flows if flow.get("entry_node_id")], business.MAX_FEATURE_NODES))
        else:
            features, reach = None, None
        flow_ids = {flow["id"] for flow in flows}

        def in_system(node_id: str | None) -> bool:
            node = index.nodes.get(node_id or "")
            return not system or bool(node) and system in {str(node["system"]).lower(), str(node["owner"]).lower()}

        def keep_flow(flow: dict[str, Any]) -> bool:
            return flow["id"] in flow_ids and in_system(flow.get("entry_node_id"))

        def keep_node(node_id: str) -> bool:
            return (reach is None or node_id in reach) and in_system(node_id)

        sections: list[tuple[str, list[str]]] = []
        if kind in {"flow_doc", "all"}:
            sections.append(("Flow documentation", [line for _, line in _flow_gaps(db, index, tree, keep_flow)][:share]))
        if kind in {"link", "all"}:
            sections.append(("Links the extract could not follow", _link_gaps(workspace, db, index, keep_node, share)))
    body = [f"> {workspace.status_line()}", ""]
    for title, lines in sections:
        body.append(f"## {title}")
        body.extend(lines or ["(none)"])
    body.append("")
    body.append("Next: codemap_get_flow_doc + codemap_propose_flow_doc for a flow; codemap_resolve + "
                "codemap_propose_link (with gap_id) for a link. Cite the documents; tell the user about every "
                "difference between documents and code in your answer.")
    return "\n".join(body)


# --------------------------------------------------------------------------- writes

def _gap_mark(gap_id: str) -> str:
    return f"[gap {gap_id}]"


def _link_item(position: int, raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ToolError(f"links[{position}] must be an object")
    source = raw.get("source")
    target = raw.get("target")
    for name, value in (("source", source), ("target", target)):
        if not isinstance(value, str) or not value.strip() or len(value) > 500:
            raise ToolError(f"links[{position}].{name} must be a node id or name")
    edge_type = raw.get("edge_type")
    if not isinstance(edge_type, str) or edge_type.upper() not in business.LINK_TYPES:
        raise ToolError(f"links[{position}].edge_type must be one of {', '.join(business.LINK_TYPES)}")
    reason = raw.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ToolError(f"links[{position}].reason is required: why the two nodes are linked")
    confidence = raw.get("confidence")
    if confidence is not None and (isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1):
        raise ToolError(f"links[{position}].confidence must be a number from 0 to 1")
    gap_id = raw.get("gap_id") or ""
    if not isinstance(gap_id, str) or len(gap_id) > 300:
        raise ToolError(f"links[{position}].gap_id must be the id from codemap_knowledge_gaps")
    try:
        cited = knowledge.citations(raw.get("citations"), required=True, field=f"links[{position}].citations")
    except knowledge.KnowledgeError as exc:
        raise ToolError(exc.message) from exc
    marks = [f"độ tin cậy {confidence:g}" if confidence is not None else "",
             _gap_mark(gap_id.strip()) if gap_id.strip() else "[ngoài điểm gãy]"]
    suffix = " · ".join(mark for mark in marks if mark)
    note = f"{reason.strip()[:MAX_NOTE - len(suffix) - 3]} · {suffix}"
    return {"source": source.strip(), "target": target.strip(), "edge_type": edge_type.upper(), "note": note,
            "citations": cited, "gap_id": gap_id.strip()}


@_errors
def propose_link(workspace: Workspace, arguments: dict[str, Any]) -> str:
    items = [_link_item(position, raw) for position, raw in enumerate(_items(arguments, "links"))]
    ids, failed = resolve_refs(workspace, [ref for item in items for ref in (item["source"], item["target"])])
    if failed:
        return unresolved_answer(failed)
    who = arguments.get("_user", "agent")
    results = []
    with _web(workspace) as db:
        index = business.graph_index(db, workspace.output / SERVING_DATABASE_NAME)
        for position, item in enumerate(items):
            body = {**item, "source": ids[item["source"]], "target": ids[item["target"]]}
            label = f"links[{position}] {item['source']} -{item['edge_type']}-> {item['target']}"
            try:
                state, link = ai_link(db, index, body, who)
            except business.BusinessError as exc:
                results.append(f"- {label}: rejected, {exc.message}")
                continue
            flag = "" if item["gap_id"] else " (not tied to a gap: say which gap it closes when there is one)"
            results.append(f"- {label}: {state} {link['link_id']} (in use, origin ai){flag}")
        db.commit()
        business.apply_links(db, index)
    return "\n".join([f"Links: {len(items)} sent. {AI_HINT}", *results])


@_errors
def propose_note(workspace: Workspace, arguments: dict[str, Any]) -> str:
    reference = _text(arguments, "node", limit=500)
    text = _text(arguments, "text", limit=knowledge.MAX_TEXT)
    cited = _cite(arguments.get("citations"), required=False)
    ids, failed = resolve_refs(workspace, [reference])
    if failed:
        return unresolved_answer(failed)
    node_id = ids[reference]
    who = arguments.get("_user", "agent")
    with _web(workspace) as db:
        found = db.execute("SELECT knowledge_id, status, created_by FROM kn.graph_knowledge WHERE target_id=? AND body=?",
                           (node_id, text)).fetchone()
        if found and not found["created_by"]:
            # The same text written by a person (the web page records no author): never changed by an agent.
            return f"Note {found['knowledge_id']} on `{node_id}` already has this text; nothing changed."
        if found:
            db.execute("UPDATE kn.graph_knowledge SET citations_json=?,created_by=?,updated_at=? WHERE knowledge_id=?",
                       (json.dumps(cited, ensure_ascii=False), who, knowledge.now(), found["knowledge_id"]))
            note_id, state = found["knowledge_id"], "Updated"
        else:
            note_id = db.execute(
                "INSERT INTO kn.graph_knowledge(target_id,body,status,citations_json,created_by) VALUES(?,?,'approved',?,?)",
                (node_id, text, json.dumps(cited, ensure_ascii=False), who)).lastrowid
            state = "Created"
        db.commit()
    return f"{state} note {note_id} (in use) on `{node_id}`. {AI_HINT}"


_LINK_ITEM = {
    "type": "object",
    "properties": {
        "source": {"type": "string", "description": "Node id (from codemap_resolve) or exact name of the caller / writer."},
        "target": {"type": "string", "description": "Node id or exact name of what it calls, starts, reads or writes."},
        "edge_type": {"type": "string", "enum": list(business.LINK_TYPES)},
        "reason": {"type": "string", "description": "Why the two nodes are linked, in one or two sentences."},
        "citations": CITATIONS_SCHEMA,
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "gap_id": {"type": "string", "description": "The gap this link closes (from codemap_knowledge_gaps kind=link)."},
    },
    "required": ["source", "target", "edge_type", "reason", "citations"],
}

DOC_TOOLS: list[Tool] = [
    Tool(
        "codemap_knowledge_gaps",
        "What knowledge is missing",
        "The work list for documenting the system: flows with no documentation or whose parts no longer match the "
        "code, and calls / reads / writes the extract could not follow (with the top candidate targets). "
        "Each line starts with a gap id to pass back to the propose tools.",
        {"type": "object", "properties": {
            "kind": {"type": "string", "enum": list(GAP_KINDS), "description": "Which gaps (default all)."},
            "system": {"type": "string", "description": "Only this system / repository / database."},
            "feature": {"type": "string", "description": "Only this feature (id or name in the business tree)."},
            "limit": {"type": "integer", "minimum": 1, "maximum": MAX_GAPS, "description": "Lines per kind (default 20)."},
        }},
        knowledge_gaps,
    ),
    Tool(
        "codemap_resolve",
        "Names in a document to graph nodes",
        "Look up the screens, APIs, tables, jobs or terms a document names (Japanese, English, Vietnamese or "
        "technical names) and get, per name, the one node it means (exact), the candidates (ambiguous) or none. "
        "Use the ids in the propose tools; never guess an id.",
        {"type": "object", "properties": {
            "names": {"type": "array", "items": {"type": "string"}, "maxItems": MAX_NAMES},
            "type": {"type": "string", "description": "Node type to narrow to: SCREEN, API_OPERATION, TABLE, JOB, PROCEDURE…"},
            "system": {"type": "string", "description": "System / repository / database to narrow to."},
        }, "required": ["names"]},
        resolve,
    ),
    Tool(
        "codemap_propose_link",
        "Add links between nodes",
        "Add edges the extract missed (a dynamic call, a job started from configuration, a table written "
        "through a helper), each with the reason and the document it comes from. Up to 20 per call. Links are in "
        "use at once (trace, impact, flows), marked as written by AI; sending the same source, target and type "
        "again updates your link. A link a person added is never changed.",
        {"type": "object", "properties": {"links": {"type": "array", "items": _LINK_ITEM, "maxItems": MAX_ITEMS}},
         "required": ["links"]},
        propose_link,
        write=True,
    ),
    Tool(
        "codemap_propose_note",
        "Add a note on a node",
        "Attach a business note (what a screen, table or job means for the business) to one node, with the "
        "documents it comes from. In use at once, marked as written by AI.",
        {"type": "object", "properties": {
            "node": {"type": "string", "description": "Node id or exact name."},
            "text": {"type": "string"},
            "citations": CITATIONS_SCHEMA,
        }, "required": ["node", "text"]},
        propose_note,
        write=True,
    ),
]

TOOLS.extend(DOC_TOOLS)
