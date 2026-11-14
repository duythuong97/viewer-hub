"""Code-map viewer: page, API over a pack, HTTP MCP, stdio MCP and the no-pack case."""
from __future__ import annotations

import io
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

DEMO = Path(os.environ.get("CODEMAP_DEMO", "/Volumes/thuong.pham/sources/code-map/var/output/demo"))
FILES = ("codemap.sqlite", "graph.sqlite", "manifest.json", "quality-report.json")
API = "/code-map/api/graph"

needs_demo = pytest.mark.skipif(not (DEMO / "codemap.sqlite").is_file(), reason=f"code-map demo output not found at {DEMO}")


def _install_pack(app, paths, pack_id="demo", version="2026.10.30-1", title="Demo", source=True) -> Path:
    folder = paths.packs / pack_id / version
    (folder / "codemap").mkdir(parents=True)
    for name in FILES:
        if (DEMO / name).is_file():
            shutil.copy2(DEMO / name, folder / "codemap" / name)
    if source:
        program = folder / "source" / "order-fulfillment" / "Program.cs"
        program.parent.mkdir(parents=True)
        program.write_text("\n".join(f"// line {number}" for number in range(1, 120)), encoding="utf-8")
    components = {"codemap": {"path": "codemap/", "schema": 3, "contractVersion": "3.0"}}
    (folder / "pack.json").write_text(json.dumps({"format": 1, "id": pack_id, "version": version, "title": title,
                                                  "components": components}), encoding="utf-8")
    with app.extensions["hub"].db.write() as db:
        db.execute("INSERT INTO packs (id, version, title, format, components, imported_at, active) VALUES (?,?,?,?,?,?,1)",
                   (pack_id, version, title, 1, json.dumps(components), "2026-11-13T00:00:00"))
    return folder


@pytest.fixture()
def pack(app, paths):
    folder = _install_pack(app, paths)
    # Packs are immutable: remember every file's bytes to prove nothing was written there.
    before = {path: path.read_bytes() for path in folder.rglob("*") if path.is_file()}
    yield folder
    after = {path: path.read_bytes() for path in folder.rglob("*") if path.is_file()}
    assert after == before, "the viewer wrote into the pack folder"


# --------------------------------------------------------------------------- page


def test_page_without_pack_explains_how_to_get_one(client):
    response = client.get("/code-map/")
    assert response.status_code == 200
    assert '<div id="app">' in response.get_data(as_text=True)  # the app shell (React)
    data = client.get("/code-map/config").get_json()
    assert data["current"] == "" and data["config"]["pack"] == "" and data["config"]["packs"] == []  # empty state


@needs_demo
def test_page_mounts_react_with_config(client, pack):
    response = client.get("/code-map/")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "/static/dist/app.js" in html and "<script>" not in html  # CSP: no inline script; config is JSON
    assert client.get("/code-map/config").get_json()["config"]["pack"] == "demo"
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_page_unknown_pack(client):
    assert client.get("/code-map/?pack=nope").status_code == 200
    assert client.get("/code-map/config?pack=nope").get_json()["wanted"] == "nope"


# --------------------------------------------------------------------------- API


def test_api_without_pack(client):
    response = client.get(f"{API}/business/tree")
    assert response.status_code == 503
    assert response.get_json()["error"]["code"] == "no_codemap_pack"


def test_api_refuses_other_hosts(client):
    response = client.get(f"{API}/stats", headers={"Host": "evil.example"})
    assert response.status_code == 400


@needs_demo
def test_api_reads_the_pack(client, pack):
    stats = client.get(f"{API}/stats").get_json()
    assert stats["nodes"] > 0 and stats["edges"] > 0

    tree = client.get(f"{API}/business/tree").get_json()
    assert tree["menus"]
    flows = []
    stack = list(tree["menus"])
    while stack:
        item = stack.pop()
        if item["kind"] == "flow":
            flows.append(item["id"])
        stack.extend(item.get("children") or [])
    assert flows

    flow = client.get(f"{API}/business/flows/{flows[0]}").get_json()
    assert flow["nodes"] and "flow" in flow

    search = client.get(f"{API}/business/search?q=order").get_json()
    assert search["business"] or search["nodes"]

    node_id = flow["nodes"][0]["node_id"]
    detail = client.get(f"{API}/detail?target_id={node_id}&target_type=NODE&locale=vi&relations=0")
    assert detail.status_code == 200

    expansion = client.get(f"{API}/flow?node_id={node_id}&mode=1&direction=out&max_nodes=50&semantic_level=TECHNICAL")
    assert expansion.status_code == 200 and "nodes" in expansion.get_json()

    kb = client.get(f"{API}/business/kb-status").get_json()
    assert kb["stale"]["fresh"] is None and "pack snapshot" in kb["summary"]
    assert kb["stale"]["revisions"]


