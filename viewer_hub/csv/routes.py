"""CSV: the page (React, web/src/modules/csv) and its JSON API: datasets, rows, export, column settings."""
from __future__ import annotations

import json
import secrets

from flask import Blueprint, Response, g, request

from viewer_hub.app import spa

from viewer_hub.csv.store import OPERATORS, CsvError, CsvStore, Dataset, export_csv

bp = Blueprint("csv", __name__)


def store() -> CsvStore:
    from viewer_hub.packs.content import pack_dirs

    return CsvStore(g.hub.paths.csv, g.hub.paths.tmp, packs=pack_dirs(g.hub, "csv"))


def _writable(dataset: Dataset) -> Dataset:
    if dataset.readonly:  # shipped in a data pack: column settings and delete belong to the admin
        raise spa.ApiError("readonly_dataset", "File trong data pack do admin cung cấp, chỉ đọc", 403)
    return dataset


def _dataset(dataset_id: str) -> Dataset:
    dataset = store().get(dataset_id)
    if not dataset:
        raise spa.ApiError("not_found", "Không có bộ dữ liệu này", 404)
    return dataset


def _register(dataset: Dataset) -> None:
    with g.hub.db.write() as db:
        db.execute(
            """INSERT INTO datasets (id, title, origin, schema, rows, needs_rebuild, created_at, updated_at)
               VALUES (?, ?, 'workspace', ?, ?, 0, ?, ?)
               ON CONFLICT(id) DO UPDATE SET title=excluded.title, rows=excluded.rows,
                 schema=excluded.schema, needs_rebuild=0, updated_at=excluded.updated_at""",
            (dataset.id, dataset.title, dataset.meta["schema"], dataset.meta.get("rows", 0),
             dataset.meta["createdAt"], dataset.meta["updatedAt"]),
        )


LAST_KEY = "csv.last"


def _summary(d: Dataset) -> dict:
    return {"id": d.id, "title": d.title, "rows": d.meta.get("rows", 0), "columns": len(d.columns),
            "visibleColumns": len(d.visible), "description": d.description, "mcp": d.mcp, "readonly": bool(d.readonly),
            "file": (d.meta.get("source") or {}).get("filename", ""), "pack": (d.meta.get("pack") or {}).get("title", "")}


def _column(c: dict) -> dict:
    return {"key": c["key"], "name": c["name"], "label": c.get("label") or "", "description": c.get("description") or "",
            "type": c.get("type", "text"), "visible": bool(c.get("visible", True)), "filter": bool(c.get("filter")),
            "op": c.get("op", "IN")}


@bp.get("/")
@bp.get("/<dataset_id>")
def index(dataset_id: str | None = None):
    return spa.page()


@bp.get("/api/datasets")
def list_datasets():
    """Every dataset, and the one to open by default (the last viewed, like the old csv-viewer)."""
    datasets = store().list()
    saved = g.hub.db.setting(LAST_KEY)
    last = saved if any(d.id == saved for d in datasets) else (datasets[0].id if datasets else "")
    return {"datasets": [_summary(d) for d in datasets], "last": last}


@bp.post("/api/datasets")
def upload():
    files = [f for f in request.files.getlist("file") if f and f.filename]
    if not files:
        raise spa.ApiError("no_files", "Chưa chọn file CSV.")
    created, skipped = [], []
    for item in files:
        if not item.filename.lower().endswith((".csv", ".tsv", ".txt")):
            skipped.append(f"Bỏ qua {item.filename}: chỉ nhận .csv, .tsv, .txt")
            continue
        temp = g.hub.paths.tmp / f"upload-{secrets.token_hex(6)}.csv"
        item.save(temp)
        try:
            dataset = store().create(temp, item.filename)
        except (CsvError, UnicodeError) as error:
            temp.unlink(missing_ok=True)
            skipped.append(f"{item.filename}: {error}")
            continue
        _register(dataset)
        created.append(_summary(dataset))
    if not created:
        raise spa.ApiError("no_dataset", "; ".join(skipped) or "Không tải được file nào")
    # Next: name, describe and choose "Cho AI đọc" for what was just uploaded (a dialog on the page).
    return {"created": created, "skipped": skipped,
            "message": f"Đã tải {len(created)} file. Thêm mô tả để người xem và AI biết file là gì."}


