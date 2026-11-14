"""Giám sát: the page (React, web/src/modules/monitor), its JSON API over monitor.db (core/monitor.py) and the MCP
endpoint. Labels: a server is named by its MCP command (svn, search, diagram…), an event by its addon id."""
from __future__ import annotations

import time

from flask import Blueprint, g, request

from viewer_hub.app import spa
from viewer_hub.core.monitor import Reader
from viewer_hub.monitor import labels

bp = Blueprint("monitor", __name__)
HOURS = (1, 6, 24, 24 * 7, 24 * 14)


@bp.get("/")
def index():
    return spa.page()


def _hours(default: float = 24) -> float:
    try:
        value = float(request.args.get("hours", default))
    except ValueError:
        return default
    return min(max(value, 0.25), 24 * 90)


def _reader() -> Reader:
    return Reader(g.hub.paths.home)


@bp.get("/api/overview")
def overview():
    hours = _hours()
    with _reader() as reader:
        return {"totals": reader.totals(hours), "series": reader.series(int(min(hours, 24 * 14)) if hours >= 2 else 2),
                "servers": reader.by_server(hours), "clients": reader.clients(), "events": reader.events(20),
                "alerts": reader.alerts(), "settings": reader.settings(), "labels": labels(g.hub), "now": time.time()}


@bp.get("/api/calls")
def calls():
    args = request.args
    with _reader() as reader:
        rows = reader.calls(since_id=int(args.get("since") or 0), before_id=int(args.get("before") or 0),
                            limit=int(args.get("limit") or 200), server=args.get("server", ""), tool=args.get("tool", ""),
                            client=args.get("client", ""), errors=args.get("errors") == "1")
        return {"calls": rows, "clients": [c["client"] for c in reader.clients()], "labels": labels(g.hub)}


@bp.get("/api/tools")
def tools():
    with _reader() as reader:
        return {"tools": reader.tools(_hours()), "labels": labels(g.hub)}


def _gateway_stats(runner) -> dict | None:
    """A daemon that gathers MCP servers (MCP Bridge) reports its own calls (GET /api/stats, my-bridge)."""
    try:
        status, body = runner.request("GET", "/api/stats?hours=24")
    except Exception:  # noqa: BLE001  (an older bridge, or not running)
        return None
    return body if status == 200 and isinstance(body, dict) else None


@bp.get("/api/addons")
def addons():
    from viewer_hub.addons.gateway import PROVIDES

    hub = g.hub
    with _reader() as reader:
        samples = reader.samples(6)
        out = [{"id": "hub", "name": "Viewer Hub", "lifecycle": "hub", "running": True, "samples": samples.get("hub", []),
                "events": [], "gateway": None}]
        for module in hub.modules:
            addon = module.addon
            if addon is None:
                continue
            runner = hub.addons.runner(addon)
            problem = runner.problem()
            running = not problem and runner.running()
            item = {"id": addon.id, "name": module.label, "lifecycle": addon.lifecycle, "running": running,
                    "problem": problem, "mcp": addon.mcp.command if addon.mcp else None,
                    "samples": samples.get(addon.id, []), "events": reader.events(10, source=addon.id),
                    "crashes": len([e for e in reader.events(200, source=addon.id, hours=24) if e["kind"] == "crash"]),
                    "gateway": None}
            if running and addon.daemon and PROVIDES in addon.provides:
                item["gateway"] = _gateway_stats(runner)
            out.append(item)
        return {"addons": out, "labels": labels(hub)}


@bp.get("/api/alerts")
def alerts():
    with _reader() as reader:
        return {"alerts": reader.alerts(), "labels": labels(g.hub)}


@bp.put("/api/settings")
def save_settings():
    with _reader() as reader:
        settings = reader.save_settings(request.get_json(silent=True) or {})
    return {"settings": settings, "message": "Đã lưu cài đặt giám sát (áp dụng trong vòng 30 giây)"}


@bp.post("/api/clear")
def clear():
    with _reader() as reader:
        reader.clear()
    return {"message": "Đã xoá dữ liệu giám sát"}


@bp.route("/mcp", methods=["POST", "GET", "DELETE"])
def mcp_endpoint():
    """MCP (streamable HTTP) over the monitor data; see monitor/mcp.py."""
    from viewer_hub.core.mcp import http_endpoint
    from viewer_hub.monitor import mcp

    home = g.hub.paths.home
    return http_endpoint(request, lambda message: mcp.handle(message, home))
