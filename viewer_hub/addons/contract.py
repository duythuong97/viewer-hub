"""What one addon lets other addons read (``exports``) and what it reads of them (``uses``): docs/plans/addon-interop.md.

Schemas are a small subset of JSON Schema that the Hub checks itself, small enough that ``compare`` can always say
whether a change breaks the addons that use it:

    {"type": "object" | "array" | "string" | "integer" | "number" | "boolean" | "null",
     "description": "…", "properties": {...}, "required": [...],   # object
     "items": {...},                                               # array
     "enum": [...], "default": …,
     "minLength" / "maxLength" (string), "minimum" / "maximum" (integer, number)}

Any other keyword is refused when addon.json is read. ``params`` and ``returns`` of an export are objects at the top,
so both can grow later without a break.

Direction matters when two versions of a schema are compared:
- ``params`` flow in (the caller sends, the addon accepts): the new schema must accept everything the old one did.
- ``returns`` flow out (the addon sends, the caller reads): the caller must still get everything it relied on.
  A caller ignores fields it does not know, so adding a field to a reply never breaks it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

TYPES = ("object", "array", "string", "integer", "number", "boolean", "null")
KEYWORDS = {"type", "description", "properties", "required", "items", "enum", "default",
            "minLength", "maxLength", "minimum", "maximum"}
NAME_RE = re.compile(r"^[a-z0-9_]{1,64}$")
FIELD_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
MAX_DEPTH = 6
MAX_NODES = 400          # schema nodes in one export (params + returns)
MAX_EXPORTS = 64
MAX_ENUM = 200
MAX_TEXT = 400
IN, OUT = "params", "returns"


class ContractError(ValueError):
    """A schema or an export that does not follow this module's rules."""


