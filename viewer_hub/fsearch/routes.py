"""F-Search: the page (React, web/src/modules/fsearch) and its JSON API, ported from ocr-demo `main` app.py
(Solr → SQLite). The URL parameters are the old ones, so bookmarks keep working."""
from __future__ import annotations

import platform
import subprocess
from ntpath import basename as nt_basename
from pathlib import Path
from posixpath import basename as posix_basename
from urllib.parse import quote

from flask import Blueprint, current_app, g, jsonify, request

from viewer_hub.app import spa

from viewer_hub.fsearch import store as search_store
from viewer_hub.fsearch.store import SearchStore

bp = Blueprint("fsearch", __name__)

DEFAULT_ROWS = 10
LANGUAGES = [("", "Tất cả ngôn ngữ"), ("en", "English"), ("ja", "日本語"), ("vi", "Tiếng Việt")]
SORT_OPTIONS = [
    ("score desc", "Liên quan nhất"),
    ("last_modified desc", "Mới nhất"),
    ("last_modified asc", "Cũ nhất"),
    ("title asc", "Tên A→Z"),
    ("title desc", "Tên Z→A"),
]
GROUP_OPTIONS = [("", "Không nhóm"), ("file_path", "File"), ("repository", "Repository"),
                 ("file_type", "Loại file"), ("author", "Tác giả"), ("language", "Ngôn ngữ")]
LOCAL_ROOT_KEY = "ocr.localFileRoot"


def _int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_form(args) -> dict:
    """Same parameters as the Solr app, so old bookmarks keep working."""
    rows = min(max(_int(args.get("rows"), DEFAULT_ROWS), 1), 100)
    page = max(_int(args.get("page"), 1), 1)
    return {
        "query": args.get("q", "").strip(),
        "phrase_mode": args.get("phrase", "") == "1",
        "exact_terms": args.get("exact", "") == "1",
        "fuzzy": args.get("fuzzy", "0").strip(),
        "proximity": args.get("proximity", "0").strip(),
        "operator": "AND" if args.get("op") == "AND" else "OR",
        "parser": args.get("parser", "edismax"),
        "boost_func": args.get("bf", "").strip(),
        "debug_mode": args.get("debug", "") == "1",
        "language": args.get("lang", "").strip(),
        "repository": [v.strip() for v in args.getlist("repository") if v.strip()],
        "file_type": [v for part in args.getlist("file_type") for v in part.split(",") if v.strip()],
        "date_from": args.get("date_from", "").strip(),
        "date_to": args.get("date_to", "").strip(),
        "extra_fq": args.get("fq", "").strip(),
        "sort_val": args.get("sort", "score desc"),
        "rows": rows,
        "page": page,
        "start": (page - 1) * rows,
        "mm_val": args.get("mm", "").strip(),
        "group_by": args.get("group_by", "").strip(),
        "hl_enabled": args.get("hl", "1") != "0",
        "pack": args.get("pack", "").strip(),
    }


def _has_input(p: dict) -> bool:
    return bool(p["query"] or p["language"] or p["repository"] or p["file_type"] or p["date_from"] or p["date_to"])


def _local_root() -> Path | None:
    value = g.hub.db.setting(LOCAL_ROOT_KEY)
    if not value:
        return None
    root = Path(value)
    return root if root.is_dir() else None


# ── Results as JSON ──────────────────────────────────────────────────────────────────

def _text(value) -> str:
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value or "")


def _basename(value: str) -> str:
    return nt_basename(value) if "\\" in value else posix_basename(value)


def repository_href(doc: dict) -> str | None:
    direct = doc.get("url")
    if direct and str(direct).startswith(("http://", "https://")):
        return direct
    file_path, repo_path = doc.get("file_path"), doc.get("repository_path")
    if repo_path and str(repo_path).startswith(("http://", "https://")):
        if not file_path:
            return repo_path
        return f"{repo_path.rstrip('/')}/{quote(str(file_path).lstrip('/'), safe='/:@')}"
    return None


def _local_file(doc: dict, root: Path | None) -> bool:
    if not root or not doc.get("file_path"):
        return False
    path = Path(_text(doc["file_path"]))
    return (path if path.is_absolute() else root / path).exists()


def _doc(doc: dict, hl: dict, root: Path | None) -> dict:
    """One result for the page. Highlight snippets are HTML-escaped text with <mark> (fsearch/highlight.py)."""
    path = _text(doc.get("file_path"))
    code = hl.get("source_code_content") or []
    snippets = code or hl.get("content") or hl.get("image_orc_text") or []
    kind = "code" if code else ("ocr" if hl.get("image_orc_text") else "text")
    plain = ""  # no highlight: the start of the text, shown as plain text
    if not snippets:
        for field, size in (("source_code_content", 1200), ("image_orc_text", 300), ("content", 300)):
            if doc.get(field):
                plain, kind = _text(doc[field])[:size], ("code" if field == "source_code_content" else "text")
                break
    title_hl = hl.get("title") or []
    return {
        "id": _text(doc.get("id")), "titleHtml": title_hl[0] if title_hl else "",
        "title": _text(doc.get("title")) or _basename(path) or _text(doc.get("id")), "path": path,
        "kind": kind, "snippets": snippets, "plain": plain, "fileType": _text(doc.get("file_type")),
        "repository": _text(doc.get("repository")), "author": _text(doc.get("author")),
        "modified": _text(doc.get("last_modified"))[:10], "href": repository_href(doc),
        "local": _local_file(doc, root),
    }


