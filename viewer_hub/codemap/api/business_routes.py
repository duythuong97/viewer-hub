"""Ported from code-map web/backend/api/business_routes.py.

HTTP routes for the business layer (menus, features, flow documents, AI export/import).

Registered on the graph blueprint, so they live under ``/api/graph/business``.
Writes follow the business-semantic-mapping route: bounded JSON bodies, no
cookies; the reviewer name comes from the optional ``X-Code-Map-User`` header.
"""
from __future__ import annotations

from urllib.parse import unquote

from flask import current_app, jsonify, request

from viewer_hub.codemap import business
from viewer_hub.codemap.storage import SERVING_DATABASE_NAME
from viewer_hub.codemap.api.graph_routes import bp, connection, error, graph_output, knowledge_db

MAX_EDIT_BYTES = 256 * 1024
MAX_IMPORT_BYTES = 4 * 1024 * 1024


@bp.errorhandler(business.BusinessError)
def business_error(exc: business.BusinessError):
    return error(exc.code, exc.message, exc.status)


_TREE_CACHE: dict[str, tuple[tuple, dict]] = {}


def _stamp(path) -> tuple[int, int]:
    try:
        stat = path.stat()
        return stat.st_size, stat.st_mtime_ns
    except OSError:
        return 0, 0


def tree_context(db, output, knowledge):
    """Graph index and tree of one pack (``output`` folder, ``knowledge`` db), rebuilt only when the extract or the
    knowledge database changes. Also used outside a code-map request (codemap/exports.py)."""
    web_path = output / SERVING_DATABASE_NAME
    index = business.graph_index(db, web_path)
    key = (_stamp(web_path), _stamp(knowledge))
    cached = _TREE_CACHE.get(str(web_path))
    if cached and cached[0] == key:
        return index, cached[1], web_path
    return index, _build(db, index, output, knowledge, key), web_path


def _build(db, index, output, knowledge, key=None):
    """Build the tree and keep it for the next request, unless a file changed while it was being built."""
    web_path = output / SERVING_DATABASE_NAME
    key = key or (_stamp(web_path), _stamp(knowledge))
    tree = business.build_tree(db, index)
    if key == (_stamp(web_path), _stamp(knowledge)):
        _TREE_CACHE[str(web_path)] = (key, tree)
    return tree


def _context(db):
    return tree_context(db, graph_output(), knowledge_db())


def _rebuild(db, index, key=None):
    return _build(db, index, graph_output(), knowledge_db(), key)


def _body(limit: int) -> dict:
    if not request.is_json or request.content_length is None or request.content_length > limit:
        raise business.BusinessError("invalid_business", "Bounded JSON body required", 415)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise business.BusinessError("invalid_business", "JSON object required")
    return body


def _who() -> str:
    """The reviewer's name; percent-encoded by the UI because HTTP headers cannot carry "Nguyễn"."""
    return unquote(request.headers.get("X-Code-Map-User") or "").strip()[:100]


def _flag(name: str) -> bool:
    return request.args.get(name, "1").lower() not in {"0", "false", "no"}


@bp.get("/business/tree")
def business_tree():
    with connection() as db:
        _index, tree, _path = _context(db)
        return jsonify(tree)


@bp.get("/business/items/<path:item_id>")
def business_item(item_id):
    with connection() as db:
        index, tree, _path = _context(db)
        return jsonify(business.feature_detail(db, index, tree, item_id))


@bp.patch("/business/items/<path:item_id>")
def business_item_update(item_id):
    body = _body(MAX_EDIT_BYTES)
    with connection() as db:
        index, tree, _path = _context(db)
        business.update_item(db, tree, item_id, body, _who(), index)
        tree = _rebuild(db, index)
        item = business.find_item(tree, item_id) or business.find_item(tree, body.get("parent_id", ""))
        return jsonify({"tree": tree, "item": business.feature_detail(db, index, tree, item["id"]) if item and item["kind"] != "entry" else None})


@bp.get("/business/features/<path:feature_id>/data")
def business_feature_data(feature_id):
    """The tables of a feature, the CRUD matrix flow × table and the ERD of those tables (exports, MCP)."""
    return jsonify(_item_data(feature_id))


@bp.get("/business/flows/<path:flow_id>/data")
def business_flow_data(flow_id):
    """The flow page's "Dữ liệu" view: the tables the open flow reads and writes, its CRUD row and their ERD."""
    return jsonify(_item_data(flow_id))


def _item_data(item_id):
    from viewer_hub.codemap import erd, erd_addon

    with connection() as db:
        index, tree, _path = _context(db)
        data = business.feature_data(index, tree, item_id)
        ids = [table["id"] for table in data["tables"] if table["node_type"] == "TABLE"]
        model = None
        if ids:
            try:
                model = erd.build(db, tables=ids)
            except erd.ErdError as exc:
                data["erd_error"] = exc.message
        data["erd"] = model
    data["erd_addon"] = erd_addon.addon_path(current_app.extensions["codemap_hub"])
    return data


@bp.get("/business/flows/<path:flow_id>")
def business_flow(flow_id):
    with connection() as db:
        index, tree, _path = _context(db)
        return jsonify(business.load_flow(db, index, tree, flow_id))


@bp.get("/business/nodes/<path:node_id>")
def business_node(node_id):
    with connection() as db:
        index, tree, _path = _context(db)
        return jsonify(business.node_page(db, index, tree, node_id))


