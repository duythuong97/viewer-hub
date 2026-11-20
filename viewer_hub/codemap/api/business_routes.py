"""Ported from code-map web/backend/api/business_routes.py.

HTTP routes for the business layer (menus, features, flow documents, AI export/import).

Registered on the graph blueprint, so they live under ``/api/graph/business``.
Writes follow the business-semantic-mapping route: bounded JSON bodies, no
cookies; the reviewer name comes from the optional ``X-Code-Map-User`` header.
"""
from __future__ import annotations

from urllib.parse import unquote

from flask import current_app, g, jsonify, request

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


@bp.get("/business/notes")
def business_notes():
    """Business notes on one node (``?node=<id>``); node ids may hold slashes, so they go in the query."""
    from viewer_hub.codemap.business import notes

    with connection() as db:
        return jsonify({"notes": notes.list_notes(db, [request.args.get("node", "")])})


@bp.post("/business/notes")
def business_note_create():
    from viewer_hub.codemap.business import notes

    body = _body(MAX_EDIT_BYTES)
    node = body.get("node") if isinstance(body.get("node"), str) else ""
    with connection() as db:
        return jsonify({"note": notes.create_note(db, node, body, _who())})


@bp.patch("/business/notes/<int:note_id>")
def business_note_update(note_id):
    from viewer_hub.codemap.business import notes

    body = _body(MAX_EDIT_BYTES)
    with connection() as db:
        return jsonify({"note": notes.update_note(db, note_id, body, _who())})


@bp.delete("/business/notes/<int:note_id>")
def business_note_delete(note_id):
    from viewer_hub.codemap.business import notes

    with connection() as db:
        notes.delete_note(db, note_id)
        return jsonify({"ok": True})


@bp.patch("/business/flows/<path:flow_id>/parts/<part>")
def business_flow_part(flow_id, part):
    body = _body(MAX_EDIT_BYTES)
    with connection() as db:
        index, tree, _path = _context(db)
        business.update_part(db, index, tree, flow_id, part, body, _who())
        tree = _rebuild(db, index)
        return jsonify({**business.load_flow(db, index, tree, flow_id), "tree": tree})


@bp.post("/business/features/<path:feature_id>/ai-export")
def business_ai_export(feature_id):
    with connection() as db:
        index, tree, web_path = _context(db)
        return jsonify(business.export_pack(
            db, index, tree, web_path, feature_id,
            include_code=_flag("code"), include_locked=_flag("locked"),
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


@bp.post("/business/overview/ai-export")
def business_overview_export():
    """AI file for the names and overviews of a menu and its sub-menus (``?item=<menu id>``; none = every menu)."""
    from viewer_hub.codemap.business import overview

    with connection() as db:
        _index, tree, web_path = _context(db)
        return jsonify(overview.export_overview(db, tree, web_path, request.args.get("item", ""),
                                                include_instructions=_flag("instructions")))


@bp.post("/business/overview/ai-import/check")
def business_overview_check():
    from viewer_hub.codemap.business import overview

    body = _body(MAX_IMPORT_BYTES)
    with connection() as db:
        _index, tree, _path = _context(db)
        return jsonify(overview.check_overview(db, tree, str(body.get("item") or ""), body.get("text")))


@bp.post("/business/overview/ai-import")
def business_overview_import():
    from viewer_hub.codemap.business import overview

    body = _body(MAX_IMPORT_BYTES)
    with connection() as db:
        index, tree, _path = _context(db)
        result = overview.apply_overview(db, index, tree, str(body.get("item") or ""), body.get("text"))
        return jsonify({**result, "tree": _rebuild(db, index)})


@bp.get("/business/search")
def business_search():
    query = request.args.get("q", "").strip()
    with connection() as db:
        index, tree, _path = _context(db)
        return jsonify({"business": business.search(db, tree, query), "nodes": business.search_nodes(db, index, tree, query)})


# --------------------------------------------------------------------------- gaps ("Chỗ hở")

MAX_GAP_PAGE = 50


@bp.get("/business/gaps")
def business_gaps():
    """Calls, reads and writes the extract could not follow, each with the nodes it may mean (business/gaps.py)."""
    from viewer_hub.codemap.business import gaps
    from viewer_hub.codemap.business.resolve import names
    from viewer_hub.codemap.mcp.resolve import candidates as search_candidates
    from viewer_hub.codemap.workspace import for_source

    try:
        limit = max(1, min(MAX_GAP_PAGE, int(request.args.get("limit", 20))))
        offset = max(0, int(request.args.get("offset", 0)))
    except ValueError:
        raise business.BusinessError("invalid_business", "limit / offset must be numbers")
    system = request.args.get("system", "").strip().lower()
    with connection() as db, for_source(g.codemap).retriever() as retriever:
        index, _tree, _path = _context(db)
        known = names(index, db)

        def keep(node_id: str) -> bool:
            node = index.nodes[node_id]
            return not system or system in {str(node["system"]).lower(), str(node["owner"]).lower()}

        def options(text: str, source: str) -> list[dict]:
            """A name the code wrote resolves by address / name first; free text (dynamic SQL, a config key) goes
            through the search index, the candidates agents get from codemap_knowledge_gaps."""
            found: dict[str, dict] = {}
            for candidate in known.resolve(text, near=[source], max_level=5).candidates:
                found.setdefault(candidate.node_id, candidate.as_dict())
            for hit in search_candidates(retriever, text, exclude={source}):
                if hit.node_id in index.nodes and hit.node_id not in found:
                    found[hit.node_id] = known.candidate(hit.node_id, "tìm theo chữ trong code").as_dict()
            return [{**candidate, "node_type": index.nodes[node_id]["node_type"]}
                    for node_id, candidate in found.items() if node_id != source][:5]

        found = gaps.link_gaps(db, index, keep, limit=limit, offset=offset, candidates=options)
        for item in found["items"]:
            for end in [item["source"], *item["sources"]]:
                end["address"] = known.address.get(end["node_id"], "")
        systems = sorted({str(node["system"]) for node in index.nodes.values() if node["node_type"] != "UNRESOLVED_REFERENCE"})
        return jsonify({**found, "systems": systems,
                        "types": {"calls": list(business.LINK_CALL_TYPES), "data": list(business.LINK_DATA_TYPES)}})


@bp.post("/business/gaps/dismiss")
def business_gap_dismiss():
    """"Không phải" (``{gap}``), or undo it (``{gap, undo: true}``)."""
    from viewer_hub.codemap.business import gaps

    body = _body(MAX_EDIT_BYTES)
    gap_id = body.get("gap") if isinstance(body.get("gap"), str) else ""
    with connection() as db:
        if body.get("undo") is True:
            gaps.restore(db, gap_id)
        else:
            gaps.dismiss(db, gap_id, _who())
        return jsonify({"ok": True})


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
