from __future__ import annotations

import io
import json

from viewer_hub.fsearch import mcp


def call(path, name, **arguments):
    out = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}, lambda: path)
    return out["result"]["content"][0]["text"], out["result"]["isError"]


def test_two_lean_tools():
    tools = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, lambda: None)["result"]["tools"]
    assert [t["name"] for t in tools] == ["search_documents", "read_document"]
    assert all(t["annotations"]["readOnlyHint"] for t in tools)
    assert len(json.dumps(tools)) < 3000  # the tool list itself costs few tokens


def test_search_is_compact_plain_text(search_db):
    text, error = call(search_db, "search_documents", query="dang nhap")
    assert not error
    assert "<mark>" not in text and "&amp;" not in text and "«đăng nhập»" in text.replace("» «", " ")
    assert "| docs/huong-dan.md |" in text and text.startswith("1 results")
    assert len(text) < 800


def test_search_filters_paging_and_empty(search_db):
    text, _ = call(search_db, "search_documents", query="ログイン OR token", limit=1)
    assert "more: offset=1" in text
    text, _ = call(search_db, "search_documents", query="token", repository="docs")
    assert text.startswith("0 results")


def test_read_document_passages_and_slices(search_db):
    text, error = call(search_db, "read_document", id="a", query="generate_token")
    assert not error and "passage" in text and "«" in text
    text, _ = call(search_db, "read_document", id="a", max_chars=200)
    assert "chars 0-" in text and ("offset=" in text or "[end]" in text)
    text, error = call(search_db, "read_document", id="nope")
    assert error and "No document" in text


def test_no_data_is_reported_not_crashing():
    text, error = call(None, "search_documents", query="x")
    assert error and "admin" in text


def test_http_endpoint(client, search_db):
    init = client.post("/ocr-search/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
    assert init.status_code == 200 and init.json["result"]["serverInfo"]["name"] == "viewer-hub-search"
    assert client.post("/ocr-search/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
    hit = client.post("/ocr-search/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                                               "params": {"name": "search_documents", "arguments": {"query": "token"}}})
    assert "authentication.py" in hit.json["result"]["content"][0]["text"]
    blocked = client.post("/ocr-search/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "ping"}, headers={"Origin": "https://evil.example"})
    assert blocked.status_code == 403


def test_stdio(monkeypatch, search_db, capsys):
    lines = [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}), "not json",
             json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})]
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(lines) + "\n"))
    assert mcp.serve_stdio(lambda: search_db) == 0
    out = [json.loads(l) for l in capsys.readouterr().out.splitlines()]
    assert len(out) == 2 and out[0]["result"]["tools"] and out[1]["error"]["code"] == -32700