@bp.get("/api/datasets/<dataset_id>")
def dataset(dataset_id: str):
    current = _dataset(dataset_id)
    if not g.hub.readonly:
        g.hub.db.set_setting(LAST_KEY, current.id)
    return {**_summary(current), "columnList": [_column(c) for c in current.columns],
            "visible": [_column(c) for c in current.visible], "defaults": current.default_filters,
            "operators": list(OPERATORS)}


@bp.patch("/api/datasets/<dataset_id>")
def info(dataset_id: str):
    """Name, description and "Cho AI đọc" (the describe and edit dialogs)."""
    dataset = _writable(_dataset(dataset_id))
    body = request.get_json(silent=True) or {}
    title = str(body.get("title", "")).strip()
    if title:
        dataset.meta["title"] = title[:120]
    if "description" in body:
        dataset.meta["description"] = str(body.get("description") or "").strip()[:2000]
    if "mcp" in body:
        dataset.meta["mcp"] = bool(body.get("mcp"))
    dataset.save()
    _register(dataset)
    return {"dataset": _summary(dataset), "message": f"Đã lưu thông tin {dataset.title}"}


@bp.put("/api/datasets/<dataset_id>/columns")
def settings(dataset_id: str):
    """Column settings: display name, description (AI reads it), shown, default filter, operator."""
    dataset = _writable(_dataset(dataset_id))
    wanted = {c.get("key"): c for c in (request.get_json(silent=True) or {}).get("columns", []) if isinstance(c, dict)}
    for column in dataset.columns:
        new = wanted.get(column["key"])
        if new is None:
            continue
        column["visible"] = bool(new.get("visible"))
        column["filter"] = bool(new.get("filter"))
        column["op"] = new.get("op") if new.get("op") in OPERATORS else "IN"
        column["label"] = str(new.get("label") or "").strip()[:120] or None
        column["description"] = str(new.get("description") or "").strip()[:500] or None
    if not dataset.visible:
        raise spa.ApiError("no_columns", "Cần ít nhất một cột hiển thị.")
    dataset.save()
    _register(dataset)
    return {"message": "Đã lưu cấu hình cột"}


def _query_args(dataset: Dataset) -> dict:
    try:
        rules = json.loads(request.args.get("filters", "[]"))
    except ValueError as exc:
        raise spa.ApiError("bad_filters", "Bộ lọc không hợp lệ") from exc
    if not isinstance(rules, list):
        raise spa.ApiError("bad_filters", "Bộ lọc không hợp lệ")
    keys = {c["key"] for c in dataset.columns}
    return {
        "text": request.args.get("q", ""),
        "rules": [r for r in rules if isinstance(r, dict) and r.get("column") in keys and r.get("operator", "IN") in OPERATORS],
    }


@bp.get("/api/datasets/<dataset_id>/rows")
def rows(dataset_id: str):
    dataset = _dataset(dataset_id)
    args = _query_args(dataset)
    limit = min(max(int(request.args.get("limit", 50)), 1), 1000)
    offset = max(int(request.args.get("offset", 0)), 0)
    result = dataset.search(**args, sort=request.args.get("sort") or None,
                            desc=request.args.get("desc") == "1", offset=offset, limit=limit)
    return {"total": result["total"], "rows": result["rows"], "offset": offset, "limit": limit,
            "columns": [{"key": c["key"], "name": c.get("label") or c["name"], "type": c["type"]} for c in result["columns"]]}


@bp.get("/api/datasets/<dataset_id>/export.csv")
def export(dataset_id: str):
    dataset = _dataset(dataset_id)
    rows_iter = dataset.iter_rows(**_query_args(dataset))
    name = f"{dataset.id}.csv"
    return Response(export_csv(dataset, rows_iter), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@bp.delete("/api/datasets/<dataset_id>")
def delete(dataset_id: str):
    dataset = _writable(_dataset(dataset_id))
    store().delete(dataset)
    with g.hub.db.write() as db:
        db.execute("DELETE FROM datasets WHERE id = ?", (dataset.id,))
    return {"message": f"Đã xoá {dataset.title}"}


@bp.route("/mcp", methods=["POST", "GET", "DELETE"])
def mcp_endpoint():
    """MCP (streamable HTTP) over the CSV files shared with AI; see csv/mcp.py."""
    from viewer_hub.core.mcp import http_endpoint
    from viewer_hub.csv import mcp

    current = store()
    return http_endpoint(request, lambda message: mcp.handle(message, lambda: current))
