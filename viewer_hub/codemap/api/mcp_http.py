"""Streamable HTTP MCP transport (JSON responses, no server-sent stream): ``POST /code-map/mcp[?pack=<id>]``.

* The caller's name comes from ``X-Code-Map-User`` (VS Code ``mcp.json`` can send it in ``headers``).
* The propose_* tools are offered only with ``X-Code-Map-Token`` (or ``Authorization: Bearer``) equal to the
  knowledge token (packs.knowledge_token); read tools need no token. Never when the hub is read-only.
* A browser ``Origin`` must be localhost (DNS-rebinding protection); transport in core/mcp.http_endpoint.
"""
from __future__ import annotations

import hmac
from urllib.parse import unquote

from flask import Blueprint, current_app, g, request

from viewer_hub.codemap.mcp.server import CallContext, McpServer
from viewer_hub.core import mcp
from viewer_hub.codemap.packs import knowledge_token
from viewer_hub.codemap.workspace import for_source

MAX_BODY_BYTES = 1024 * 1024

bp = Blueprint("codemap_mcp", __name__)


@bp.route("/mcp", methods=["POST", "GET", "DELETE"])
def mcp_endpoint():
    source = g.codemap
    context = CallContext(
        user=unquote(request.headers.get("X-Code-Map-User") or "").strip()[:100],
        allow_write=not source.readonly and _write_allowed(),
    )
    server = McpServer(for_source(source))
    return mcp.http_endpoint(request, lambda message: server.handle(message, context), max_body=MAX_BODY_BYTES)


def _write_allowed() -> bool:
    token = knowledge_token(current_app.extensions["codemap_hub"])
    supplied = request.headers.get("X-Code-Map-Token", "")
    authorization = request.headers.get("Authorization", "")
    if not supplied and authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    return bool(token) and bool(supplied) and hmac.compare_digest(supplied, token)
