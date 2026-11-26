"""Search over search.sqlite with the same result shape the Solr version returned.

Supported from the old form: free text, OR/AND, phrase, exact terms, proximity
(NEAR), -negation, language / repository / file_type / date filters, facets with
multi-select, sort, paging, group by, highlighting.
Not supported (shown as a notice): fuzzy, lucene/dismax parser, raw fq, bf, mm.
"""
from __future__ import annotations

import codecs
import logging
import math
import re
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from viewer_hub.core.atomic import read_json
from viewer_hub.fsearch import highlight, schema

logger = logging.getLogger(__name__)

GROUP_LIMIT = 10
GROUP_PAGE_DOCS = 100  # documents one grouped page shows in all (fewer per group when there are many groups)
HIGHLIGHT_BUDGET = 3.0  # seconds for the snippets of one page; the documents left over are shown without
HIGHLIGHT_SCAN = 32 * 1024 * 1024  # bytes of one field read looking for matches
CHUNK_BYTES = 64 * 1024
PREVIEW_CHARS = 1200
BODY_FIELDS = ("source_code_content", "image_orc_text", "content")  # large text, read in chunks only
MAX_PARALLEL = 2   # searches running at once; the others wait their turn
QUEUE_WAIT = 30.0
_RUNNING = threading.BoundedSemaphore(MAX_PARALLEL)
BUSY = "F-Search đang bận với các lần tìm khác. Hãy thử lại sau ít giây."
NO_MEMORY = "Máy không đủ bộ nhớ cho lần tìm này. Hãy thêm từ khoá cụ thể hơn hoặc lọc theo Repository / Loại file."
TOO_SLOW = "Một số kết quả không có đoạn trích vì tài liệu quá lớn; thêm từ khoá hoặc lọc để thu hẹp."
RANK_LIMIT = 20000   # bm25 is computed only for queries matching at most this many documents (see _select)
TIME_BUDGET = 8.0    # seconds one search may run before it is interrupted instead of hanging the page
_TOKEN = re.compile(r'(-?)"([^"]+)"|(-?)(\S+)')

SORTS = ("score desc", "last_modified desc", "last_modified asc", "title asc", "title desc")


@dataclass
class Term:
    text: str
    negate: bool = False
    quoted: bool = False  # written in "…": matched as whole words, never as a prefix


def parse_terms(query: str) -> list[Term]:
    terms = []
    for neg1, phrase, neg2, word in _TOKEN.findall(query or ""):
        text = (phrase or word).strip()
        if text and text not in {"AND", "OR", "NOT", "*", "*:*"}:
            terms.append(Term(text, bool(neg1 or neg2), bool(phrase)))
    return terms


def _quote(text: str) -> str:
    return '"' + text.replace('"', '""') + '"'


def _word(term: Term, p: dict) -> str:
    """A term as typed matches the word itself or any word it starts ("au" finds "audit", "author"), the exact
    word ranking first because it matches both. Quoted terms and "Từng từ chính xác" match whole words only."""
    if term.quoted or p.get("exact_terms"):
        return _quote(term.text)
    return f"({_quote(term.text)} OR {_quote(term.text)}*)"


def build_match(p: dict, terms: list[Term]) -> str | None:
    positive = [t.text for t in terms if not t.negate]
    negative = [t.text for t in terms if t.negate]
    if not positive:
        return None
    try:
        prox = int(p.get("proximity") or 0)
    except ValueError:
        prox = 0
    if prox > 0 and len(positive) > 1:
        expr = f"NEAR({' '.join(_quote(t) for t in positive)}, {prox})"
    elif p.get("phrase_mode"):
        expr = _quote(" ".join(positive))
    else:
        joiner = " AND " if p.get("operator") == "AND" else " OR "
        expr = joiner.join(_word(t, p) for t in terms if not t.negate)
    for t in negative:
        expr = f"({expr}) NOT {_quote(t)}"
    return expr


