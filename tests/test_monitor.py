"""Giám sát: MCP calls recorded at the two capture points (core/mcp.dispatch, addons/proxy.mcp_call), privacy of
arguments, the queries behind the page (totals, p95, alerts), the page API, the MCP tools and the upkeep."""
from __future__ import annotations

import json
import sqlite3
import time

import pytest

from viewer_hub.core import mcp, monitor
from viewer_hub.core.monitor import Reader


@pytest.fixture()
def rec(paths):
    recorder = monitor.configure(paths.home, "stdio")
    yield recorder
    recorder.flush()
    monitor.disable()


def _server(message):
    tools = [{"name": "echo", "inputSchema": {"type": "object"}}, {"name": "boom", "inputSchema": {"type": "object"}}]

    def run(name, arguments):
        if name == "boom":
            raise mcp.ToolError("bad path")
        return "x" * 400

    return mcp.dispatch(message, name="viewer-hub-svn", title="T", instructions="", tools=tools, run=run)


def _call(i, tool, arguments=None):
    return {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": tool, "arguments": arguments or {}}}


def test_dispatch_records_calls_client_and_hides_argument_values(paths, rec):
    _server({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"clientInfo": {"name": "claude-code", "version": "2.1"}}})
    _server(_call(1, "echo", {"path": "secret/file.py", "line": 3}))
    _server(_call(2, "boom", {"path": "x"}))
    _server(_call(3, "missing"))
    rec.flush()
    with Reader(paths.home) as reader:
        calls = reader.calls()
        assert [c["tool"] for c in calls] == ["missing", "boom", "echo"]
        echo = calls[2]
        assert echo["server"] == "svn" and echo["ok"] and echo["outChars"] == 400 and echo["tokens"] == 100
        assert echo["client"] == "claude-code 2.1" and echo["transport"] == "stdio"
        assert json.loads(echo["args"]) == {"path": "text(14)", "line": "number"}  # names and sizes, never values
        assert "secret" not in echo["args"]
        assert not calls[1]["ok"] and "bad path" in calls[1]["error"]
        assert not calls[0]["ok"] and "Unknown tool" in calls[0]["error"]
        totals = reader.totals()
        assert totals["calls"] == 3 and totals["errors"] == 2 and totals["clients"] == 1
        assert {c["client"] for c in reader.clients()} == {"claude-code 2.1"}
        series = reader.series(24)
        assert len(series) == 24 and series[-1]["calls"] == 3 and series[-1]["errors"] == 2
        tools = {t["tool"]: t for t in reader.tools()}
        assert tools["echo"]["calls"] == 1 and tools["boom"]["errors"] == 1


def test_full_arguments_mode_and_switch_off(paths, rec):
    with Reader(paths.home) as reader:
        reader.save_settings({"args": "full"})
    rec._settings_at = 0  # re-read the settings now
    _server(_call(1, "echo", {"q": "abc"}))
    rec.flush()
    with Reader(paths.home) as reader:
        assert json.loads(reader.calls()[0]["args"]) == {"q": "abc"}
        reader.save_settings({"enabled": False})
    rec._settings_at = 0
    _server(_call(2, "echo"))
    rec.flush()
    with Reader(paths.home) as reader:
        assert len(reader.calls()) == 1


def test_nothing_recorded_unless_configured(paths):
    monitor.disable()
    _server(_call(1, "echo"))
    assert not monitor.db_path(paths.home).exists()


def test_http_context_names_a_client_behind_a_gateway(paths, rec):
    token = monitor.http_context({"X-MCP-Client": "gateway/0.4", "User-Agent": "node"})
    try:
        _server(_call(1, "echo"))
    finally:
        monitor.reset_context(token)
    rec.flush()
    with Reader(paths.home) as reader:
        call = reader.calls()[0]
    assert call["transport"] == "http" and call["via"] == "gateway/0.4" and call["client"] == "gateway/0.4"


