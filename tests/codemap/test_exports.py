"""Builtin modules as export providers (addons/builtin.py) and what Code map exports (codemap/exports.py), the feature
"Dữ liệu" tab (business/data.py) and the move of the whole-database ERD to the erd addon (codemap/erd_addon.py)."""
from __future__ import annotations

import json
from urllib.parse import quote

import pytest

import erd_fixture
from test_erd import MERMAID_SHIPMENT, _install
from tests.addon_kit import install as install_addon
from viewer_hub import __version__
from viewer_hub.addons import builtin, deps, sdk_kit
from viewer_hub.addons.manifest import parse

needs_demo = pytest.mark.skipif(not (erd_fixture.DEMO / "codemap.sqlite").is_file(),
                                reason=f"code-map demo output not found at {erd_fixture.DEMO}")
CALLER = "X-Viewer-Hub-Caller"


def _consumer(range_: str = f">={__version__}", exports=("erd_model", "db_objects", "table_usage"), built=None) -> dict:
    from tests.addon_kit import EXAMPLE

    data = json.loads((EXAMPLE / "addon.json").read_text(encoding="utf-8"))
    use = {"version": range_, "exports": list(exports)}
    if built is not None:
        use["built"] = built
    data.update(schemaVersion=3, id="erdtest", name="ERD test", version="1.0.0", mcp=None, uses={"codemap": use})
    return data


# ── the provider ───────────────────────────────────────────────────────────────────────────────────────────────

def test_codemap_is_a_builtin_provider():
    provider = builtin.providers()["codemap"]
    assert provider.version == __version__ and provider.builtin and provider.premium is None and provider.uses == ()
    assert [e.name for e in provider.exports] == ["erd_model", "db_objects", "table_usage"]
    assert set(builtin.with_builtin({"x": "addon"})) == {"codemap", "x"}


def test_deps_treat_a_builtin_provider_as_installed():
    cons = parse(_consumer())
    assert deps.check_install(cons, builtin.with_builtin({})) == []
    assert [(i.level, i.code) for i in deps.check_install(parse(_consumer(">=99.0.0")), builtin.with_builtin({}))] == \
        [("warn", "version")]
    assert [(i.level, i.code) for i in deps.check_install(parse(_consumer(exports=("nope",))), builtin.with_builtin({}))] == \
        [("warn", "export")]
    states = deps.statuses(builtin.with_builtin({"erdtest": cons}))
    assert states["erdtest"].state == deps.OK and states["codemap"].used_by[0]["id"] == "erdtest"
    # a contract the consumer was built against, changed in a breaking way: the same rules as for an addon
    erd_model = next(e for e in builtin.providers()["codemap"].exports if e.name == "erd_model")
    old = {"params": erd_model.params, "returns": {**erd_model.returns, "required": [*erd_model.returns["required"], "gone"],
                                                   "properties": {**erd_model.returns["properties"], "gone": {"type": "string"}}}}
    built = {"version": __version__, "contract": {"erd_model": old}}
    issues = deps.check_install(parse(_consumer(exports=("erd_model",), built=built)), builtin.with_builtin({}))
    assert [(i.level, i.code) for i in issues] == [("warn", "contract")]


def test_contracts_list_builtin_providers(client):
    body = client.get("/api/addons/contracts").get_json()
    codemap = next(item for item in body["addons"] if item["id"] == "codemap")
    assert codemap["builtin"] is True and codemap["version"] == __version__
    assert {e["name"] for e in codemap["exports"]} == {"erd_model", "db_objects", "table_usage"}
    text = sdk_kit.contract_markdown(codemap)
    assert f'">={__version__}"' in text and "mục có sẵn của Viewer Hub" in text
    files = sdk_kit.contract_files(body["addons"])
    assert ".sdk/addons/codemap.json" in files


# ── the call route ─────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def caller(app, monkeypatch):
    """A running addon that uses codemap: the call route sees it behind the token "t"."""
    addon = parse(_consumer())
    hub = app.extensions["hub"]
    monkeypatch.setattr(hub.addons, "caller", lambda token: addon if token == "t" else None)
    return addon


def _call(client, export, params=None, token="t"):
    return client.post(f"/api/addons/call/codemap/{export}", data=json.dumps(params or {}),
                       content_type="application/json", headers={CALLER: token}, base_url="http://127.0.0.1/")


def test_call_without_a_pack(client, caller):
    reply = _call(client, "db_objects")
    assert reply.status_code == 404 and reply.get_json()["error"]["code"] == "no_codemap_pack"
    assert _call(client, "db_objects", token="x").status_code == 403
    assert _call(client, "nope").get_json()["error"]["code"] == "export_unknown"