class SearchStore:
    """The search.sqlite files of active packs; one is searched at a time."""

    def __init__(self, sources: list[tuple[str, str, Path]]):
        self.sources = sources  # (pack_id, title, path)

    @classmethod
    def for_hub(cls, hub) -> "SearchStore":
        sources = []
        for row in hub.db.query("SELECT id, version, title FROM packs WHERE active = 1 ORDER BY title"):
            folder = hub.paths.packs / row["id"] / row["version"]
            pack = read_json(folder / "pack.json", {}) or {}
            component = (pack.get("components") or {}).get("search")
            if component:
                path = folder / component.get("path", "search/search.sqlite")
                if path.is_file():
                    sources.append((row["id"], row["title"], path))
        local = hub.paths.home / "search" / "search.sqlite"  # dev / single-user copy
        if local.is_file():
            sources.append(("local", "search.sqlite", local))
        return cls(sources)

    def pick(self, pack_id: str | None):
        for source in self.sources:
            if source[0] == pack_id:
                return source
        return self.sources[0] if self.sources else None

    def count(self) -> int:
        total = 0
        for _, _, path in self.sources:
            with closing(_connect(path)) as db:
                total += db.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
        return total


def _connect(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, check_same_thread=False)
    db.row_factory = sqlite3.Row
    return db


def _connect_limited(path: Path) -> sqlite3.Connection:
    """A connection that aborts a statement still running after TIME_BUDGET seconds (OperationalError "interrupted"),
    so one very broad query cannot keep the CPU busy for minutes behind a page nobody is looking at."""
    db = _connect(path)
    deadline = time.monotonic() + TIME_BUDGET
    db.set_progress_handler(lambda: time.monotonic() > deadline, 50000)
    return db


def _failure(error: sqlite3.OperationalError) -> str:
    if "interrupted" in str(error):
        return ("Truy vấn quá rộng nên bị dừng sau vài giây. Hãy thêm từ khoá cụ thể hơn, đặt trong \"…\", "
                "hoặc lọc theo Repository / Loại file.")
    return f"Không hiểu câu truy vấn: {error}"


def field_chunks(db: sqlite3.Connection, rid: int, column: str, limit: int | None = None,
                 deadline: float | None = None) -> Iterator[str]:
    """One text column of one document, piece by piece (incremental blob I/O): a document of any size costs one
    chunk of memory. ``limit``: stop after this many bytes; ``deadline`` (time.monotonic): stop when passed."""
    if db.execute(f"SELECT typeof({column}) FROM docs WHERE rowid = ?", [rid]).fetchone()[0] != "text":
        return
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    with db.blobopen("docs", column, rid, readonly=True) as blob:
        read = 0
        while (limit is None or read < limit) and (data := blob.read(CHUNK_BYTES)):
            read += len(data)
            if text := decoder.decode(data):
                yield text
            if deadline is not None and time.monotonic() > deadline:
                return
    if tail := decoder.decode(b"", final=True):
        yield tail


def preview(db: sqlite3.Connection, rid: int) -> tuple[str, str]:
    """(field, first characters) of the first large text field that has something: shown when nothing is marked."""
    for column in BODY_FIELDS:
        text = ""
        for chunk in field_chunks(db, rid, column, limit=CHUNK_BYTES):
            text = chunk[:PREVIEW_CHARS]
            break
        if text:
            return column, text
    return "", ""


def notices_for(p: dict) -> list[str]:
    out = []
    if str(p.get("fuzzy") or "0") not in {"", "0"}:
        out.append("Tìm gần đúng (fuzzy) không còn hỗ trợ; đang tìm chính xác theo từ.")
    if p.get("parser") not in (None, "", "edismax"):
        out.append("Parser lucene/dismax không còn; cú pháp được hiểu như tìm theo từ.")
    if p.get("extra_fq"):
        out.append("Bộ lọc fq tự do không còn hỗ trợ; đã bỏ qua.")
    if p.get("boost_func"):
        out.append("Boost function (bf) không còn hỗ trợ; đã bỏ qua.")
    if p.get("mm_val"):
        out.append("Minimum should match (mm) không còn hỗ trợ; dùng OR/AND.")
    return out


def _substring_eligible(p: dict, terms: list[Term]) -> bool:
    """A substring search can stand in for an empty word search: every term has 3+ characters (the trigram index's
    minimum) and none was asked to match exactly."""
    positive = [t for t in terms if not t.negate]
    return not (p.get("exact_terms") or p.get("phrase_mode") or any(t.quoted or len(t.text) < 3 for t in positive))