@bp.patch("/business/flows/<path:flow_id>/parts/<part>")
def business_flow_part(flow_id, part):
    body = _body(MAX_EDIT_BYTES)
    with connection() as db:
        index, tree, _path = _context(db)
        business.update_part(db, index, tree, flow_id, part, body, _who())
        tree = _rebuild(db, index)
        return jsonify({**business.load_flow(db, index, tree, flow_id), "tree": tree})


@bp.post("/business/flows/<path:flow_id>/questions/<question_id>/answer")
def business_flow_answer(flow_id, question_id):
    body = _body(MAX_EDIT_BYTES)
    with connection() as db:
        index, tree, _path = _context(db)
        business.answer_question(db, index, tree, flow_id, question_id, body.get("answer"), _who())
        tree = _rebuild(db, index)
        return jsonify({**business.load_flow(db, index, tree, flow_id), "tree": tree})


@bp.post("/business/features/<path:feature_id>/ai-export")
def business_ai_export(feature_id):
    with connection() as db:
        index, tree, web_path = _context(db)
        return jsonify(business.export_pack(
            db, index, tree, web_path, feature_id,
            include_code=_flag("code"), include_locked=_flag("locked"), include_answers=_flag("answers"),
            include_instructions=_flag("instructions"),
        ))


@bp.post("/business/features/<path:feature_id>/ai-import/check")
def business_ai_import_check(feature_id):
    body = _body(MAX_IMPORT_BYTES)
    with connection() as db:
        index, tree, web_path = _context(db)
        return jsonify(business.check_import(db, index, tree, web_path, feature_id, body.get("text")))


@bp.post("/business/features/<path:feature_id>/ai-import")
def business_ai_import(feature_id):
    body = _body(MAX_IMPORT_BYTES)
    with connection() as db:
        index, tree, web_path = _context(db)
        result = business.apply_import(db, index, tree, web_path, feature_id, body.get("text"))
        return jsonify({**result, "tree": _rebuild(db, index)})


@bp.get("/business/search")
def business_search():
    query = request.args.get("q", "").strip()
    with connection() as db:
        index, tree, _path = _context(db)
        return jsonify({"business": business.search(db, tree, query), "nodes": business.search_nodes(db, index, tree, query)})


# --------------------------------------------------------------------------- hand-made links

@bp.get("/business/links")
def business_links():
    from viewer_hub.codemap.business import links

    node = request.args.get("node")
    status = request.args.get("status") or None
    with connection() as db:
        index, _tree, _path = _context(db)
        return jsonify({"links": links.list_links(db, index, [node] if node else None, status),
                        "types": {"calls": list(business.LINK_CALL_TYPES), "data": list(business.LINK_DATA_TYPES)}})


@bp.post("/business/links")
def business_link_create():
    from viewer_hub.codemap.business import links

    body = _body(MAX_EDIT_BYTES)
    with connection() as db:
        index, _tree, _path = _context(db)
        link = links.create_link(db, index, body, _who())
        return jsonify({"link": link, "tree": _rebuild(db, index)})


@bp.patch("/business/links/<link_id>")
def business_link_update(link_id):
    from viewer_hub.codemap.business import links

    body = _body(MAX_EDIT_BYTES)
    with connection() as db:
        index, _tree, _path = _context(db)
        link = links.update_link(db, index, link_id, body, _who())
        return jsonify({"link": link, "tree": _rebuild(db, index)})


@bp.delete("/business/links/<link_id>")
def business_link_delete(link_id):
    from viewer_hub.codemap.business import links

    with connection() as db:
        index, _tree, _path = _context(db)
        links.delete_link(db, index, link_id)
        return jsonify({"ok": True, "tree": _rebuild(db, index)})


# --------------------------------------------------------------------------- share knowledge

MAX_KNOWLEDGE_BYTES = 64 * 1024 * 1024


@bp.get("/business/knowledge/export")
def business_knowledge_export():
    import json
    import re
    from datetime import datetime

    from flask import Response, g

    from viewer_hub.codemap import knowledge_share

    with connection() as db:
        web_path = graph_output() / SERVING_DATABASE_NAME
        pack = {"id": g.codemap.pack_id, "title": g.codemap.title, "version": g.codemap.version}
        data = knowledge_share.export_knowledge(db, pack, business.graph_hash(web_path), _who())
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", g.codemap.pack_id).strip("-") or "codemap"
    name = f"{slug}-{datetime.now().strftime('%Y%m%d-%H%M')}.codemap-knowledge.json"
    return Response(json.dumps(data, ensure_ascii=False, indent=1), mimetype="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@bp.post("/business/knowledge/import/check")
def business_knowledge_check():
    from flask import g

    from viewer_hub.codemap import knowledge_share

    body = _body(MAX_KNOWLEDGE_BYTES)
    with connection() as db:
        return jsonify(knowledge_share.check_import(db, body.get("data"), str(body.get("mode") or "newer"), g.codemap.pack_id))


@bp.post("/business/knowledge/import")
def business_knowledge_import():
    from flask import g

    from viewer_hub.codemap import knowledge_share

    body = _body(MAX_KNOWLEDGE_BYTES)
    with connection() as db:
        index = business.graph_index(db, graph_output() / SERVING_DATABASE_NAME)
        result = knowledge_share.apply_import(db, index, body.get("data"), str(body.get("mode") or "newer"),
                                              g.codemap.pack_id, knowledge_db())
        return jsonify({**result, "tree": _rebuild(db, index)})