def test_addon_proxy_records_each_call_of_a_batch(paths, rec, monkeypatch):
    from viewer_hub.addons import proxy

    def fake_post(_port, _token, message):
        replies = [{"jsonrpc": "2.0", "id": m["id"], "result": {"content": [{"type": "text", "text": "ok!"}],
                                                                  "isError": m["params"]["name"] == "bad"}}
                   for m in message]
        return 200, replies

    monkeypatch.setattr(proxy, "_post", fake_post)
    allowed = {"good", "bad"}
    proxy.mcp_call(1, "t", [_call(1, "good", {"a": 1}), _call(2, "bad")], allowed, "diagram")
    proxy.mcp_call(1, "t", _call(3, "write"), allowed, "diagram")
    rec.flush()
    with Reader(paths.home) as reader:
        calls = {c["tool"]: c for c in reader.calls()}
    assert set(calls) == {"good", "bad", "write"}
    assert calls["good"]["ok"] and calls["good"]["server"] == "diagram" and calls["good"]["outChars"] == 3
    assert not calls["bad"]["ok"]
    assert not calls["write"]["ok"] and "readOnlyHint" in calls["write"]["error"]  # refused by the Hub, still seen


def test_alerts_for_failing_server_slow_tool_and_crash_loop(paths, rec):
    for i in range(6):
        rec.call("csv", "csv_query", {}, 12000 if i < 4 else 50, ok=i % 2 == 0, error="boom")
    for _ in range(3):
        rec.event("diagram", "crash", "error", "exit 1")
    rec.flush()
    with Reader(paths.home) as reader:
        kinds = {(a["source"], a["kind"]) for a in reader.alerts()}
    assert ("csv", "errors") in kinds and ("csv", "slow") in kinds and ("diagram", "crash-loop") in kinds


def test_percentile():
    values = list(range(1, 101))
    assert monitor.percentile(values, 0.5) == 50 and monitor.percentile(values, 0.95) == 95
    assert monitor.percentile([], 0.95) == 0


def test_prune_drops_old_rows(paths, rec):
    rec.call("svn", "svn_read", {}, 5, ok=True)
    rec.flush()
    db = monitor.connect(monitor.db_path(paths.home))
    with db:
        db.execute("UPDATE calls SET at = at - 30 * 86400")
        db.execute("INSERT INTO events(at, source, kind, level, message) VALUES (?, 'x', 'start', 'info', '')",
                   (time.time() - 40 * 86400,))
    monitor.prune(db, 14)
    assert db.execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM hourly").fetchone()[0] == 1  # hourly totals stay 90 days
    db.close()