# Indexed columns (schema.DDL): read through their index, never through the docs row. The small columns come after
# the large text columns in a row, so reading one from the row walks the overflow pages of the whole document; on a
# pack of 200 000 files a join with docs for a facet or a sort took seconds, the index takes milliseconds.
_INDEXED = {"repository": "docs_repository", "file_type": "docs_file_type", "language": "docs_language",
            "last_modified": "docs_last_modified"}
_OPTIONAL_INDEXES = {"title": "docs_title", "file_path": "docs_file_path", "author": "docs_author"}  # newer packs
NO_GROUP = "(không có)"


@dataclass
class _Plan:
    engine: str
    match: str | None
    source_sql: str  # SELECT rid, score of the documents the query matches
    source_params: list
    positive: list[str]
    like_terms: list[str]
    fallback: "_Plan | None" = None  # tried when this one matches nothing
    rank_sql: str = ""  # same documents with the bm25 score, run only when few enough match
    rank_params: list | None = None
    ranked: bool = True  # False: too many matches to rank, ordered by date (notice shown)


def _plan(p: dict, with_score: bool) -> _Plan:
    """Which index answers the query (words, trigram, LIKE or every document); bm25 only when sorting by it."""
    terms = parse_terms(p.get("query", ""))
    positive = [t.text for t in terms if not t.negate]
    negative = [t.text for t in terms if t.negate]
    match = build_match(p, terms)
    weights = ", ".join(str(w) for w in schema.WEIGHTS)

    def fts(table: str, expr: str) -> tuple[str, list]:
        return f"SELECT rowid AS rid, 0.0 AS score FROM {table} WHERE {table} MATCH ?", [expr]

    def ranked(plan: _Plan) -> _Plan:
        if with_score and plan.engine in {"fts_word", "fts_tri"}:
            plan.rank_sql = (f"SELECT rowid AS rid, bm25({plan.engine}, {weights}) AS score FROM {plan.engine} "
                             f"WHERE {plan.engine} MATCH ?")
            plan.rank_params = [plan.match]
        return plan

    if match:
        cjk = any(highlight.has_cjk(t) for t in positive)
        if cjk and all(len(t) >= 3 for t in positive):
            return ranked(_Plan("fts_tri", match, *fts("fts_tri", match), positive, []))
        if cjk:
            # Trigram needs 3+ characters; short Japanese terms fall back to LIKE.
            joiner = " AND " if p.get("operator") == "AND" else " OR "
            parts, params = [], []
            for term in positive:
                parts.append("(" + " OR ".join(f"{f} LIKE ?" for f in schema.TEXT_FIELDS) + ")")
                params.extend([f"%{term}%"] * len(schema.TEXT_FIELDS))
            return _Plan("like", match, f"SELECT rowid AS rid, 0.0 AS score FROM docs WHERE {joiner.join(parts)}",
                         params, positive, positive)
        # No word starts with what was typed: look for it inside words ("dit" in "audit").
        tri = build_match({**p, "exact_terms": True}, terms)
        fallback = ranked(_Plan("fts_tri", tri, *fts("fts_tri", tri), positive, [])) if _substring_eligible(p, terms) else None
        return ranked(_Plan("fts_word", match, *fts("fts_word", match), positive, [], fallback))
    if negative:
        return _Plan("all", None, "SELECT rowid AS rid, 0.0 AS score FROM docs WHERE rowid NOT IN "
                     "(SELECT rowid FROM fts_word WHERE fts_word MATCH ?)",
                     [" OR ".join(_quote(t) for t in negative)], positive, [])
    return _Plan("all", None, "SELECT rowid AS rid, 0.0 AS score FROM docs", [], positive, [])


def _order_key(p: dict, plan: _Plan) -> str:
    key = p.get("sort_val") if p.get("sort_val") in SORTS else "score desc"
    if key == "score desc" and (plan.engine in {"all", "like"} or not plan.ranked):
        key = "last_modified desc"
    return key


