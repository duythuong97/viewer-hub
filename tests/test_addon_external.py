"""External addons (kit/AGENTS.md §5.4): the user's own program (any language) on 127.0.0.1, which the Hub connects to
but never starts or stops. The program here is a stand-in: a tiny HTTP server with /health, /api/info and /mcp."""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tests.test_addon_sdk import _package
from tests.test_core import _client_with
from viewer_hub.addons import install as installer
from viewer_hub.addons.manifest import AddonError, parse
from viewer_hub.addons.pack import pack

H = {"X-Viewer-Hub": "1"}
BASE = "/api/addons/my-service"
TOOLS = [{"name": "service_info", "annotations": {"readOnlyHint": True}, "inputSchema": {"type": "object"}},
         {"name": "service_delete", "inputSchema": {"type": "object"}}]


class _Program(BaseHTTPRequestHandler):
    seen: list[dict] = []

    def log_message(self, *_args):
        pass

    def _reply(self, status: int, body) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.seen.append(dict(self.headers))
        if self.path == "/health":
            return self._reply(200, {"ok": True})
        if self.path == "/api/info":
            return self._reply(200, {"name": "Stand-in", "version": "1.0.0", "status": "OK"})
        return self._reply(404, {"error": {"code": "not_found", "message": "không có"}})

    def do_POST(self):
        message = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path != "/mcp":
            return self._reply(404, {})
        if message.get("method") == "tools/list":
            return self._reply(200, {"jsonrpc": "2.0", "id": message["id"], "result": {"tools": TOOLS}})
        name = message["params"]["name"]
        return self._reply(200, {"jsonrpc": "2.0", "id": message["id"],
                                 "result": {"content": [{"type": "text", "text": f"called {name}"}]}})


@pytest.fixture()
def program():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Program)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_port
    server.shutdown()
    server.server_close()


def test_manifest_rules():
    base = {"schema": "viewer-hub/addon", "schemaVersion": 3, "sdk": "1", "id": "tool-x", "name": "X", "version": "1.0.0",
            "lifecycle": "external", "service": {"port": 5123}, "menu": {"label": "X", "icon": "lan", "summary": "x"}}
    addon = parse(base)
    assert addon.external and addon.entry == "" and addon.port == 5123
    assert addon.settings[0].key == "port" and addon.settings[0].default == "5123"  # the Hub's own setting
    for bad in ({"runtime": "python", "entry": "main.py"}, {"service": {"port": 80}}, {"service": None},
                {"commands": {"init": [], "start": [], "status": []}}):
        with pytest.raises(AddonError):
            parse({**base, **bad})
    with pytest.raises(AddonError, match="service"):
        parse({**base, "lifecycle": "managed", "runtime": "python", "entry": "main.py"})


def test_connects_relays_and_never_runs_it(paths, tmp_path, program):
    installer.install_zip(paths, pack(_package(tmp_path, "external"), tmp_path / "dist", log=lambda _: None))
    client = _client_with(paths)
    info = client.get(BASE).get_json()
    assert info["lifecycle"] == "external" and info["port"] == 5123
    assert [s["key"] for s in info["settings"]] == ["port"]

    assert client.put(f"{BASE}/settings", json={"values": {"port": str(program)}}, headers=H).status_code == 200
    info = client.get(BASE).get_json()
    assert info["running"] is True and info["port"] == program
    assert client.get(f"{BASE}/status").get_json()["running"] is True

    reply = client.get("/x/my-service/api/info")
    assert reply.status_code == 200 and reply.get_json()["name"] == "Stand-in"
    assert not any("X-Viewer-Hub-Token" in h for h in _Program.seen)  # no token: the Hub did not start it

    def mcp(message):
        return client.post("/x/my-service/mcp", data=json.dumps(message), content_type="application/json").get_json()

    listed = mcp({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert [t["name"] for t in listed["result"]["tools"]] == ["service_info"]  # read-only tools only
    assert "error" in mcp({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "service_delete"}})
    assert mcp({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "service_info"}})["result"]

    for action in ("start", "stop", "restart"):
        assert client.post(f"{BASE}/{action}", headers=H).status_code == 404
    assert client.get(f"{BASE}/log").get_json()["text"] == ""
    assert client.delete(BASE, headers=H).status_code == 200  # removing it leaves the program running
    assert _client_with(paths).application.extensions["hub"].addons.get("my-service") is None


def test_not_connected_and_bad_port(paths, tmp_path):
    installer.install_zip(paths, pack(_package(tmp_path, "external"), tmp_path / "dist", log=lambda _: None))
    client = _client_with(paths)
    from viewer_hub.addons.runner import free_port

    client.put(f"{BASE}/settings", json={"values": {"port": str(free_port())}}, headers=H)
    assert client.get(BASE).get_json()["running"] is False
    reply = client.get("/x/my-service/api/info")
    assert reply.status_code == 503 and "Viewer Hub không tự chạy" in reply.get_json()["error"]["message"]
    client.put(f"{BASE}/settings", json={"values": {"port": "80"}}, headers=H)
    assert "1024-65535" in client.get(BASE).get_json()["problem"]


@pytest.mark.skipif(not shutil.which("node"), reason="needs Node.js")
def test_sdk_new_external(tmp_path):
    from viewer_hub.addons import sdk_kit
    import io

    with zipfile.ZipFile(io.BytesIO(sdk_kit.build())) as archive:
        archive.extractall(tmp_path)
    folder = tmp_path / sdk_kit.TOP
    made = subprocess.run(["node", ".sdk/new.mjs", "external", "my-tool"], cwd=folder, capture_output=True, text=True)
    assert made.returncode == 0, made.stderr
    shutil.rmtree(folder / "web")
    data = json.loads((folder / "addon" / "addon.json").read_text())
    data.pop("ui")
    (folder / "addon" / "addon.json").write_text(json.dumps(data))
    checked = subprocess.run(["node", ".sdk/build.mjs", "check"], cwd=folder, capture_output=True, text=True)
    assert checked.returncode == 0, checked.stderr
    assert "127.0.0.1:5123" in checked.stdout