# ── Routes ───────────────────────────────────────────────────────────────────────────

@bp.get("/")
@bp.get("/search")
def index():
    return spa.page()


@bp.get("/api/search")
def api_search():
    p = parse_form(request.args)
    sources = SearchStore.for_hub(g.hub)
    source = sources.pick(p["pack"])
    data = search_store.search(source[2], p) if source and _has_input(p) else None
    # Repository / file type pickers in the toolbar need their values before the first search too.
    facets = data["facets"] if data and not data.get("error") else (
        search_store.search(source[2], {**p, "query": "", "rows": 0, "hl_enabled": False})["facets"] if source else {})
    root = _local_root()
    result = None
    if data is not None:
        hl = data.get("highlighting") or {}
        convert = lambda docs: [_doc(d, hl.get(d.get("id", ""), {}), root) for d in docs]  # noqa: E731
        result = {"error": data.get("error"), "notices": data.get("notices") or [], "engine": data.get("engine", ""),
                  "grouped": bool(data.get("grouped")), "numFound": data.get("num_found", 0),
                  "page": data.get("page", 1), "totalPages": data.get("total_pages", 0),
                  "docs": convert(data.get("docs") or []),
                  "groups": [{"key": grp["key"], "count": grp["count"], "docs": convert(grp["docs"])}
                             for grp in data.get("groups") or []],
                  "debug": data.get("debug") if p["debug_mode"] else None}
    return {"sources": [{"id": s[0], "title": s[1]} for s in sources.sources], "source": source[0] if source else "",
            "facets": {k: [[v, c] for v, c in vals] for k, vals in facets.items()}, "search": result,
            "localRoot": str(root) if root else "",
            "options": {"languages": LANGUAGES, "sort": SORT_OPTIONS, "group": GROUP_OPTIONS}}


@bp.get("/api/search/groups/<path:group_key>/items")
def search_group_items(group_key):
    """Trả về thêm các item con của một nhóm cụ thể khi user nhấn 'Xem thêm'."""
    p = parse_form(request.args)
    limit = min(max(_int(request.args.get("limit"), 15), 1), 100)
    offset = max(_int(request.args.get("offset"), 10), 0)
    sources = SearchStore.for_hub(g.hub)
    source = sources.pick(p["pack"])
    if not source:
        return {"items": [], "group_key": group_key, "offset": offset}
    docs, hl = search_store.get_group_items(source[2], p, group_key, limit=limit, offset=offset)
    root = _local_root()
    convert = lambda ds: [_doc(d, hl.get(d.get("id", ""), {}), root) for d in ds]  # noqa: E731
    return {"items": convert(docs), "group_key": group_key, "offset": offset}


@bp.route("/mcp", methods=["POST", "GET", "DELETE"])
def mcp_endpoint():
    """MCP (streamable HTTP, JSON replies only) for AI agents; see fsearch/mcp.py."""
    from viewer_hub.core.mcp import http_endpoint
    from viewer_hub.fsearch import mcp

    pack = request.args.get("pack") or None
    hub = g.hub

    def resolve():
        source = SearchStore.for_hub(hub).pick(pack)
        return source[2] if source else None

    return http_endpoint(request, lambda message: mcp.handle(message, resolve))


@bp.post("/api/local-root")
def set_local_root():
    value = str((request.get_json(silent=True) or {}).get("path") or "").strip()
    if value and not Path(value).is_dir():
        return jsonify(error="Thư mục không tồn tại"), 400
    g.hub.db.set_setting(LOCAL_ROOT_KEY, value)
    return jsonify(ok=True, path=value)


@bp.get("/api/open-file")
def api_open_file():
    """Reveal a file in Explorer/Finder. Off until the user sets a local root; paths must stay under it."""
    root = _local_root()
    if not root:
        return jsonify(error="Chưa cấu hình thư mục file gốc"), 403
    raw = request.args.get("path", "").strip()
    if not raw:
        return jsonify(error="Thiếu đường dẫn"), 400
    path = Path(raw)
    path = (path if path.is_absolute() else root / path).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return jsonify(error="Đường dẫn nằm ngoài thư mục cho phép"), 403
    if not path.exists():
        return jsonify(error="Không tìm thấy file"), 404
    system = platform.system()
    try:
        # Direct executables with an argument list (no shell); see GUIDELINE §5.
        if system == "Windows":
            subprocess.Popen(["explorer.exe", f"/select,{path}"])
        elif system == "Darwin":
            subprocess.Popen(["open", "-R", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path.parent)])
    except OSError as exc:
        current_app.logger.error("open-file failed: %s", exc)
        return jsonify(error="Không mở được file"), 500
    return jsonify(ok=True)