def _hit_filters(p: dict, exclude: str | None = None) -> tuple[str, list]:
    """WHERE on the hit table (h.rid): every filter is on an indexed column, answered from its index."""
    where, params = [], []

    def on(column: str, condition: str, values: list) -> None:
        where.append(f"h.rid IN (SELECT rowid FROM docs INDEXED BY {_INDEXED[column]} WHERE {condition})")
        params.extend(values)

    if p.get("language"):
        on("language", "language = ?", [p["language"]])
    for field in schema.FACET_FIELDS:
        values = p.get(field) or []
        if values and field != exclude:
            on(field, f"{field} IN ({', '.join('?' for _ in values)})", list(values))
    dates, values = [], []
    if p.get("date_from"):
        dates.append("last_modified >= ?")
        values.append(f"{p['date_from']}T00:00:00Z")
    if p.get("date_to"):
        dates.append("last_modified <= ?")
        values.append(f"{p['date_to']}T23:59:59Z")
    if dates:
        on("last_modified", " AND ".join(dates), values)
    return (f"WHERE {' AND '.join(where)}" if where else ""), params


def _value_table(db: sqlite3.Connection, name: str, column: str) -> None:
    """temp.<name>(rid, v): the column of every selected document, from its index when it has one."""
    db.execute(f"CREATE TEMP TABLE {name} (rid INTEGER PRIMARY KEY, v)")
    index = _INDEXED.get(column)
    if not index and column in _OPTIONAL_INDEXES and db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = ?", [_OPTIONAL_INDEXES[column]]).fetchone():
        index = _OPTIONAL_INDEXES[column]
    if index:
        db.execute(f"INSERT INTO {name} SELECT rowid, {column} FROM docs INDEXED BY {index} "
                   "WHERE rowid IN (SELECT rid FROM sel)")
    else:  # a pack made before docs_title / docs_file_path / docs_author: read from the rows
        db.execute(f"INSERT INTO {name} SELECT d.rowid, d.{column} FROM sel s JOIN docs d ON d.rowid = s.rid")


_ORDER_SQL = {  # over temp.sel s and, when the sort needs one, temp.ov o (the sort column)
    "score desc": ("", "s.score ASC, s.rid"),  # bm25: lower is better
    "last_modified desc": ("last_modified", "o.v IS NULL, o.v DESC, s.rid"),
    "last_modified asc": ("last_modified", "o.v IS NULL, o.v ASC, s.rid"),
    "title asc": ("title", "o.v COLLATE NOCASE ASC, s.rid"),
    "title desc": ("title", "o.v COLLATE NOCASE DESC, s.rid"),
}


def _select(db: sqlite3.Connection, plan: _Plan, p: dict) -> tuple[_Plan, str, str]:
    """Fill temp.hit (what the query matches), temp.sel (hit after the filters) and the sort column; returns
    (the plan that matched, FROM clause over sel, ORDER BY)."""
    db.execute("PRAGMA temp_store = MEMORY")
    db.execute("CREATE TEMP TABLE hit (rid INTEGER PRIMARY KEY, score REAL)")
    db.execute(f"INSERT OR IGNORE INTO hit {plan.source_sql}", plan.source_params)
    if plan.fallback and db.execute("SELECT 1 FROM hit LIMIT 1").fetchone() is None:
        plan = plan.fallback
        db.execute(f"INSERT OR IGNORE INTO hit {plan.source_sql}", plan.source_params)
    if plan.rank_sql:
        # bm25 costs about as much as the match itself and reads every hit's postings: only worth it when the
        # result is small enough to be a ranking at all. A query matching 200 000 documents orders by date.
        if db.execute("SELECT COUNT(*) FROM (SELECT 1 FROM hit LIMIT ?)", [RANK_LIMIT + 1]).fetchone()[0] <= RANK_LIMIT:
            db.execute(f"INSERT OR REPLACE INTO hit {plan.rank_sql}", plan.rank_params)
        else:
            plan.ranked = False
    where, params = _hit_filters(p)
    db.execute("CREATE TEMP TABLE sel (rid INTEGER PRIMARY KEY, score REAL)")
    db.execute(f"INSERT INTO sel SELECT h.rid, h.score FROM hit h {where}", params)
    column, order = _ORDER_SQL[_order_key(p, plan)]
    if not column:
        return plan, "FROM sel s", order
    _value_table(db, "ov", column)
    return plan, "FROM sel s JOIN ov o ON o.rid = s.rid", order


# What a result shows. The large text columns are never selected: see field_chunks.
_SMALL_COLUMNS = ("id, substr(title, 1, 500) AS title, substr(file_path, 1, 2000) AS file_path, "
                  "substr(author, 1, 500) AS author, " + ", ".join(schema.STRING_FIELDS))


