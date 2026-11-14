"""Entity-relationship diagrams from a code-map pack (pure: no Flask, read-only SQLite).

The extractor writes, in ``codemap.sqlite``:

* ``TABLE`` nodes (properties: database, schema, table, comment) that ``CONTAINS`` ``COLUMN`` nodes
  (properties: data_type, data_length, data_precision, data_scale, nullable, primary_key 'Y',
  ordinal_position, comment); logical names in ``graph_localization`` (field ``name``, locale ja/en/vi);
* ``REFERENCES`` edges, FK column -> referenced column, properties
  ``{"constraint", "position", "source": "catalog"|"ddl", "delete_rule", "referenced_constraint"}``;
  a composite key is one edge per column pair.

Packs from older extracts have no ``REFERENCES`` edges: the model is still built (tables and columns) and
says so in ``message`` (NO_FK_MESSAGE).

``build(db, table=..., depth=..)`` / ``build(db, schema=...)`` / ``build(db, system=...)`` returns a plain
dict (the JSON API answer); ``to_mermaid(model)`` and ``to_dbml(model)`` turn it into text.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from collections import OrderedDict, defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable

MAX_TABLES = 80
LOCALES = ("ja", "en", "vi")
NO_FK_MESSAGE = "Chưa có dữ liệu khoá ngoại — cần extract lại bằng code-map mới."
TABLE_TYPE = "TABLE"
# Types whose data_length means something (for NUMBER/DATE Oracle reports a byte size, not a length).
LENGTH_TYPES = frozenset({
    "CHAR", "NCHAR", "VARCHAR", "VARCHAR2", "NVARCHAR", "NVARCHAR2", "RAW", "BINARY", "VARBINARY",
    "CHARACTER", "CHARACTER VARYING", "BIT", "UROWID",
})
# DBML ``delete:`` setting; NO ACTION is the default and is left out.
DELETE_RULES = {"CASCADE": "cascade", "SET NULL": "set null", "SET DEFAULT": "set default", "RESTRICT": "restrict"}
_CHUNK = 500


class ErdError(ValueError):
    """A request the model cannot answer (unknown table, bad argument); ``status`` is the HTTP status."""

    def __init__(self, code: str, message: str, status: int = 400, **details: Any) -> None:
        super().__init__(message)
        self.code, self.message, self.status, self.details = code, message, status, details


# --------------------------------------------------------------------------- reading


def _json(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _chunks(values: list[str]) -> Iterable[list[str]]:
    for start in range(0, len(values), _CHUNK):
        yield values[start:start + _CHUNK]


def _rows(db: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
    cursor = db.execute(sql, tuple(params))
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


# --------------------------------------------------------------------------- per-pack index (performance)
#
# A pack never changes after import, so the parts every ERD request needs (all tables with their logical
# names, all REFERENCES edges with the table at each end) are read once per pack file and kept in memory.
# graph_edges has no index on edge_type: reading the FKs scans every edge (hundreds of thousands in a big
# pack), which must not happen per request or per keystroke in the table picker. Measured on 4,000 tables /
# 60,000 columns / 6,000 FKs / 366,000 edges: picker 200 ms -> a few ms, hub table depth 2: 420 ms -> ~100 ms.


@dataclass
class _PackIndex:
    tables: dict[str, dict[str, Any]] = field(default_factory=dict)
    logical: dict[str, dict[str, str]] = field(default_factory=dict)       # table id -> {ja, en, vi}
    haystack: dict[str, str] = field(default_factory=dict)                 # table id -> lower-case logical names
    refs: list[dict[str, Any]] = field(default_factory=list)
    refs_by_table: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: defaultdict(list))


_INDEX: "OrderedDict[tuple, _PackIndex]" = OrderedDict()
_INDEX_LOCK = threading.Lock()
_INDEX_SIZE = 4  # packs kept in memory


def _db_key(db: sqlite3.Connection) -> tuple | None:
    row = db.execute("PRAGMA database_list").fetchone()
    path = row[2] if row else ""
    if not path:
        return None  # in-memory database: nothing stable to cache on
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return (path, stat.st_mtime_ns, stat.st_size)


_REFS_SQL = ("SELECT e.edge_id, e.source_node_id AS from_column, e.target_node_id AS to_column, e.properties_json, "
             "st.source_node_id AS from_table, tt.source_node_id AS to_table "
             "FROM graph_edges e "
             "JOIN graph_edges st ON st.target_node_id=e.source_node_id AND st.edge_type='CONTAINS' "
             "JOIN graph_nodes sn ON sn.node_id=st.source_node_id AND sn.node_type='TABLE' "
             "JOIN graph_edges tt ON tt.target_node_id=e.target_node_id AND tt.edge_type='CONTAINS' "
             "JOIN graph_nodes tn ON tn.node_id=tt.source_node_id AND tn.node_type='TABLE' "
             "WHERE e.edge_type='REFERENCES'")


def _load_index(db: sqlite3.Connection) -> _PackIndex:
    index = _PackIndex()
    for row in _rows(db, f"SELECT {_TABLE_COLUMNS} FROM graph_nodes WHERE node_type=?", [TABLE_TYPE]):
        item = _table_item(row)
        index.tables[item["id"]] = item
    for row in db.execute(
        f"SELECT l.target_id, l.locale, l.value FROM graph_localization l JOIN graph_nodes n ON n.node_id=l.target_id "
        f"AND n.node_type=? WHERE l.target_type='NODE' AND l.field_name='name' "
        f"AND l.locale IN ({','.join('?' * len(LOCALES))})", [TABLE_TYPE, *LOCALES]
    ).fetchall():
        if row[2]:
            index.logical.setdefault(row[0], {})[row[1]] = str(row[2])
    index.haystack = {table_id: " ".join(names.values()).lower() for table_id, names in index.logical.items()}
    for row in _rows(db, _REFS_SQL):
        row["properties"] = _json(row.pop("properties_json"))
        index.refs.append(row)
        index.refs_by_table[row["from_table"]].append(row)
        if row["to_table"] != row["from_table"]:
            index.refs_by_table[row["to_table"]].append(row)
    index.refs.sort(key=lambda ref: ref["edge_id"])
    return index


def _index(db: sqlite3.Connection) -> _PackIndex:
    key = _db_key(db)
    if key is None:
        return _load_index(db)
    with _INDEX_LOCK:
        if key in _INDEX:
            _INDEX.move_to_end(key)
            return _INDEX[key]
    index = _load_index(db)  # outside the lock: a slow first load must not block other packs
    with _INDEX_LOCK:
        _INDEX[key] = index
        while len(_INDEX) > _INDEX_SIZE:
            _INDEX.popitem(last=False)
    return index


def has_fk_data(db: sqlite3.Connection) -> bool:
    return bool(_index(db).refs)


def _table_item(row: dict[str, Any]) -> dict[str, Any]:
    props = _json(row.get("properties_json"))
    qualified = str(row.get("qualified_name") or "")
    parts = qualified.split(".")
    database = str(props.get("database") or row.get("database_key") or (parts[0] if len(parts) == 3 else ""))
    schema = str(props.get("schema") or (parts[-2] if len(parts) >= 2 else ""))
    name = str(props.get("table") or row.get("technical_name") or parts[-1])
    return {
        "id": row["node_id"], "database": database, "schema": schema, "name": name,
        "qualified_name": qualified or ".".join(part for part in (database, schema, name) if part),
        "system": str(row.get("system_key") or ""), "comment": str(props.get("comment") or ""),
    }


_TABLE_COLUMNS = "node_id, technical_name, qualified_name, system_key, database_key, properties_json"


def _tables_by_id(db: sqlite3.Connection, ids: list[str]) -> dict[str, dict[str, Any]]:
    tables = _index(db).tables
    return {table_id: dict(tables[table_id]) for table_id in ids if table_id in tables}


def _all_tables(db: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(item) for item in _index(db).tables.values()]


def _logical(db: sqlite3.Connection, ids: list[str]) -> dict[str, dict[str, str]]:
    names: dict[str, dict[str, str]] = defaultdict(dict)
    for chunk in _chunks(ids):
        marks = ",".join("?" * len(chunk))
        for row in db.execute(
            f"SELECT target_id, locale, value FROM graph_localization WHERE target_type='NODE' AND field_name='name' "
            f"AND locale IN ({','.join('?' * len(LOCALES))}) AND target_id IN ({marks})", [*LOCALES, *chunk]
        ).fetchall():
            if row[2]:
                names[row[0]][row[1]] = str(row[2])
    return names


def format_type(props: dict[str, Any]) -> str:
    """``VARCHAR2(32)``, ``NUMBER(18,0)``, ``NUMBER(10)``, ``DATE``; unknown -> ``""``."""
    data_type = str(props.get("data_type") or "").strip().upper()
    if not data_type or "(" in data_type:
        return data_type
    precision = str(props.get("data_precision") or "").strip()
    scale = str(props.get("data_scale") or "").strip()
    length = str(props.get("data_length") or "").strip()
    if precision:
        return f"{data_type}({precision},{scale})" if scale else f"{data_type}({precision})"
    if length and data_type in LENGTH_TYPES:
        return f"{data_type}({length})"
    return data_type


def _position(value: Any, fallback: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return fallback


def _columns(db: sqlite3.Connection, table_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Columns per table, in ordinal order."""
    by_table: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk in _chunks(table_ids):
        marks = ",".join("?" * len(chunk))
        rows = _rows(db, "SELECT e.source_node_id AS table_id, n.node_id, n.technical_name, n.properties_json "
                         "FROM graph_edges e JOIN graph_nodes n ON n.node_id=e.target_node_id AND n.node_type='COLUMN' "
                         f"WHERE e.edge_type='CONTAINS' AND e.source_node_id IN ({marks})", chunk)
        for index, row in enumerate(rows):
            props = _json(row["properties_json"])
            by_table[row["table_id"]].append({
                "id": row["node_id"],
                "name": str(props.get("column") or row["technical_name"] or row["node_id"].rsplit(":", 1)[-1]),
                "type": format_type(props),
                "nullable": str(props.get("nullable") or "Y").upper() != "N",
                "pk": str(props.get("primary_key") or "").upper() in {"Y", "YES", "TRUE", "1", "P"},
                "fk": False,
                "referenced": False,
                "position": _position(props.get("ordinal_position"), 10_000 + index),
                "comment": str(props.get("comment") or ""),
            })
    for columns in by_table.values():
        columns.sort(key=lambda column: (column["position"], column["name"]))
    return by_table