class ExportError(Exception):
    """A builtin module's export refusing a call (addons/builtin.py): ``message`` is Vietnamese, for the user."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


# ── schemas ────────────────────────────────────────────────────────────────────────────────────────────────────

def _is_type(value, kind: str) -> bool:
    if kind == "object":
        return isinstance(value, dict)
    if kind == "array":
        return isinstance(value, list)
    if kind == "string":
        return isinstance(value, str)
    if kind == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "boolean":
        return isinstance(value, bool)
    return value is None


def check_schema(schema, where: str, *, _depth: int = 0, _count: list[int] | None = None) -> None:
    """ContractError naming the first problem of ``schema`` (``where`` is its path, e.g. ``svn_log.params``)."""
    count = _count if _count is not None else [0]
    count[0] += 1
    if count[0] > MAX_NODES:
        raise ContractError(f"{where}: schema quá lớn (tối đa {MAX_NODES} nút)")
    if _depth > MAX_DEPTH:
        raise ContractError(f"{where}: schema lồng quá sâu (tối đa {MAX_DEPTH})")
    if not isinstance(schema, dict):
        raise ContractError(f"{where}: schema phải là object")
    unknown = set(schema) - KEYWORDS
    if unknown:
        raise ContractError(f"{where}: không hỗ trợ {', '.join(sorted(unknown))} (chỉ: {', '.join(sorted(KEYWORDS))})")
    kind = schema.get("type")
    if kind not in TYPES:
        raise ContractError(f"{where}: type phải là một trong {', '.join(TYPES)}")
    description = schema.get("description", "")
    if not isinstance(description, str) or len(description) > MAX_TEXT:
        raise ContractError(f"{where}: description là chuỗi, tối đa {MAX_TEXT} ký tự")
    allowed = {"type", "description", "enum", "default"} | {
        "object": {"properties", "required"}, "array": {"items"}, "string": {"minLength", "maxLength"},
        "integer": {"minimum", "maximum"}, "number": {"minimum", "maximum"}}.get(kind, set())
    misplaced = set(schema) - allowed
    if misplaced:
        raise ContractError(f"{where}: {', '.join(sorted(misplaced))} không dùng được với type {kind}")
    if kind == "object":
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            raise ContractError(f"{where}.properties phải là object")
        for name, sub in properties.items():
            if not FIELD_RE.match(name):
                raise ContractError(f"{where}: tên trường {name!r} không hợp lệ (chữ, số, _)")
            check_schema(sub, f"{where}.{name}", _depth=_depth + 1, _count=count)
        required = schema.get("required", [])
        if not isinstance(required, list) or not all(isinstance(r, str) for r in required) \
                or len(set(required)) != len(required):
            raise ContractError(f"{where}.required phải là danh sách tên trường, không trùng")
        missing = [r for r in required if r not in properties]
        if missing:
            raise ContractError(f"{where}.required có trường không khai trong properties: {', '.join(missing)}")
    if kind == "array":
        if "items" not in schema:
            raise ContractError(f"{where}: array cần items")
        check_schema(schema["items"], f"{where}[]", _depth=_depth + 1, _count=count)
    for low, high in (("minLength", "maxLength"), ("minimum", "maximum")):
        for key in (low, high):
            if key in schema:
                value = schema[key]
                integer = key.endswith("Length")
                if not _is_type(value, "integer" if integer else "number") or (integer and value < 0):
                    raise ContractError(f"{where}.{key} phải là số{' nguyên ≥ 0' if integer else ''}")
        if low in schema and high in schema and schema[low] > schema[high]:
            raise ContractError(f"{where}: {low} lớn hơn {high}")
    if "enum" in schema:
        values = schema["enum"]
        if not isinstance(values, list) or not values or len(values) > MAX_ENUM:
            raise ContractError(f"{where}.enum phải là danh sách 1-{MAX_ENUM} giá trị")
        if kind in ("object", "array"):
            raise ContractError(f"{where}: enum chỉ dùng cho kiểu đơn (string, số, boolean)")
        bad = [v for v in values if not _is_type(v, kind)]
        if bad:
            raise ContractError(f"{where}.enum có giá trị không phải {kind}: {bad[0]!r}")
    if "default" in schema:
        problems = validate(schema, schema["default"], f"{where}.default", extra=False)
        if problems:
            raise ContractError(problems[0])


def validate(schema: dict, value, where: str = "", *, extra: bool, limit: int = 20) -> list[str]:
    """Why ``value`` does not match ``schema`` (empty = it does). ``extra``: fields not in ``properties`` are fine
    (a reply may carry more than the caller knows) or refused (params: a typo must not pass silently)."""
    problems: list[str] = []
    _validate(schema, value, where or "giá trị", extra, problems, limit)
    return problems


def _validate(schema: dict, value, where: str, extra: bool, problems: list[str], limit: int) -> None:
    if len(problems) >= limit:
        return
    kind = schema["type"]
    if not _is_type(value, kind):
        problems.append(f"{where}: cần {kind}, nhận {type(value).__name__}")
        return
    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{where}: {value!r} không thuộc {schema['enum']}")
    if kind == "string":
        if "minLength" in schema and len(value) < schema["minLength"]:
            problems.append(f"{where}: ngắn hơn {schema['minLength']} ký tự")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            problems.append(f"{where}: dài hơn {schema['maxLength']} ký tự")
    if kind in ("integer", "number"):
        if "minimum" in schema and value < schema["minimum"]:
            problems.append(f"{where}: nhỏ hơn {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            problems.append(f"{where}: lớn hơn {schema['maximum']}")
    if kind == "object":
        properties = schema.get("properties", {})
        for name in schema.get("required", []):
            if name not in value:
                problems.append(f"{where}.{name}: thiếu (bắt buộc)")
        for name, sub in value.items():
            if name in properties:
                _validate(properties[name], sub, f"{where}.{name}", extra, problems, limit)
            elif not extra:
                problems.append(f"{where}.{name}: trường không có trong schema")
    if kind == "array":
        for index, item in enumerate(value):
            _validate(schema["items"], item, f"{where}[{index}]", extra, problems, limit)


def with_defaults(schema: dict, value: dict) -> dict:
    """``value`` (params, an object) with the top-level defaults filled in."""
    out = dict(value)
    for name, sub in schema.get("properties", {}).items():
        if name not in out and "default" in sub:
            out[name] = sub["default"]
    return out


# ── compare ────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Change:
    path: str
    message: str
    breaking: bool

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


def compare(old: dict, new: dict, direction: str, path: str = "") -> list[Change]:
    """How ``new`` differs from ``old`` for callers built against ``old``; ``direction`` is IN (params) or OUT
    (returns). Both schemas passed check_schema."""
    if direction not in (IN, OUT):
        raise ValueError(direction)
    changes: list[Change] = []
    _compare(old, new, direction, path or direction, changes)
    return changes


def _compare(old: dict, new: dict, direction: str, path: str, out: list[Change]) -> None:
    inbound = direction == IN
    a, b = old["type"], new["type"]
    if a != b:
        # A wider number type is fine where the addon accepts it, a narrower one where it produces it.
        widened = (a, b) == ("integer", "number")
        narrowed = (a, b) == ("number", "integer")
        fine = widened if inbound else narrowed
        out.append(Change(path, f"đổi kiểu {a} → {b}", not fine))
        if not fine:
            return
    _compare_enum(old, new, inbound, path, out)
    _compare_bounds(old, new, inbound, path, out)
    if "default" in old or "default" in new:
        if old.get("default") != new.get("default"):
            out.append(Change(path, f"đổi default {old.get('default')!r} → {new.get('default')!r}", False))
    if a == b == "object":
        _compare_object(old, new, inbound, direction, path, out)
    if a == b == "array":
        _compare(old["items"], new["items"], direction, f"{path}[]", out)


def _compare_enum(old: dict, new: dict, inbound: bool, path: str, out: list[Change]) -> None:
    before, after = old.get("enum"), new.get("enum")
    if before == after:
        return
    if inbound:  # the addon must still accept every value it accepted
        lost = [v for v in before or [] if after is not None and v not in after]
        if before is None and after is not None:
            out.append(Change(path, f"chỉ còn nhận {after}", True))
        elif lost:
            out.append(Change(path, f"không còn nhận {lost}", True))
        else:
            out.append(Change(path, "nhận thêm giá trị", False))
    else:  # the caller must not meet a value it never expected
        new_values = [v for v in after or [] if before is not None and v not in before]
        if after is None and before is not None:
            out.append(Change(path, f"có thể trả giá trị ngoài {before}", True))
        elif new_values:
            out.append(Change(path, f"có thể trả thêm {new_values}", True))
        else:
            out.append(Change(path, "trả ít loại giá trị hơn", False))


def _compare_bounds(old: dict, new: dict, inbound: bool, path: str, out: list[Change]) -> None:
    for key, upper in (("minLength", False), ("maxLength", True), ("minimum", False), ("maximum", True)):
        before, after = old.get(key), new.get(key)
        if before == after:
            continue
        # Tighter: a new bound, a lower maximum, a higher minimum.
        tighter = before is None or (after is not None and (after < before if upper else after > before))
        if after is None:
            tighter = False
        out.append(Change(path, f"{key} {before} → {after}", tighter if inbound else not tighter))


def _compare_object(old: dict, new: dict, inbound: bool, direction: str, path: str, out: list[Change]) -> None:
    before, after = old.get("properties", {}), new.get("properties", {})
    was, now = set(old.get("required", [])), set(new.get("required", []))
    for name in sorted(set(before) | set(after)):
        where = f"{path}.{name}"
        if name not in after:
            if inbound:
                out.append(Change(where, "bỏ tham số (bên gọi đang gửi sẽ bị từ chối)", True))
            else:
                out.append(Change(where, "bỏ trường" + (" bắt buộc" if name in was else ""), name in was))
            continue
        if name not in before:
            if inbound:
                out.append(Change(where, "thêm tham số" + (" bắt buộc" if name in now else ""), name in now))
            else:
                out.append(Change(where, "thêm trường", False))
            continue
        if (name in was) != (name in now):
            becomes_required = name in now
            # params: required where it was optional breaks callers that leave it out;
            # returns: optional where it was required breaks callers that read it.
            breaking = becomes_required if inbound else not becomes_required
            out.append(Change(where, "thành bắt buộc" if becomes_required else "thành không bắt buộc", breaking))
        _compare(before[name], after[name], direction, where, out)


# ── exports ────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Export:
    name: str
    description: str
    params: dict = field(hash=False)
    returns: dict = field(hash=False)
    example: dict = field(hash=False)
    since: str = ""

    def schemas(self) -> dict:
        """The part a caller snapshots when it is built (uses.<id>.built.contract.<name>)."""
        return {"params": self.params, "returns": self.returns}


def _top_object(schema, where: str) -> dict:
    count = [0]
    check_schema(schema, where, _count=count)
    if schema["type"] != "object":
        raise ContractError(f"{where}: phải là type object")
    return schema


def parse_export(raw, where: str = "exports") -> Export:
    if not isinstance(raw, dict):
        raise ContractError(f"{where}: mỗi export là một object")
    name = raw.get("name")
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise ContractError(f"{where}: name phải là chữ thường, số, _ (vd. svn_log_search)")
    where = f"exports.{name}"
    unknown = set(raw) - {"name", "description", "params", "returns", "example", "since"}
    if unknown:
        raise ContractError(f"{where}: không hỗ trợ {', '.join(sorted(unknown))}")
    description = raw.get("description")
    if not isinstance(description, str) or not description.strip() or len(description) > MAX_TEXT:
        raise ContractError(f"{where}.description: bắt buộc, tối đa {MAX_TEXT} ký tự")
    params = _top_object(raw.get("params", {"type": "object"}), f"{where}.params")
    returns = _top_object(raw.get("returns"), f"{where}.returns")
    if "example" not in raw:
        raise ContractError(f"{where}: cần example (một kết quả mẫu đúng returns)")
    problems = validate(returns, raw["example"], f"{where}.example", extra=False)
    if problems:
        raise ContractError("example không khớp returns: " + "; ".join(problems[:3]))
    since = raw.get("since") or ""
    if not isinstance(since, str):
        raise ContractError(f"{where}.since phải là version")
    return Export(name, description.strip(), params, returns, raw["example"], since)


def parse_exports(raw) -> tuple[Export, ...]:
    if not isinstance(raw, list):
        raise ContractError("exports phải là danh sách")
    if len(raw) > MAX_EXPORTS:
        raise ContractError(f"tối đa {MAX_EXPORTS} export")
    out = [parse_export(item, f"exports[{index}]") for index, item in enumerate(raw)]
    names = [e.name for e in out]
    duplicate = next((n for n in names if names.count(n) > 1), None)
    if duplicate:
        raise ContractError(f"export {duplicate} bị khai hai lần")
    return tuple(out)


def parse_snapshot(raw, where: str) -> dict[str, dict]:
    """``uses.<id>.built.contract``: {export name: {"params": schema, "returns": schema}}."""
    if not isinstance(raw, dict):
        raise ContractError(f"{where} phải là object {{tên export: {{params, returns}}}}")
    out = {}
    for name, schemas in raw.items():
        if not isinstance(name, str) or not NAME_RE.match(name):
            raise ContractError(f"{where}: tên export {name!r} không hợp lệ")
        if not isinstance(schemas, dict) or set(schemas) != {"params", "returns"}:
            raise ContractError(f"{where}.{name}: cần đúng params và returns")
        out[name] = {"params": _top_object(schemas["params"], f"{where}.{name}.params"),
                     "returns": _top_object(schemas["returns"], f"{where}.{name}.returns")}
    return out


def compare_export(name: str, old: dict, new: Export | None) -> list[Change]:
    """A caller built against ``old`` ({params, returns}) and the export ``new`` as now installed (None: gone)."""
    if new is None:
        return [Change(name, "export không còn", True)]
    return (compare(old["params"], new.params, IN, f"{name}.params")
            + compare(old["returns"], new.returns, OUT, f"{name}.returns"))


def compare_exports(old: tuple[Export, ...], new: tuple[Export, ...]) -> list[Change]:
    """Every change from one version of an addon's exports to the next (an update of the addon itself)."""
    after = {e.name: e for e in new}
    changes: list[Change] = []
    for export in old:
        changes += compare_export(export.name, export.schemas(), after.get(export.name))
    known = {e.name for e in old}
    changes += [Change(e.name, "export mới", False) for e in new if e.name not in known]
    return changes


def breaking(changes: list[Change]) -> list[Change]:
    return [c for c in changes if c.breaking]
