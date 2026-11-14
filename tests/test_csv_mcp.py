"""MCP over CSV files shared with AI: csv_list (files, descriptions, columns, samples) and csv_search (rows)."""
from __future__ import annotations

import io
import json

from viewer_hub.csv import mcp
from viewer_hub.csv.store import CsvStore

DICTIONARY = ("TABLE_NAME,COLUMN_NAME,DATA_TYPE,論理名\n"
              "ORDER_HEADER,ORDER_ID,NUMBER,注文ID\nORDER_HEADER,STS_CD,CHAR(2),状態\n"
              "ORDER_LINE,ORDER_ID,NUMBER,注文ID\nCUSTOMER,CUSTOMER_ID,NUMBER,顧客ID\n")


def upload(client, text: str, name: str, description: str = "", ai_read: str = ""):
    """Upload, then fill the describe dialog that follows (name, description, Cho AI đọc)."""
    response = client.post("/csv/api/datasets", data={"file": (io.BytesIO(text.encode("utf-8")), name)})
    dataset_id = response.get_json()["created"][0]["id"]
    client.patch(f"/csv/api/datasets/{dataset_id}", json={"description": description, "mcp": bool(ai_read)})
    return dataset_id


def call(client, name, arguments=None, request_id=1):
    body = {"jsonrpc": "2.0", "id": request_id, "method": "tools/call", "params": {"name": name, "arguments": arguments or {}}}
    reply = client.post("/csv/mcp", data=json.dumps(body), content_type="application/json").get_json()
    result = reply["result"]
    return result["content"][0]["text"], result["isError"]


def test_only_files_shared_with_ai_are_listed(client, paths):
    upload(client, DICTIONARY, "columns.csv", description="Từ điển cột của DB đơn hàng", ai_read="on")
    upload(client, "name,salary\nAn,100\n", "luong.csv")  # not shared: the switch was off
    text, error = call(client, "csv_list")
    assert not error
    assert "columns — columns" in text and "Từ điển cột của DB đơn hàng" in text
    assert "- TABLE_NAME (text)" in text and "e.g. ORDER_HEADER" in text
    assert "luong" not in text and "salary" not in text
    assert call(client, "csv_list", {"query": "mã lỗi"})[0].startswith("No shared CSV file matches")


def test_search_rows_with_filters_and_columns(client, paths):
    upload(client, DICTIONARY, "columns.csv", description="DB", ai_read="on")
    text, error = call(client, "csv_search", {"id": "columns", "filters": [{"column": "table_name", "operator": "==", "value": "order_header"}],
                                               "columns": ["COLUMN_NAME", "DATA_TYPE"]})
    assert not error
    lines = text.splitlines()
    assert lines[0].endswith("rows 1-2 of 2") and lines[1] == "COLUMN_NAME | DATA_TYPE"
    assert lines[2:] == ["ORDER_ID | NUMBER", "STS_CD | CHAR(2)"]

    cut, _ = call(client, "csv_search", {"id": "columns", "text": "ORDER_ID", "limit": 1})
    assert "rows 1-1 of 2" in cut and "offset=1" in cut

    bad, error = call(client, "csv_search", {"id": "columns", "filters": [{"column": "NOPE", "value": "x"}]})
    assert error and "columns: TABLE_NAME" in bad
    hidden, error = call(client, "csv_search", {"id": "luong"})
    assert error and "csv_list" in hidden


def test_settings_turn_sharing_and_descriptions_on(client, paths):
    upload(client, "code,message\nE01,Timeout\n", "errors.csv")
    d = CsvStore(paths.csv, paths.tmp).list()[0]
    assert not d.mcp
    client.patch(f"/csv/api/datasets/{d.id}", json={"mcp": True, "description": "Mã lỗi"})
    columns = [{"key": c["key"], "visible": True} for c in d.columns]
    columns[0]["description"] = "Mã lỗi trong log"
    client.put(f"/csv/api/datasets/{d.id}/columns", json={"columns": columns})
    text, _ = call(client, "csv_list")
    assert "Mã lỗi" in text and "- code (text): Mã lỗi trong log · e.g. E01" in text


def test_pack_csv_config_description_and_mcp(tmp_path):
    from viewer_hub.packs.builder import _add_csv

    folder = tmp_path / "in"
    folder.mkdir()
    (folder / "a.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    (folder / "b.csv").write_text("x,y\n1,2\n", encoding="utf-8")
    (folder / "config.json").write_text(json.dumps({
        "A": {"path": "a.csv", "description": "File A", "columnDescriptions": {"x": "khoá"}},
        "B": {"path": "b.csv", "mcp": False}}))
    _add_csv(tmp_path / "work", {}, [folder / "a.csv", folder / "b.csv"])
    by_title = {d.title: d for d in CsvStore(tmp_path / "work" / "csv", tmp_path / "tmp").list()}
    assert by_title["A"].mcp and by_title["A"].description == "File A" and by_title["A"].columns[0]["description"] == "khoá"
    assert not by_title["B"].mcp  # the admin said no


def test_stdio(client, paths, monkeypatch, capsys):
    upload(client, DICTIONARY, "columns.csv", description="DB", ai_read="on")
    store = CsvStore(paths.csv, paths.tmp)
    lines = [json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}),
             json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "csv_list", "arguments": {}}})]
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(lines) + "\n"))
    assert mcp.serve_stdio(lambda: store) == 0
    replies = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [t["name"] for t in replies[0]["result"]["tools"]] == ["csv_list", "csv_search"]
    assert "columns — columns" in replies[1]["result"]["content"][0]["text"]
