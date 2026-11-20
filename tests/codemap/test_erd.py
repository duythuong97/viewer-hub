"""ERD: model, Mermaid / DBML exporters, API, MCP tool and CLI over a pack with foreign keys (erd_fixture.py)."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import pytest

import erd_fixture
from viewer_hub.codemap import erd

needs_demo = pytest.mark.skipif(not (erd_fixture.DEMO / "codemap.sqlite").is_file(),
                                reason=f"code-map demo output not found at {erd_fixture.DEMO}")
pytestmark = needs_demo


@pytest.fixture(scope="module")
def fk_output(tmp_path_factory) -> Path:
    return erd_fixture.make_output(tmp_path_factory.mktemp("erd") / "codemap")


@pytest.fixture()
def graph(fk_output):
    db = sqlite3.connect(f"{(fk_output / 'codemap.sqlite').as_uri()}?mode=ro", uri=True)
    yield db
    db.close()


def _install(app, paths, *, foreign_keys=True, pack_id="erd", version="2026.11.13-1") -> Path:
    folder = paths.packs / pack_id / version
    erd_fixture.make_output(folder / "codemap", foreign_keys=foreign_keys)
    components = {"codemap": {"path": "codemap/", "schema": 3, "contractVersion": "3.0"}}
    (folder / "pack.json").write_text(json.dumps({"format": 1, "id": pack_id, "version": version, "title": "ERD",
                                                  "components": components}), encoding="utf-8")
    with app.extensions["hub"].db.write() as db:
        db.execute("INSERT INTO packs (id, version, title, format, components, imported_at, active) VALUES (?,?,?,?,?,?,1)",
                   (pack_id, version, "ERD", 1, json.dumps(components), "2026-11-13T00:00:00"))
    return folder


@pytest.fixture()
def fk_pack(app, paths):
    folder = _install(app, paths)
    before = {path: path.read_bytes() for path in folder.rglob("*") if path.is_file()}
    yield folder
    assert {path: path.read_bytes() for path in folder.rglob("*") if path.is_file()} == before, "the viewer wrote into the pack"


def test_fixture_leaves_the_demo_alone(tmp_path):
    before = (erd_fixture.DEMO / "codemap.sqlite").read_bytes()
    erd_fixture.make_output(tmp_path / "copy")
    assert (erd_fixture.DEMO / "codemap.sqlite").read_bytes() == before


# --------------------------------------------------------------------------- model


def test_focus_depth_one(graph):
    model = erd.build(graph, table="ORDERS")
    assert model["mode"] == "table" and model["focus"] == "table:DB1:ORDERS" and model["has_fk_data"]
    names = [table["name"] for table in model["tables"]]
    assert names[0] == "ORDERS"
    assert set(names) == {"ORDERS", "BACKORDER", "ORDER_HEADER", "ORDER_LINE", "PAYMENT_TRANSACTION", "SHIPMENT"}
    by_name = {table["name"]: table for table in model["tables"]}
    assert by_name["ORDER_LINE"]["distance"] == 1 and by_name["ORDER_LINE"]["layer"] == -1  # child: left of ORDERS
    orders = by_name["ORDERS"]
    assert isinstance(orders["logical"], dict)
    assert orders["columns"][0] == {**orders["columns"][0], "name": "ORDER_ID", "type": "NUMBER(18,0)", "pk": True,
                                    "fk": False, "referenced": True, "nullable": False}
    line = by_name["ORDER_LINE"]
    assert [column["name"] for column in line["columns"]] == ["ORDER_LINE_ID", "ORDER_ID", "PRODUCT_ID", "QUANTITY", "UNIT_PRICE"]
    assert line["logical"]["ja"] == "注文明細行" and line["columns"][1]["logical"]["en"] == "Order ID"
    assert line["columns"][1]["fk"] and not line["columns"][0]["fk"]
    relations = {relation["constraint"]: relation for relation in model["relations"]}
    assert set(relations) == {"FK_ORDER_LINE_ORDER", "FK_SHIPMENT_ORDER", "FK_PAYMENT_ORDER", "FK_BACKORDER_ORDER", "FK_ORDER_HEADER_ORDER"}
    cascade = relations["FK_ORDER_LINE_ORDER"]
    assert cascade["delete_rule"] == "CASCADE" and cascade["cardinality"] == "many-to-one" and cascade["source"] == "catalog"
    assert cascade["label"] == "ORDER_ID → ORDER_ID"
    assert relations["FK_ORDER_HEADER_ORDER"]["cardinality"] == "one-to-one"  # FK column is the whole PK
    assert relations["FK_PAYMENT_ORDER"]["source"] == "ddl"
    assert not model["truncated"] and model["omitted"] == 0


def test_focus_depth_two_and_composite(graph):
    model = erd.build(graph, table="DB1.APP.ORDERS", depth=2)
    names = {table["name"] for table in model["tables"]}
    assert {"SHIPMENT_PACKAGE", "SHIPMENT_AUDIT", "INVENTORY_RESERVATION", "CUSTOMERS"} <= names
    composite = next(relation for relation in model["relations"] if relation["constraint"] == "FK_RESERVATION_LINE")
    assert composite["from_columns"] == ["ORDER_ID", "PRODUCT_ID"] and composite["to_columns"] == ["ORDER_ID", "PRODUCT_ID"]
    assert composite["label"] == "(ORDER_ID, PRODUCT_ID) → (ORDER_ID, PRODUCT_ID)"
    assert erd.build(graph, table="column:DB1:SHIPMENT:ORDER_ID")["focus"] == "table:DB1:SHIPMENT"  # a column opens its table


def test_cap_and_scopes(graph):
    capped = erd.build(graph, table="ORDERS", depth=2, limit=3)
    assert capped["truncated"] and len(capped["tables"]) == 3 and capped["omitted"] == 7
    assert capped["tables"][0]["name"] == "ORDERS"
    assert all(relation["from_table"] in {t["id"] for t in capped["tables"]} for relation in capped["relations"])
    schema = erd.build(graph, schema="DB1.APP")
    assert schema["mode"] == "schema" and len(schema["tables"]) == 12
    assert schema["outside_relations"] == 1  # ORDER_HEADER -> DB2.MASTER.CUSTOMERS
    assert len(erd.build(graph, schema="MASTER")["tables"]) == 1
    assert len(erd.build(graph, system="code-map-demo")["tables"]) == 13


@pytest.mark.parametrize("arguments, code", [
    ({"table": "NOPE"}, "unknown_table"),
    ({"schema": "X.Y"}, "unknown_schema"),
    ({"table": "ORDERS", "schema": "DB1.APP"}, "bad_scope"),
    ({}, "bad_scope"),
    ({"table": "ORDERS", "depth": 3}, "bad_depth"),
])
def test_bad_requests(graph, arguments, code):
    with pytest.raises(erd.ErdError) as error:
        erd.build(graph, **arguments)
    assert error.value.code == code


def test_types():
    assert erd.format_type({"data_type": "VARCHAR2", "data_length": "32"}) == "VARCHAR2(32)"
    assert erd.format_type({"data_type": "NUMBER", "data_precision": "18", "data_scale": "0"}) == "NUMBER(18,0)"
    assert erd.format_type({"data_type": "NUMBER", "data_precision": "10"}) == "NUMBER(10)"
    assert erd.format_type({"data_type": "NUMBER", "data_length": "22"}) == "NUMBER"
    assert erd.format_type({"data_type": "date", "data_length": "7"}) == "DATE"
    assert erd.format_type({}) == ""


def test_search_tables(graph):
    by_ja = erd.search_tables(graph, "出荷")
    assert {table["name"] for table in by_ja["tables"]} >= {"SHIPMENT", "SHIPMENT_AUDIT", "SHIPMENT_PACKAGE"}
    assert erd.search_tables(graph, "order_line")["tables"][0]["name"] == "ORDER_LINE"  # exact first
    assert erd.search_tables(graph, "Inventory Reservation")["tables"][0]["name"] == "INVENTORY_RESERVATION"
    listing = erd.search_tables(graph, "")
    assert {item["id"] for item in listing["schemas"]} == {"DB1.APP", "DB2.MASTER"} and listing["has_fk_data"]
    assert [table["name"] for table in erd.search_tables(graph, "", schema="DB2.MASTER")["tables"]] == ["CUSTOMERS"]


# --------------------------------------------------------------------------- exporters (golden)

MERMAID_SHIPMENT = '''erDiagram
    %% ERD quanh bảng DB1.APP.SHIPMENT (độ sâu 1): 4 bảng, 3 khoá ngoại
    %% DB1.APP.SHIPMENT: 出荷 / Shipment
    SHIPMENT {
        NUMBER SHIPMENT_ID PK "出荷ID / Shipment ID"
        NUMBER ORDER_ID FK "注文ID / Order ID"
        VARCHAR2 STATUS "ステータス / Status"
    }
    %% DB1.APP.ORDERS
    ORDERS {
        NUMBER(18_0) ORDER_ID PK "Order identifier"
    }
    %% DB1.APP.SHIPMENT_AUDIT: 出荷監査 / Shipment Audit
    SHIPMENT_AUDIT {
        NUMBER AUDIT_ID PK "監査ID / Audit ID"
        NUMBER SHIPMENT_ID FK "出荷ID / Shipment ID"
        VARCHAR2 STATUS "ステータス / Status"
    }
    %% DB1.APP.SHIPMENT_PACKAGE: 出荷梱包 / Shipment Package
    SHIPMENT_PACKAGE {
        NUMBER PACKAGE_ID PK "梱包ID / Package ID"
        NUMBER SHIPMENT_ID FK "出荷ID / Shipment ID"
    }
    SHIPMENT }o--|| ORDERS : "FK_SHIPMENT_ORDER: ORDER_ID → ORDER_ID"
    SHIPMENT_AUDIT }o--|| SHIPMENT : "FK_AUDIT_SHIPMENT: SHIPMENT_ID → SHIPMENT_ID"
    SHIPMENT_PACKAGE }o--|| SHIPMENT : "FK_PACKAGE_SHIPMENT: SHIPMENT_ID → SHIPMENT_ID"
'''

DBML_SHIPMENT = '''// ERD quanh bảng DB1.APP.SHIPMENT (độ sâu 1): 4 bảng, 3 khoá ngoại

Table APP.SHIPMENT [note: '出荷 / Shipment'] {
  SHIPMENT_ID NUMBER [pk, not null, note: '出荷ID / Shipment ID']
  ORDER_ID NUMBER [not null, note: '注文ID / Order ID']
  STATUS VARCHAR2 [not null, note: 'ステータス / Status']
}

Table APP.ORDERS [note: 'Order header'] {
  ORDER_ID NUMBER(18,0) [pk, not null, note: 'Order identifier']
}

Table APP.SHIPMENT_AUDIT [note: '出荷監査 / Shipment Audit'] {
  AUDIT_ID NUMBER [pk, not null, note: '監査ID / Audit ID']
  SHIPMENT_ID NUMBER [not null, note: '出荷ID / Shipment ID']
  STATUS VARCHAR2 [not null, note: 'ステータス / Status']
}

Table APP.SHIPMENT_PACKAGE [note: '出荷梱包 / Shipment Package'] {
  PACKAGE_ID NUMBER [pk, not null, note: '梱包ID / Package ID']
  SHIPMENT_ID NUMBER [not null, note: '出荷ID / Shipment ID']
}

Ref FK_SHIPMENT_ORDER: APP.SHIPMENT.ORDER_ID > APP.ORDERS.ORDER_ID
Ref FK_AUDIT_SHIPMENT: APP.SHIPMENT_AUDIT.SHIPMENT_ID > APP.SHIPMENT.SHIPMENT_ID [delete: set null]
Ref FK_PACKAGE_SHIPMENT: APP.SHIPMENT_PACKAGE.SHIPMENT_ID > APP.SHIPMENT.SHIPMENT_ID
'''

DBML_COMPOSITE_KEYS = '''// ERD quanh bảng DB1.APP.INVENTORY_RESERVATION (độ sâu 1): 2 bảng, 1 khoá ngoại

Table APP.INVENTORY_RESERVATION [note: '在庫引当 / Inventory Reservation'] {
  RESERVATION_ID NUMBER [pk, not null, note: '引当ID / Reservation ID']
  ORDER_ID NUMBER [not null, note: '注文ID / Order ID']
  PRODUCT_ID NUMBER [not null, note: '商品ID / Product ID']
}

Table APP.ORDER_LINE [note: '注文明細行 / Order Line'] {
  ORDER_LINE_ID NUMBER [pk, not null, note: '注文明細行ID / Order Line ID']
  ORDER_ID NUMBER [not null, note: '注文ID / Order ID']
  PRODUCT_ID NUMBER [not null, note: '商品ID / Product ID']
}

Ref FK_RESERVATION_LINE: APP.INVENTORY_RESERVATION.(ORDER_ID, PRODUCT_ID) > APP.ORDER_LINE.(ORDER_ID, PRODUCT_ID)
'''


def test_mermaid_golden(graph):
    assert erd.to_mermaid(erd.build(graph, table="SHIPMENT")) == MERMAID_SHIPMENT


def test_dbml_golden(graph):
    assert erd.to_dbml(erd.build(graph, table="SHIPMENT")) == DBML_SHIPMENT
    # keys only keeps the columns a composite FK points to, so every Ref names a declared column
    assert erd.to_dbml(erd.build(graph, table="INVENTORY_RESERVATION"), keys_only=True) == DBML_COMPOSITE_KEYS


def test_one_to_one_and_cascade(graph):
    model = erd.build(graph, table="ORDERS")
    mermaid, dbml = erd.to_mermaid(model), erd.to_dbml(model)
    assert 'ORDER_HEADER |o--|| ORDERS : "FK_ORDER_HEADER_ORDER: ORDER_ID → ORDER_ID"' in mermaid
    assert "NUMBER ORDER_ID PK, FK" in mermaid
    assert "Ref FK_ORDER_HEADER_ORDER: APP.ORDER_HEADER.ORDER_ID - APP.ORDERS.ORDER_ID" in dbml
    assert "Ref FK_ORDER_LINE_ORDER: APP.ORDER_LINE.ORDER_ID > APP.ORDERS.ORDER_ID [delete: cascade]" in dbml


def _awkward_model() -> dict:
    column = {"id": "c1", "name": "注文 \"ID\"", "type": "NUMBER(18,0)", "nullable": True, "pk": True, "fk": False,
              "referenced": False, "position": 1, "comment": "it's \"quoted\"\nnext line", "logical": {}}
    other = {**column, "id": "c2", "name": "2nd-col", "type": "TIMESTAMP(6) WITH TIME ZONE", "pk": False, "fk": True,
             "comment": "", "logical": {"ja": "日時 \"x\"", "en": "it's"}}
    tables = [
        {"id": "t1", "database": "DB", "schema": "my schema", "name": "ORDER-ITEMS", "qualified_name": "DB.my schema.ORDER-ITEMS",
         "system": "", "comment": "O'Reilly \\ path", "logical": {}, "columns": [column, other]},
        {"id": "t2", "database": "DB", "schema": "s", "name": "ORDER_ITEMS", "qualified_name": "DB.s.ORDER_ITEMS",
         "system": "", "comment": "", "logical": {}, "columns": [{**column, "id": "c3", "name": "ID", "comment": ""}]},
    ]
    relations = [{"id": "r", "constraint": "FK \"odd\" name", "from_table": "t1", "from_columns": ["2nd-col"], "to_table": "t2",
                  "to_columns": ["ID"], "delete_rule": "CASCADE", "source": "ddl", "referenced_constraint": "",
                  "cardinality": "many-to-one", "optional": True, "label": "2nd-col → ID"}]
    return {"tables": tables, "relations": relations, "summary": 'ERD "test"\nline'}


# Mermaid erDiagram grammar (mermaid/src/diagrams/er/parser/erDiagram.jison): what each line may contain.
_ENTITY = r"[A-Za-z_][A-Za-z0-9_-]*"
_ATTRIBUTE_WORD = r"[A-Za-z_][A-Za-z0-9_()\[\]-]*"
_MERMAID_LINE = re.compile("|".join([
    r"^erDiagram$",
    r"^\s*%%[^\n]*$",
    rf"^\s*{_ENTITY} \{{$",
    r"^\s*\}$",
    rf'^\s*{_ATTRIBUTE_WORD} {_ATTRIBUTE_WORD}( (PK|FK|UK)(, (PK|FK|UK))*)?( "[^"\n]*")?$',
    rf'^\s*{_ENTITY} (\|o|\|\||\}}o|\}}\|)--(o\||\|\||o\{{|\|\{{) {_ENTITY} : "[^"\n]*"$',
]))


def _assert_valid_mermaid(text: str) -> None:
    for line in text.splitlines():
        assert _MERMAID_LINE.match(line), f"not valid erDiagram syntax: {line!r}"


def test_mermaid_is_valid_syntax(graph):
    for model in (erd.build(graph, table="ORDERS", depth=2), erd.build(graph, schema="DB1.APP"), _awkward_model()):
        _assert_valid_mermaid(erd.to_mermaid(model))
    text = erd.to_mermaid(_awkward_model())
    # ORDER-ITEMS and ORDER_ITEMS sanitise to the same entity name, so both get their schema
    assert "    my_schema_ORDER_ITEMS {" in text and "    s_ORDER_ITEMS {" in text
    assert 'NUMBER(18_0) ID PK "it\'s \'quoted\' next line"' in text
    assert 'TIMESTAMP(6)_WITH_TIME_ZONE C_2nd_col FK "日時 \'x\' / it\'s"' in text
    assert 'my_schema_ORDER_ITEMS }o--o| s_ORDER_ITEMS : "FK \'odd\' name: 2nd-col → ID"' in text


def test_dbml_escaping():
    text = erd.to_dbml(_awkward_model())
    assert "// ERD \"test\" line" in text
    assert "Table \"my schema\".\"ORDER-ITEMS\" [note: 'O\\'Reilly \\\\ path'] {" in text
    assert "  \"注文 \\\"ID\\\"\" NUMBER(18,0) [pk, note: 'it\\'s \"quoted\" next line']" in text
    assert "  \"2nd-col\" \"TIMESTAMP(6) WITH TIME ZONE\" [note: '日時 \"x\" / it\\'s']" in text
    assert "Ref \"FK \\\"odd\\\" name\": \"my schema\".\"ORDER-ITEMS\".\"2nd-col\" > s.ORDER_ITEMS.ID [delete: cascade]" in text


# --------------------------------------------------------------------------- tables mode


def test_given_tables(graph):
    model = erd.build(graph, tables=["ORDER_LINE", "DB1.APP.ORDERS", "NOPE", "ORDERS"])
    assert model["mode"] == "tables" and model["focus"] is None and model["missing"] == ["NOPE"]
    assert [table["name"] for table in model["tables"]] == ["ORDER_LINE", "ORDERS"]  # given order, no duplicate
    assert [relation["constraint"] for relation in model["relations"]] == ["FK_ORDER_LINE_ORDER"]  # only between them
    # SHIPMENT, PAYMENT_TRANSACTION, BACKORDER, ORDER_HEADER -> ORDERS; INVENTORY_RESERVATION -> ORDER_LINE
    assert model["outside_tables"] == 5 and len(model["outside"]) == 5
    assert "5 bảng khác có khoá ngoại" in model["summary"]
    assert erd.build(graph, tables=[])["tables"] == []
    with pytest.raises(erd.ErdError) as error:
        erd.build(graph, tables=["NOPE"])
    assert error.value.code == "unknown_table"
    with pytest.raises(erd.ErdError) as error:
        erd.build(graph, table="ORDERS", tables=["ORDERS"])
    assert error.value.code == "bad_scope"


def test_whole_database_api_is_gone(client, fk_pack):
    """The whole-database ERD is the erd addon now (it reads the codemap exports, tests/codemap/test_exports.py)."""
    assert client.get("/code-map/api/erd?table=ORDERS").status_code == 404
    config = client.get("/code-map/config").get_json()["config"]
    assert "erdBase" not in config and config["erdAddon"] == ""


# --------------------------------------------------------------------------- MCP + CLI


def _rpc(client, method, params=None):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return client.post("/code-map/mcp", data=json.dumps(body), content_type="application/json").get_json()


def test_mcp_tool(client, fk_pack):
    tools = {tool["name"]: tool for tool in _rpc(client, "tools/list")["result"]["tools"]}
    assert "codemap_erd" in tools and "impact" in tools["codemap_erd"]["description"]
    assert tools["codemap_erd"]["annotations"]["readOnlyHint"] is True
    result = _rpc(client, "tools/call", {"name": "codemap_erd", "arguments": {"table": "SHIPMENT"}})["result"]
    text = result["content"][0]["text"]
    assert result["isError"] is False
    assert text.startswith("> KB built") and "## ERD quanh bảng DB1.APP.SHIPMENT" in text
    assert "```mermaid\nerDiagram" in text and "## Not certain" in text
    assert "- FK_AUDIT_SHIPMENT: DB1.APP.SHIPMENT_AUDIT.(SHIPMENT_ID) → DB1.APP.SHIPMENT.(SHIPMENT_ID) [many-to-one; ON DELETE SET NULL; from catalog]" in text
    dbml = _rpc(client, "tools/call", {"name": "codemap_erd", "arguments": {"schema": "DB1.APP", "format": "dbml", "columns": "keys"}})
    assert "```dbml" in dbml["result"]["content"][0]["text"] and "QUANTITY" not in dbml["result"]["content"][0]["text"]
    bad = _rpc(client, "tools/call", {"name": "codemap_erd", "arguments": {"table": "NOPE"}})["result"]
    assert bad["isError"] is True and "NOPE" in bad["content"][0]["text"]


def test_mcp_tool_without_fk_data(client, app, paths):
    _install(app, paths, foreign_keys=False, pack_id="old")
    text = _rpc(client, "tools/call", {"name": "codemap_erd", "arguments": {"table": "ORDERS"}})["result"]["content"][0]["text"]
    assert erd.NO_FK_MESSAGE in text and "re-extract" in text


def test_cli(app, paths, fk_pack, tmp_path, capsys):
    from viewer_hub.cli import main

    out = tmp_path / "shipment.dbml"
    assert main(["--data-dir", str(paths.home), "erd", "--table", "SHIPMENT", "--format", "dbml", "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == DBML_SHIPMENT
    assert main(["--data-dir", str(paths.home), "erd", "--schema", "DB1.APP", "--keys-only"]) == 0
    printed = capsys.readouterr()
    assert printed.out.startswith("erDiagram") and "QUANTITY" not in printed.out and "12 bảng" in printed.err
    assert main(["--data-dir", str(paths.home), "erd", "--table", "NOPE"]) == 1
    assert main(["--data-dir", str(paths.home), "erd", "--pack", "zzz", "--table", "ORDERS"]) == 2


def test_current_demo_extract(tmp_path):
    """Whatever the code-map demo holds now (a newer extract writes real REFERENCES edges, some with no constraint name)."""
    import shutil

    shutil.copy2(erd_fixture.DEMO / "codemap.sqlite", tmp_path / "codemap.sqlite")
    with sqlite3.connect(f"{(tmp_path / 'codemap.sqlite').as_uri()}?mode=ro", uri=True) as db:
        model = erd.build(db, schema="DB1.APP")
        assert model["has_fk_data"] == erd.has_fk_data(db)
        _assert_valid_mermaid(erd.to_mermaid(model))
        dbml = erd.to_dbml(model)
        for relation in model["relations"]:
            assert relation["label"] and relation["from_columns"] and len(relation["from_columns"]) == len(relation["to_columns"])
        assert dbml.count("\nRef") == len(model["relations"])


def test_pack_index_is_cached_and_refreshed_when_the_file_changes(tmp_path):
    """ERD reads tables/FKs once per pack file (performance on thousands of tables), and re-reads a changed file."""
    import os
    import shutil
    import sqlite3

    from viewer_hub.codemap import erd

    from pathlib import Path

    demo = Path(__file__).resolve().parents[3] / "code-map" / "var" / "output" / "demo" / "codemap.sqlite"
    if not demo.is_file():
        import pytest

        pytest.skip("code-map demo output not available")
    copy = tmp_path / "codemap.sqlite"
    shutil.copy(demo, copy)
    db = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
    first = erd._index(db)
    assert erd._index(db) is first  # cached
    before = len(first.tables)
    writer = sqlite3.connect(copy)
    writer.execute("DELETE FROM graph_nodes WHERE node_id IN (SELECT node_id FROM graph_nodes WHERE node_type='TABLE' LIMIT 1)")
    writer.commit()
    writer.close()
    os.utime(copy, ns=(os.stat(copy).st_atime_ns, os.stat(copy).st_mtime_ns + 1_000_000))
    assert len(erd._index(db).tables) == before - 1  # file changed: index rebuilt
    db.close()


def test_retriever_whole_table_facts_are_computed_once_per_pack(tmp_path):
    """Counting/grouping whole tables is done once per pack file, not on every MCP call (1.5 GB extracts)."""
    import shutil
    import sqlite3
    from pathlib import Path

    from viewer_hub.codemap import retriever

    demo = Path(__file__).resolve().parents[3] / "code-map" / "var" / "output" / "demo" / "codemap.sqlite"
    if not demo.is_file():
        import pytest

        pytest.skip("code-map demo output not available")
    copy = tmp_path / "codemap.sqlite"
    shutil.copy(demo, copy)
    db = sqlite3.connect(f"file:{copy}?mode=ro", uri=True)
    first, second = retriever.Retriever(db), retriever.Retriever(db)
    assert first._facts is second._facts and first.stats() == second.stats()
    name = db.execute("SELECT file FROM search_nodes WHERE file LIKE '%/%' LIMIT 1").fetchone()[0]
    exact = first.file_seeds(name)
    assert exact and first.file_seeds(name.upper()) == exact  # exact miss (case) -> suffix match, any case
    assert first.file_seeds("C:\\work\\" + name.replace("/", "\\")) == exact or name.count("/") < 2
    db.close()