@needs_demo
def test_unknown_pack_param(client, pack):
    response = client.get(f"{API}/stats?pack=other")
    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "unknown_pack"
    assert client.get(f"{API}/stats?pack=demo").status_code == 200


@needs_demo
def test_knowledge_goes_to_user_folder(client, pack, paths):
    response = client.post(f"{API}/business/rules", json={"title": "Đơn đã giao không được hủy", "domain": "ORD"},
                           headers={"X-Code-Map-User": "An"})
    assert response.status_code == 201, response.get_data(as_text=True)
    knowledge = paths.user / "codemap" / "demo" / "knowledge.sqlite"
    assert knowledge.is_file()
    with sqlite3.connect(knowledge) as db:
        assert db.execute("SELECT COUNT(*) FROM biz_rules").fetchone()[0] == 1
    assert len(client.get(f"{API}/business/rules").get_json()) == 1


@needs_demo
def test_snippet_reads_pack_source(client, pack):
    flow_nodes = []
    tree = client.get(f"{API}/business/tree").get_json()
    stack = list(tree["menus"])
    while stack:
        item = stack.pop()
        if item["kind"] == "flow":
            flow_nodes += client.get(f"{API}/business/flows/{item['id']}").get_json()["nodes"]
        stack.extend(item.get("children") or [])
    node = next(node for node in flow_nodes if node.get("file") == "order-fulfillment/Program.cs")
    response = client.get(f"{API}/snippet?path=order-fulfillment/Program.cs&target_id={node['node_id']}")
    body = response.get_json()
    assert response.status_code == 200 and body["status"] == "available"
    assert body["content"].startswith("// line 1")
    escape = client.get(f"{API}/snippet?path=../pack.json")
    assert escape.status_code == 403


@needs_demo
def test_snippet_without_source(client, app, paths):
    _install_pack(app, paths, source=False)
    response = client.get(f"{API}/snippet?path=order-fulfillment/Program.cs")
    assert response.status_code == 404
    assert response.get_json()["status"] == "source_unavailable"
    assert client.get("/code-map/config").get_json()["config"]["source"] is False


@needs_demo
def test_dev_folder_is_served(client, paths):
    local = paths.home / "codemap"
    local.mkdir()
    shutil.copy2(DEMO / "codemap.sqlite", local / "codemap.sqlite")
    response = client.get(f"{API}/stats?pack=local")
    assert response.status_code == 200
    assert response.get_json()["nodes"] > 0


# --------------------------------------------------------------------------- MCP


def _rpc(client, method, params=None, request_id=1, **headers):
    body = {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
    return client.post("/code-map/mcp", data=json.dumps(body), content_type="application/json", headers=headers)


@needs_demo
def test_mcp_over_http(client, pack, paths):
    init = _rpc(client, "initialize", {"protocolVersion": "2025-06-18", "clientInfo": {"name": "pytest"}})
    assert init.status_code == 200
    assert init.get_json()["result"]["serverInfo"]["name"] == "codemap"

    tools = _rpc(client, "tools/list", request_id=2).get_json()["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert "codemap_status" in names and "codemap_search" in names
    assert not any(name.startswith("codemap_propose") for name in names)  # no token, no write tools

    call = _rpc(client, "tools/call", {"name": "codemap_search", "arguments": {"question": "order"}}, request_id=3).get_json()
    assert call["result"]["isError"] is False
    assert "pack snapshot" in call["result"]["content"][0]["text"]
    # The call log goes to the user's knowledge db, never into the pack.
    with sqlite3.connect(paths.user / "codemap" / "demo" / "knowledge.sqlite") as db:
        assert db.execute("SELECT tool FROM mcp_calls").fetchall() == [("codemap_search",)]


def test_mcp_without_pack(client):
    response = _rpc(client, "initialize")
    assert response.status_code == 503
    assert "No code-map pack" in response.get_json()["error"]["message"]


def test_mcp_rejects_foreign_origin(client):
    response = _rpc(client, "ping", Origin="http://evil.example")
    assert response.status_code in (403, 503)


@needs_demo
def test_mcp_cli_stdio(app, paths, pack, monkeypatch, capsys):
    from viewer_hub.codemap.cli.mcp import main

    lines = [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "codemap_status", "arguments": {"detail": "brief"}}}),
    ]
    stdin = io.TextIOWrapper(io.BytesIO(("\n".join(lines) + "\n").encode("utf-8")))
    stdout = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    assert main([], paths) == 0
    stdout.flush()
    replies = [json.loads(line) for line in stdout.buffer.getvalue().decode("utf-8").splitlines()]
    assert [reply["id"] for reply in replies] == [1, 2]
    assert replies[1]["result"]["isError"] is False


def test_mcp_cli_without_pack(paths, capsys):
    from viewer_hub.codemap.cli.mcp import main

    assert main(["--self-test"], paths) == 2
    assert "no an active code-map pack" in capsys.readouterr().err