def _fetch(db: sqlite3.Connection, rids: list[int]) -> list[dict]:
    """The small columns of the documents shown, in the given order, with "rid" and a text preview."""
    if not rids:
        return []
    rows = db.execute(f"SELECT rowid AS rid, {_SMALL_COLUMNS} FROM docs WHERE rowid IN "
                      f"({', '.join('?' for _ in rids)})", rids).fetchall()
    by_id = {r["rid"]: {k: r[k] for k in r.keys() if r[k] not in (None, "")} for r in rows}
    docs = [by_id[r] for r in rids if r in by_id]
    for doc in docs:
        doc["preview_field"], doc["preview"] = preview(db, doc["rid"])
    return docs


def _highlights(db: sqlite3.Connection, docs: list[dict], positive: list[str], p: dict) -> tuple[dict, bool]:
    """({id: {field: snippets}}, whether the time budget ran out). ``p``: "hl_count" / "hl_size" change how many
    snippets and how long, "hl_plain" cuts code like text (MCP)."""
    out: dict = {}
    deadline = time.monotonic() + HIGHLIGHT_BUDGET
    options = {k: p[f"hl_{k}"] for k in ("count", "size") if p.get(f"hl_{k}")}
    late = False
    for doc in docs:
        hl = {}
        title = highlight.whole(doc.get("title"), positive)
        if title:
            hl["title"] = [title]
        for field in ("content", "source_code_content", "image_orc_text"):
            if time.monotonic() > deadline:
                late = True
                break
            chunks = field_chunks(db, doc["rid"], field, limit=HIGHLIGHT_SCAN, deadline=deadline)
            if field == "source_code_content" and not p.get("hl_plain"):  # keep lines: rendered as a code block
                parts = highlight.code_snippets(chunks, positive)
            else:
                parts = highlight.snippets(chunks, positive, **options)
            chunks.close()
            if parts:
                hl[field] = parts
        out[doc.get("id", "")] = hl
    return out, late or time.monotonic() > deadline


def _group_column(p: dict) -> str | None:
    return p.get("group_by") if p.get("group_by") in schema.GROUP_FIELDS else None


_GROUP_KEY = f"COALESCE(NULLIF(g.v, ''), '{NO_GROUP}')"


def search(path: Path, p: dict) -> dict:
    if not _RUNNING.acquire(timeout=QUEUE_WAIT):
        return {**_empty(p), "error": BUSY}
    try:
        return _search(path, p)
    except MemoryError:
        logger.exception("search ran out of memory")
        return {**_empty(p), "error": NO_MEMORY}
    finally:
        _RUNNING.release()


def _empty(p: dict) -> dict:
    return {"docs": [], "groups": [], "grouped": False, "num_found": 0, "total_pages": 0, "page": p.get("page", 1),
            "rows": int(p.get("rows") or 10), "start": int(p.get("start") or 0), "facets": {}, "highlighting": {},
            "debug": {}, "error": None, "notices": [], "engine": "", "q": "", "params": {}}


