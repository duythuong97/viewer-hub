"""Addons reading each other: compatibility at install / remove / start, and the call through the Hub
(docs/addons.md §3.2)."""
from __future__ import annotations

import copy
import json
import threading
from pathlib import Path

import pytest

from tests.addon_kit import EXAMPLE, install, zip_folder
from tests.test_core import _client_with
from viewer_hub.addons import deps
from viewer_hub.addons import install as installer
from viewer_hub.addons.manifest import parse

H = {"X-Viewer-Hub": "1"}
LOG_PARAMS = {"type": "object", "required": ["repo"], "properties": {
    "repo": {"type": "string"}, "limit": {"type": "integer", "default": 2, "minimum": 1, "maximum": 50}}}
LOG_RETURNS = {"type": "object", "required": ["items"], "properties": {"items": {"type": "array", "items": {
    "type": "object", "required": ["rev", "author"], "properties": {"rev": {"type": "integer"}, "author": {"type": "string"},
                                                                   "msg": {"type": "string"}}}}}}
LOG = {"name": "prov_log", "description": "Lịch sử", "params": LOG_PARAMS, "returns": LOG_RETURNS,
       "example": {"items": [{"rev": 1, "author": "an"}]}}


def _base(addon_id: str, version: str = "1.0.0", **fields) -> dict:
    data = json.loads((EXAMPLE / "addon.json").read_text(encoding="utf-8"))
    data.update(schemaVersion=3, id=addon_id, name=addon_id.title(), version=version, mcp=None, **fields)
    return data


def _provider(version: str = "1.0.0", exports=None) -> dict:
    return _base("prov", version, exports=[LOG] if exports is None else exports)


def _consumer(version: str = "1.0.0", *, range_="^1.0.0", optional=False, built: str | None = "1.0.0",
              exports=("prov_log",)) -> dict:
    use = {"version": range_, "exports": list(exports), "optional": optional}
    if built:
        use["built"] = {"version": built, "contract": {"prov_log": {"params": LOG_PARAMS, "returns": LOG_RETURNS}}}
    return _base("cons", version, uses={"prov": use})


def _addons(*manifests) -> dict:
    found = [parse(m) for m in manifests]
    return {a.id: a for a in found}


def _codes(issues) -> list[tuple[str, str]]:
    return [(i.level, i.code) for i in issues]


def _breaking_log() -> dict:
    changed = copy.deepcopy(LOG)
    del changed["returns"]["properties"]["items"]["items"]["properties"]["author"]
    changed["returns"]["properties"]["items"]["items"]["required"] = ["rev"]
    changed["example"] = {"items": [{"rev": 1}]}
    return changed


# ── deps.py ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_user_side_checks():
    cons = parse(_consumer())
    assert _codes(deps.check_install(cons, {})) == [("warn", "missing")]
    assert _codes(deps.check_install(parse(_consumer(optional=True)), {})) == [("note", "missing")]
    assert deps.check_install(cons, _addons(_provider())) == []
    assert _codes(deps.check_install(cons, _addons(_provider("2.0.0")))) == [("warn", "version")]
    assert _codes(deps.check_install(cons, _addons(_provider(exports=[])))) == [("warn", "export")]
    issues = deps.check_install(cons, _addons(_provider("1.1.0", [_breaking_log()])))
    assert _codes(issues) == [("warn", "contract")]
    assert "prov_log.returns.items[].author" in issues[0].message
    premium = _addons({**_provider(), "premium": "gold"})
    assert _codes(deps.check_install(cons, premium, lambda _p: False)) == [("note", "premium")]
    # no snapshot: version and names only
    assert deps.check_install(parse(_consumer(built=None)), _addons(_provider("1.1.0", [_breaking_log()]))) == []


def test_provider_side_checks():
    installed = _addons(_provider(), _consumer())
    assert deps.check_install(parse(_provider("1.1.0")), installed) == []
    blocked = deps.check_install(parse(_provider("1.1.0", [_breaking_log()])), installed)
    assert ("block", "breaking") in _codes(blocked) and "Tăng version lên 2.0.0" in blocked[0].message
    major = deps.check_install(parse(_provider("2.0.0", [_breaking_log()])), installed)
    assert _codes(major) == [("warn", "dependent"), ("warn", "dependent")]  # version range and contract
    assert {i.addon for i in major} == {"cons"} and all(i.key for i in major)
    down = deps.check_install(parse(_provider("0.9.0")), installed)
    assert ("warn", "downgrade") in _codes(down) and ("warn", "dependent") in _codes(down)
    # an optional use that would break is still the admin's choice
    optional = _addons(_provider(), _consumer(optional=True))
    assert _codes(deps.check_install(parse(_provider("2.0.0")), optional)) == [("warn", "dependent")]
    # dropping an export nobody uses is only a note
    with_two = _addons(_provider(exports=[LOG, {**LOG, "name": "prov_old"}]), _consumer())
    assert _codes(deps.check_install(parse(_provider("2.0.0")), with_two)) == [("warn", "dependent"), ("note", "unused")]
    # already broken before this zip: not reported again
    broken_before = _addons(_provider("2.0.0"), _consumer())
    assert deps.check_install(parse(_provider("2.1.0")), broken_before) == []


