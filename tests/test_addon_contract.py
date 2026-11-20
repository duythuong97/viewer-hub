"""exports / uses of addon.json: semver ranges, the schema subset, compare (docs/plans/addon-interop.md §2, §4.4)."""
from __future__ import annotations

import copy
import json

import pytest

from tests.addon_kit import EXAMPLE
from viewer_hub.addons import contract, semver
from viewer_hub.addons.contract import IN, OUT, ContractError, check_schema, compare, validate
from viewer_hub.addons.manifest import AddonError, OutdatedAddon, parse


# ── semver ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_version_order():
    order = ["1.0.0-alpha", "1.0.0-alpha.1", "1.0.0-alpha.beta", "1.0.0-beta.2", "1.0.0-beta.11", "1.0.0-rc.1",
             "1.0.0", "1.0.0.1", "1.0.1", "1.10.0", "2.0.0"]
    parsed = [semver.parse(v) for v in order]
    assert all(a < b for a, b in zip(parsed, parsed[1:]))
    assert str(semver.parse("1.2.3-beta.1")) == "1.2.3-beta.1"
    assert semver.parse("1.2.3.beta").pre == ("beta",)  # manifest.VERSION_RE allows a dot before it
    for bad in ("1.2", "v1.2.3", "1.2.3-", "1.2.3-a..b", "", None):
        with pytest.raises(semver.VersionError):
            semver.parse(bad)


@pytest.mark.parametrize("range_text, yes, no", [
    ("^1.2.3", ["1.2.3", "1.9.0", "1.2.3.4"], ["1.2.2", "2.0.0", "2.0.0-beta", "1.3.0-beta"]),
    ("^0.2.3", ["0.2.3", "0.2.9"], ["0.3.0", "0.2.2"]),
    ("^0.0.3", ["0.0.3"], ["0.0.4"]),
    ("^1.2", ["1.2.0", "1.99.0"], ["2.0.0"]),
    ("^1", ["1.0.0", "1.5.5"], ["2.0.0", "0.9.0"]),
    ("~1.2.3", ["1.2.3", "1.2.9"], ["1.3.0", "1.2.2"]),
    ("~1", ["1.9.9"], ["2.0.0"]),
    (">=1.2.0 <2", ["1.2.0", "1.9.9"], ["2.0.0", "1.1.9"]),
    (">= 1.2.0 < 2", ["1.5.0"], ["2.0.0"]),
    ("1.2.3", ["1.2.3"], ["1.2.4", "1.2.3.1"]),
    ("1.2", ["1.2.0", "1.2.7"], ["1.3.0"]),
    ("^1.0.0 || ^3.0.0", ["1.1.0", "3.2.0"], ["2.0.0"]),
    ("*", ["0.0.1", "9.9.9"], ["1.0.0-beta"]),
    (">=1.3.0-rc.0 <2", ["1.3.0-rc.1", "1.3.0", "1.9.0"], ["1.4.0-rc.1", "1.2.0"]),
])
def test_ranges(range_text, yes, no):
    for version in yes:
        assert semver.satisfies(version, range_text), (version, range_text)
    for version in no:
        assert not semver.satisfies(version, range_text), (version, range_text)


@pytest.mark.parametrize("bad", ["", " ", "^", "^x", ">=1.2 ||", "1.2-beta", "latest", "a" * 300, 12])
def test_bad_ranges(bad):
    with pytest.raises(semver.VersionError):
        semver.parse_range(bad)


# ── schema ─────────────────────────────────────────────────────────────────────────────────────────────────────

ITEMS = {"type": "object", "required": ["items"], "properties": {
    "items": {"type": "array", "items": {"type": "object", "required": ["rev", "author"], "properties": {
        "rev": {"type": "integer", "minimum": 1}, "author": {"type": "string"}, "msg": {"type": "string"},
        "kind": {"type": "string", "enum": ["add", "edit"]}}}},
    "total": {"type": "integer"}}}
PARAMS = {"type": "object", "required": ["q"], "properties": {
    "q": {"type": "string", "minLength": 1, "maxLength": 200},
    "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 500},
    "order": {"type": "string", "enum": ["new", "old"], "default": "new"}}}


