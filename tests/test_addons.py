"""Addons (docs/addons.md, viewer_hub/addons): manifest, install (zip checks, signature, security scan), the managed
runtime with the test addon (tests/fixtures/example), the MCP read-only filter, stdio MCP, daemon addons over their
admin channel and the MCP gateway, and addons shipped in a release."""
from __future__ import annotations

import io
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import zipfile
from pathlib import Path

import pytest

from tests.addon_kit import EXAMPLE, install, zip_folder
from tests.test_core import _client_with
from viewer_hub.addons import install as installer
from viewer_hub.addons import signature
from viewer_hub.addons.manifest import AddonError, parse
from viewer_hub.core import ed25519, unlock
from viewer_hub.core.scan import scan_addon

H = {"X-Viewer-Hub": "1"}
TEST_KEY = bytes(range(32))


def _manifest(**changes) -> dict:
    data = json.loads((EXAMPLE / "addon.json").read_text(encoding="utf-8"))
    data.update(changes)
    return data


@pytest.fixture()
def stop_addons():
    """Stops every addon process a test started (the Hub does it at exit)."""
    from viewer_hub.addons import runner

    yield
    runner._stop_all()


# ── manifest ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_manifest_is_checked():
    addon = parse(_manifest())
    assert addon.id == "example" and addon.prefix == "/x/example" and addon.mcp.tools == ("example_greet",)
    daemon = {"lifecycle": "daemon", "commands": {"init": ["init"], "start": ["start"], "status": ["status", "--json"]}}
    bad = [
        {"id": "Bad_Id"}, {"sdk": "2"}, {"schemaVersion": 2}, {"schemaVersion": 4}, {"exports": "x"},  # exports: a list of objects
        {"runtime": "ruby"}, {"entry": "../main.py"},
        {"lifecycle": "forever"}, {"ui": {"script": "../ui.js"}}, {"ui": {"style": "ui/ui.css"}},
        {"menu": {"label": "X", "icon": "Bad Icon", "summary": "x"}}, {"premium": "Not A Name"},
        {**daemon, "mcp": {"command": "x", "tools": ["a"]}},  # MCP is for managed addons
        {"lifecycle": "daemon"},  # no commands
        {**daemon, "mcp": None, "commands": {"init": ["init;rm"], "start": [], "status": []}},
        {"settings": [{"key": "a", "label": "A", "type": "text", "arg": "--a"}]},  # arg: daemon only
        {"settings": [{"key": "a", "label": "A", "type": "select"}]},  # select without options
    ]
    for change in bad:
        with pytest.raises(AddonError):
            parse(_manifest(**change))


# ── install ────────────────────────────────────────────────────────────────────────────────────────────────────

def _zip(tmp_path: Path, files: dict[str, bytes | str], name: str = "addon.zip") -> Path:
    out = tmp_path / name
    with zipfile.ZipFile(out, "w") as archive:
        for path, data in files.items():
            archive.writestr(path, data)
    return out


def _example_files(**extra) -> dict:
    files = {f"example/{p.relative_to(EXAMPLE).as_posix()}": p.read_bytes() for p in EXAMPLE.rglob("*") if p.is_file()
             and "__pycache__" not in p.parts}
    files.update({f"example/{k}": v for k, v in extra.items()})
    return files


def test_install_from_the_settings_page_without_restart(paths, tmp_path, stop_addons):
    client = _client_with(paths)
    archive = _zip(tmp_path, _example_files())
    upload = lambda headers: client.post("/api/addons", headers=headers,  # noqa: E731
                                         data={"file": (io.BytesIO(archive.read_bytes()), "example-0.1.0.zip")})
    assert upload({}).status_code == 403  # a cross-site form cannot install an addon
    answer = upload(H)
    assert answer.status_code == 200, answer.get_json()
    body = answer.get_json()
    assert body["trust"] == "unsigned" and "chưa ký" in body["message"] and body["path"] == "/x/example/"
    assert "example" in [item["key"] for item in client.get("/api/app").get_json()["nav"]]
    assert client.put("/api/addons/example/settings", json={"values": {"names": ["An"]}}, headers=H).status_code == 200
    again = upload(H).get_json()
    assert "thay bản 0.1.0" in again["message"]
    assert client.get("/api/addons/example").get_json()["values"]["names"] == ["An"]  # data kept on update
    removed = client.delete("/api/addons/example", headers=H)
    assert removed.status_code == 200 and "Dữ liệu" in removed.get_json()["message"]
    assert "example" not in [item["key"] for item in client.get("/api/app").get_json()["nav"]]
    assert (paths.addon_data("example") / "settings.json").is_file()  # uninstall keeps its data