def test_page_api_and_mcp(client, paths, rec):
    rec.call("csv", "svn_read", {"path": "a"}, 30, ok=True, out_chars=800)
    rec.call("csv", "svn_log", {}, 20, ok=False, error="no such branch")
    rec.event("diagram", "start", "info", "Đã chạy")
    rec.flush()
    assert '<div id="app">' in client.get("/monitor/").data.decode()
    overview = client.get("/monitor/api/overview?hours=24").get_json()
    assert overview["totals"]["calls"] == 2 and overview["labels"]["csv"] == "CSV"
    assert overview["servers"][0]["server"] == "csv" and overview["events"][0]["kind"] == "start"
    calls = client.get("/monitor/api/calls?errors=1").get_json()["calls"]
    assert [c["tool"] for c in calls] == ["svn_log"]
    since = client.get("/monitor/api/calls").get_json()["calls"][0]["id"]
    assert client.get(f"/monitor/api/calls?since={since}").get_json()["calls"] == []
    assert {t["tool"] for t in client.get("/monitor/api/tools").get_json()["tools"]} == {"svn_read", "svn_log"}
    addons = client.get("/monitor/api/addons").get_json()["addons"]
    assert addons[0]["id"] == "hub"
    saved = client.put("/monitor/api/settings", json={"args": "off", "retention_days": 500}).get_json()["settings"]
    assert saved["args"] == "off" and saved["retention_days"] == "90"
    assert client.get("/api/home").get_json()["alerts"] == []

    def tool(name, arguments=None):
        reply = client.post("/monitor/mcp", json=_call(9, name, arguments)).get_json()
        return reply["result"]["content"][0]["text"]

    assert "csv.svn_log" in tool("monitor_errors") and "no such branch" in tool("monitor_errors")
    assert "csv.svn_read" in tool("monitor_tools", {"server": "csv"})
    assert "Last 24 h" in tool("monitor_status")
    rec.flush()

    # MCP Playground tester API
    servers = client.get("/monitor/api/mcp/servers").get_json()["servers"]
    assert any(s["command"] == "monitor" for s in servers)
    inv_list = client.post("/monitor/api/mcp/invoke", json={"path": "/monitor/mcp", "method": "tools/list"}).get_json()
    assert inv_list["ok"] is True and isinstance(inv_list["raw_response"]["result"]["tools"], list)
    inv_call = client.post("/monitor/api/mcp/invoke", json={"path": "/monitor/mcp", "method": "tools/call", "params": {"name": "monitor_status", "arguments": {}}}).get_json()
    assert inv_call["ok"] is True and inv_call["latency_ms"] >= 0
    bad_call = client.post("/monitor/api/mcp/invoke", json={"path": "/not-mcp", "method": "tools/list"})
    assert bad_call.status_code == 403

    assert {c["server"] for c in client.get("/monitor/api/calls").get_json()["calls"]} >= {"monitor"}  # itself too
    assert client.post("/monitor/api/clear").status_code == 200
    assert client.get("/monitor/api/overview").get_json()["totals"]["calls"] == 0


def test_writer_survives_a_broken_database(paths, rec):
    path = monitor.db_path(paths.home)
    rec.flush()
    rec._put(lambda db: db.execute("INSERT INTO nowhere VALUES (1)"))  # a failing job is dropped
    rec.call("svn", "svn_read", {}, 1, ok=True)
    rec.flush()
    assert sqlite3.connect(path).execute("SELECT COUNT(*) FROM calls").fetchone()[0] == 1


def test_addon_crash_event_and_process_usage(paths, rec):
    import os
    import subprocess
    import sys
    from types import SimpleNamespace

    from viewer_hub.addons.runner import Managed, process_usage

    runner = Managed.__new__(Managed)
    runner.addon = SimpleNamespace(id="x", name="X")
    runner._failures = []
    runner.process = subprocess.Popen([sys.executable, "-c", "raise SystemExit(3)"])
    runner.process.wait()
    assert runner.check_exit() == 3 and runner.process is None
    assert runner.check_exit() is None  # recorded once
    rec.flush()
    with Reader(paths.home) as reader:
        events = reader.events()
    assert [(e["source"], e["kind"]) for e in events] == [("x", "crash")] and "3" in events[0]["message"]
    rss, _cpu = process_usage(os.getpid())
    assert rss is None or rss > 1024 * 1024
    assert process_usage(None) == (None, None)


def test_daemon_reports_its_own_usage_or_its_pid():
    from viewer_hub.monitor.sampler import _daemon_usage

    class Runner:
        def __init__(self, replies):
            self.replies = replies

        def request(self, _method, path):
            return self.replies.get(path, (404, None))

    seen = []

    def usage(pid):
        seen.append(pid)
        return 123, 1.5

    assert _daemon_usage(Runner({"/api/process": (200, {"rss": 4096, "cpuPct": 2})}), usage) == (4096, 2.0)
    assert _daemon_usage(Runner({"/api/health": (200, {"pid": 77})}), usage) == (123, 1.5) and seen == [77]
    assert _daemon_usage(Runner({}), usage) == (None, None)
