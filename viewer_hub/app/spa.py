"""The single-page app: every page URL answers templates/app.html (web/src/app loads the page), every module's data
is JSON. Helpers for module routes:

    @bp.get("/")                        def index(): return spa.page()
    @bp.get("/api/repos")               def repos(): return {"repos": [...]}
    raise spa.ApiError("bad_url", "…", 400)   →  {"error": {"code", "message"}} with that status
"""
from __future__ import annotations

from flask import jsonify, render_template, request


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def page(status: int = 200):
    return render_template("app.html"), status


def error(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


def wants_json() -> bool:
    """API calls (``/api/…``, ``/<module>/api/…``, ``…/mcp``) and anything that is not a page GET get JSON errors."""
    path = request.path
    return (request.method != "GET" or path.startswith("/api/") or "/api/" in path or path.endswith("/mcp")
            or request.accept_mimetypes.best == "application/json")


def register(app) -> None:
    """Error handlers: JSON for API calls, the app page (which shows the error) for page URLs."""
    from viewer_hub.core.db import ReadOnlyError

    @app.errorhandler(ApiError)
    def _api_error(exc: ApiError):
        return error(exc.code, exc.message, exc.status)

    @app.errorhandler(404)
    def _not_found(_exc):
        return error("not_found", "Không tìm thấy", 404) if wants_json() else page(404)

    @app.errorhandler(405)
    def _method(_exc):
        return error("method_not_allowed", "Không hỗ trợ thao tác này", 405)

    @app.errorhandler(413)
    def _too_large(_exc):
        return error("too_large", "File vượt quá giới hạn 512 MB.", 413)

    @app.errorhandler(ReadOnlyError)
    def _readonly(exc):
        return error("readonly", str(exc), 409)
