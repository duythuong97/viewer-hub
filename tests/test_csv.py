from __future__ import annotations

import io
import json

from viewer_hub.csv.store import CsvStore, detect_encoding


def upload(client, text: bytes | str, name="people.csv"):
    data = text.encode("utf-8") if isinstance(text, str) else text
    return client.post("/csv/api/datasets", data={"file": (io.BytesIO(data), name)})


def dataset(paths):
    return CsvStore(paths.csv, paths.tmp).list()[0]


def test_upload_detects_headers_and_types(client, paths):
    response = upload(client, "Tên;Tuổi;Email\nAn;30;an@x.vn\nBình;25;binh@x.vn\n")
    # Next step after an upload: describe the new file (dialog on the list page).
    assert response.status_code == 200 and [d["id"] for d in response.get_json()["created"]] == ["people"]
    d = dataset(paths)
    assert [c["name"] for c in d.columns] == ["Tên", "Tuổi", "Email"]
    assert d.meta["source"]["delimiter"] == ";"
    assert [c["type"] for c in d.columns] == ["text", "number", "text"]
    assert d.meta["rows"] == 2


def test_shift_jis_and_duplicate_headers(client, paths):
    raw = "名前,名前,部署\n山田,太郎,営業\n".encode("cp932")
    assert detect_encoding(raw) in {"cp932", "shift_jis", "euc-jp"}
    upload(client, raw, "jp.csv")
    d = dataset(paths)
    assert [c["name"] for c in d.columns] == ["名前", "名前 (2)", "部署"]


def test_search_filters_and_sort(client, paths):
    upload(client, "name,age,city\nAn,30,Hà Nội\nBình,25,Đà Nẵng\nChi,41,Hà Nội\n")
    d = dataset(paths)
    get = lambda **q: json.loads(client.get(f"/csv/api/datasets/{d.id}/rows", query_string=q).data)
    assert get(q="Hà Nội")["total"] == 2
    assert get(q="An")["total"] == 1  # 2 chars: LIKE fallback
    rule = json.dumps([{"column": "c2", "operator": "==", "value": "hà nội"}])
    assert get(filters=rule)["total"] == 2
    rows = get(sort="c1", desc="1")["rows"]
    assert [r[1] for r in rows] == ["41", "30", "25"]


def test_export_neutralises_formulas(client, paths):
    upload(client, "a,b\n=cmd|' /C calc'!A0,ok\n")
    d = dataset(paths)
    body = client.get(f"/csv/api/datasets/{d.id}/export.csv").data.decode("utf-8-sig")
    assert "'=cmd" in body


def test_column_settings_persist_in_dataset_json(client, paths):
    upload(client, "a,b,c\n1,2,3\n")
    d = dataset(paths)
    client.patch(f"/csv/api/datasets/{d.id}", json={"title": "Mới"})
    columns = [{"key": "c0", "visible": True, "filter": True, "op": "==", "label": "Cột A"},
               {"key": "c1", "visible": False}, {"key": "c2", "visible": False}]
    assert client.put(f"/csv/api/datasets/{d.id}/columns", json={"columns": columns}).status_code == 200
    d = dataset(paths)
    assert d.title == "Mới"
    assert [c["key"] for c in d.visible] == ["c0"]
    assert d.columns[0]["label"] == "Cột A" and d.columns[0]["op"] == "=="


def test_rejects_binary(client, paths):
    upload(client, b"\x00\x01\x02binary", "bad.csv")
    assert CsvStore(paths.csv, paths.tmp).list() == []


def test_delete(client, paths):
    upload(client, "a\n1\n")
    d = dataset(paths)
    assert client.delete(f"/csv/api/datasets/{d.id}").status_code == 200
    assert CsvStore(paths.csv, paths.tmp).list() == []


def test_index_opens_last_dataset_with_picker(client, paths):
    upload(client, "a\n1\n", "first.csv")
    upload(client, "b\n2\n", "second.csv")
    client.get("/csv/api/datasets/first")  # viewing a dataset makes it the one /csv/ opens next time
    listing = client.get("/csv/api/datasets").get_json()
    assert listing["last"] == "first" and {d["id"] for d in listing["datasets"]} == {"first", "second"}
    assert client.get("/csv/").status_code == 200 and client.get("/csv/?manage=1").status_code == 200



def test_old_csv_viewer_config_sets_columns_and_default_filters(tmp_path):
    """input/csv/config.json from the old csv-viewer: name, visibleCols and filterCol carry over to the pack."""
    from viewer_hub.packs.builder import _add_csv

    (tmp_path / "in").mkdir()
    source = tmp_path / "in" / "fileB.csv"
    source.write_text("name,age,email,phone,note\nAn,30,an@x.vn,1,a\n", encoding="utf-8")
    (tmp_path / "in" / "config.json").write_text(json.dumps({"Nhân viên": {
        "path": "data/fileB.csv", "filterCol": [{"name": "IN"}, {"phone": "=="}], "visibleCols": ["name", "age", "email"]}}))
    files: dict = {}
    entries = _add_csv(tmp_path / "work", files, [source])
    assert entries[0]["title"] == "Nhân viên"
    d = CsvStore(tmp_path / "work" / "csv", tmp_path / "work" / "tmp").list()[0]
    assert [c["name"] for c in d.visible] == ["name", "age", "email", "phone"]  # a filter column is always shown
    assert d.default_filters == [{"column": "c0", "operator": "IN"}, {"column": "c3", "operator": "=="}]


def test_default_filter_is_the_first_column(client, paths):
    upload(client, "a,b,c\n1,2,3\n")
    assert dataset(paths).default_filters == [{"column": "c0", "operator": "IN"}]



def test_describe_after_upload_and_edit_later(client, paths):
    upload(client, "a,b\n1,2\n", "first.csv")
    upload(client, "a,b\n1,2\n", "second.csv")
    saved = client.patch("/csv/api/datasets/first", json={"title": "Danh mục", "description": "Danh mục sản phẩm", "mcp": True})
    assert saved.status_code == 200 and saved.get_json()["dataset"]["title"] == "Danh mục"
    client.patch("/csv/api/datasets/second", json={"description": ""})
    by_id = {d.id: d for d in CsvStore(paths.csv, paths.tmp).list()}
    assert by_id["first"].title == "Danh mục" and by_id["first"].description == "Danh mục sản phẩm" and by_id["first"].mcp
    assert not by_id["second"].mcp
    # Edit later: the same call from the list's "Sửa" dialog.
    client.patch("/csv/api/datasets/first", json={"mcp": False})
    assert not CsvStore(paths.csv, paths.tmp).get("first").mcp
