"""MCP server for document search (search.sqlite), built to keep an agent's token use low.

Two tools only, plain compact text (no HTML, no JSON blobs):
  search_documents  ranked hits: one line of metadata + one short snippet each (default 5)
  read_document     one document, either the passages around a query or a bounded slice

Transports: HTTP ``POST /ocr-search/mcp`` (routes.py) and stdio ``viewer-hub mcp search``.
Read-only: nothing here writes anywhere.
"""
from __future__ import annotations

import html
import re
import sqlite3
from contextlib import closing
from typing import Any, Callable

from viewer_hub.core.mcp import ToolError, dispatch
from viewer_hub.core.mcp import int_arg as _int
from viewer_hub.core.mcp import serve_stdio as _serve_stdio
from viewer_hub.fsearch import highlight
from viewer_hub.fsearch import store as search_store

SNIPPET_CHARS = 180
DEFAULT_LIMIT, MAX_LIMIT = 5, 20
DEFAULT_READ, MAX_READ = 3000, 12000
PASSAGE_CHARS, MAX_PASSAGES = 500, 4
_WS = re.compile(r"\s+")

INSTRUCTIONS = (
    "Full-text search over the user's indexed documents, source code and OCR'd scans "
    "(English, Vietnamese incl. without diacritics, Japanese). Call search_documents first "
    "(small limit), then read_document on the 1-2 best ids, preferably with `query` so only "
    "matching passages come back. Quote ids and paths in answers."
)

TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_documents",
        "description": (
            "Search documents/code/OCR. Returns per hit: id, title, path, repository, type, date and one short "
            "snippet with matches in «». Syntax: words (OR by default), \"exact phrase\", -exclude. Use filters to narrow "
            "instead of raising limit."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keywords; Vietnamese works without diacritics."},
                "match": {"type": "string", "enum": ["any", "all"], "description": "any = OR (default), all = AND"},
                "repository": {"type": "string"},
                "file_type": {"type": "string", "description": "e.g. pdf, md, py, xlsx"},
                "language": {"type": "string", "enum": ["en", "ja", "vi"]},
                "date_from": {"type": "string", "description": "YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "YYYY-MM-DD"},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT, "default": DEFAULT_LIMIT},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "read_document",
        "description": (
            "Read one document by id from search_documents. With `query`: only the passages around the matches "
            "(cheapest). Without: a slice of the text from `offset` up to `max_chars`; the reply says the next offset."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "query": {"type": "string", "description": "Return only passages containing these words."},
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "max_chars": {"type": "integer", "minimum": 200, "maximum": MAX_READ, "default": DEFAULT_READ},
            },
            "required": ["id"],
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
]




def _plain(fragment: str) -> str:
    """Snippet from highlight.py (HTML-escaped, <mark>) → plain text with «» marks."""
    return html.unescape(fragment.replace("<mark>", "«").replace("</mark>", "»"))


def _clip(text: str, size: int) -> str:
    text = _WS.sub(" ", text or "").strip()
    return text if len(text) <= size else text[: size - 1].rstrip() + "…"


def search_documents(path, arguments: dict) -> str:
    query = str(arguments.get("query") or "").strip()
    if not query:
        raise ToolError("query is required")
    limit = _int(arguments, "limit", DEFAULT_LIMIT, 1, MAX_LIMIT)
    offset = _int(arguments, "offset", 0, 0, 100000)
    p = {
        "query": query, "operator": "AND" if arguments.get("match") == "all" else "OR",
        "rows": limit, "start": offset, "page": offset // limit + 1, "sort_val": "score desc",
        "repository": [arguments["repository"]] if arguments.get("repository") else [],
        "file_type": [arguments["file_type"]] if arguments.get("file_type") else [],
        "language": arguments.get("language") or "", "date_from": arguments.get("date_from") or "",
        "date_to": arguments.get("date_to") or "", "hl_enabled": False,
    }
    result = search_store.search(path, p)
    if result.get("error"):
        raise ToolError(result["error"])
    terms = [t.text for t in search_store.parse_terms(query) if not t.negate]
    total = result["num_found"]
    if not result["docs"]:
        return f'0 results for "{query}". Try fewer words, match=any, or drop filters.'
    lines = [f'{total} results for "{query}" (showing {offset + 1}-{offset + len(result["docs"])}):']
    for index, doc in enumerate(result["docs"], start=offset + 1):
        meta = [doc.get("id", ""), _clip(doc.get("title") or "", 80) or "(no title)"]
        if doc.get("file_path"):
            meta.append(doc["file_path"])
        for key in ("repository", "file_type"):
            if doc.get(key):
                meta.append(str(doc[key]))
        if doc.get("last_modified"):
            meta.append(str(doc["last_modified"])[:10])
        lines.append(f"[{index}] " + " | ".join(meta))
        snippet = ""
        for field in ("content", "source_code_content", "image_orc_text"):
            found = highlight.snippets(doc.get(field), terms, count=1, size=SNIPPET_CHARS)
            if found:
                snippet = ("[OCR] " if field == "image_orc_text" else "") + _plain(found[0])
                break
        if not snippet:
            snippet = _clip(doc.get("content") or doc.get("source_code_content") or doc.get("image_orc_text") or "", SNIPPET_CHARS)
        if snippet:
            lines.append(f"    {snippet}")
    more = total - offset - len(result["docs"])
    if more > 0:
        lines.append(f"{more} more: offset={offset + len(result['docs'])}.")
    lines.append('Next: read_document(id, query="…") for the passages that matter.')
    return "\n".join(lines)


def _load(path, doc_id: str) -> sqlite3.Row | None:
    db = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    with closing(db):
        return db.execute("SELECT * FROM docs WHERE id = ?", (doc_id,)).fetchone()


def read_document(path, arguments: dict) -> str:
    doc_id = str(arguments.get("id") or "").strip()
    if not doc_id:
        raise ToolError("id is required")
    row = _load(path, doc_id)
    if row is None:
        raise ToolError(f"No document with id {doc_id}; take ids from search_documents.")
    parts = []
    for field, label in (("content", "TEXT"), ("source_code_content", "CODE"), ("image_orc_text", "OCR")):
        value = (row[field] or "").strip()
        if value and value not in [p[1] for p in parts]:
            parts.append((label, value))
    text = "\n\n".join(f"[{label}]\n{value}" for label, value in parts) if len(parts) > 1 else (parts[0][1] if parts else "")
    header = " | ".join(x for x in (doc_id, row["title"] or "", row["file_path"] or "", row["repository"] or "") if x)
    query = str(arguments.get("query") or "").strip()
    max_chars = _int(arguments, "max_chars", DEFAULT_READ, 200, MAX_READ)
    if query:
        terms = [t.text for t in search_store.parse_terms(query) if not t.negate]
        passages = highlight.snippets(text, terms, count=MAX_PASSAGES, size=PASSAGE_CHARS)
        if passages:
            body = "\n…\n".join(_plain(p) for p in passages)[:max_chars]
            return f"{header}\n{len(text)} chars; {len(passages)} passage(s) around «{query}»:\n…{body}…"
        header += f"\n(no passage matches «{query}»; showing the start)"
    offset = _int(arguments, "offset", 0, 0, max(0, len(text)))
    chunk = text[offset: offset + max_chars]
    end = offset + len(chunk)
    tail = f"\n[{len(text) - end} chars left: offset={end}]" if end < len(text) else "\n[end]"
    return f"{header}\nchars {offset}-{end} of {len(text)}:\n{chunk}{tail}"


HANDLERS: dict[str, Callable] = {"search_documents": search_documents, "read_document": read_document}


def handle(message: Any, resolve_path: Callable[[], Any]) -> dict | list | None:
    """One JSON-RPC message (or batch). ``resolve_path`` returns the search.sqlite to use, or None."""
    def run(name: str, arguments: dict) -> str:
        path = resolve_path()
        if path is None:
            raise ToolError("No search data on this PC yet (no data pack with documents). Ask the admin.")
        return HANDLERS[name](path, arguments)

    return dispatch(message, name="viewer-hub-search", title="F-Search", instructions=INSTRUCTIONS, tools=TOOLS, run=run)


def serve_stdio(resolve_path: Callable[[], Any]) -> int:
    return _serve_stdio(lambda message: handle(message, resolve_path))
