"""Code-map viewer in the hub (design.md §6.1).

* The page ``GET /code-map/`` is the app page (React: web/src/modules/codemap); ``GET /code-map/config`` gives it
  the packs and API bases. Both are on the main app (``register_page``).
* The JSON API (``/code-map/api/graph/...``) and HTTP MCP (``/code-map/mcp``) are a
  separate Flask app, ``create_codemap_app(hub)``, written to sit at ``/code-map``;
  ``codemap_mounts(hub)`` gives the DispatcherMiddleware entries for its two prefixes.

Every request picks its pack from ``?pack=<id>`` (default: the first active one).
"""
from __future__ import annotations

from flask import Blueprint, Flask, g, jsonify, request

from viewer_hub.app import spa

from viewer_hub.codemap import erd_addon, packs

APP_HOST = "127.0.0.1"  # app/origins.py: app pages and their APIs live on this host only
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

page_bp = Blueprint("codemap", __name__)


@page_bp.get("/code-map/")
def index():
    return spa.page()


@page_bp.get("/code-map/config")
def page_config():
    hub = g.hub
    available = packs.sources(hub)
    wanted = request.args.get("pack", "").strip()
    current = next((source for source in available if source.pack_id == wanted), None) if wanted else None
    if current is None and available and not wanted:
        current = available[0]
    return {"wanted": wanted if current is None else "", "current": current.title if current else "",
            "config": {"apiBase": "/code-map/api/graph", "mcpUrl": "/code-map/mcp", "erdAddon": erd_addon.addon_path(hub) or "",
                       "pack": current.pack_id if current else "", "packs": [source.describe() for source in available],
                       "source": bool(current and current.has_source), "readonly": bool(hub.readonly)}}


def register_page(app: Flask) -> None:
    app.register_blueprint(page_bp)


def create_codemap_app(hub) -> Flask:
    """API + MCP for code-map packs; expects SCRIPT_NAME=/code-map (see codemap_mounts)."""
    from viewer_hub.codemap.api import business_routes, knowledge_routes  # noqa: F401  (routes on graph_routes.bp)
    from viewer_hub.codemap.api import graph_routes, mcp_http

    app = Flask("viewer_hub.codemap")
    app.json.ensure_ascii = False
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024  # a shared knowledge file (business_routes)
    app.extensions["codemap_hub"] = hub
    app.register_blueprint(graph_routes.bp, url_prefix="/api/graph")
    app.register_blueprint(mcp_http.bp)

    def api_error(code: str, message: str, status: int):
        return jsonify({"error": {"code": code, "message": message, "details": {}}}), status

    @app.before_request
    def _pick_pack():
        # DispatcherMiddleware bypasses the main app's origin check; apply the same rule here.
        if app.config.get("SPLIT_ORIGINS", True) and request.host.partition(":")[0].lower() != APP_HOST:
            return api_error("bad_host", "Code map chỉ phục vụ trên http://127.0.0.1", 400)
        if hub.readonly and request.method in WRITE_METHODS and request.path != "/mcp":
            return api_error("readonly", "Dữ liệu đang mở ở chế độ chỉ đọc; không lưu được thay đổi.", 409)
        pack_id = request.args.get("pack", "").strip() or None
        source = packs.pick(hub, pack_id)
        if source is None:
            if request.path == "/mcp":
                return jsonify({"jsonrpc": "2.0", "id": None, "error": {
                    "code": -32002, "message": "No code-map pack is installed (import a .sapack with a codemap component)"}}), 503
            if pack_id:
                return api_error("unknown_pack", f"Không có pack code-map đang bật tên '{pack_id}'.", 404)
            return api_error("no_codemap_pack", "Chưa có pack code-map nào. Import một .sapack có thành phần codemap.", 503)
        g.codemap = source
        return None

    @app.after_request
    def _headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.errorhandler(404)
    def _not_found(_error):
        return api_error("not_found", "API route not found", 404)

    @app.errorhandler(405)
    def _method(_error):
        return api_error("method_not_allowed", "HTTP method not allowed", 405)

    @app.errorhandler(413)
    def _too_large(_error):
        return api_error("body_too_large", "Request body exceeds the limit", 413)

    return app


class _Under:
    """Restore ``/code-map`` as SCRIPT_NAME after DispatcherMiddleware stripped a longer prefix."""

    def __init__(self, app, segment: str):
        self.app, self.segment = app, segment

    def __call__(self, environ, start_response):
        script = environ.get("SCRIPT_NAME", "")
        if script.endswith(self.segment):
            environ["SCRIPT_NAME"] = script[: -len(self.segment)]
            environ["PATH_INFO"] = self.segment + environ.get("PATH_INFO", "")
        return self.app(environ, start_response)


def codemap_mounts(hub) -> dict:
    """DispatcherMiddleware entries: the page stays on the main app, API and MCP go to the sub-app."""
    api = create_codemap_app(hub)
    return {"/code-map/api": _Under(api, "/api"), "/code-map/mcp": _Under(api, "/mcp")}
