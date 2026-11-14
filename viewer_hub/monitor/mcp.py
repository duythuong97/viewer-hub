"""MCP server: AI checks how its own tool calls went (errors, slow tools) and whether addons are healthy.

Tools
  monitor_errors  recent failed tool calls: when, server.tool, client, time taken, error
  monitor_tools   per tool over a window: calls, errors, p50 / p95 time, average size of the answer
  monitor_status  what needs attention now (alerts) and the latest addon events

Only figures: tool names, times, error messages, argument names; never what the tools returned.
Transports: HTTP ``POST /monitor/mcp`` (routes.py) and stdio ``viewer-hub mcp monitor``.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from viewer_hub.core.mcp import ToolError, dispatch, int_arg, serve_stdio as _serve_stdio
from viewer_hub.core.monitor import Reader

INSTRUCTIONS = (
    "Monitoring of the Viewer Hub MCP servers (Code map, F-Search, CSV, addons such as SVN). When one of their tools fails "
    "or answers oddly, call monitor_errors (optionally server=<name>) to read the recent errors; monitor_tools shows "
    "which tools are slow or return big answers; monitor_status lists what needs attention (failing servers, "
    "addons that crashed). Read-only figures; tool results are never stored."
)

_HOURS = {"hours": {"type": "number", "description": "Window in hours (default 24, max 336)"}}
_SERVER = {"server": {"type": "string", "description": "MCP server name, e.g. svn, search, csv, codemap, diagram"}}

TOOLS: list[dict[str, Any]] = [
    {"name": "monitor_errors", "description": "Recent failed tool calls, newest first: time, server.tool, client, "
                                              "duration, error message, argument names.",
     "inputSchema": {"type": "object", "properties": {**_HOURS, **_SERVER,
                                                      "limit": {"type": "integer", "minimum": 1, "maximum": 100}}}},
    {"name": "monitor_tools", "description": "Per tool over the window: calls, errors, p50 / p95 / max time in ms, "
                                             "average answer size (characters) and estimated tokens returned.",
     "inputSchema": {"type": "object", "properties": {**_HOURS, **_SERVER}}},
    {"name": "monitor_status", "description": "What needs attention now (servers failing, slow tools, addons that "
                                              "crashed or use much memory), call totals of the last 24 h and the "
                                              "latest addon events.",
     "inputSchema": {"type": "object", "properties": {}}},
]


def _when(at: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(at))


def _hours(arguments: dict) -> float:
    try:
        return min(max(float(arguments.get("hours") or 24), 0.25), 336)
    except (TypeError, ValueError) as exc:
        raise ToolError("hours must be a number") from exc


def run(home: Path, name: str, arguments: dict) -> str:
    with Reader(home) as reader:
        if name == "monitor_errors":
            limit = int_arg(arguments, "limit", 20, 1, 100)
            rows = [r for r in reader.calls(errors=True, limit=limit, server=str(arguments.get("server") or ""),
                                            hours=_hours(arguments))]
            if not rows:
                return "No failed tool calls in this window."
            lines = [f"{len(rows)} failed call(s), newest first. time | server.tool | client | ms | error | args"]
            lines += [f"{_when(r['at'])} | {r['server']}.{r['tool']} | {r['client']} | {r['ms']:.0f} | "
                      f"{r['error'].replace(chr(10), ' ')[:200]} | {r['args']}" for r in rows]
            return "\n".join(lines)
        if name == "monitor_tools":
            server = str(arguments.get("server") or "")
            rows = [t for t in reader.tools(_hours(arguments)) if not server or t["server"] == server]
            if not rows:
                return "No tool calls in this window."
            lines = ["server.tool | calls | errors | p50 ms | p95 ms | max ms | avg chars | ~tokens total"]
            lines += [f"{t['server']}.{t['tool']} | {t['calls']} | {t['errors']} | {t['p50Ms']:.0f} | {t['p95Ms']:.0f} | "
                      f"{t['maxMs']:.0f} | {t['avgOut']} | {t['tokens']}" for t in rows]
            return "\n".join(lines)
        if name == "monitor_status":
            totals = reader.totals(24)
            alerts = reader.alerts()
            lines = [f"Last 24 h: {totals['calls']} calls, {totals['errors']} errors, p95 {totals['p95Ms']:.0f} ms, "
                     f"~{totals['tokens']} tokens returned, {totals['clients']} client(s)."]
            lines.append("Alerts:" if alerts else "Alerts: none.")
            lines += [f"- [{a['level']}] {a['source']}: {a['message']}" for a in alerts]
            events = reader.events(10)
            if events:
                lines.append("Latest addon events:")
                lines += [f"- {_when(e['at'])} {e['source']} {e['kind']}: {e['message']}" for e in events]
            return "\n".join(lines)
    raise ToolError(f"Unknown tool: {name}")


def handle(message: Any, home: Path) -> dict | list | None:
    return dispatch(message, name="viewer-hub-monitor", title="Giám sát", instructions=INSTRUCTIONS, tools=TOOLS,
                    run=lambda name, arguments: run(home, name, arguments))


def serve_stdio(home: Path) -> int:
    return _serve_stdio(lambda message: handle(message, home))
