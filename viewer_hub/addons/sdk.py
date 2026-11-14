"""SDK for Python addons (AGENTS.md §4.1 of the addon SDK): the HTTP side of the contract, so an addon is only its
functions.

    from viewer_hub.addons.sdk import Addon, ApiError

    addon = Addon("svn-lite", title="SVN Lite", instructions="Read-only SVN for AI.")

    @addon.get("/repos")                      # → GET /x/<id>/api/repos on the Hub
    def repos(request):
        return {"repos": addon.settings().get("repos", [])}

    @addon.tool("svn_list", "List a folder", {"type": "object", "properties": {"path": {"type": "string"}}})
    def svn_list(arguments):
        return "text for the AI"              # or raise ToolError("…")

    if __name__ == "__main__":
        addon.run()

Runs in the addon's own process (never in the Hub): a small threaded HTTP server on 127.0.0.1 that refuses any
request without the Hub's per-run token. Errors are ``{"error": {"code", "message"}}`` like the Hub's own API.
MCP tools are read-only (viewer_hub.core.mcp marks them so); the Hub hides any tool without readOnlyHint anyway.

Tests call the two entry points without a server:  addon.handle_api("GET", "/items", {}, None, {}) → (status, body)
and  addon.handle_mcp({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {...}}) → JSON-RPC reply.
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlsplit

from viewer_hub.core.mcp import ToolError, ToolResult, dispatch, int_arg  # noqa: F401  (re-exported for addons)
from viewer_hub.core.text import decode_text, fold, looks_binary  # noqa: F401  (re-exported for addons)

logger = logging.getLogger("addon")
MAX_BODY = 8 * 1024 * 1024
TOKEN_HEADER = "X-Viewer-Hub-Token"


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass
class Request:
    method: str
    path: str                 # after /api, e.g. "/repos/abc"
    params: dict[str, str]    # from the route pattern, e.g. {"name": "abc"} for "/repos/<name>"
    query: dict[str, str]
    body: Any                 # decoded JSON (None when there is none)
    headers: Any


class Addon:
    def __init__(self, name: str, *, title: str = "", instructions: str = "", version: str = "") -> None:
        self.name = name
        self.title = title or name
        self.instructions = instructions
        self.version = version or "0"
        self.tools: list[dict] = []
        self._tool_handlers: dict[str, Callable[[dict], Any]] = {}
        self._routes: list[tuple[str, re.Pattern, Callable]] = []
        self.data = Path(os.environ.get("VIEWER_HUB_ADDON_DATA") or Path.cwd() / "data")
        self._settings_file = Path(os.environ.get("VIEWER_HUB_ADDON_SETTINGS") or self.data / "settings.json")
        self._token = os.environ.get("VIEWER_HUB_ADDON_TOKEN", "")
        self._server: ThreadingHTTPServer | None = None

    # ── declaring ───────────────────────────────────────────────────────────────────────────────────────────
    def route(self, method: str, pattern: str):
        regex = re.compile("^" + re.sub(r"<([a-zA-Z_][a-zA-Z0-9_]*)>", r"(?P<\1>[^/]+)", pattern.rstrip("/") or "/") + "/?$")

        def wrap(handler):
            self._routes.append((method.upper(), regex, handler))
            return handler
        return wrap

    def get(self, pattern: str):
        return self.route("GET", pattern)

    def post(self, pattern: str):
        return self.route("POST", pattern)

    def put(self, pattern: str):
        return self.route("PUT", pattern)

    def patch(self, pattern: str):
        return self.route("PATCH", pattern)

    def delete(self, pattern: str):
        return self.route("DELETE", pattern)

    def tool(self, name: str, description: str, schema: dict | None = None, *, title: str = ""):
        def wrap(handler):
            self.tools.append({"name": name, "title": title or name, "description": description,
                               "inputSchema": schema or {"type": "object", "properties": {}}})
            self._tool_handlers[name] = handler
            return handler
        return wrap

    # ── reading ─────────────────────────────────────────────────────────────────────────────────────────────
    def settings(self) -> dict:
        """The values of the settings form (addon.json ``settings``), as the Hub saved them."""
        try:
            value = json.loads(self._settings_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    # ── serving ─────────────────────────────────────────────────────────────────────────────────────────────
    def handle_mcp(self, message):
        def run(tool: str, arguments: dict):
            return self._tool_handlers[tool](arguments)

        return dispatch(message, name=self.name, title=self.title, instructions=self.instructions,
                        tools=self.tools, run=run, version=self.version)

    def handle_api(self, method: str, path: str, query: dict, body, headers) -> tuple[int, Any]:
        allowed = False
        for route_method, regex, handler in self._routes:
            match = regex.match(path)
            if not match:
                continue
            allowed = True
            if route_method != method:
                continue
            try:
                result = handler(Request(method, path, match.groupdict(), query, body, headers))
            except ApiError as exc:
                return exc.status, {"error": {"code": exc.code, "message": exc.message}}
            except Exception:  # noqa: BLE001  (one bad call never stops the addon)
                logger.exception("api %s %s failed", method, path)
                return 500, {"error": {"code": "internal", "message": "Lỗi trong addon (xem log)"}}
            return 200, result if result is not None else {}
        if allowed:
            return 405, {"error": {"code": "method_not_allowed", "message": "Không hỗ trợ thao tác này"}}
        return 404, {"error": {"code": "not_found", "message": "Không tìm thấy"}}

    def _handler(self):
        addon = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, fmt, *args):  # quiet: the Hub logs calls
                return

            def _send(self, status: int, value) -> None:
                data = b"" if value is None else json.dumps(value, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _serve(self) -> None:
                if not addon._token or self.headers.get(TOKEN_HEADER) != addon._token:
                    return self._send(403, {"error": {"code": "forbidden", "message": "Chỉ Viewer Hub gọi được addon"}})
                url = urlsplit(self.path)
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    return self._send(413, {"error": {"code": "too_large", "message": "Dữ liệu quá lớn"}})
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw) if raw.strip() else None
                except ValueError:
                    return self._send(400, {"error": {"code": "bad_json", "message": "Body không phải JSON"}})
                method = self.command
                if url.path == "/health":
                    return self._send(200, {"ok": True})
                if url.path == "/shutdown" and method == "POST":
                    self._send(200, {"ok": True})
                    threading.Thread(target=addon._server.shutdown, daemon=True).start()
                    return None
                if url.path == "/mcp" and method == "POST":
                    reply = addon.handle_mcp(body)
                    return self._send(202, None) if reply is None else self._send(200, reply)
                if url.path == "/api" or url.path.startswith("/api/"):
                    query = {k: v[-1] for k, v in parse_qs(url.query).items()}
                    status, value = addon.handle_api(method, url.path[4:] or "/", query, body, self.headers)
                    return self._send(status, value)
                return self._send(404, {"error": {"code": "not_found", "message": "Không tìm thấy"}})

            do_GET = do_POST = do_PUT = do_PATCH = do_DELETE = _serve

        return Handler

    def run(self, argv: list[str] | None = None) -> None:
        """``serve --port N`` (what the Hub runs)."""
        import argparse

        logging.basicConfig(level=logging.INFO, format=f"%(levelname)s {self.name}: %(message)s", stream=sys.stderr)
        parser = argparse.ArgumentParser(prog=self.name)
        parser.add_argument("command", choices=["serve"])
        parser.add_argument("--port", type=int, required=True)
        args = parser.parse_args(sys.argv[1:] if argv is None else argv)
        self.data.mkdir(parents=True, exist_ok=True)
        self._server = ThreadingHTTPServer(("127.0.0.1", args.port), self._handler())
        self._server.daemon_threads = True
        logger.info("listening on 127.0.0.1:%s", args.port)
        try:
            self._server.serve_forever()
        finally:
            self._server.server_close()