def test_unsafe_zips_are_refused(paths, tmp_path):
    cases = {
        "slip": {"example/addon.json": json.dumps(_manifest()), "example/../evil.py": "x"},
        "two tops": {"example/addon.json": json.dumps(_manifest()), "other/x.txt": "x"},
        "native": _example_files(**{"app/lib/fast.pyd": b"MZ"}),
        "launcher": _example_files(**{"run.cmd": "@echo off"}),
        "eval": _example_files(**{"app/main.py": "eval('1')\n"}),
        "shell": _example_files(**{"app/lib/x.py": "import subprocess\nsubprocess.run('x', shell=True)\n"}),
        "ui innerHTML": _example_files(**{"ui/ui.js": "document.body.innerHTML = x"}),
        "no manifest": {"example/app/main.py": "x"},
    }
    for name, files in cases.items():
        with pytest.raises(AddonError):
            installer.install_zip(paths, _zip(tmp_path, files, f"{name.replace(' ', '-')}.zip"))
    assert not any(paths.addons.iterdir())


def test_scan_notes_what_an_addon_does_beyond_the_hub(tmp_path):
    folder = tmp_path / "example"
    (folder / "app" / "node").mkdir(parents=True)
    (folder / "app" / "main.py").write_text("import subprocess, urllib.request\n", encoding="utf-8")
    (folder / "app" / "server.mjs").write_text("import { spawn } from 'node:child_process';\n", encoding="utf-8")
    (folder / "app" / "node" / "node.exe").write_bytes(b"MZ")  # the one runtime an addon may carry
    errors, notes = scan_addon(folder)
    assert errors == []
    assert any("gọi mạng" in n for n in notes) and any("chạy tiến trình" in n for n in notes)
    assert any("child_process" in n for n in notes)


def test_signed_addon(paths, tmp_path, monkeypatch):
    monkeypatch.setattr(unlock, "PUBLIC_KEY", ed25519.public_key(TEST_KEY))
    stage = tmp_path / "stage" / "example"
    shutil.copytree(EXAMPLE, stage, ignore=shutil.ignore_patterns("__pycache__"))  # a copy to sign
    signature.sign(stage, "example", "0.1.0", TEST_KEY)
    result = installer.install_zip(paths, zip_folder(stage, tmp_path / "signed.zip"))
    assert result.trust == "signed"
    (stage / "app" / "main.py").write_text("# changed after signing\n", encoding="utf-8")
    with pytest.raises(AddonError, match="khác với bản đã ký"):
        installer.install_zip(paths, zip_folder(stage, tmp_path / "tampered.zip"))
    monkeypatch.setattr(unlock, "PUBLIC_KEY", ed25519.public_key(bytes(32)))  # someone else's key
    signature.sign(stage, "example", "0.1.0", TEST_KEY)
    with pytest.raises(AddonError, match="chữ ký"):
        installer.install_zip(paths, zip_folder(stage, tmp_path / "other-key.zip"))


def test_release_addons_install_on_start(paths, tmp_path):
    bundled = tmp_path / "release-addons"
    bundled.mkdir()
    _zip(bundled, _example_files(), "example-0.1.0.zip")
    assert installer.install_bundled(paths, bundled) == ["Example addon 0.1.0"]
    assert installer.install_bundled(paths, bundled) == []  # already there
    newer = _example_files(**{"addon.json": json.dumps(_manifest(version="0.2.0"))})
    _zip(bundled, newer, "example-0.2.0.zip")
    assert installer.install_bundled(paths, bundled) == ["Example addon 0.2.0"]
    # the user removes it: a newer default addon does not put it back...
    installer.uninstall(paths, "example")
    _zip(bundled, _example_files(**{"addon.json": json.dumps(_manifest(version="0.3.0"))}), "example-0.3.0.zip")
    assert installer.install_bundled(paths, bundled) == [] and not (paths.addons / "example").exists()
    # ...until they install it by hand again
    installer.install_zip(paths, bundled / "example-0.3.0.zip")
    assert "example" not in installer.removed_ids(paths)


