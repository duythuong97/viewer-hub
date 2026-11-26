"""MCP server for document search (search.sqlite), built to keep an agent's token use low.

Two tools only, plain compact text (no HTML, no JSON blobs):
  search_documents  ranked hits: one line of metadata + one short snippet each (default 5)
  read_document     one document, either the passages around a query or a bounded slice

Transports: HTTP ``POST /ocr-search/mcp`` (routes.py) and stdio ``viewer-hub mcp search``.
Read-only: nothing here writes anywhere.
"""
from __future__ import annotations

import hashlib
import html
import re
import sqlite3
from contextlib import closing
from typing import Any, Callable, Iterable, Iterator

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
        "date_to": arguments.get("date_to") or "",
        "hl_enabled": True, "hl_plain": True, "hl_count": 1, "hl_size": SNIPPET_CHARS,
    }
    result = search_store.search(path, p)
    if result.get("error"):
        raise ToolError(result["error"])
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
        marked = result["highlighting"].get(doc.get("id", ""), {})
        for field in ("content", "source_code_content", "image_orc_text"):
            if marked.get(field):
                snippet = ("[OCR] " if field == "image_orc_text" else "") + _plain(marked[field][0])
                break
        if not snippet:
            snippet = _clip(doc.get("preview") or "", SNIPPET_CHARS)
        if snippet:
            lines.append(f"    {snippet}")
    more = total - offset - len(result["docs"])
    if more > 0:
        lines.append(f"{more} more: offset={offset + len(result['docs'])}.")
    lines.append('Next: read_document(id, query="…") for the passages that matter.')
    return "\n".join(lines)


_FIELDS = (("content", "TEXT"), ("source_code_content", "CODE"), ("image_orc_text", "OCR"))


def _stripped(chunks: Iterable[str]) -> Iterator[str]:
    """The chunks without the white space at the start and end of the whole text."""
    pending, started = "", False
    for chunk in chunks:
        if not started:
            chunk = chunk.lstrip()
            started = bool(chunk)
        body = chunk.rstrip()
        if body:
            yield pending + body
            pending = chunk[len(body):]
        elif started:
            pending += chunk


def _fingerprint(db: sqlite3.Connection, rid: int, field: str) -> bytes | None:
    """Digest of a field's text without surrounding white space, or None when there is none."""
    digest, found = hashlib.sha256(), False
    for chunk in _stripped(search_store.field_chunks(db, rid, field)):
        digest.update(chunk.encode("utf-8"))
        found = True
    return digest.digest() if found else None


def _document(db: sqlite3.Connection, rid: int, fields: list[tuple[str, str]]) -> Iterator[str]:
    """The text of a document as one stream: its fields, each headed by a label when there is more than one."""
    for index, (field, label) in enumerate(fields):
        if len(fields) > 1:
            yield ("\n\n" if index else "") + f"[{label}]\n"
        yield from _stripped(search_store.field_chunks(db, rid, field))


def _slice(chunks: Iterable[str], offset: int, size: int) -> tuple[str, int]:
    """(characters offset … offset + size, total number of characters), holding only the slice."""
    parts, total = [], 0
    for chunk in chunks:
        low, high = max(0, offset - total), min(len(chunk), offset + size - total)
        if high > low:
            parts.append(chunk[low:high])
        total += len(chunk)
    return "".join(parts), total


def read_document(path, arguments: dict) -> str:
    doc_id = str(arguments.get("id") or "").strip()
    if not doc_id:
        raise ToolError("id is required")
    db = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    with closing(db):
        row = db.execute("SELECT rowid, substr(title, 1, 500), substr(file_path, 1, 2000), repository "
                         "FROM docs WHERE id = ?", (doc_id,)).fetchone()
        if row is None:
            raise ToolError(f"No document with id {doc_id}; take ids from search_documents.")
        rid = row[0]
        fields, seen = [], set()
        for field, label in _FIELDS:
            fingerprint = _fingerprint(db, rid, field)
            if fingerprint and fingerprint not in seen:
                seen.add(fingerprint)
                fields.append((field, label))
        header = " | ".join(x for x in (doc_id, *row[1:]) if x)
        query = str(arguments.get("query") or "").strip()
        max_chars = _int(arguments, "max_chars", DEFAULT_READ, 200, MAX_READ)
        offset = _int(arguments, "offset", 0, 0, 2**31)
        if query:
            terms = [t.text for t in search_store.parse_terms(query) if not t.negate]
            passages = highlight.snippets(_document(db, rid, fields), terms, count=MAX_PASSAGES, size=PASSAGE_CHARS)
            if passages:
                total = _slice(_document(db, rid, fields), 0, 0)[1]
                body = "\n…\n".join(_plain(p) for p in passages)[:max_chars]
                return f"{header}\n{total} chars; {len(passages)} passage(s) around «{query}»:\n…{body}…"
            header += f"\n(no passage matches «{query}»; showing the start)"
        chunk, total = _slice(_document(db, rid, fields), offset, max_chars)
    offset = min(offset, total)
    end = offset + len(chunk)
    tail = f"\n[{total - end} chars left: offset={end}]" if end < total else "\n[end]"
    return f"{header}\nchars {offset}-{end} of {total}:\n{chunk}{tail}"


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
