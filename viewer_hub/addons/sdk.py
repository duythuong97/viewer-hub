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

Tests call the entry points without a server:  addon.handle_api("GET", "/items", {}, None, {}) → (status, body),
addon.handle_mcp({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {...}}) → JSON-RPC reply and
addon.handle_export("svn_log", {...}) → (status, body).

Addons reading each other (docs/plans/addon-interop.md): what an addon lets others read is declared in addon.json
``exports`` and served with ``@addon.export``; what it reads is declared in ``uses`` and fetched with ``addon.call``,
which goes through the Hub (it checks the contract, starts the other addon, records the call):

    @addon.export("svn_log")                  # addon.json: "exports": [{"name": "svn_log", "params": …, "returns": …}]
    def svn_log(params):
        return {"items": [...]}               # a dict matching "returns"; raise ApiError(...) for an error

    reply = addon.call("svn", "svn_log", {"repo": "core", "limit": 20})   # addon.json: "uses": {"svn": {...}}
    # CallError(code, message, status) when it cannot: dependency_missing, dependency_incompatible, export_unknown,
    # bad_params, bad_reply, dependency_unavailable, call_depth, forbidden

Without a Hub (the addon's own tests), ``addon.call`` answers with the ``example`` of the contract the kit saved in
``.sdk/addons/<id>.json`` (params checked against it), or what ``addon.fake(id, export, reply)`` set.
"""
from __future__ import annotations

import http.client
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

from viewer_hub.addons.contract import validate
from viewer_hub.core.mcp import ToolError, ToolResult, dispatch, int_arg  # noqa: F401  (re-exported for addons)
from viewer_hub.core.text import decode_text, fold, looks_binary  # noqa: F401  (re-exported for addons)

logger = logging.getLogger("addon")
MAX_BODY = 8 * 1024 * 1024
TOKEN_HEADER = "X-Viewer-Hub-Token"
CALLER_HEADER = "X-Viewer-Hub-Caller"
DEPTH_HEADER = "X-Viewer-Hub-Depth"
CALL_TIMEOUT = 60.0
EXPORT_RE = re.compile(r"^/export/([a-z0-9_]{1,64})$")


class ApiError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class CallError(Exception):
    """``addon.call`` could not get the other addon's answer: ``code`` says why (see the module docstring)."""

    def __init__(self, code: str, message: str, status: int = 0):
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.status = code, message, status


_depth = threading.local()  # how deep the export being served is in a chain of calls (the Hub's DEPTH header)


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
        self._exports: dict[str, Callable[[dict], Any]] = {}
        self._fakes: dict[tuple[str, str], Any] = {}
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

    def export(self, name: str):
        """Serve the export ``name`` of addon.json ``exports``: the handler gets the params (checked by the Hub
        against the contract, defaults filled in) and returns a dict matching ``returns``."""
        def wrap(handler):
            self._exports[name] = handler
            return handler
        return wrap

    # ── other addons ────────────────────────────────────────────────────────────────────────────────────────
    def call(self, addon_id: str, export: str, params: dict | None = None, *, timeout: float = CALL_TIMEOUT) -> Any:
        """The reply of another addon's export, through the Hub. Only what addon.json ``uses`` names; CallError
        otherwise. Without a Hub (tests): the fake set by ``fake()``, else the example of .sdk/addons/<id>.json."""
        params = {} if params is None else params
        if not isinstance(params, dict):
            raise CallError("bad_params", "params phải là dict")
        url = os.environ.get("VIEWER_HUB_URL", "")
        caller = os.environ.get("VIEWER_HUB_CALLER_TOKEN", "")
        if not url or not caller:
            return self._fake_call(addon_id, export, params)
        match = re.match(r"^http://127\.0\.0\.1:(\d+)$", url)
        if not match:
            raise CallError("forbidden", "VIEWER_HUB_URL phải là http://127.0.0.1:<cổng>")
        body = json.dumps(params, ensure_ascii=False).encode("utf-8")
        conn = http.client.HTTPConnection("127.0.0.1", int(match.group(1)), timeout=timeout)
        try:
            conn.request("POST", f"/api/addons/call/{addon_id}/{export}", body=body, headers={
                "Content-Type": "application/json", CALLER_HEADER: caller,
                DEPTH_HEADER: str(getattr(_depth, "value", 0))})
            response = conn.getresponse()
            data = response.read()
            status = response.status
        except (OSError, http.client.HTTPException) as exc:
            raise CallError("dependency_unavailable", f"không gọi được Viewer Hub: {exc}") from exc
        finally:
            conn.close()
        try:
            reply = json.loads(data) if data.strip() else None
        except ValueError:
            raise CallError("bad_reply", f"Viewer Hub trả lời không phải JSON ({status})", status) from None
        if status != 200:
            error = reply.get("error") if isinstance(reply, dict) and isinstance(reply.get("error"), dict) else {}
            raise CallError(str(error.get("code") or "call_failed"), str(error.get("message") or f"lỗi {status}"), status)
        return reply

    def fake(self, addon_id: str, export: str, reply: Any) -> None:
        """Tests: what ``call(addon_id, export)`` answers without a Hub (an Exception instance is raised instead)."""
        self._fakes[(addon_id, export)] = reply

    def _contract(self, addon_id: str) -> dict | None:
        folder = Path(os.environ.get("VIEWER_HUB_FAKE_EXPORTS") or self._folder() / ".sdk" / "addons")
        try:
            return json.loads((folder / f"{addon_id}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _fake_call(self, addon_id: str, export: str, params: dict) -> Any:
        uses = (self._manifest().get("uses") or {}).get(addon_id)
        if uses is not None and export not in (uses.get("exports") or []):
            raise CallError("export_unknown", f"addon.json chưa khai {addon_id}.{export} trong uses", 403)
        contract = self._contract(addon_id)
        exported = next((e for e in (contract or {}).get("exports", []) if e.get("name") == export), None)
        if exported is not None:
            problems = validate(exported.get("params") or {"type": "object"}, params, "params", extra=False)
            if problems:
                raise CallError("bad_params", f"{addon_id}.{export}: " + "; ".join(problems[:5]), 400)
        if (addon_id, export) in self._fakes:
            reply = self._fakes[(addon_id, export)]
            if isinstance(reply, Exception):
                raise reply
            return reply
        if exported is None:
            raise CallError("dependency_missing", f"không có Viewer Hub và chưa có contract của {addon_id} "
                                                  f"(.sdk/addons/{addon_id}.json: npm run exports), cũng chưa fake()")
        return exported.get("example")

    def _folder(self) -> Path:
        if os.environ.get("VIEWER_HUB_ADDON_FOLDER"):
            return Path(os.environ["VIEWER_HUB_ADDON_FOLDER"])
        main = sys.modules.get("__main__")
        return Path(getattr(main, "__file__", "") or Path.cwd() / "x").resolve().parent

    def _manifest(self) -> dict:
        try:
            value = json.loads((self._folder() / "addon.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

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

    def handle_export(self, name: str, params, depth: int = 0) -> tuple[int, Any]:
        handler = self._exports.get(name)
        if handler is None:
            return 404, {"error": {"code": "export_unknown", "message": f"addon chưa có hàm cho export {name}"}}
        _depth.value = depth
        try:
            result = handler(params if isinstance(params, dict) else {})
        except ApiError as exc:
            return exc.status, {"error": {"code": exc.code, "message": exc.message}}
        except CallError as exc:  # an addon further down the chain failed: pass its reason on
            return 424, {"error": {"code": exc.code, "message": exc.message}}
        except Exception:  # noqa: BLE001
            logger.exception("export %s failed", name)
            return 500, {"error": {"code": "internal", "message": "Lỗi trong addon (xem log)"}}
        finally:
            _depth.value = 0
        return 200, result if result is not None else {}

    def missing_exports(self) -> list[str]:
        """Exports addon.json declares that have no @addon.export handler."""
        declared = [e.get("name") for e in self._manifest().get("exports") or [] if isinstance(e, dict)]
        return [name for name in declared if name not in self._exports]

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
                export = EXPORT_RE.match(url.path)
                if export and method == "POST":
                    try:
                        depth = int(self.headers.get(DEPTH_HEADER) or 0)
                    except ValueError:
                        depth = 0
                    return self._send(*addon.handle_export(export.group(1), body, depth))
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
        missing = self.missing_exports()
        if missing:
            logger.error("addon.json khai export nhưng chưa có @addon.export: %s", ", ".join(missing))
            raise SystemExit(2)
        self.data.mkdir(parents=True, exist_ok=True)
        self._server = ThreadingHTTPServer(("127.0.0.1", args.port), self._handler())
        self._server.daemon_threads = True
        logger.info("listening on 127.0.0.1:%s", args.port)
        try:
            self._server.serve_forever()
        finally:
            self._server.server_close()
