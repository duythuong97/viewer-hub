"""HTTP to an addon program on 127.0.0.1 (the only network code of the Hub that runs on the user's machine): a
managed addon on the port the Hub gave the process it started, or an external addon's program on the port its
settings name (runner.py). Never another host.

A managed addon's calls carry the per-run token (X-Viewer-Hub-Token), so another program on this PC cannot talk to
it without going through the Hub; an external program gets none (the Hub did not start it). Also here: the MCP read-only filter, used for both the HTTP and the stdio route.
"""
from __future__ import annotations

import http.client
import json
import time
from typing import Iterator
from urllib.parse import urlencode

from viewer_hub.core import monitor

TOKEN_HEADER = "X-Viewer-Hub-Token"
HOST = "127.0.0.1"
TIMEOUT = 60
STREAM_IDLE = 300  # an event stream with nothing for this long is closed (the page's EventSource reconnects)
MAX_REPLY = 64 * 1024 * 1024
PASS_HEADERS = ("Content-Type", "Cache-Control", "Content-Disposition", "MCP-Protocol-Version", "Mcp-Session-Id")


class Unavailable(Exception):
    """The addon process does not answer."""


def _connect(port: int, timeout: float | None) -> http.client.HTTPConnection:
    return http.client.HTTPConnection(HOST, port, timeout=timeout)


def request(port: int, token: str, method: str, path: str, *, query: dict | None = None, body: bytes | None = None,
            headers: dict | None = None, timeout: float | None = TIMEOUT) -> tuple[int, dict, bytes]:
    """(status, headers worth passing on, body)."""
    target = path + (("?" + urlencode(query, doseq=True)) if query else "")
    conn = _connect(port, timeout)
    try:
        conn.request(method, target, body=body, headers={**(headers or {}), **({TOKEN_HEADER: token} if token else {})})
        response = conn.getresponse()
        data = response.read(MAX_REPLY + 1)
        if len(data) > MAX_REPLY:
            raise Unavailable("reply too large")
        kept = {name: response.getheader(name) for name in PASS_HEADERS if response.getheader(name)}
        return response.status, kept, data
    except (OSError, http.client.HTTPException) as exc:
        raise Unavailable(str(exc)) from exc
    finally:
        conn.close()


def stream(port: int, token: str, path: str, query: dict | None = None) -> tuple[int, dict, Iterator[bytes]]:
    """A GET whose reply is read as it comes (server-sent events)."""
    target = path + (("?" + urlencode(query, doseq=True)) if query else "")
    conn = _connect(port, STREAM_IDLE)
    try:
        conn.request("GET", target, headers={**({TOKEN_HEADER: token} if token else {}), "Accept": "text/event-stream"})
        response = conn.getresponse()
    except (OSError, http.client.HTTPException) as exc:
        conn.close()
        raise Unavailable(str(exc)) from exc
    kept = {name: response.getheader(name) for name in PASS_HEADERS if response.getheader(name)}

    def chunks() -> Iterator[bytes]:
        try:
            while True:
                chunk = response.read1(65536) if hasattr(response, "read1") else response.read(65536)
                if not chunk:
                    return
                yield chunk
        except (OSError, http.client.HTTPException):
            return
        finally:
            conn.close()

    return response.status, kept, chunks()


def healthy(port: int, token: str) -> bool:
    try:
        return request(port, token, "GET", "/health", timeout=2)[0] == 200
    except Unavailable:
        return False


# ── MCP: only read-only tools pass (AGENTS.md "MCP chỉ đọc") ─────────────────────────────────────────────────────

def _read_only(tool: dict) -> bool:
    return bool((tool.get("annotations") or {}).get("readOnlyHint"))


def filter_mcp(request_message, reply, allowed: set[str] | None = None):
    """Hides tools without readOnlyHint from tools/list; ``allowed`` (the names that passed) is filled in."""
    if isinstance(reply, list):
        return [filter_mcp(request_message, item, allowed) for item in reply]
    if isinstance(reply, dict) and isinstance(reply.get("result"), dict) and isinstance(reply["result"].get("tools"), list):
        tools = [t for t in reply["result"]["tools"] if isinstance(t, dict) and _read_only(t)]
        if allowed is not None:
            allowed.update(str(t.get("name")) for t in tools)
        return {**reply, "result": {**reply["result"], "tools": tools}}
    return reply


def _calls(message) -> list[dict]:
    items = message if isinstance(message, list) else [message]
    return [m for m in items if isinstance(m, dict) and m.get("method") == "tools/call"]


def _post(port: int, token: str, message) -> tuple[int, object]:
    status, _headers, data = request(port, token, "POST", "/mcp", body=json.dumps(message).encode("utf-8"),
                                     headers={"Content-Type": "application/json", "Accept": "application/json"})
    if status == 202 or not data.strip():
        return status, None
    try:
        return status, json.loads(data)
    except ValueError as exc:
        raise Unavailable(f"addon trả MCP không phải JSON: {exc}") from exc


def mcp_call(port: int, token: str, message, read_only_tools: set[str], server: str = "") -> tuple[int, object]:
    """One MCP JSON-RPC message (or batch) to the addon's /mcp, filtered. ``read_only_tools`` caches the tools seen
    with readOnlyHint for this run of the addon; a call of any other tool is refused without reaching the addon.
    ``server`` (the addon's MCP command) names the calls in the monitor (core/monitor.py)."""
    started = time.perf_counter()
    try:
        status, reply = _mcp_call(port, token, message, read_only_tools)
    except Unavailable as exc:
        _record(server, message, None, started, str(exc))
        raise
    _record(server, message, reply, started)
    return status, reply


def _record(server: str, message, reply, started: float, failure: str = "") -> None:
    if not server or monitor.recorder() is None:
        return
    items = message if isinstance(message, list) else [message]
    for item in items:
        if isinstance(item, dict) and item.get("method") == "initialize":
            monitor.initialized(item.get("params"))
    calls = _calls(message)
    if not calls:
        return
    replies = {r.get("id"): r for r in (reply if isinstance(reply, list) else [reply]) if isinstance(r, dict)}
    ms = (time.perf_counter() - started) * 1000 / len(calls)  # a batch shares its time
    for call in calls:
        params = call.get("params") or {}
        answer = {"error": {"message": failure}} if failure else replies.get(call.get("id"))  # None: not answered
        monitor.call(server, str(params.get("name")), params.get("arguments"), ms, answer)


def _mcp_call(port: int, token: str, message, read_only_tools: set[str]) -> tuple[int, object]:
    calls = _calls(message)
    if calls and not read_only_tools:
        _status, listed = _post(port, token, {"jsonrpc": "2.0", "id": "viewer-hub-tools", "method": "tools/list"})
        filter_mcp(None, listed, read_only_tools)
    refused = [m for m in calls if (m.get("params") or {}).get("name") not in read_only_tools]
    if refused:
        errors = [{"jsonrpc": "2.0", "id": m.get("id"), "error": {
            "code": -32602, "message": f"Tool {(m.get('params') or {}).get('name')} không có readOnlyHint: "
                                       "Viewer Hub chỉ cho AI dùng tool đọc"}} for m in refused]
        return 200, errors if isinstance(message, list) else errors[0]
    status, reply = _post(port, token, message)
    return status, filter_mcp(message, reply, read_only_tools)