def test_svn_repos_move_to_the_svn_addon(paths):
    """SVN was a builtin module: its list (hub.db) goes to the addon's data once, the old addresses redirect."""
    from viewer_hub.addons.legacy import migrate_svn

    client = _client_with(paths)
    db = client.application.extensions["hub"].db
    assert not migrate_svn(paths, db)  # nothing to move
    repos = [{"name": "core", "url": "https://svn.test/repo", "description": "Order system"}]
    db.set_setting("svn.repos", json.dumps(repos))
    assert migrate_svn(paths, db)
    target = paths.addon_data("svn") / "repos.json"
    assert json.loads(target.read_text(encoding="utf-8")) == repos
    target.write_text("[]", encoding="utf-8")  # the user empties the list in the addon: not copied again
    assert not migrate_svn(paths, db) and json.loads(target.read_text(encoding="utf-8")) == []
    moved = client.post("/svn/mcp?x=1", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert moved.status_code == 308 and moved.headers["Location"].endswith("/x/svn/mcp?x=1")
    assert client.get("/svn").headers["Location"].endswith("/x/svn/")


def test_broken_addons_are_listed_not_loaded(paths):
    install(paths, "codemap")  # takes a builtin key
    (paths.addons / "half").mkdir()
    (paths.addons / "half" / "addon.json").write_text("{", encoding="utf-8")
    client = _client_with(paths)
    listed = client.get("/api/addons").get_json()
    assert listed["addons"] == [] and {b["folder"] for b in listed["broken"]} == {"codemap", "half"}
    assert [i["key"] for i in client.get("/api/app").get_json()["nav"]].count("codemap") == 1


# ── managed runtime ────────────────────────────────────────────────────────────────────────────────────────────

def test_managed_addon_api_and_mcp(paths, stop_addons):
    install(paths, "example")
    client = _client_with(paths)
    info = client.get("/api/addons/example").get_json()
    assert info["running"] is False and info["settings"][0]["key"] == "greeting" and "example_greet" in info["guide"]
    assert client.put("/api/addons/example/settings", json={"values": {"names": "An\nBình"}}).status_code == 403
    saved = client.put("/api/addons/example/settings", json={"values": {"names": "An\nBình", "x": 1}}, headers=H)
    assert saved.get_json()["values"] == {"greeting": "Xin chào", "names": ["An", "Bình"]}
    # Started on first use, with its own token: the addon process is only reachable through the Hub.
    assert client.get("/x/example/api/greetings").get_json() == {"greetings": ["Xin chào, An!", "Xin chào, Bình!"]}
    missing = client.get("/x/example/api/greetings/Zed")
    assert missing.status_code == 404 and missing.get_json()["error"]["code"] == "unknown_name"
    assert client.post("/x/example/api/greetings", json={}).status_code == 403  # writes need the page header
    assert client.post("/x/example/api/greetings", json={}, headers=H).status_code == 405
    listed = client.post("/x/example/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).get_json()
    assert [t["name"] for t in listed["result"]["tools"]] == ["example_greet"]
    called = client.post("/x/example/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                                  "params": {"name": "example_greet", "arguments": {"name": "An"}}})
    assert called.get_json()["result"]["content"][0]["text"] == "Xin chào, An!"
    runner = client.application.extensions["hub"].addons.runner(client.application.extensions["hub"].addons.get("example"))
    import http.client

    conn = http.client.HTTPConnection("127.0.0.1", runner.port, timeout=5)
    conn.request("GET", "/api/greetings")
    assert conn.getresponse().status == 403  # no token: refused by the addon itself
    conn.close()
    stopped = client.post("/api/addons/example/stop", headers=H).get_json()
    assert stopped["running"] is False


WRITER = '''
from viewer_hub.addons.sdk import Addon

class Writer(Addon):
    def handle_mcp(self, message):
        tools = [{"name": "safe_read", "annotations": {"readOnlyHint": True}}, {"name": "delete_all"}]
        if message.get("method") == "tools/list":
            return {"jsonrpc": "2.0", "id": message.get("id"), "result": {"tools": tools}}
        name = message["params"]["name"]
        return {"jsonrpc": "2.0", "id": message.get("id"), "result": {"content": [{"type": "text", "text": "ran " + name}]}}

if __name__ == "__main__":
    Writer("writer").run()
'''


def test_mcp_tools_without_read_only_hint_are_hidden_and_refused(paths, stop_addons):
    install(paths, "writer", files={"app/main.py": WRITER}, mcp={"command": "writer", "tools": ["safe_read"]})
    client = _client_with(paths)
    call = lambda tool: client.post("/x/writer/mcp", json={  # noqa: E731
        "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": {}}}).get_json()
    assert "không có readOnlyHint" in call("delete_all")["error"]["message"]  # refused before any tools/list
    listed = client.post("/x/writer/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).get_json()
    assert [t["name"] for t in listed["result"]["tools"]] == ["safe_read"]
    assert call("safe_read")["result"]["content"][0]["text"] == "ran safe_read"


def test_stdio_mcp_of_an_addon(paths, monkeypatch, capsys):
    from viewer_hub import cli

    install(paths, "example")
    lines = [{"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
             {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "example_greet", "arguments": {"name": "An"}}}]
    (paths.addon_data("example")).mkdir(parents=True, exist_ok=True)
    (paths.addon_data("example") / "settings.json").write_text(json.dumps({"names": ["An"]}), encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", io.StringIO("".join(json.dumps(line) + "\n" for line in lines)))
    assert cli.main(["--data-dir", str(paths.home), "mcp", "example"]) == 0
    replies = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert replies[0]["result"]["tools"][0]["name"] == "example_greet"
    assert replies[1]["result"]["content"][0]["text"] == "Xin chào, An!"
    assert cli.main(["--data-dir", str(paths.home), "mcp", "nope"]) == 2


# ── daemon addons ──────────────────────────────────────────────────────────────────────────────────────────────

class FakeDaemon:
    """Speaks the admin channel (my-bridge src/api/admin-channel.ts) on a Unix socket: one JSON line in, one out;
    {"method": "EVENTS"} streams lines. Keeps the servers registered with it."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.requests: list[dict] = []
        self.servers: dict[str, dict] = {}
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(path)
        self.server.listen()
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self) -> None:
        while True:
            try:
                conn, _ = self.server.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _reply(self, message: dict) -> tuple[int, object]:
        method, path = message["method"], message["path"]
        if path == "/api/health":
            return 200, {"ok": True}
        if path == "/api/servers" and method == "GET":
            return 200, {"servers": list(self.servers.values())}
        if path == "/api/servers" and method == "POST":
            for server in message["body"]["servers"]:
                self.servers[server["name"]] = {**server, "tools": {"total": 0}}
            return 200, {"ok": True}
        if path.endswith("/refresh"):
            return 200, {"ok": True}
        return 200, {"echo": message}

    def _serve(self, conn: socket.socket) -> None:
        with conn:
            data = b""
            while b"\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    return
                data += chunk
            message = json.loads(data.split(b"\n", 1)[0])
            if message.get("method") == "EVENTS":
                for event in ({"event": "hello", "data": {"version": "test"}}, {"event": "tools.changed", "data": {}}):
                    conn.sendall(json.dumps(event).encode() + b"\n")
                return
            self.requests.append(message)
            status, body = self._reply(message)
            conn.sendall(json.dumps({"status": status, "body": body}).encode() + b"\n")

    def close(self) -> None:
        self.server.close()


STATUS = '''
import json, os, sys
if sys.argv[1:] == ["status", "--json"]:
    print(json.dumps({"version": "test", "adminChannel": os.environ["FAKE_CHANNEL"]}))
'''


@pytest.fixture()
def daemon(paths, monkeypatch):
    if sys.platform == "win32":
        pytest.skip("the fake daemon uses a Unix socket")
    folder = tempfile.mkdtemp(prefix="vh-addon-")  # short path: Unix socket paths are limited to ~100 chars
    where = os.path.join(folder, "admin.sock")
    monkeypatch.setenv("FAKE_CHANNEL", where)
    fake = FakeDaemon(where)
    install(paths, "fake-bridge", label="Cầu giả", lifecycle="daemon", mcp=None, provides=["mcp-servers"],
            commands={"init": ["init"], "start": ["start"], "status": ["status", "--json"]},
            settings=[{"key": "boxRoot", "label": "Thư mục Box", "type": "folder", "arg": "--box-root"}],
            files={"app/main.py": STATUS})
    yield fake
    fake.close()


def test_daemon_addon_relay_events_and_gateway(paths, daemon):
    client = _client_with(paths)
    info = client.get("/api/addons/fake-bridge").get_json()
    assert info["running"] is True and info["autostart"] is True and info["gateway"] is True
    relayed = client.get("/x/fake-bridge/api/status?x=1").get_json()
    assert relayed["echo"]["path"] == "/api/status" and relayed["echo"]["query"] == {"x": "1"}
    assert client.post("/x/fake-bridge/api/pause", json={}).status_code == 403
    assert client.post("/x/fake-bridge/api/pause", json={"a": 1}, headers=H).get_json()["echo"]["body"] == {"a": 1}
    events = client.get("/x/fake-bridge/api/events").data.decode()
    assert "event: hello" in events and "event: tools.changed" in events
    # Start (it runs already) registers every MCP of the Hub in it, at this Hub's port.
    started = client.post("/api/addons/fake-bridge/start", headers=H).get_json()
    assert started["ok"] and "Đã đăng ký" in started["message"], started
    assert {"viewer-codemap", "viewer-search", "viewer-csv", "viewer-monitor"} <= set(daemon.servers)
    assert daemon.servers["viewer-csv"]["url"].endswith("/csv/mcp")
    assert client.post("/api/addons/fake-bridge/gateway", json={"on": False}, headers=H).get_json()["gateway"] is False
    assert client.post("/api/addons/fake-bridge/autostart", json={"on": False}, headers=H).get_json()["autostart"] is False
    assert client.get("/api/addons/fake-bridge").get_json()["autostart"] is False


def test_daemon_setting_arguments(paths, daemon):
    from viewer_hub.addons.runner import Daemon

    hub = _client_with(paths).application.extensions["hub"]
    addon = hub.addons.get("fake-bridge")
    runner = hub.addons.runner(addon)
    assert isinstance(runner, Daemon)
    assert runner.setting_args({"boxRoot": " /tmp/Box "}, "init") == ["--box-root", "/tmp/Box"]
    assert runner.setting_args({"boxRoot": ""}, "init") == [] and runner.setting_args({"boxRoot": "x"}, "start") == []


# ── viewer-hub pack (a release, no source) ─────────────────────────────────────────────────────────────────────

def test_pack_command_builds_from_an_input_folder(paths, tmp_path, capsys):
    from viewer_hub import cli

    source = tmp_path / "input"
    (source / "csv").mkdir(parents=True)
    (source / "csv" / "nhan-vien.csv").write_text("ma,ten\n1,An\n", encoding="utf-8")
    assert cli.main(["--data-dir", str(paths.home), "pack", "--input", str(source), "--out", str(tmp_path)]) == 1
    assert "pack.yaml" in capsys.readouterr().err  # id and title are needed
    (source / "pack.yaml").write_text("id: demo\ntitle: Demo\nversion: 1.0.0\n", encoding="utf-8")
    assert cli.main(["--data-dir", str(paths.home), "pack", "--input", str(source), "--out", str(tmp_path),
                     "--install"]) == 0
    assert (tmp_path / "demo-1.0.0.sapack").is_file()
    assert "Đã import demo 1.0.0" in capsys.readouterr().out


def test_python_addon_exits_when_the_hub_is_gone():
    """A killed Hub cannot stop its addons: they exit when its stdin pipe closes (host.watch_parent)."""
    import os
    import subprocess
    import sys

    code = ("import sys, time; sys.path[:0] = %r; from viewer_hub.addons.host import watch_parent; "
            "watch_parent(); time.sleep(30)") % [p for p in sys.path if p]
    env = {**os.environ, "VIEWER_HUB_PARENT_PIPE": "1"}
    process = subprocess.Popen([sys.executable, "-c", code], stdin=subprocess.PIPE, env=env)
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            process.wait(1)  # alive while the pipe is open
        process.stdin.close()  # what the OS does when the Hub dies
        assert process.wait(5) == 0
    finally:
        if process.poll() is None:
            process.kill()


def test_install_refuses_a_page_that_redraws_the_hub_header(paths, tmp_path):
    """An addon page with its own settings form / banner / run-stop buttons is refused (kit/AGENTS.md "Hub vẽ sẵn")."""
    from viewer_hub.core.scan import scan_addon

    folder = tmp_path / "a"
    (folder / "ui").mkdir(parents=True)
    (folder / "ui" / "ui.js").write_text(
        'export default function P({api}){return h("div",{className:"md-banner md-banner--warning",'
        'children:"Ch\\u01B0a c\\u1EA5u h\\xECnh. M\\u1EDF C\\xE0i \\u0111\\u1EB7t"})}\n', encoding="utf-8")
    errors, _notes = scan_addon(folder)
    assert errors and "banner tự làm về cấu hình" in errors[0] and "openSettings" in errors[0]


def test_mcp_list_names_every_server_builtin_and_addon(paths, tmp_path, stop_addons):
    """GET /api/mcp: one list for tools outside the Hub (where to connect, which tools), without starting anything."""
    client = _client_with(paths)
    builtin = {s["key"]: s for s in client.get("/api/mcp").get_json()["servers"]}
    assert builtin["csv"]["kind"] == "builtin" and builtin["csv"]["path"] == "/csv/mcp"
    assert builtin["csv"]["url"].startswith("http://") and builtin["csv"]["url"].endswith("/csv/mcp") and builtin["csv"]["tools"]   # tool names, never empty
    assert all(set(s) == {"key", "label", "kind", "command", "path", "url", "scope", "tools"} for s in builtin.values())
    archive = _zip(tmp_path, _example_files())
    assert client.post("/api/addons", headers=H, data={"file": (io.BytesIO(archive.read_bytes()), "example-0.1.0.zip")}
                       ).status_code == 200
    listed = {s["key"]: s for s in client.get("/api/mcp").get_json()["servers"]}
    assert listed["example"]["kind"] == "addon" and listed["example"]["path"] == "/x/example/mcp"
    assert listed["example"]["tools"] and listed["csv"] == builtin["csv"]
    assert client.get("/api/addons/example").get_json()["running"] is False   # listing it did not start the addon
    assert list(listed)[:len(builtin)] == list(builtin)                       # builtin first, addons after (menu order)


def test_mcp_list_detail_gives_descriptions_and_schemas(paths, tmp_path, stop_addons):
    """GET /api/mcp?detail=1: the tools as {name, description, inputSchema, readOnly}, from each server's own tools/list."""
    client = _client_with(paths)
    plain = {s["key"]: s for s in client.get("/api/mcp").get_json()["servers"]}
    detailed = {s["key"]: s for s in client.get("/api/mcp?detail=1").get_json()["servers"]}
    assert list(detailed) == list(plain)
    csv = detailed["csv"]["tools"]
    assert [t["name"] for t in csv] == plain["csv"]["tools"]
    assert all(t["description"] and isinstance(t["inputSchema"], dict) and t["readOnly"] is True for t in csv)
    archive = _zip(tmp_path, _example_files())
    assert client.post("/api/addons", headers=H, data={"file": (io.BytesIO(archive.read_bytes()), "example-0.1.0.zip")}
                       ).status_code == 200
    example = {s["key"]: s for s in client.get("/api/mcp?detail=1").get_json()["servers"]}["example"]
    tools = example.get("tools")
    assert (tools and isinstance(tools[0], dict) and tools[0]["description"]) or example.get("unavailable")
