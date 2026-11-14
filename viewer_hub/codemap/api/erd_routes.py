"""ERD API over the request's code-map pack (``g.codemap``, set by mount.py); reads codemap.sqlite read-only.

* ``GET /code-map/api/erd?table=|schema=|system=&depth=1|2&format=json|mermaid|dbml[&download=1][&keys=1]``
* ``GET /code-map/api/erd/tables?q=&schema=`` — table picker (technical and ja/en logical names) + schema list.
"""
from __future__ import annotations

from flask import Blueprint, Response, g, jsonify, request

from viewer_hub.codemap import erd
from viewer_hub.codemap.storage import open_search

bp = Blueprint("erd_api", __name__, url_prefix="/api/erd")
MIMETYPES = {"mermaid": "text/plain", "dbml": "text/plain", "json": "application/json"}


@bp.errorhandler(erd.ErdError)
def erd_error(exc: erd.ErdError):
    return jsonify({"error": {"code": exc.code, "message": exc.message, "details": exc.details}}), exc.status


def _arg(name: str, limit: int = 300) -> str:
    value = request.args.get(name, "").strip()
    if len(value) > limit:
        raise erd.ErdError("bad_argument", f"{name} dài quá {limit} ký tự.")
    return value


def _flag(name: str) -> bool:
    return request.args.get(name, "0").lower() in {"1", "true", "yes"}


@bp.get("")
def erd_model():
    fmt = _arg("format") or "json"
    if fmt not in MIMETYPES:
        raise erd.ErdError("bad_format", "format phải là json, mermaid hoặc dbml.")
    depth = _arg("depth") or "1"
    if depth not in {"1", "2"}:
        raise erd.ErdError("bad_depth", "depth phải là 1 hoặc 2.")
    with open_search(g.codemap.output) as db:
        model = erd.build(db, table=_arg("table"), schema=_arg("schema"), system=_arg("system"), depth=int(depth))
    download = _flag("download")
    if fmt == "json" and not download:
        return jsonify(model)
    text = erd.render(model, fmt, keys_only=_flag("keys"))
    response = Response(text, mimetype=MIMETYPES[fmt])
    response.charset = "utf-8"
    if download:
        response.headers["Content-Disposition"] = f'attachment; filename="{erd.filename(model, fmt)}"'
    return response


@bp.get("/tables")
def erd_tables():
    limit = _arg("limit") or "30"
    if not limit.isdigit():
        raise erd.ErdError("bad_argument", "limit phải là số.")
    with open_search(g.codemap.output) as db:
        return jsonify(erd.search_tables(db, _arg("q"), schema=_arg("schema"), limit=int(limit)))