def test_schema_subset_is_checked():
    check_schema(ITEMS, "x")
    check_schema(PARAMS, "x")
    bad = [
        {"type": "object", "additionalProperties": False},       # outside the subset
        {"type": "thing"}, {}, [], {"type": "string", "items": {"type": "string"}},  # items: arrays only
        {"type": "array"},                                         # no items
        {"type": "object", "required": ["a"]},                     # required, not declared
        {"type": "object", "properties": {"bad-name": {"type": "string"}}},
        {"type": "object", "required": ["a", "a"], "properties": {"a": {"type": "string"}}},
        {"type": "string", "enum": []}, {"type": "string", "enum": [1]}, {"type": "object", "enum": [{}]},
        {"type": "string", "minLength": -1}, {"type": "string", "minLength": 3, "maxLength": 2},
        {"type": "integer", "maximum": "9"}, {"type": "string", "maximum": 3},
        {"type": "integer", "default": "x"}, {"type": "string", "description": 3},
    ]
    for schema in bad:
        with pytest.raises(ContractError):
            check_schema(schema, "x")
    deep = {"type": "string"}
    for _ in range(contract.MAX_DEPTH + 1):
        deep = {"type": "array", "items": deep}
    with pytest.raises(ContractError, match="sâu"):
        check_schema(deep, "x")
    wide = {"type": "object", "properties": {f"f{i}": {"type": "string"} for i in range(contract.MAX_NODES)}}
    with pytest.raises(ContractError, match="lớn"):
        check_schema(wide, "x")


def test_validate():
    good = {"items": [{"rev": 3, "author": "an", "kind": "add", "extra": 1}], "total": 1}
    assert validate(ITEMS, good, extra=True) == []
    assert validate(ITEMS, good, extra=False) == ["giá trị.items[0].extra: trường không có trong schema"]
    problems = validate(ITEMS, {"items": [{"rev": 0, "author": 5, "kind": "drop"}], "total": True}, extra=True)
    assert problems == ["giá trị.items[0].rev: nhỏ hơn 1", "giá trị.items[0].author: cần string, nhận int",
                        "giá trị.items[0].kind: 'drop' không thuộc ['add', 'edit']", "giá trị.total: cần integer, nhận bool"]
    assert validate(PARAMS, {}, extra=False) == ["giá trị.q: thiếu (bắt buộc)"]
    assert validate({"type": "number"}, 2, extra=False) == []   # an integer is a number
    assert contract.with_defaults(PARAMS, {"q": "x", "limit": 5}) == {"q": "x", "limit": 5, "order": "new"}


# ── compare (plan §4.4) ────────────────────────────────────────────────────────────────────────────────────────

def _edit(schema: dict, change) -> dict:
    new = copy.deepcopy(schema)
    change(new)
    return new


def _breaks(old: dict, new: dict, direction: str) -> list[str]:
    return [str(c) for c in compare(old, new, direction) if c.breaking]


def _props(schema):
    return schema["properties"]