def _references(db: sqlite3.Connection, table_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """REFERENCES edges with the table of each end; only those touching ``table_ids`` when given."""
    index = _index(db)
    if table_ids is None:
        return [dict(ref) for ref in index.refs]
    found: dict[str, dict[str, Any]] = {}
    for table_id in table_ids:
        for ref in index.refs_by_table.get(table_id, ()):
            found[ref["edge_id"]] = ref
    return [dict(found[edge_id]) for edge_id in sorted(found)]


# --------------------------------------------------------------------------- resolving what to show


def resolve_table(db: sqlite3.Connection, name: str) -> dict[str, Any]:
    """A TABLE by node id, column node id (its table), qualified name (DB.SCHEMA.TABLE or SCHEMA.TABLE) or name."""
    text = str(name or "").strip()
    if not text:
        raise ErdError("table_required", "Cần tên bảng (table).")
    found = _tables_by_id(db, [text])
    if text in found:
        return found[text]
    row = db.execute("SELECT e.source_node_id FROM graph_edges e JOIN graph_nodes n ON n.node_id=e.source_node_id "
                     "AND n.node_type='TABLE' WHERE e.edge_type='CONTAINS' AND e.target_node_id=?", (text,)).fetchone()
    if row:
        return _tables_by_id(db, [row[0]])[row[0]]
    upper = text.upper()
    candidates = [table for table in _all_tables(db)
                  if table["qualified_name"].upper() == upper
                  or f"{table['schema']}.{table['name']}".upper() == upper
                  or table["name"].upper() == upper]
    if not candidates:
        raise ErdError("unknown_table", f"Không có bảng '{text}' trong pack.", 404)
    if len(candidates) > 1:
        exact = [table for table in candidates if table["qualified_name"].upper() == upper]
        if len(exact) == 1:
            return exact[0]
        names = sorted(table["qualified_name"] for table in candidates)
        raise ErdError("ambiguous_table", f"Có {len(candidates)} bảng tên '{text}': {', '.join(names[:10])}. "
                       "Ghi rõ DB.SCHEMA.TABLE.", 409, candidates=names[:20])
    return candidates[0]


def _schema_matches(table: dict[str, Any], schema: str) -> bool:
    wanted = schema.strip().upper()
    if wanted.startswith("DATABASE-SCHEMA:"):
        wanted = wanted.split(":", 1)[1].replace(":", ".")
    database, name = (wanted.split(".", 1) if "." in wanted else ("", wanted))
    return table["schema"].upper() == name and (not database or table["database"].upper() == database)


def _walk(db: sqlite3.Connection, focus: str, depth: int) -> tuple[dict[str, int], dict[str, int]]:
    """Tables within ``depth`` REFERENCES hops of ``focus`` (either direction): distance and layer.

    The layer places a table left (it references the table it was reached from: a child) or right (it is
    referenced: a parent) of where it was reached from, so the diagram reads FK -> PK left to right.
    """
    distance, layer = {focus: 0}, {focus: 0}
    frontier = [focus]
    for step in range(1, depth + 1):
        following: list[str] = []
        for ref in _references(db, frontier):
            for here, there, side in ((ref["from_table"], ref["to_table"], 1), (ref["to_table"], ref["from_table"], -1)):
                if here in distance and distance[here] == step - 1 and there not in distance:
                    distance[there] = step
                    layer[there] = layer[here] + side
                    following.append(there)
        frontier = sorted(set(following))
        if not frontier:
            break
    return distance, layer


def _group_relations(refs: list[dict[str, Any]], kept: set[str], columns: dict[str, list[dict[str, Any]]],
                     tables: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    by_column = {column["id"]: column for items in columns.values() for column in items}
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for ref in refs:
        if ref["from_table"] not in kept or ref["to_table"] not in kept:
            continue
        constraint = str(ref["properties"].get("constraint") or "")
        key = (ref["from_table"], ref["to_table"], constraint or f"#{ref['from_column']}")
        groups[key].append(ref)
    relations = []
    for (from_table, to_table, _key), items in groups.items():
        items.sort(key=lambda ref: (_position(ref["properties"].get("position"), 0), ref["from_column"]))
        first = items[0]["properties"]
        from_columns = [by_column.get(ref["from_column"], {}).get("name") or ref["from_column"].rsplit(":", 1)[-1] for ref in items]
        to_columns = [by_column.get(ref["to_column"], {}).get("name") or ref["to_column"].rsplit(":", 1)[-1] for ref in items]
        pk = {column["name"] for column in columns.get(from_table, []) if column["pk"]}
        one_to_one = bool(pk) and pk == set(from_columns)
        nullable = any(by_column.get(ref["from_column"], {}).get("nullable", True) for ref in items)
        relations.append({
            "id": f"{from_table}->{to_table}:{first.get('constraint') or items[0]['from_column']}",
            "constraint": str(first.get("constraint") or ""),
            "from_table": from_table, "from_columns": from_columns, "from_column_ids": [ref["from_column"] for ref in items],
            "to_table": to_table, "to_columns": to_columns, "to_column_ids": [ref["to_column"] for ref in items],
            "delete_rule": str(first.get("delete_rule") or "").upper(),
            "source": str(first.get("source") or ""),
            "referenced_constraint": str(first.get("referenced_constraint") or ""),
            "cardinality": "one-to-one" if one_to_one else "many-to-one",
            "optional": nullable,
            "label": relation_label(from_columns, to_columns),
        })
    order = {table_id: (tables[table_id]["schema"], tables[table_id]["name"]) for table_id in tables}
    relations.sort(key=lambda rel: (order.get(rel["from_table"], ("", "")), rel["constraint"], order.get(rel["to_table"], ("", ""))))
    return relations


def relation_label(from_columns: list[str], to_columns: list[str]) -> str:
    """``a → b``, or ``(a, b) → (c, d)`` for a composite key."""
    if len(from_columns) == 1 and len(to_columns) == 1:
        return f"{from_columns[0]} → {to_columns[0]}"
    return f"({', '.join(from_columns)}) → ({', '.join(to_columns)})"


def build(db: sqlite3.Connection, *, table: str = "", schema: str = "", system: str = "", depth: int = 1,
          limit: int = MAX_TABLES) -> dict[str, Any]:
    """The ERD model: focus on ``table`` (``depth`` 1-2 hops), or every table of ``schema`` or ``system``."""
    if sum(bool(str(value or "").strip()) for value in (table, schema, system)) != 1:
        raise ErdError("bad_scope", "Chọn đúng một trong: table, schema hoặc system.")
    try:
        depth = int(depth)
    except (TypeError, ValueError):
        raise ErdError("bad_depth", "depth phải là 1 hoặc 2.") from None
    if depth not in (1, 2):
        raise ErdError("bad_depth", "depth phải là 1 hoặc 2.")
    limit = max(1, min(int(limit or MAX_TABLES), MAX_TABLES))
    fk_data = has_fk_data(db)
    distance: dict[str, int] = {}
    layer: dict[str, int] = {}
    focus = None
    if table.strip():
        focus = resolve_table(db, table)
        if fk_data:
            distance, layer = _walk(db, focus["id"], depth)
        else:
            distance, layer = {focus["id"]: 0}, {focus["id"]: 0}
        tables = _tables_by_id(db, list(distance))
        ordered = sorted(tables, key=lambda table_id: (distance[table_id], tables[table_id]["schema"], tables[table_id]["name"]))
        mode, scope = "table", focus["qualified_name"]
    else:
        everything = _all_tables(db)
        if schema.strip():
            chosen = [item for item in everything if _schema_matches(item, schema)]
            mode, scope = "schema", schema.strip()
            if not chosen:
                raise ErdError("unknown_schema", f"Không có bảng nào trong schema '{schema.strip()}'.", 404)
        else:
            chosen = [item for item in everything if item["system"].upper() == system.strip().upper()]
            mode, scope = "system", system.strip()
            if not chosen:
                raise ErdError("unknown_system", f"Không có bảng nào thuộc hệ thống '{system.strip()}'.", 404)
        tables = {item["id"]: item for item in chosen}
        ordered = sorted(tables, key=lambda table_id: (tables[table_id]["database"], tables[table_id]["schema"], tables[table_id]["name"]))
    kept_ids = ordered[:limit]
    omitted = len(ordered) - len(kept_ids)
    kept = set(kept_ids)
    columns = _columns(db, kept_ids)
    refs = _references(db, kept_ids) if fk_data else []
    fk_columns = {ref["from_column"] for ref in refs}
    referenced = {ref["to_column"] for ref in refs}
    for items in columns.values():
        for column in items:
            column["fk"] = column["id"] in fk_columns
            column["referenced"] = column["id"] in referenced
    relations = _group_relations(refs, kept, columns, tables)
    outside = len({(ref["from_table"], ref["to_table"], str(ref["properties"].get("constraint") or ref["from_column"]))
                   for ref in refs if ref["from_table"] not in kept or ref["to_table"] not in kept})
    names = _logical(db, kept_ids + [column["id"] for table_id in kept_ids for column in columns.get(table_id, [])])
    shown = []
    for table_id in kept_ids:
        item = dict(tables[table_id])
        item["logical"] = names.get(table_id, {})
        item["distance"] = distance.get(table_id)
        item["layer"] = layer.get(table_id)
        item["columns"] = [{**column, "logical": names.get(column["id"], {})} for column in columns.get(table_id, [])]
        shown.append(item)
    model = {
        "mode": mode, "scope": scope, "focus": focus["id"] if focus else None,
        "depth": depth if focus else None, "has_fk_data": fk_data, "message": "" if fk_data else NO_FK_MESSAGE,
        "tables": shown, "relations": relations, "outside_relations": outside,
        "truncated": omitted > 0, "omitted": omitted, "limit": limit,
    }
    model["summary"] = summary(model)
    return model


def summary(model: dict[str, Any]) -> str:
    what = {"table": f"quanh bảng {model['scope']} (độ sâu {model['depth']})",
            "schema": f"schema {model['scope']}", "system": f"hệ thống {model['scope']}"}[model["mode"]]
    text = f"ERD {what}: {len(model['tables'])} bảng, {len(model['relations'])} khoá ngoại"
    if model["truncated"]:
        text += f"; ẩn {model['omitted']} bảng vượt giới hạn {model['limit']}"
    if not model["has_fk_data"]:
        text += f". {NO_FK_MESSAGE}"
    return text


def search_tables(db: sqlite3.Connection, query: str = "", *, schema: str = "", limit: int = 30) -> dict[str, Any]:
    """Table picker: tables matching ``query`` (technical, qualified or ja/en/vi logical name) + every schema."""
    term = str(query or "").strip()
    limit = max(1, min(int(limit or 30), 100))
    everything = _all_tables(db)
    schemas: dict[tuple[str, str], int] = defaultdict(int)
    systems: dict[str, int] = defaultdict(int)
    for item in everything:
        schemas[(item["database"], item["schema"])] += 1
        if item["system"]:
            systems[item["system"]] += 1
    pool = [item for item in everything if not schema or _schema_matches(item, schema)]
    index = _index(db)
    logical, haystack = index.logical, index.haystack
    lowered = term.lower()

    def rank(item: dict[str, Any]) -> int | None:
        if not lowered:
            return 3
        name, qualified = item["name"].lower(), item["qualified_name"].lower()
        if name == lowered or qualified == lowered:
            return 0
        if name.startswith(lowered):
            return 1
        if lowered in name or lowered in qualified:
            return 2
        if lowered in haystack.get(item["id"], ""):
            return 2
        return None

    hits = sorted(((rank(item), item) for item in pool), key=lambda pair: (pair[0] if pair[0] is not None else 9, pair[1]["schema"], pair[1]["name"]))
    found = [{**item, "logical": logical.get(item["id"], {})} for score, item in hits if score is not None]
    return {
        "tables": found[:limit], "total": len(found),
        "schemas": [{"id": f"{database}.{name}" if database else name, "database": database, "schema": name, "tables": count}
                    for (database, name), count in sorted(schemas.items())],
        "systems": [{"id": name, "tables": count} for name, count in sorted(systems.items())],
        "has_fk_data": bool(index.refs), "message": "" if index.refs else NO_FK_MESSAGE,
    }


# --------------------------------------------------------------------------- exporters

_MERMAID_WORD = re.compile(r"[^A-Za-z0-9_]")


def _mermaid_word(value: str, fallback: str) -> str:
    """Mermaid entity / attribute names: ASCII letters, digits and ``_``, starting with a letter."""
    word = _MERMAID_WORD.sub("_", value).strip("_") or fallback
    return word if word[0].isalpha() else f"{fallback[0]}_{word}"


def _mermaid_type(value: str) -> str:
    """Mermaid allows ``(``/``)`` in a type but not ``,`` or spaces: ``NUMBER(18,0)`` -> ``NUMBER(18_0)``."""
    text = re.sub(r"\s*,\s*", "_", value.strip())
    text = re.sub(r"[^A-Za-z0-9_()\[\]]", "_", text) or "UNKNOWN"
    return text if text[0].isalpha() else f"T_{text}"


def _mermaid_string(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace('"', "'")).strip()


def _logical_text(logical: dict[str, str], *, sep: str = " / ") -> str:
    return sep.join(value for value in (logical.get("ja"), logical.get("en")) if value)


def _entity_names(tables: list[dict[str, Any]], word) -> dict[str, str]:
    """Short names when unique (TABLE), else SCHEMA_TABLE, else DB_SCHEMA_TABLE (+ a counter)."""
    names: dict[str, str] = {}
    candidates = [lambda t: t["name"], lambda t: f"{t['schema']}_{t['name']}", lambda t: f"{t['database']}_{t['schema']}_{t['name']}"]
    for pick in candidates:
        counts: dict[str, int] = defaultdict(int)
        for table in tables:
            counts[word(pick(table))] += 1
        for table in tables:
            if table["id"] not in names and counts[word(pick(table))] == 1:
                names[table["id"]] = word(pick(table))
    used = set(names.values())
    for table in tables:
        if table["id"] not in names:
            base, number = word(candidates[-1](table)), 2
            while f"{base}_{number}" in used:
                number += 1
            names[table["id"]] = f"{base}_{number}"
            used.add(names[table["id"]])
    return names


def _visible_columns(table: dict[str, Any], keys_only: bool) -> list[dict[str, Any]]:
    """Every column, or (keys_only) the PK / FK columns and those a foreign key points to."""
    return [column for column in table["columns"] if not keys_only or column["pk"] or column["fk"] or column.get("referenced")]


def to_mermaid(model: dict[str, Any], *, keys_only: bool = False) -> str:
    """Mermaid ``erDiagram``: ``TYPE name PK, FK "logical / comment"`` and crow's-foot relationships."""
    tables = model["tables"]
    names = _entity_names(tables, lambda value: _mermaid_word(value, "T"))
    lines = ["erDiagram", f"    %% {_mermaid_string(model.get('summary') or '')}"]
    for table in tables:
        title = _logical_text(table.get("logical") or {})
        lines.append(f"    %% {table['qualified_name']}" + (f": {_mermaid_string(title)}" if title else ""))
        columns = _visible_columns(table, keys_only)
        if not columns:
            lines.append(f"    {names[table['id']]} {{")
            lines.append("    }")
            continue
        lines.append(f"    {names[table['id']]} {{")
        for column in columns:
            keys = ", ".join(key for key, on in (("PK", column["pk"]), ("FK", column["fk"])) if on)
            note = _logical_text(column.get("logical") or {}) or column.get("comment") or ""
            parts = [_mermaid_type(column["type"] or "UNKNOWN"), _mermaid_word(column["name"], "C")]
            if keys:
                parts.append(keys)
            if note:
                parts.append(f'"{_mermaid_string(note)}"')
            lines.append("        " + " ".join(parts))
        lines.append("    }")
    for relation in model["relations"]:
        left = "|o" if relation["cardinality"] == "one-to-one" else "}o"
        right = "o|" if relation["optional"] else "||"
        label = relation["label"]
        if relation["constraint"]:
            label = f"{relation['constraint']}: {label}"
        lines.append(f"    {names[relation['from_table']]} {left}--{right} {names[relation['to_table']]} : \"{_mermaid_string(label)}\"")
    return "\n".join(lines) + "\n"


_DBML_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DBML_TYPE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\(\d+(,\d+)?\))?$")


def _dbml_name(value: str) -> str:
    return value if _DBML_NAME.match(value) else '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _dbml_string(value: str) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _dbml_type(value: str) -> str:
    text = value.strip() or "UNKNOWN"
    return text if _DBML_TYPE.match(text) else '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def to_dbml(model: dict[str, Any], *, keys_only: bool = False) -> str:
    """DBML for dbdiagram.io: ``Table schema.name [note: '…'] { col type [pk, not null, note: 'ja / en'] }`` and ``Ref``."""
    tables = model["tables"]
    by_id = {table["id"]: table for table in tables}
    # schema.table is the DBML name; two databases with the same schema and table get the database in the schema.
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for table in tables:
        counts[(table["schema"], table["name"])] += 1

    def schema_of(table: dict[str, Any]) -> str:
        schema = table["schema"] or "public"
        return f"{table['database']}_{schema}" if counts[(table["schema"], table["name"])] > 1 and table["database"] else schema

    def full(table: dict[str, Any]) -> str:
        return f"{_dbml_name(schema_of(table))}.{_dbml_name(table['name'])}"

    lines = ["// " + re.sub(r"\s+", " ", model.get("summary") or "").strip()]
    for table in tables:
        logical = table.get("logical") or {}
        comment = table.get("comment") or ""
        note = " · ".join(value for value in (_logical_text(logical), "" if comment in logical.values() else comment) if value)
        lines.append("")
        lines.append(f"Table {full(table)}" + (f" [note: {_dbml_string(note)}]" if note else "") + " {")
        for column in _visible_columns(table, keys_only):
            settings = []
            if column["pk"]:
                settings.append("pk")
            if not column["nullable"]:
                settings.append("not null")
            column_note = _logical_text(column.get("logical") or {}) or column.get("comment") or ""
            if column_note:
                settings.append(f"note: {_dbml_string(column_note)}")
            lines.append(f"  {_dbml_name(column['name'])} {_dbml_type(column['type'])}" + (f" [{', '.join(settings)}]" if settings else ""))
        lines.append("}")
    if model["relations"]:
        lines.append("")
    for relation in model["relations"]:
        source, target = by_id[relation["from_table"]], by_id[relation["to_table"]]
        if len(relation["from_columns"]) == 1:
            left = f"{full(source)}.{_dbml_name(relation['from_columns'][0])}"
            right = f"{full(target)}.{_dbml_name(relation['to_columns'][0])}"
        else:
            left = f"{full(source)}.({', '.join(_dbml_name(name) for name in relation['from_columns'])})"
            right = f"{full(target)}.({', '.join(_dbml_name(name) for name in relation['to_columns'])})"
        operator = "-" if relation["cardinality"] == "one-to-one" else ">"
        name = f" {_dbml_name(relation['constraint'])}" if relation["constraint"] else ""
        rule = DELETE_RULES.get(relation["delete_rule"])
        lines.append(f"Ref{name}: {left} {operator} {right}" + (f" [delete: {rule}]" if rule else ""))
    return "\n".join(lines) + "\n"


def render(model: dict[str, Any], fmt: str, *, keys_only: bool = False) -> str:
    if fmt == "mermaid":
        return to_mermaid(model, keys_only=keys_only)
    if fmt == "dbml":
        return to_dbml(model, keys_only=keys_only)
    if fmt == "json":
        return json.dumps(model, ensure_ascii=False, indent=2) + "\n"
    raise ErdError("bad_format", "format phải là json, mermaid hoặc dbml.")


FILE_EXTENSIONS = {"mermaid": "mmd", "dbml": "dbml", "json": "json"}


def filename(model: dict[str, Any], fmt: str) -> str:
    """ASCII file name for a download: ``erd-DB1.APP.ORDERS.mmd``."""
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", str(model.get("scope") or "erd")).strip("._") or "erd"
    return f"erd-{stem[:80]}.{FILE_EXTENSIONS.get(fmt, 'txt')}"
