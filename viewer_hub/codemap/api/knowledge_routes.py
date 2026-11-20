"""Ported from code-map web/backend/api/knowledge_routes.py.

HTTP routes for the knowledge layer: business rules and KB status.

Registered on the graph blueprint under ``/api/graph/business``. Nothing is approved: a rule is in use when saved.
"""
from __future__ import annotations

from flask import g, jsonify, request

from viewer_hub.codemap import knowledge
from viewer_hub.codemap.api.business_routes import MAX_EDIT_BYTES, _body, _who
from viewer_hub.codemap.api.graph_routes import bp, connection, error
from viewer_hub.codemap.workspace import for_source


@bp.errorhandler(knowledge.KnowledgeError)
def knowledge_error(exc: knowledge.KnowledgeError):
    return error(exc.code, exc.message, exc.status)


def _revalidated(db) -> None:
    knowledge.revalidate(db, knowledge.graph_stamp(db))


def _named(db, items):
    """Add {node id: technical name} so the UI shows ORDER_HEADER instead of table:DB1:ORDER_HEADER."""
    single = isinstance(items, dict)
    rows = [items] if single else items
    names = knowledge.node_names(db, [node for row in rows for node in row.get("node_ids") or []])
    for row in rows:
        row["node_names"] = {node: names.get(node, node).split(" ", 1)[-1] for node in row.get("node_ids") or []}
    return rows[0] if single else rows


@bp.get("/business/rules")
def rules_list():
    with connection() as db:
        _revalidated(db)
        return jsonify(_named(db, knowledge.list_rules(
            db, status=request.args.get("status") or None, node_id=request.args.get("node") or None,
            domain=request.args.get("domain") or None,
        )))


@bp.post("/business/rules")
def rules_create():
    body = _body(MAX_EDIT_BYTES)
    with connection() as db:
        return jsonify(knowledge.create_rule(db, body, _who())), 201


@bp.get("/business/rules/<rule_id>")
def rules_get(rule_id):
    with connection() as db:
        _revalidated(db)
        return jsonify(knowledge.get_rule(db, rule_id))


@bp.patch("/business/rules/<rule_id>")
def rules_update(rule_id):
    body = _body(MAX_EDIT_BYTES)
    with connection() as db:
        return jsonify(knowledge.update_rule(db, rule_id, body, _who()))


@bp.post("/business/revalidate")
def revalidate():
    with connection() as db:
        return jsonify(knowledge.revalidate(db, knowledge.graph_stamp(db), force=True))


@bp.get("/business/owners")
def owners():
    with connection() as db:
        return jsonify(list(knowledge.owners(db).values()))


@bp.get("/business/ops-facts")
def ops_facts():
    node = request.args.get("node")
    with connection() as db:
        return jsonify(knowledge.ops_facts(db, [node] if node else None))


@bp.get("/business/kb-status")
def kb_status():
    """Freshness of the graph, extraction quality, what is still open and how agents use the KB."""
    workspace = for_source(g.codemap)
    with connection() as db:
        open_items = knowledge.open_items(db)
        usage = knowledge.mcp_usage(db, int(request.args.get("days", "30") or 30))
    report = workspace.stale()
    return jsonify({
        "summary": workspace.status_line(),
        "stale": report,
        "quality": workspace.quality().get("metrics", {}),
        "open": open_items,
        "usage": usage,
    })