PARAM_CASES = [  # (what, change, breaking?)
    ("new required param", lambda s: (_props(s).update(repo={"type": "string"}), s["required"].append("repo")), True),
    ("param removed", lambda s: _props(s).pop("limit"), True),
    ("type changed", lambda s: _props(s).update(q={"type": "integer"}), True),
    ("enum narrowed", lambda s: _props(s)["order"].update(enum=["new"]), True),
    ("enum added", lambda s: _props(s)["q"].update(enum=["a"]), True),
    ("maxLength lowered", lambda s: _props(s)["q"].update(maxLength=10), True),
    ("minimum raised", lambda s: _props(s)["limit"].update(minimum=10), True),
    ("optional to required", lambda s: s["required"].append("limit"), True),
    ("new optional param", lambda s: _props(s).update(author={"type": "string"}), False),
    ("enum widened", lambda s: _props(s)["order"]["enum"].append("random"), False),
    ("enum removed", lambda s: _props(s)["order"].pop("enum"), False),
    ("required to optional", lambda s: s["required"].clear(), False),
    ("default changed", lambda s: _props(s)["limit"].update(default=20), False),
    ("description changed", lambda s: _props(s)["q"].update(description="từ khoá"), False),
    ("maximum raised", lambda s: _props(s)["limit"].update(maximum=1000), False),
    ("bound removed", lambda s: _props(s)["q"].pop("maxLength"), False),
    ("integer to number", lambda s: _props(s)["limit"].update(type="number"), False),
]
ITEM = lambda s: s["properties"]["items"]["items"]  # noqa: E731
REPLY_CASES = [
    ("required field removed", lambda s: (_props(ITEM(s)).pop("author"), ITEM(s)["required"].remove("author")), True),
    ("required to optional", lambda s: ITEM(s)["required"].remove("author"), True),
    ("type changed", lambda s: _props(ITEM(s)).update(rev={"type": "string"}), True),
    ("enum widened", lambda s: _props(ITEM(s))["kind"]["enum"].append("delete"), True),
    ("enum removed", lambda s: _props(ITEM(s))["kind"].pop("enum"), True),
    ("minimum lowered", lambda s: _props(ITEM(s))["rev"].update(minimum=0), True),
    ("number to integer is fine", lambda s: _props(s)["total"].update(type="integer"), False),
    ("integer to number", lambda s: _props(s)["total"].update(type="number"), True),
    ("field added", lambda s: _props(ITEM(s)).update(date={"type": "string"}), False),
    ("optional field removed", lambda s: _props(ITEM(s)).pop("msg"), False),
    ("optional to required", lambda s: ITEM(s)["required"].append("msg"), False),
    ("enum narrowed", lambda s: _props(ITEM(s))["kind"].update(enum=["add"]), False),
    ("enum added", lambda s: _props(ITEM(s))["msg"].update(enum=["x"]), False),
    ("maximum added", lambda s: _props(ITEM(s))["rev"].update(maximum=10), False),
]


@pytest.mark.parametrize("what, change, breaking", PARAM_CASES, ids=[c[0] for c in PARAM_CASES])
def test_params_compare(what, change, breaking):
    new = _edit(PARAMS, change)
    check_schema(new, "x")
    changes = compare(PARAMS, new, IN)
    assert changes or not breaking, what  # a new description is no change at all
    assert any(c.breaking for c in changes) is breaking, [str(c) for c in changes]


@pytest.mark.parametrize("what, change, breaking", REPLY_CASES, ids=[c[0] for c in REPLY_CASES])
def test_returns_compare(what, change, breaking):
    schema = _edit(ITEMS, lambda s: _props(s)["total"].update(type="number")) if what.startswith("number") else ITEMS
    new = _edit(schema, change)
    check_schema(new, "x")
    changes = compare(schema, new, OUT)
    assert changes, what
    assert any(c.breaking for c in changes) is breaking, [str(c) for c in changes]


def test_compare_names_the_path():
    new = _edit(ITEMS, lambda s: _props(ITEM(s)).update(rev={"type": "string"}))
    assert _breaks(ITEMS, new, OUT) == ["returns.items[].rev: đổi kiểu integer → string"]
    assert compare(PARAMS, PARAMS, IN) == []


# ── exports / uses in addon.json ───────────────────────────────────────────────────────────────────────────────

EXPORT = {"name": "svn_log_search", "description": "Tìm commit", "params": PARAMS, "returns": ITEMS,
          "example": {"items": [{"rev": 1, "author": "an"}]}, "since": "0.1.0"}


def _manifest(**changes) -> dict:
    data = json.loads((EXAMPLE / "addon.json").read_text(encoding="utf-8"))
    data.update({"schemaVersion": 3}, **changes)
    return data


def _use(**changes) -> dict:
    entry = {"version": "^1.2.0", "exports": ["svn_log_search"],
             "built": {"version": "1.3.0", "contract": {"svn_log_search": {"params": PARAMS, "returns": ITEMS}}}}
    entry.update(changes)
    return entry


