"""MCP server for the CSV files people chose to share with AI ("Cho AI đọc"), built to keep token use low.

Two tools, plain compact text:
  csv_list    every shared file: id, name, description, row count, and its columns (type, description, a few
              sample values) — enough for an agent to pick the right file and the right filter values
  csv_search  rows of one file: filters as on the CSV page (column · IN/== · value, all must match) and/or text
              anywhere, only the columns asked for, bounded

Only datasets with ``mcp`` on are visible (Dataset.mcp: off for uploads until the user turns it on, on for data
pack files unless the admin's config.json says no) and only their visible columns. Read-only.
Transports: HTTP ``POST /csv/mcp`` (routes.py) and stdio ``viewer-hub mcp csv``.
"""
from __future__ import annotations

from contextlib import closing
from typing import Any, Callable

from viewer_hub.core.mcp import ToolError, dispatch, int_arg, serve_stdio as _serve_stdio
from viewer_hub.csv.store import CsvStore, Dataset

SAMPLES = 3
SAMPLE_CHARS = 40
CELL_CHARS = 200
DEFAULT_LIMIT, MAX_LIMIT = 50, 500

INSTRUCTIONS = (
    "CSV files the user shared with you (lookup tables, code lists, database column dictionaries…). "
    "Call csv_list first: read each file's description and columns to pick the file, and use the sample values to "
    "write filters. Then csv_search with filters (== for exact codes/names, IN for 'contains') and only the columns "
    "you need. If the reply says it was cut, narrow the filters instead of raising the limit."
)

TOOLS: list[dict[str, Any]] = [
    {
        "name": "csv_list",
        "description": (
            "List the CSV files you may read: id, name, description, rows, and each column with its type, description "
            "and sample values. No row data. Optional `query` keeps the files whose name/description/columns contain it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "e.g. 'bảng', 'mã lỗi', 'TABLE_NAME'"}},
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "csv_search",
        "description": (
            "Rows of one CSV file (id from csv_list). `filters`: every one must match; operator IN = contains, "
            "== = equals; case-insensitive; column by name. `text`: contained in any column. `columns`: return only "
            "these. Answer is a '|' table with 'rows a-b of N'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "filters": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "column": {"type": "string"},
                            "operator": {"type": "string", "enum": ["IN", "=="], "default": "IN"},
                            "value": {"type": "string"},
                        },
                        "required": ["column", "value"],
                    },
                },
                "text": {"type": "string"},
                "columns": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT, "default": DEFAULT_LIMIT},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
            },
            "required": ["id"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
]


def _shared(store: CsvStore) -> list[Dataset]:
    return [dataset for dataset in store.list() if dataset.mcp]


def _name(column: dict) -> str:
    return column.get("label") or column["name"]


def _samples(dataset: Dataset) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    with closing(dataset.connect()) as db:
        for column in dataset.visible:
            key = column["key"]
            rows = db.execute(f"SELECT DISTINCT {key} FROM rows WHERE trim(coalesce({key}, '')) <> '' LIMIT ?", (SAMPLES,))
            out[key] = [str(value)[:SAMPLE_CHARS] for (value,) in rows]
    return out


def csv_list(store: CsvStore, arguments: dict) -> str:
    query = str(arguments.get("query") or "").strip().casefold()
    datasets = _shared(store)
    if not datasets:
        return "No CSV file is shared with AI on this PC (CSV page → Cấu hình cột → “Cho AI đọc”)."
    blocks = []
    for dataset in datasets:
        text = " ".join([dataset.title, dataset.description, *(_name(c) for c in dataset.visible)]).casefold()
        if query and query not in text:
            continue
        origin = f" · data pack {dataset.meta['pack']['title']}" if dataset.readonly else ""
        lines = [f"## {dataset.id} — {dataset.title}",
                 dataset.description or "(no description: judge from the columns)",
                 f"{dataset.meta.get('rows', 0):,} rows · file {dataset.meta.get('source', {}).get('filename', '')}{origin}",
                 "columns:"]
        samples = _samples(dataset)
        for column in dataset.visible:
            note = f": {column['description']}" if column.get("description") else ""
            seen = samples.get(column["key"]) or []
            example = f" · e.g. {', '.join(seen)}" if seen else ""
            lines.append(f"- {_name(column)} ({column.get('type', 'text')}){note}{example}")
        blocks.append("\n".join(lines))
    if not blocks:
        return f"No shared CSV file matches «{query}». Call csv_list without query to see all."
    return f"{len(blocks)} CSV file(s):\n\n" + "\n\n".join(blocks)