def test_cycles_are_refused():
    a = _base("aa", uses={"bb": {"version": "*", "exports": ["x"]}})
    b = _base("bb", uses={"cc": {"version": "*", "exports": ["x"], "optional": True}})
    c = _base("cc", uses={"aa": {"version": "*", "exports": ["x"]}})
    issues = deps.check_install(parse(c), _addons(a, b))
    assert ("block", "cycle") in _codes(issues)
    assert "cc → aa → bb → cc" in next(i.message for i in issues if i.code == "cycle")


def test_remove_statuses_order_and_calls():
    installed = _addons(_provider(), _consumer(), {**_consumer(optional=True), "id": "opt"})
    assert _codes(deps.check_remove("prov", installed)) == [("warn", "dependent"), ("note", "dependent")]
    status = deps.statuses(installed)
    assert status["cons"].state == "ok" and status["prov"].used_by[0]["id"] == "cons"
    gone = deps.statuses({k: v for k, v in installed.items() if k != "prov"})
    assert gone["cons"].state == "broken" and gone["opt"].state == "degraded"
    assert [a.id for a in deps.install_order(installed.values())] == ["prov", "cons", "opt"]
    cons = installed["cons"]
    assert deps.call_problem(cons, "prov", "prov_log", installed, lambda _p: True) is None
    assert deps.call_problem(cons, "prov", "prov_other", installed, lambda _p: True)[0] == "export_unknown"
    assert deps.call_problem(cons, "other", "x", installed, lambda _p: True)[0] == "export_unknown"
    newer = _addons(_provider("2.0.0"))
    assert deps.call_problem(cons, "prov", "prov_log", newer, lambda _p: True)[0] == "dependency_incompatible"
    assert deps.call_problem(cons, "prov", "prov_log", {}, lambda _p: True)[0] == "dependency_missing"
    off = deps.statuses(installed, disabled={"prov"})
    assert off["cons"].state == "broken" and off["opt"].state == "degraded"
    assert deps.call_problem(cons, "prov", "prov_log", installed, lambda _p: True, {"prov"})[0] == "dependency_disabled"
    changed = _addons(_provider("1.2.0", [_breaking_log()]))
    assert deps.call_problem(cons, "prov", "prov_log", changed, lambda _p: True)[0] == "dependency_incompatible"
    locked = _addons({**_provider(), "premium": "gold"})
    assert deps.call_problem(cons, "prov", "prov_log", locked, lambda _p: False)[0] == "dependency_missing"


# ── the addons used in the tests below ─────────────────────────────────────────────────────────────────────────

PROVIDER = '''
from viewer_hub.addons.sdk import Addon, ApiError

addon = Addon("prov")


@addon.export("prov_log")
def prov_log(params):
    if params["repo"] == "missing":
        raise ApiError("no_repo", "Không có repo " + params["repo"], 404)
    if params["repo"] == "bad":
        return {"items": [{"rev": "x"}]}
    if params["repo"] == "deeper":
        return addon.call("cons", "cons_echo", {})  # cons → prov → cons: the depth limit ends it
    return {"items": [{"rev": i + 1, "author": "an"} for i in range(params["limit"])], "extra": True}


if __name__ == "__main__":
    addon.run()
'''
CONSUMER = '''
from viewer_hub.addons.sdk import Addon, CallError

addon = Addon("cons")


@addon.get("/read/<repo>")
def read(request):
    params = {"repo": request.params["repo"]}
    if request.query.get("limit"):
        params["limit"] = int(request.query["limit"])
    if request.query.get("junk"):
        params["junk"] = 1
    try:
        return {"ok": True, "reply": addon.call(request.query.get("addon", "prov"), request.query.get("export", "prov_log"), params)}
    except CallError as exc:
        return {"ok": False, "code": exc.code, "message": exc.message}


@addon.export("cons_echo")
def cons_echo(params):
    return addon.call("prov", "prov_log", {"repo": "deeper"})


if __name__ == "__main__":
    addon.run()
'''


