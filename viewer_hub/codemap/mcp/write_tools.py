"""Tools that let an agent write knowledge. There is no approval: what they write is in use at once, marked as
written by AI (``source='ai'`` / part status ``ai``) so every reader can tell it from what a person wrote.
The names keep ``propose`` so existing agent configurations go on working.

* ``codemap_get_flow_doc``      read a flow document to fill (step ids, nodes, locked parts);
* ``codemap_propose_flow_doc``  write AI text into the parts no person edited;
* ``codemap_propose_rule``      a business rule (RULE-…, source ai / doc), with code evidence or document citations;
* ``codemap_get_item_doc``      read a feature's name and overview to fill, with the summaries of its flows;
* ``codemap_propose_item_doc``  write a feature's name and overview (never over what a person wrote).

Gaps, name resolution and the document-based link / note tools are in doc_tools.py.
The write tools are only offered when the server allows writes (stdio
``--allow-write``; HTTP with the knowledge token).
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

import yaml

from viewer_hub.codemap import knowledge
from viewer_hub.codemap import business
from viewer_hub.codemap.business import resolve
from viewer_hub.codemap.storage import SERVING_DATABASE_NAME

from .tools import TOOLS, Tool, ToolError, _answer, _text
from viewer_hub.codemap.workspace import Workspace

AI_HINT = "It is in use now, shown to people and agents as written by AI; cite it as AI-written, not as confirmed by a person."


@contextmanager
def _business(workspace: Workspace) -> Iterator[tuple[Any, business.GraphIndex, dict[str, Any]]]:
    with workspace.web() as db:
        if db is None:
            raise ToolError("the knowledge database is not configured for this server")
        index = business.graph_index(db, workspace.output / SERVING_DATABASE_NAME)
        yield db, index, business.build_tree(db, index)


def _flows(tree: dict[str, Any]) -> list[dict[str, Any]]:
    found, stack = [], list(tree["menus"])
    while stack:
        item = stack.pop()
        if item["kind"] == "flow":
            found.append(item)
        stack.extend(item.get("children", []))
    return found


def _find_flow(index: business.GraphIndex, tree: dict[str, Any], query: str) -> dict[str, Any]:
    flows = _flows(tree)
    exact = [flow for flow in flows if flow["id"] == query]
    if exact:
        return exact[0]
    wanted = query.lower().strip()
    matches = []
    for flow in flows:
        entry = index.nodes.get(flow.get("entry_node_id") or "")
        names = {flow["name"].lower()}
        if entry:
            names |= {entry["technical_name"].lower(), business.ref_name(entry).lower(), entry["display_name"].lower()}
        if wanted in names:
            matches.append(flow)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ToolError(f"no flow matches {query!r}; give a flow id or the name of its UI action, API or job")
    raise ToolError(f"{len(matches)} flows match {query!r}: " + ", ".join(flow["id"] for flow in matches[:10]))


def _errors(function):
    def wrapped(workspace: Workspace, arguments: dict[str, Any]) -> str:
        try:
            return function(workspace, arguments)
        except (business.BusinessError, knowledge.KnowledgeError) as exc:
            raise ToolError(exc.message) from exc
    return wrapped


@_errors
def get_flow_doc(workspace: Workspace, arguments: dict[str, Any]) -> str:
    query = _text(arguments, "flow", limit=500)
    with _business(workspace) as (db, index, tree):
        flow = _find_flow(index, tree, query)
        document = business.flow_document(db, index, tree, flow["id"])
    body = [
        f"## Flow document {flow['id']} (feature {document['feature_id']})",
        "Fill the empty fields and send the whole `flow` object back with codemap_propose_flow_doc. Parts with "
        "`locked: true` were edited by a person: read them, never rewrite them. Cite nodes as [[name]] "
        "with the names after `type:` in each step's `nodes`; every rule needs `evidence` (file:line) or `citations` "
        "([{doc, section, url?, quote?}] from the business documents); a step may carry `citations` too.",
        "```yaml",
        yaml.safe_dump({"flow": document["flow"]}, allow_unicode=True, sort_keys=False, width=110).rstrip(),
        "```",
    ]
    # Not cut: the agent sends the whole document back.
    return _answer(workspace, body, [], None)


def _find_feature(tree: dict[str, Any], query: str) -> dict[str, Any]:
    item = business.find_item(tree, query)
    if item and item["kind"] == "feature":
        return item
    wanted, found, stack = query.lower(), [], list(tree["menus"])
    while stack:
        current = stack.pop()
        if current["kind"] == "feature" and wanted in {current["name"].lower(), str(current.get("route", "")).lower()}:
            found.append(current)
        stack.extend(child for child in current.get("children", []) if child["kind"] in {"menu", "feature"})
    if len(found) == 1:
        return found[0]
    if found:
        raise ToolError(f"{query!r} matches {len(found)} features; give the feature id: "
                        + ", ".join(item["id"] for item in found[:10]))
    raise ToolError(f"no feature matches {query!r}; give a feature id, its name or its route")


@_errors
def get_item_doc(workspace: Workspace, arguments: dict[str, Any]) -> str:
    query = _text(arguments, "feature", limit=500)
    with _business(workspace) as (db, _index, tree):
        feature = _find_feature(tree, query)
        document = business.item_document(db, tree, feature["id"])
    flows = [{"name": flow["name"], "summary": flow.get("summary") or "(no summary yet: write the flow first)"}
             for flow in feature.get("children", []) if flow["kind"] == "flow"]
    state = ("LOCKED: a person wrote it. Read it, never rewrite it." if document["locked"]
             else "Fill `name` and `description` and send them with codemap_propose_item_doc.")
    body = [
        f"## Feature {feature['id']}" + (f" ({feature.get('route')})" if feature.get("route") else ""),
        state,
        "Write the overview from the flows below (what the feature is for, who uses it or which batch runs it, the "
        "main flows and their results, the main tables / systems, what it does NOT do). Cite nodes as [[name]].",
        "```yaml",
        yaml.safe_dump({"feature": {"name": document["name"] or document["graph_name"], "description": document["description"]},
                        "flows": flows}, allow_unicode=True, sort_keys=False, width=110).rstrip(),
        "```",
    ]
    return _answer(workspace, body, [], None)


@_errors
def propose_item_doc(workspace: Workspace, arguments: dict[str, Any]) -> str:
    query = _text(arguments, "feature", limit=500)
    body = {"name": arguments.get("name"), "description": arguments.get("description")}
    with _business(workspace) as (db, _index, tree):
        feature = _find_feature(tree, query)
        state = business.ai_item(db, tree, feature["id"], body)
    if state == "locked":
        return f"Nothing was written: a person wrote the name / overview of {feature['id']}."
    if state == "empty":
        raise ToolError("send a name, a description or both")
    if state == "same":
        return f"Nothing changed: {feature['id']} already has this text."
    return f"Wrote the name / overview of {feature['id']} as AI text. {AI_HINT}"


@_errors
def propose_flow_doc(workspace: Workspace, arguments: dict[str, Any]) -> str:
    flow_id = _text(arguments, "flow_id", limit=500)
    document = arguments.get("document")
    if isinstance(document, str):
        try:
            document = yaml.safe_load(document)
        except yaml.YAMLError as exc:
            raise ToolError(f"document is not valid YAML/JSON: {exc}") from exc
    if isinstance(document, dict) and isinstance(document.get("flow"), dict):
        document = document["flow"]
    with _business(workspace) as (db, index, tree):
        result = business.propose_flow(db, index, tree, flow_id, document, arguments.get("_user", "agent"))
    lines = [f"Wrote {result['parts_written']} part(s) of {result['flow_id']} as AI text. {AI_HINT}"]
    if result["locked_steps_kept"]:
        lines.append(f"- Kept unchanged (a person edited them): steps {', '.join(result['locked_steps_kept'])}")
    if result["unresolved_citations"]:
        lines.append("- Citations not in this flow's graph (shown as broken; fix them): "
                     + ", ".join(result["unresolved_citations"]))
    if result["rules_without_evidence"]:
        lines.append("- Rules without evidence (marked 'needs confirmation'): " + "; ".join(result["rules_without_evidence"]))
    if not result["parts_written"]:
        lines.append("- Nothing was written: every part was empty or locked.")
    return "\n".join(lines)


def _node_ids(workspace: Workspace, db: Any, references: Any) -> list[str] | str:
    """Node ids for the names an agent wrote (address, ``type: name``, full or short name, close spelling), or the
    answer to send back when a name does not point at exactly one node (nothing is written then)."""
    if references in (None, []):
        return []
    if not isinstance(references, list) or len(references) > knowledge.MAX_NODES or any(
            not isinstance(item, str) for item in references):
        raise ToolError(f"nodes must be a list of up to {knowledge.MAX_NODES} node ids or names")
    index = business.graph_index(db, workspace.output / SERVING_DATABASE_NAME)
    lookup = resolve.names(index, db)
    results = [lookup.resolve(reference) for reference in references if reference.strip()]
    failed = [result for result in results if result.status != "match"]
    if failed:
        return ("Nothing was written. Some node names do not point at exactly one node; write the address "
                "(system › type › full name) or the id of a candidate:\n" + "\n".join(f"- {result.message()}" for result in failed))
    return [result.node_id for result in results]


@_errors
def propose_rule(workspace: Workspace, arguments: dict[str, Any]) -> str:
    body = {key: arguments.get(key) for key in ("title", "text", "evidence", "domain", "requirement_refs", "test_refs",
                                                "citations")}
    if not body.get("evidence") and not body.get("citations"):
        raise ToolError("evidence (file:line of the code that implements the rule) or citations (the business "
                        "document and section that state it) is required; if there is neither, do not record a rule: "
                        "tell the user what is unclear")
    with workspace.web() as db:
        if db is None:
            raise ToolError("the knowledge database is not configured for this server")
        nodes = _node_ids(workspace, db, arguments.get("nodes"))
        if isinstance(nodes, str):
            return nodes
        body["nodes"] = nodes
        rule = knowledge.create_rule(db, body, arguments.get("_user", "agent"), by_ai=True)
    return f"Created {rule['rule_id']} (in use, source {rule['source']}): {rule['title']}. {AI_HINT}"


_NODES = {"type": "array", "items": {"type": "string"},
          "description": "Graph nodes it is about, by name: 'table: ORDER_HEADER', 'PKG_ORDER.CANCEL_ORDER', "
                         "'OrderService.Create', 'POST /api/orders', an address 'system › type › full name' or a "
                         "node id. Close spellings are found; a name shared by several nodes returns the candidates."}
_CITATIONS = {
    "type": "array", "maxItems": knowledge.MAX_CITATIONS,
    "items": {"type": "object", "properties": {"doc": {"type": "string"}, "section": {"type": "string"},
                                               "url": {"type": "string"}, "quote": {"type": "string"}},
              "required": ["doc", "section"]},
    "description": f"Business documents it comes from: document name, section, optional http(s) url and quote "
                   f"(up to {knowledge.MAX_QUOTE} characters).",
}

WRITE_TOOLS: list[Tool] = [
    Tool(
        "codemap_get_flow_doc",
        "Get a flow document to fill",
        "The documentation skeleton of one business flow: step ids per system, the nodes of each step, existing "
        "text and which parts are locked (edited by a person). Use it before codemap_propose_flow_doc.",
        {"type": "object", "properties": {"flow": {"type": "string", "description": "Flow id, or the UI action / API / job it starts from."}},
         "required": ["flow"]},
        get_flow_doc,
    ),
    Tool(
        "codemap_get_item_doc",
        "Get a feature overview to fill",
        "A feature's business name and overview as stored (or locked, when a person wrote them), with the name and "
        "summary of each of its flows. Use it before codemap_propose_item_doc; write the flows first.",
        {"type": "object", "properties": {"feature": {"type": "string", "description": "Feature id, name or route."}},
         "required": ["feature"]},
        get_item_doc,
    ),
    Tool(
        "codemap_propose_item_doc",
        "Write a feature overview",
        "Write a feature's business name and overview (2-4 paragraphs: purpose, who uses it, main flows and results, "
        "main tables / systems, what it does not do; [[node]] references). In use at once, marked 'written by AI'. "
        "What a person wrote is never overwritten.",
        {"type": "object", "properties": {
            "feature": {"type": "string", "description": "Feature id, name or route."},
            "name": {"type": "string", "description": "Business name, e.g. 'Quản lý đơn hàng'."},
            "description": {"type": "string"},
        }, "required": ["feature"]},
        propose_item_doc,
        write=True,
    ),
    Tool(
        "codemap_propose_flow_doc",
        "Write flow documentation",
        "Write a flow's documentation (summary, steps with [[node]] references and document `citations`, rules "
        "with code evidence or document citations, edge cases). Locked parts are never overwritten. "
        "What is written is in use at once, marked 'written by AI'.",
        {"type": "object", "properties": {
            "flow_id": {"type": "string"},
            "document": {"type": "object", "description": "The `flow` object from codemap_get_flow_doc with the empty fields filled."},
        }, "required": ["flow_id", "document"]},
        propose_flow_doc,
        write=True,
    ),
    Tool(
        "codemap_propose_rule",
        "Record a business rule",
        "Record a business rule; it is in use at once, marked as written by AI. Needs evidence (file:line in the "
        "code) or citations (the business document stating it). When neither can tell whether the "
        "behaviour is intended, or the document and the code disagree, tell the user instead of recording a rule.",
        {"type": "object", "properties": {
            "title": {"type": "string", "description": "One assertive sentence, e.g. 'A shipped order cannot be cancelled'."},
            "text": {"type": "string", "description": "What happens when the rule is not met."},
            "evidence": {"type": "string", "description": "file:line of the condition in the code."},
            "domain": {"type": "string", "description": "Short domain code for the id, e.g. ORD -> RULE-ORD-001."},
            "citations": _CITATIONS,
            "nodes": _NODES,
            "requirement_refs": {"type": "array", "items": {"type": "string"}},
        }, "required": ["title", "nodes"]},
        propose_rule,
        write=True,
    ),
]

TOOLS.extend(WRITE_TOOLS)