@needs_demo
def test_exports_read_the_pack(client, app, paths, caller, monkeypatch):
    from viewer_hub.addons import routes

    recorded = []
    monkeypatch.setattr(routes.monitor, "call", lambda server, export, *_args: recorded.append((server, export)))
    _install(app, paths)
    model = _call(client, "erd_model", {"table": "SHIPMENT", "format": "mermaid"})
    assert model.status_code == 200
    body = model.get_json()
    assert body["pack"] == "erd" and body["mode"] == "table" and body["text"] == MERMAID_SHIPMENT
    assert body["filename"] == "erd-DB1.APP.SHIPMENT.mmd"
    given = _call(client, "erd_model", {"tables": ["ORDERS", "ORDER_LINE"]}).get_json()
    assert given["mode"] == "tables" and "focus" not in given and given["outside_tables"] == 5
    assert _call(client, "erd_model", {"schema": "DB1.APP"}).get_json()["tables"]
    bad = _call(client, "erd_model", {"table": "NOPE"})
    assert bad.status_code == 404 and bad.get_json()["error"]["code"] == "unknown_table"
    assert _call(client, "erd_model", {"table": "ORDERS", "junk": 1}).get_json()["error"]["code"] == "bad_params"
    assert _call(client, "erd_model", {"table": "ORDERS", "pack": "zzz"}).get_json()["error"]["code"] == "unknown_pack"

    objects = _call(client, "db_objects", {"q": "出荷"}).get_json()
    assert {t["name"] for t in objects["tables"]} >= {"SHIPMENT", "SHIPMENT_AUDIT"}
    assert [p["id"] for p in objects["packs"]] == ["erd"] and [s["id"] for s in objects["schemas"]] == ["DB1.APP", "DB2.MASTER"]

    usage = _call(client, "table_usage", {"table": "ORDER_LINE"}).get_json()
    assert usage["table"]["id"] == "table:DB1:ORDER_LINE" and usage["ops"] == "CR"
    kinds = {(f["kind"], f["ops"]) for f in usage["features"]}
    assert ("plsql", "CR") in kinds and ("api", "R") in kinds
    assert all(f["url"].startswith("/code-map/?pack=erd#/feature/") for f in usage["features"])
    assert any(a["name"].endswith("CREATE_ORDER") and a["ops"] == "CR" for a in usage["accessors"])
    assert _call(client, "table_usage", {}).get_json()["error"]["code"] == "bad_params"  # table is required

    assert ("erdtest→codemap", "table_usage") in recorded  # every call goes to Giám sát, errors too
    assert ("erdtest→codemap", "erd_model") in recorded


# ── Code map: feature data tab, the old ERD route ──────────────────────────────────────────────────────────────

@needs_demo
def test_feature_data_tab(client, app, paths):
    _install(app, paths)
    feature = "feature:procedure:DB1:PKG_ORDER:CREATE_ORDER:NUMBER_VARCHAR2"
    body = client.get(f"/code-map/api/graph/business/features/{quote(feature, safe='')}/data").get_json()
    tables = {table["name"]: table for table in body["tables"]}
    assert tables["ORDER_LINE"]["ops"] == "CR" and tables["ORDER_HEADER"]["ops"] == "C"
    assert list(tables)[-1] == "ORDER_STAGING_LINES"  # read-only tables after the written ones
    assert body["rows"] and all(set(cell) <= set("CRUD") for row in body["rows"] for cell in row["cells"].values())
    erd = body["erd"]
    assert erd["mode"] == "tables" and {t["name"] for t in erd["tables"]} <= set(tables)
    assert {r["constraint"] for r in erd["relations"]} >= {"FK_RESERVATION_LINE"}
    assert body["erd_addon"] is None and not body["truncated"]
    job = client.get(f"/code-map/api/graph/business/features/{quote('feature:job-network:ORDER_DAILY', safe='')}/data").get_json()
    assert len(job["rows"]) >= 2 and any(row["kind"] == "flow" for row in job["rows"])
    assert client.get("/code-map/api/graph/business/features/nope/data").status_code == 404


@needs_demo
def test_erd_addon_link(client, app, paths):
    from viewer_hub.codemap import erd_addon

    _install(app, paths)
    hub = app.extensions["hub"]
    assert erd_addon.addon_path(hub) is None
    install_addon(paths, "erd", label="ERD")
    assert erd_addon.addon_path(hub) == "/x/erd"
    assert erd_addon.addon_url(hub, table="ORDERS", pack="erd") == "/x/erd/?table=ORDERS&pack=erd"
    assert client.get("/code-map/config").get_json()["config"]["erdAddon"] == "/x/erd"
    feature = quote("feature:job-network:ORDER_DAILY", safe="")
    assert client.get(f"/code-map/api/graph/business/features/{feature}/data").get_json()["erd_addon"] == "/x/erd"
    hub.addons.premium_ok = lambda _name: False
    (paths.addons / "erd" / "addon.json").write_text(json.dumps({**json.loads((paths.addons / "erd" / "addon.json").read_text(
        encoding="utf-8")), "premium": "erd"}), encoding="utf-8")
    hub.addons.refresh(force=True)
    assert erd_addon.addon_path(hub) is None  # a locked premium addon does not exist