def test_exports_and_uses_are_read():
    addon = parse(_manifest(exports=[EXPORT], uses={"svn": _use(optional=True)}, requires={"hub": ">=0.1.0"}),
                  hub_version="0.2.0")
    export, = addon.exports
    assert export.name == "svn_log_search" and export.schemas() == {"params": PARAMS, "returns": ITEMS}
    use, = addon.uses
    assert use.id == "svn" and use.optional and use.exports == ("svn_log_search",) and use.built_version == "1.3.0"
    assert use.range.satisfied_by("1.9.0") and not use.range.satisfied_by("2.0.0")
    assert addon.requires_hub == ">=0.1.0"
    plain = parse(_manifest())  # an addon without them
    assert plain.exports == () and plain.uses == () and plain.requires_hub == ""
    # built is optional (checked by version and names only, plan §2.2)
    assert parse(_manifest(uses={"svn": {"version": "^1", "exports": ["svn_log_search"]}})).uses[0].built == {}


@pytest.mark.parametrize("changes, message", [
    ({"schemaVersion": 2, "exports": [EXPORT]}, "chỉ đọc v3"),  # the old layout (flat) is not read any more
    ({"requires": {"hub": ">=9.0.0"}}, "cập nhật Viewer Hub"),
    ({"requires": {"hub": "latest"}}, "requires.hub"),
    ({"requires": {"python": "3"}}, "requires"),
    ({"exports": [EXPORT, EXPORT]}, "hai lần"),
    ({"exports": [{**EXPORT, "name": "Bad"}]}, "name"),
    ({"exports": [{**EXPORT, "example": {"items": [{"rev": 1}]}}]}, "example"),
    ({"exports": [{**EXPORT, "example": {"items": [], "more": 1}}]}, "example"),
    ({"exports": [{k: v for k, v in EXPORT.items() if k != "example"}]}, "example"),
    ({"exports": [{**EXPORT, "returns": {"type": "array", "items": {"type": "string"}}}]}, "object"),
    ({"exports": [{**EXPORT, "params": {"type": "object", "oneOf": []}}]}, "không hỗ trợ"),
    ({"exports": [{**EXPORT, "since": "9.0.0"}]}, "mới hơn"),
    ({"exports": [{**EXPORT, "handler": "x"}]}, "không hỗ trợ"),
    ({"exports": [{**EXPORT, "description": ""}]}, "description"),
    ({"uses": {"example": _use()}}, "chính nó"),
    ({"uses": {"Bad": _use()}}, "id addon"),
    ({"uses": {"svn": _use(version="latest")}}, "version"),
    ({"uses": {"svn": _use(exports=[])}}, "exports"),
    ({"uses": {"svn": _use(exports=["a", "a"])}}, "exports"),
    ({"uses": {"svn": _use(optional="yes")}}, "optional"),
    ({"uses": {"svn": _use(token="x")}}, "chỉ có"),
    ({"uses": {"svn": _use(built={"version": "2.0.0", "contract": {}})}}, "ngoài khoảng"),
    ({"uses": {"svn": _use(built={"version": "1.3.0", "contract": {}})}}, "thiếu svn_log_search"),
    ({"uses": {"svn": _use(built={"version": "1.3.0"})}}, "built"),
    ({"uses": {"svn": _use(built={"version": "1.3.0", "contract": {"svn_log_search": {"params": PARAMS}}})}},
     "params và returns"),
    ({"uses": ["svn"]}, "uses"),
])
def test_bad_exports_and_uses(changes, message):
    with pytest.raises(AddonError, match=message):
        parse(_manifest(**changes), hub_version="0.2.0")


def test_schema_version_message_says_which_side_is_old():
    with pytest.raises(OutdatedAddon, match="addon cũ"):
        parse(_manifest(schemaVersion=1))
    with pytest.raises(AddonError, match="cập nhật Viewer Hub") as newer:
        parse(_manifest(schemaVersion=4))
    assert not isinstance(newer.value, OutdatedAddon)


def test_compare_exports_between_versions():
    old = parse(_manifest(exports=[EXPORT, {**EXPORT, "name": "svn_old"}])).exports
    new_params = _edit(PARAMS, lambda s: s["required"].append("limit"))
    new = parse(_manifest(exports=[{**EXPORT, "params": new_params}, {**EXPORT, "name": "svn_new"}])).exports
    changes = contract.compare_exports(old, new)
    assert [str(c) for c in contract.breaking(changes)] == ["svn_log_search.params.limit: thành bắt buộc",
                                                            "svn_old: export không còn"]
    assert "svn_new: export mới" in [str(c) for c in changes]
