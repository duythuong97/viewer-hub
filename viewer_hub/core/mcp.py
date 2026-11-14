"""The MCP plumbing every server of the hub shares (Code map, F-Search, CSV): JSON-RPC dispatch, stdio, HTTP.

A server is a list of tool definitions plus ``run(name, arguments) -> str | ToolResult``. Tools answer in plain
compact text; a ``ToolError`` becomes an ``isError`` result the agent can read, never a broken transport. Optional:
prompts (``prompts/list``, ``prompts/get``) and a hook that sees ``initialize`` (e.g. to note the client's name).
"""
from __future__ import annotations

import json
import logging
import sys
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

from viewer_hub import __version__
from viewer_hub.core import monitor

logger = logging.getLogger(__name__)

PROTOCOL_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]  # newest first
ALLOWED_ORIGIN_HOSTS = {"127.0.0.1", "localhost", "::1"}
MAX_HTTP_BODY = 256 * 1024
READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}


class ToolError(ValueError):
    """A problem with the call the agent can fix (bad argument, unknown id): shown to it as the tool result."""


@dataclass
class ToolResult:
    """A tool answer with its error flag, when ``run`` words its own errors."""
    text: str
    is_error: bool = False


@dataclass
class Prompts:
    """``prompts/list`` entries and ``get(name, arguments) -> result``; ``get`` raises ValueError for bad input."""
    listed: list[dict]
    get: Callable[[str, dict], dict]


def int_arg(arguments: dict, key: str, default: int, low: int, high: int) -> int:
    value = arguments.get(key, default)
    try:
        value = int(value)
    except (TypeError, ValueError):
        raise ToolError(f"{key} must be an integer") from None
    return max(low, min(high, value))


def dispatch(message: Any, *, name: str, title: str, instructions: str, tools: list[dict],
             run: Callable[[str, dict], "str | ToolResult"], version: str = __version__, prompts: Prompts | None = None,
             on_initialize: Callable[[dict], None] | None = None) -> dict | list | None:
    """One JSON-RPC message (or a batch); None for notifications."""
    if isinstance(message, list):
        replies = [r for r in (dispatch(m, name=name, title=title, instructions=instructions, tools=tools, run=run,
                                        version=version, prompts=prompts, on_initialize=on_initialize)
                               for m in message) if r is not None]
        return replies or None
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        if isinstance(message, dict) and "method" not in message:
            return None
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
    method, request_id, params = message["method"], message.get("id"), message.get("params") or {}
    notification = "id" not in message
    if not isinstance(params, dict):
        return None if notification else {"jsonrpc": "2.0", "id": request_id,
                                          "error": {"code": -32602, "message": "params must be an object"}}

    def reply(result=None, error=None):
        if notification:
            return None
        out = {"jsonrpc": "2.0", "id": request_id}
        out["error" if error else "result"] = error or result
        return out

    if method == "initialize":
        monitor.initialized(params)
        if on_initialize:
            on_initialize(params)
        requested = str(params.get("protocolVersion") or "")
        capabilities = {"tools": {"listChanged": False}}
        if prompts:
            capabilities["prompts"] = {"listChanged": False}
        return reply({
            "protocolVersion": requested if requested in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
            "capabilities": capabilities,
            "serverInfo": {"name": name, "title": title, "version": version},
            "instructions": instructions,
        })
    if method == "ping" or method.startswith("notifications/"):
        return reply({})
    if method == "tools/list":
        # Every tool of these servers only reads: say so (a bridge shows them as read tools; the user still turns them on).
        return reply({"tools": [{**tool, "annotations": tool.get("annotations") or READ_ONLY} for tool in tools]})
    if method == "tools/call":
        started = time.perf_counter()
        out = _call(params, tools, run, name, reply)
        # every builtin server's tool call, timed (core/monitor.py; a no-op unless this process records)
        monitor.call(monitor.server_key(name), str(params.get("name")), params.get("arguments"),
                     (time.perf_counter() - started) * 1000, out if out is not None else {"result": {}})
        return out
    if method == "prompts/list":
        return reply({"prompts": prompts.listed if prompts else []})
    if method == "prompts/get" and prompts:
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return reply(error={"code": -32602, "message": "arguments must be an object"})
        try:
            return reply(prompts.get(str(params.get("name")), {str(k): str(v) for k, v in arguments.items()}))
        except ValueError as error:
            return reply(error={"code": -32602, "message": str(error)})
    if method == "resources/list":
        return reply({"resources": []})
    if method == "resources/templates/list":
        return reply({"resourceTemplates": []})
    return reply(error={"code": -32601, "message": f"Method not found: {method}"})


def _call(params: dict, tools: list[dict], run, name: str, reply):
    tool = params.get("name")
    if tool not in {t["name"] for t in tools}:
        return reply(error={"code": -32602, "message": f"Unknown tool: {tool}"})
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        return reply(error={"code": -32602, "message": "arguments must be an object"})
    try:
        out = run(tool, arguments)
        if isinstance(out, ToolResult):
            return reply({"content": [{"type": "text", "text": out.text}], "isError": out.is_error})
        return reply({"content": [{"type": "text", "text": out}], "isError": False})
    except ToolError as error:
        return reply({"content": [{"type": "text", "text": f"Error: {error}"}], "isError": True})
    except Exception:  # noqa: BLE001  (never break the transport on one bad call)
        logger.exception("%s mcp tool failed: %s", name, tool)
        return reply({"content": [{"type": "text", "text": "Error: internal error (see the app log)."}], "isError": True})


def serve_stdio(handle: Callable[[Any], Any]) -> int:
    """One JSON-RPC message per line on stdin, replies on stdout; logs go to stderr. Bytes are UTF-8 whatever the
    console code page (Windows); a text stream without a byte buffer (tests) is used as it is."""
    source = getattr(sys.stdin, "buffer", sys.stdin)
    sink = getattr(sys.stdout, "buffer", None)
    for raw in source:
        line = (raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw).strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            out = handle(message)
        if out is not None:
            text = json.dumps(out, ensure_ascii=False) + "\n"
            if sink is not None:
                sink.write(text.encode("utf-8"))
                sink.flush()
            else:
                sys.stdout.write(text)
                sys.stdout.flush()
    return 0


def http_endpoint(request, handle: Callable[[Any], Any], max_body: int = MAX_HTTP_BODY):
    """Streamable HTTP, JSON replies only, for a Flask view: local origins only, bounded body."""
    from flask import Response, jsonify

    if request.method != "POST":
        return Response(status=405, headers={"Allow": "POST"})
    origin = request.headers.get("Origin")
    if origin and (urlparse(origin).hostname or "").lower() not in ALLOWED_ORIGIN_HOSTS:
        return jsonify(jsonrpc="2.0", id=None, error={"code": -32600, "message": "Origin not allowed"}), 403
    if request.content_length is None or request.content_length > max_body:
        return jsonify(jsonrpc="2.0", id=None, error={"code": -32600, "message": "Bounded JSON body required"}), 413
    try:
        message = json.loads(request.get_data(as_text=True))
    except ValueError:
        return jsonify(jsonrpc="2.0", id=None, error={"code": -32700, "message": "Parse error"}), 400
    token = monitor.http_context(request.headers)
    try:
        out = handle(message)
    finally:
        monitor.reset_context(token)
    if out is None:
        return Response(status=202)
    response = Response(json.dumps(out, ensure_ascii=False), mimetype="application/json")
    version = request.headers.get("MCP-Protocol-Version", "")
    if version in PROTOCOL_VERSIONS:
        response.headers["MCP-Protocol-Version"] = version
    return response