def _project(tmp_path: Path, manifest: dict, main: str) -> Path:
    folder = tmp_path / "src" / f"{manifest['id']}-{manifest['version']}" / manifest["id"]
    (folder / "app").mkdir(parents=True)
    (folder / "addon.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (folder / "app" / "main.py").write_text(main, encoding="utf-8")
    label = manifest["menu"]["label"]
    (folder / "GUIDE.md").write_text(f"## {label}\n\nThử.\n", encoding="utf-8")
    return zip_folder(folder, tmp_path / f"{manifest['id']}-{manifest['version']}.zip")


def _upload(client, zip_path: Path, accept=None):
    data = {"file": (zip_path.open("rb"), zip_path.name)}
    if accept is not None:
        data["accept"] = json.dumps(accept)
    return client.post("/api/addons", data=data, headers=H, content_type="multipart/form-data")


@pytest.fixture()
def stop_addons():
    from viewer_hub.addons import runner

    yield
    runner._stop_all()


# ── install / remove through the Settings page ────────────────────────────────────────────────────────────────

def test_install_asks_before_breaking_other_addons(paths, tmp_path, stop_addons):
    client = _client_with(paths)
    cons = _upload(client, _project(tmp_path, _consumer(), CONSUMER))
    assert cons.status_code == 409
    review = cons.get_json()["review"]
    assert review["token"] and not review["blocked"] and [i["code"] for i in review["issues"]] == ["missing"]
    assert not (paths.addons / "cons").exists()
    keys = [i["key"] for i in review["issues"] if i["level"] == "warn"]
    assert client.post(f"/api/addons/staged/{review['token']}", json={"accept": []}, headers=H).status_code == 409
    done = client.post(f"/api/addons/staged/{review['token']}", json={"accept": keys}, headers=H)
    assert done.status_code == 200, done.get_json()
    assert client.post(f"/api/addons/staged/{review['token']}", json={"accept": keys}, headers=H).status_code == 400
    listed = {a["id"]: a for a in client.get("/api/addons").get_json()["addons"]}
    assert listed["cons"]["deps"]["state"] == "broken"

    assert _upload(client, _project(tmp_path, _provider(), PROVIDER)).status_code == 200
    listed = {a["id"]: a for a in client.get("/api/addons").get_json()["addons"]}
    assert listed["cons"]["deps"]["state"] == "ok"
    assert listed["prov"]["deps"]["usedBy"] == [{"id": "cons", "name": "Cons", "exports": ["prov_log"]}]
    assert listed["prov"]["exports"] == [{"name": "prov_log", "description": "Lịch sử"}]

    # a breaking change without a new major: never installable
    blocked = _upload(client, _project(tmp_path, _provider("1.1.0", [_breaking_log()]), PROVIDER))
    assert blocked.status_code == 409 and blocked.get_json()["review"]["blocked"]
    assert blocked.get_json()["review"]["token"] == ""
    # with a new major: the admin decides
    major = _upload(client, _project(tmp_path, _provider("2.0.0", [_breaking_log()]), PROVIDER))
    assert major.status_code == 409
    review = major.get_json()["review"]
    assert {i["addon"] for i in review["issues"]} == {"cons"}
    assert parse(json.loads((paths.addons / "prov" / "addon.json").read_text()), hub_version="9.9.9").version == "1.0.0"

    # removing an addon others use asks too
    removed = client.delete("/api/addons/prov", headers=H)
    assert removed.status_code == 409 and removed.get_json()["review"]["issues"][0]["addon"] == "cons"
    keys = [i["key"] for i in removed.get_json()["review"]["issues"]]
    assert client.delete("/api/addons/prov", json={"accept": keys}, headers=H).status_code == 200
    assert not (paths.addons / "prov").exists()


def test_cli_install_refuses_warnings(paths, tmp_path):
    with pytest.raises(installer.NeedsReview) as caught:
        installer.install_zip(paths, _project(tmp_path, _consumer(), CONSUMER))
    assert not caught.value.blocked and caught.value.stopping[0].code == "missing"
    result = installer.install_zip(paths, tmp_path / "cons-1.0.0.zip", accept=True)
    assert [i.code for i in result.issues] == ["missing"]


def test_default_addons_install_in_order_and_hold_breaking_updates(paths, tmp_path):
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    # "cons" sorts before "prov" by name: the provider still goes first
    for manifest, main in ((_consumer(), CONSUMER), (_provider(), PROVIDER)):
        zip_path = _project(tmp_path, manifest, main)
        zip_path.rename(bundled / zip_path.name)
    assert installer.install_bundled(paths, bundled) == ["Prov 1.0.0", "Cons 1.0.0"]
    (bundled / "prov-1.0.0.zip").unlink()
    newer = _project(tmp_path, _provider("2.0.0"), PROVIDER)
    newer.rename(bundled / newer.name)
    assert installer.install_bundled(paths, bundled) == []
    held = installer.held_updates(paths)
    assert "prov" in held and "Cons" in held["prov"]
    assert installer.installed_addons(paths)["prov"].version == "1.0.0"
    listed = _client_with(paths).get("/api/addons").get_json()
    assert listed["held"][0]["id"] == "prov"


# ── the call through the Hub ──────────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def served(paths, tmp_path, stop_addons):
    """The Hub on a real port (the addon process calls it back), with prov and cons installed."""
    from werkzeug.serving import make_server

    installer.install_zip(paths, _project(tmp_path, _provider(), PROVIDER))
    installer.install_zip(paths, _project(tmp_path, _consumer(), CONSUMER))
    client = _client_with(paths)
    app = client.application
    server = make_server("127.0.0.1", 0, app, threaded=True)
    app.extensions["hub"].port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield client
    server.shutdown()


def test_one_addon_reads_another(served):
    client = served
    read = lambda repo, **query: client.get(f"/x/cons/api/read/{repo}", query_string=query).get_json()  # noqa: E731
    reply = read("core")
    assert reply == {"ok": True, "reply": {"items": [{"rev": 1, "author": "an"}, {"rev": 2, "author": "an"}],
                                           "extra": True}}  # default limit filled in by the Hub
    assert len(read("core", limit=3)["reply"]["items"]) == 3
    assert read("core", limit=99)["code"] == "bad_params"           # maximum 50
    assert read("core", junk=1)["code"] == "bad_params"             # a field the contract does not have
    assert read("missing") == {"ok": False, "code": "no_repo", "message": "Không có repo missing"}
    assert read("bad")["code"] == "bad_reply"                        # the provider broke its own contract
    assert read("core", export="prov_other")["code"] == "export_unknown"  # not in cons' uses
    assert read("core", addon="cons", export="cons_echo")["code"] == "export_unknown"
    assert read("deeper")["code"] in ("call_depth", "export_unknown")  # prov may not call cons (no uses)


def test_calls_need_the_addon_token(served):
    client = served
    assert client.post("/api/addons/call/prov/prov_log", json={"repo": "x"}).get_json()["error"]["code"] == "forbidden"
    assert client.post("/api/addons/call/prov/prov_log", json={}, headers={"X-Viewer-Hub-Caller": "guess"}
                       ).status_code == 403
    assert client.post("/api/addons/call/prov/prov_log", json={}, headers=H).status_code == 403  # a page
    client.get("/x/cons/api/read/core")  # cons runs: its own token works, but only without a page Origin
    hub = client.application.extensions["hub"]
    token = hub.addons.runner(hub.addons.get("cons")).caller_token
    ok = client.post("/api/addons/call/prov/prov_log", json={"repo": "core"}, headers={"X-Viewer-Hub-Caller": token})
    assert ok.status_code == 200 and len(ok.get_json()["items"]) == 2
    assert client.post("/api/addons/call/prov/prov_log", json={"repo": "core"},
                       headers={"X-Viewer-Hub-Caller": token, "Origin": "http://127.0.0.1"}).status_code == 403
    deep = client.post("/api/addons/call/prov/prov_log", json={"repo": "core"},
                       headers={"X-Viewer-Hub-Caller": token, "X-Viewer-Hub-Depth": "3"})
    assert deep.status_code == 508 and deep.get_json()["error"]["code"] == "call_depth"


def test_sdk_call_without_a_hub_uses_the_contract_example(tmp_path, monkeypatch):
    from viewer_hub.addons.sdk import Addon, CallError

    folder = tmp_path / "cons"
    (folder / ".sdk" / "addons").mkdir(parents=True)
    (folder / "addon.json").write_text(json.dumps(_consumer()), encoding="utf-8")
    contract = {"id": "prov", "name": "Prov", "version": "1.0.0", "exports": [LOG]}
    (folder / ".sdk" / "addons" / "prov.json").write_text(json.dumps(contract), encoding="utf-8")
    for key in ("VIEWER_HUB_URL", "VIEWER_HUB_CALLER_TOKEN", "VIEWER_HUB_FAKE_EXPORTS"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("VIEWER_HUB_ADDON_FOLDER", str(folder))
    addon = Addon("cons")
    assert addon.call("prov", "prov_log", {"repo": "x"}) == {"items": [{"rev": 1, "author": "an"}]}
    with pytest.raises(CallError, match="bad_params"):
        addon.call("prov", "prov_log", {})
    with pytest.raises(CallError, match="export_unknown"):
        addon.call("prov", "prov_other", {})
    addon.fake("prov", "prov_log", {"items": []})
    assert addon.call("prov", "prov_log", {"repo": "x"}) == {"items": []}
    addon.fake("prov", "prov_log", CallError("dependency_missing", "chưa cài"))
    with pytest.raises(CallError, match="dependency_missing"):
        addon.call("prov", "prov_log", {"repo": "x"})
    # an export declared without a handler stops the addon at start
    (folder / "addon.json").write_text(json.dumps(_provider()), encoding="utf-8")
    assert Addon("prov").missing_exports() == ["prov_log"]
