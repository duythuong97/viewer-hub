"""The MCP Bridge addon as my-bridge builds it (`npm run release` → dist/mcp-bridge-<ver>.zip, or the default addon
in addons/) with the real daemon: Viewer Hub installs it, starts, restarts and stops it, changes its Box folder and
registers its own MCP servers in it.

Runs in a throw-away HOME so the user's own bridge config and Box folder are never touched. Skipped when node or
no bridge addon zip is on this machine.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from tests.test_core import _client_with

ROOT = Path(__file__).resolve().parents[1]
ZIPS = sorted([*(ROOT.parent / "my-bridge" / "dist").glob("mcp-bridge-*.zip"),
               *(ROOT.parent / "viewer-hub-addons" / "my-bridge" / "dist").glob("mcp-bridge-*.zip"), *(ROOT / "addons").glob("mcp-bridge-*.zip")],
              key=lambda p: p.stat().st_mtime)
pytestmark = pytest.mark.skipif(sys.platform == "win32" or not shutil.which("node") or not ZIPS,
                                reason="needs node and the bridge addon zip (../viewer-hub-addons/my-bridge/dist or addons/; macOS / Linux)")
H = {"X-Viewer-Hub": "1"}
BASE = "/api/addons/mcp-bridge"


@pytest.fixture()
def home(monkeypatch):
    # Short path: the admin socket lives under HOME and Unix socket paths are limited to ~100 bytes.
    fake = Path(tempfile.mkdtemp(prefix="vh.", dir="/tmp"))
    config_dir = fake / "Library" / "Application Support" / "McpBridge" if sys.platform == "darwin" else fake / ".config" / "McpBridge"
    monkeypatch.setenv("HOME", str(fake))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(fake / ".config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(fake / ".local" / "share"))
    monkeypatch.delenv("MCP_BRIDGE_ADMIN", raising=False)
    box = fake / "Box" / "McpBridge"
    box.parent.mkdir(parents=True)
    yield config_dir, box
    shutil.rmtree(fake, ignore_errors=True)


@pytest.fixture()
def bridge(paths, home):
    """The newest bridge addon zip, installed as an upload would, unlocked."""
    from viewer_hub.addons.install import install_zip

    config_dir, box = home
    installed = install_zip(paths, ZIPS[-1])
    assert installed.addon.id == "mcp-bridge" and (installed.addon.folder / "ui" / "ui.js").is_file()
    client = _client_with(paths, premium={"bridge"})
    hub = client.application.extensions["hub"]
    runner = hub.addons.runner(hub.addons.get("mcp-bridge"))
    # A config on a free port (not the user's 7801) with this Box folder, as `bridge init` would write it.
    code, out = runner.cli("init", "--box-root", str(box))
    assert code == 0, out
    config = json.loads((config_dir / "config.json").read_text())
    config["ui"]["port"] = 7898
    (config_dir / "config.json").write_text(json.dumps(config))
    yield client, box
    runner.stop()


def test_start_restart_stop_and_box_folder_from_the_page(bridge):
    client, box = bridge
    state = client.get(BASE).get_json()
    assert state["lifecycle"] == "daemon" and not state["running"] and state["autostart"] is True

    started = client.post(f"{BASE}/start", headers=H)
    assert started.status_code == 200, started.get_json()
    status = client.get("/x/mcp-bridge/api/status").get_json()
    assert status["running"] is True and "personal" not in status  # no personal mode: the user turns tools on

    other = box.parent / "Other"
    other.mkdir()
    moved = client.put(f"{BASE}/settings", json={"values": {"boxRoot": str(other)}}, headers=H)
    assert moved.status_code == 200 and "Đã chạy" in moved.get_json()["message"], moved.get_json()
    assert client.get("/x/mcp-bridge/api/status").get_json()["boxRoot"] == str(other)

    assert client.post(f"{BASE}/restart", headers=H).status_code == 200
    stopped = client.post(f"{BASE}/stop", headers=H)
    assert stopped.status_code == 200 and stopped.get_json()["running"] is False
    assert client.get("/x/mcp-bridge/api/status").status_code == 503


def test_viewer_mcp_servers_registered_tools_wait_for_the_user(bridge):
    """Starting the bridge registers the Hub's MCP servers; the bridge reaches them over HTTP on this machine. Their
    tools start off, as every new tool: the user turns them on (here: all at once, as "Cho phép tất cả" does)."""
    import threading

    from werkzeug.serving import make_server

    from viewer_hub.addons import gateway

    client, _box = bridge
    assert client.post(f"{BASE}/start", headers=H).status_code == 200
    servers = {s["name"]: s for s in client.get("/x/mcp-bridge/api/servers").get_json()["servers"]}
    assert {"viewer-codemap", "viewer-search", "viewer-csv"} <= set(servers)
    assert servers["viewer-csv"]["transport"] == "http" and servers["viewer-csv"]["url"].endswith("/csv/mcp")

    # A real Viewer Hub on a free port: registering again points the servers there and fetches their tools.
    hub = client.application.extensions["hub"]
    runner = hub.addons.runner(hub.addons.get("mcp-bridge"))
    server = make_server("127.0.0.1", 0, client.application, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        ok, message = gateway.register(runner, server.server_port, hub.modules)
        assert ok, message
        tools = client.get("/x/mcp-bridge/api/tools", query_string={"server": "viewer-csv"}).get_json()
        tools = tools.get("tools", tools)
        assert {t["tool"] for t in tools} == {"csv_list", "csv_search"}
        assert all(t["policy"] == "off" for t in tools)  # new tools wait for the user
        allowed = client.put("/x/mcp-bridge/api/tools/policy", json={"policy": "allow", "server": "viewer-csv"}, headers=H)
        assert allowed.status_code == 200 and len(allowed.get_json()["changed"]) == 2
        again, note = gateway.register(runner, server.server_port, hub.modules, hub.db)
        assert again and "đã có" in note  # nothing to change the second time
        # the user removes one in the bridge: the next start does not add it back...
        assert client.delete("/x/mcp-bridge/api/servers/viewer-csv", headers=H).status_code < 300
        ok, note = gateway.register(runner, server.server_port, hub.modules, hub.db)
        assert ok and "viewer-csv" in note
        names = {s["name"] for s in client.get("/x/mcp-bridge/api/servers").get_json()["servers"]}
        assert "viewer-csv" not in names and "viewer-search" in names
        # ...until the user switches "Đăng ký MCP của Viewer Hub" on again
        assert client.post(f"{BASE}/gateway", json={"on": True}, headers=H).status_code == 200  # (no Hub on its port here)
        names = {s["name"] for s in client.get("/x/mcp-bridge/api/servers").get_json()["servers"]}
        assert "viewer-csv" in names
    finally:
        server.shutdown()