def _column(dataset: Dataset, name: str) -> dict:
    wanted = (name or "").strip().casefold()
    for column in dataset.visible:
        if wanted in {column["name"].casefold(), (column.get("label") or "").casefold(), column["key"]}:
            return column
    raise ToolError(f"No column {name!r} in {dataset.id}; columns: {', '.join(_name(c) for c in dataset.visible)}")


def _cell(value: Any) -> str:
    text = "" if value is None else " ".join(str(value).split())
    return (text[:CELL_CHARS] + "…" if len(text) > CELL_CHARS else text).replace("|", "/")


def csv_search(store: CsvStore, arguments: dict) -> str:
    dataset_id = str(arguments.get("id") or "").strip()
    dataset = store.get(dataset_id) if dataset_id else None
    if dataset is None or not dataset.mcp:
        raise ToolError(f"No shared CSV file with id {dataset_id!r}; take ids from csv_list.")
    raw_filters = arguments.get("filters") or []
    if not isinstance(raw_filters, list):
        raise ToolError("filters must be a list of {column, operator, value}")
    rules = []
    for item in raw_filters:
        if not isinstance(item, dict) or not str(item.get("value") or "").strip():
            raise ToolError("each filter needs column and a non-empty value")
        operator = str(item.get("operator") or "IN").strip()
        if operator not in {"IN", "=="}:
            raise ToolError("operator must be IN (contains) or == (equals)")
        rules.append({"column": _column(dataset, str(item.get("column") or ""))["key"], "operator": operator,
                      "value": str(item["value"]).strip()})
    wanted = arguments.get("columns") or []
    if not isinstance(wanted, list):
        raise ToolError("columns must be a list of column names")
    shown = [_column(dataset, str(name)) for name in wanted] or dataset.visible
    limit = int_arg(arguments, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
    offset = int_arg(arguments, "offset", 0, 0, 10**9)
    result = dataset.search(text=str(arguments.get("text") or ""), rules=rules, offset=offset, limit=limit)
    index = {c["key"]: i for i, c in enumerate(result["columns"])}
    header = " | ".join(_name(c) for c in shown)
    body = [" | ".join(_cell(row[index[c["key"]]]) for c in shown) for row in result["rows"]]
    total = result["total"]
    if not body:
        return f"{dataset.id}: no rows match. Check values against csv_list samples, or use IN instead of ==."
    end = offset + len(body)
    tail = f"\n(cut: {total - end:,} more; narrow the filters or call again with offset={end})" if end < total else ""
    return f"{dataset.id} — {dataset.title}: rows {offset + 1}-{end} of {total:,}\n{header}\n" + "\n".join(body) + tail


HANDLERS: dict[str, Callable[[CsvStore, dict], str]] = {"csv_list": csv_list, "csv_search": csv_search}


def handle(message: Any, resolve_store: Callable[[], CsvStore]) -> dict | list | None:
    return dispatch(message, name="viewer-hub-csv", title="CSV", instructions=INSTRUCTIONS, tools=TOOLS,
                    run=lambda name, arguments: HANDLERS[name](resolve_store(), arguments))


def serve_stdio(resolve_store: Callable[[], CsvStore]) -> int:
    return _serve_stdio(lambda message: handle(message, resolve_store))