def _search(path: Path, p: dict) -> dict:
    order_key = p.get("sort_val") if p.get("sort_val") in SORTS else "score desc"
    plan = _plan(p, with_score=order_key == "score desc")
    positive = plan.positive
    rows, start = int(p.get("rows") or 10), int(p.get("start") or 0)
    show = p.get("rows") != 0  # rows=0: facets only (the toolbar pickers before the first search)

    def describe(used: _Plan) -> dict:
        return {"notices": notices_for(p) + (
                    ["Không có từ nào bắt đầu như vậy; đã tìm cả chuỗi nằm giữa từ."] if used.engine == "fts_tri"
                    and not any(highlight.has_cjk(t) for t in positive) else []) + (
                    [f"Từ khoá khớp hơn {RANK_LIMIT:,} tài liệu nên xếp theo mới nhất thay vì độ liên quan; "
                     "thêm từ khoá để thu hẹp."] if not used.ranked else []),
                "engine": used.engine,
                "q": used.match or ("*" if not used.like_terms else " ".join(used.like_terms))}

    result = {**_empty(p), "rows": rows, **describe(plan)}
    try:
        with closing(_connect_limited(path)) as db:
            plan, source, order = _select(db, plan, p)
            result.update(describe(plan))
            shown: list[dict] = []
            group_by = _group_column(p)
            if show and group_by:
                _value_table(db, "gv", group_by)
                db.execute("CREATE TEMP TABLE ord (pos INTEGER PRIMARY KEY, rid INTEGER)")
                db.execute(f"INSERT INTO ord (rid) SELECT s.rid {source} ORDER BY {order}")
                # Groups in the order of their best document, with every match counted.
                ordered = db.execute(f"SELECT {_GROUP_KEY} AS k, COUNT(*) AS n FROM ord JOIN gv g ON g.rid = ord.rid "
                                     "GROUP BY k ORDER BY MIN(ord.pos)").fetchall()
                page_groups = []
                on_page = ordered[start:start + rows]
                per_group = max(1, min(GROUP_LIMIT, GROUP_PAGE_DOCS // max(1, len(on_page))))
                for row in on_page:
                    rids = [r[0] for r in db.execute(
                        f"SELECT ord.rid FROM ord JOIN gv g ON g.rid = ord.rid WHERE {_GROUP_KEY} = ? "
                        "ORDER BY ord.pos LIMIT ?", [row["k"], per_group])]
                    docs = _fetch(db, rids)
                    shown.extend(docs)
                    page_groups.append({"key": row["k"], "count": row["n"], "docs": docs})
                result.update(grouped=True, groups=page_groups, num_found=len(ordered),
                              total_pages=math.ceil(len(ordered) / rows) if rows else 1)
            else:
                total = db.execute("SELECT COUNT(*) FROM sel").fetchone()[0]
                if show:
                    rids = [r[0] for r in db.execute(f"SELECT s.rid {source} ORDER BY {order} LIMIT ? OFFSET ?",
                                                     [rows, start])]
                    shown = _fetch(db, rids)
                result.update(docs=shown, num_found=total, total_pages=math.ceil(total / rows) if rows else 1)

            for field in schema.FACET_FIELDS:
                where, params = _hit_filters(p, exclude=field)
                pairs = db.execute(
                    f"SELECT {field} AS v, COUNT(*) AS n FROM docs INDEXED BY {_INDEXED[field]} "
                    f"WHERE {field} IS NOT NULL AND rowid IN (SELECT h.rid FROM hit h {where}) "
                    f"GROUP BY {field} ORDER BY n DESC, v LIMIT 20",
                    params,
                ).fetchall()
                result["facets"][field] = [(r["v"], r["n"]) for r in pairs]

            if p.get("hl_enabled", True) and positive:
                result["highlighting"], late = _highlights(db, shown, positive, p)
                if late:
                    result["notices"] = [*result["notices"], TOO_SLOW]
            if p.get("debug_mode"):
                result["debug"] = {"engine": plan.engine, "match": plan.match, "order": order,
                                   "sql": plan.source_sql}
                result["params"] = {"filters": _hit_filters(p)[1]}
    except sqlite3.OperationalError as error:
        result["error"] = _failure(error)
    return result


def get_group_items(path: Path, p: dict, group_key: str, limit: int = 15, offset: int = 10) -> tuple[list[dict], dict]:
    """More documents of one group of a grouped search ("Xem thêm"), in the same order as search() shows them."""
    if not _RUNNING.acquire(timeout=QUEUE_WAIT):
        return [], {}
    try:
        return _group_items(path, p, group_key, limit, offset)
    finally:
        _RUNNING.release()


def _group_items(path: Path, p: dict, group_key: str, limit: int, offset: int) -> tuple[list[dict], dict]:
    group_by = _group_column(p) or "repository"
    order_key = p.get("sort_val") if p.get("sort_val") in SORTS else "score desc"
    plan = _plan(p, with_score=order_key == "score desc")
    try:
        with closing(_connect_limited(path)) as db:
            plan, source, order = _select(db, plan, p)
            _value_table(db, "gv", group_by)
            rids = [r[0] for r in db.execute(
                f"SELECT s.rid {source} JOIN gv g ON g.rid = s.rid WHERE {_GROUP_KEY} = ? "
                f"ORDER BY {order} LIMIT ? OFFSET ?", [group_key, limit, offset])]
            docs = _fetch(db, rids)
            marked = p.get("hl_enabled", True) and plan.positive
            hl = _highlights(db, docs, plan.positive, p)[0] if marked else {}
    except sqlite3.OperationalError:
        return [], {}
    return docs, hl
