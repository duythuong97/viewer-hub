"""What addons may read of Code map (``exports``, contract in exports.json; docs/solutions/codemap-redesign-solution.md §5.3).

The Hub calls ``call(hub, name, params)`` in-process for POST /api/addons/call/codemap/<name> (addons/builtin.py),
after checking ``params`` against the contract; the reply is checked too. Everything here only reads: the pack
(read-only SQLite) and the user's knowledge db for the hand-made links.
"""
from __future__ import annotations

from typing import Any

from viewer_hub.addons.contract import ExportError
from viewer_hub.codemap import erd, packs
from viewer_hub.codemap.storage import GraphNotReady, open_search, open_web


def _source(hub, params: dict[str, Any]):
    wanted = str(params.get("pack") or "").strip() or None
    source = packs.pick(hub, wanted)
    if source is None:
        if wanted:
            raise ExportError("unknown_pack", f"Không có pack code-map đang bật tên '{wanted}'.", 404)
        raise ExportError("no_codemap_pack", "Chưa có pack code-map nào. Import một .sapack có thành phần codemap.", 404)
    return source


def erd_model(hub, params: dict[str, Any]) -> dict[str, Any]:
    source = _source(hub, params)
    tables = params.get("tables")
    with open_search(source.output) as db:
        model = erd.build(db, table=params.get("table", ""), schema=params.get("schema", ""), system=params.get("system", ""),
                          depth=params.get("depth", 1), limit=params.get("limit", erd.MAX_TABLES),
                          tables=tables if tables is not None else None)
    fmt = params.get("format", "json")
    if fmt != "json":
        model["text"] = erd.render(model, fmt, keys_only=params.get("columns") == "keys")
        model["filename"] = erd.filename(model, fmt)
    # Optional fields are left out rather than sent as null (the contract types them as strings / integers).
    return {"pack": source.pack_id, **{key: value for key, value in model.items() if value is not None}}


def db_objects(hub, params: dict[str, Any]) -> dict[str, Any]:
    source = _source(hub, params)
    with open_search(source.output) as db:
        found = erd.search_tables(db, params.get("q", ""), schema=params.get("schema", ""), limit=params.get("limit", 30))
    return {"pack": source.pack_id, "packs": [{"id": s.pack_id, "title": s.title, "version": s.version} for s in packs.sources(hub)],
            **found}


def table_usage(hub, params: dict[str, Any]) -> dict[str, Any]:
    from viewer_hub.codemap import business
    from viewer_hub.codemap.api.business_routes import tree_context

    source = _source(hub, params)
    with open_web(source.output, source.knowledge, True) as db:
        table = erd.resolve_table(db, params["table"]) if params.get("table") else None
        index, tree, _path = tree_context(db, source.output, source.knowledge)
        usage = business.table_usage(index, tree, table["id"], params.get("limit", 50))
    for feature in usage["features"]:
        feature["url"] = f"/code-map/?pack={source.pack_id}#/feature/{_quote(feature['id'])}"
    return {"pack": source.pack_id, **usage}


def _quote(value: str) -> str:
    from urllib.parse import quote

    return quote(value, safe="")


HANDLERS = {"erd_model": erd_model, "db_objects": db_objects, "table_usage": table_usage}


def call(hub, name: str, params: dict[str, Any]) -> dict[str, Any]:
    handler = HANDLERS.get(name)
    if handler is None:
        raise ExportError("export_unknown", f"Code map chưa có hàm cho export {name}", 404)
    try:
        return handler(hub, params)
    except erd.ErdError as exc:
        raise ExportError(exc.code, exc.message, exc.status) from exc
    except GraphNotReady as exc:
        raise ExportError("graph_not_ready", exc.message or "Pack code-map chưa có dữ liệu (codemap.sqlite).", 503) from exc
    except Exception as exc:  # noqa: BLE001 - business errors carry their own code
        from viewer_hub.codemap.business import BusinessError

        if isinstance(exc, BusinessError):
            raise ExportError(exc.code, exc.message, exc.status) from exc
        raise
