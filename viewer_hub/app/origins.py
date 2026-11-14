"""Two origins on one server (design.md §6.4, §9).

The app runs on http://127.0.0.1:<port>. Content written by users (docs sites
built from their markdown) is served only from http://localhost:<port>: a
different origin, so its scripts cannot read the app's pages, call its forms
or reach the box-mcp daemon, which only allows the app origin.

Any other Host header is refused (DNS rebinding).
"""
from __future__ import annotations

import re

from flask import abort, current_app, redirect, request

APP_HOST = "127.0.0.1"
CONTENT_HOST = "localhost"
CONTENT_PATH = re.compile(r"^/docs/[a-z0-9-]+/view(/|$)")


def _split_host() -> tuple[str, str]:
    host, _, port = request.host.partition(":")
    return host.lower(), port


def _url(host: str, path: str) -> str:
    _, port = _split_host()
    netloc = f"{host}:{port}" if port else host
    return f"{request.scheme}://{netloc}{path}"


def content_url(path: str) -> str:
    """Absolute URL of user content on the content origin (use in templates)."""
    return _url(CONTENT_HOST, path)


def enforce():
    if not current_app.config.get("SPLIT_ORIGINS", True):
        return None
    host, _ = _split_host()
    if host not in (APP_HOST, CONTENT_HOST):
        abort(400)
    is_content = bool(CONTENT_PATH.match(request.path))
    if is_content and host != CONTENT_HOST:
        return redirect(_url(CONTENT_HOST, request.full_path.rstrip("?")), code=302)
    if not is_content and host == CONTENT_HOST:
        if request.method != "GET":
            abort(403)
        return redirect(_url(APP_HOST, request.full_path.rstrip("?")), code=302)
    return None
