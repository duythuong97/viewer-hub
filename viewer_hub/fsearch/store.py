"""Search over search.sqlite with the same result shape the Solr version returned.

Supported from the old form: free text, OR/AND, phrase, exact terms, proximity
(NEAR), -negation, language / repository / file_type / date filters, facets with
multi-select, sort, paging, group by, highlighting.
Not supported (shown as a notice): fuzzy, lucene/dismax parser, raw fq, bf, mm.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from viewer_hub.core.atomic import read_json
from viewer_hub.fsearch import highlight, schema

GROUP_LIMIT = 10
GROUP_SCAN_LIMIT = 10000
_TOKEN = re.compile(r'(-?)"([^"]+)"|(-?)(\S+)')

SORTS = {
    "score desc": "score ASC, d.rowid",  # bm25: lower is better
    "last_modified desc": "d.last_modified IS NULL, d.last_modified DESC, d.rowid",
    "last_modified asc": "d.last_modified IS NULL, d.last_modified ASC, d.rowid",
    "title asc": "d.title COLLATE NOCASE ASC, d.rowid",
    "title desc": "d.title COLLATE NOCASE DESC, d.rowid",
}


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


def _filters(p: dict, exclude: str | None = None) -> tuple[list[str], list]:
    where, params = [], []
    if p.get("language"):
        where.append("d.language = ?")
        params.append(p["language"])
    for field in schema.FACET_FIELDS:
        values = p.get(field) or []
        if values and field != exclude:
            where.append(f"d.{field} IN ({', '.join('?' for _ in values)})")
            params.extend(values)
    if p.get("date_from"):
        where.append("d.last_modified >= ?")
        params.append(f"{p['date_from']}T00:00:00Z")
    if p.get("date_to"):
        where.append("d.last_modified <= ?")
        params.append(f"{p['date_to']}T23:59:59Z")
    return where, params


def _doc(row: sqlite3.Row) -> dict:
    doc = {k: row[k] for k in schema.COLUMNS if k in row.keys() and row[k] not in (None, "")}
    try:
        doc["tags"] = json.loads(row["tags"] or "[]")
    except ValueError:
        doc["tags"] = []
    try:
        extra = json.loads(row["extra"] or "{}")
    except ValueError:
        extra = {}
    doc.pop("extra", None)
    for key, value in extra.items():
        doc.setdefault(key, value)
    return doc


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


def _substring_instead(path: Path, p: dict, terms: list[Term], match: str) -> bool:
    """True when the word index has nothing for the query but a substring search could: every term has 3+
    characters (the trigram index's minimum) and none was asked to match exactly."""
    positive = [t for t in terms if not t.negate]
    if p.get("exact_terms") or p.get("phrase_mode") or any(t.quoted or len(t.text) < 3 for t in positive):
        return False
    try:
        with closing(_connect(path)) as db:
            return db.execute("SELECT 1 FROM fts_word WHERE fts_word MATCH ? LIMIT 1", [match]).fetchone() is None
    except sqlite3.OperationalError:
        return False


def search(path: Path, p: dict) -> dict:
    terms = parse_terms(p.get("query", ""))
    positive = [t.text for t in terms if not t.negate]
    negative = [t.text for t in terms if t.negate]
    match = build_match(p, terms)
    engine = "all"
    source_sql, source_params = "SELECT rowid AS rid, 0.0 AS score FROM docs", []
    like_terms: list[str] = []
    weights = ", ".join(str(w) for w in schema.WEIGHTS)

    if match:
        cjk = any(highlight.has_cjk(t) for t in positive)
        if cjk and all(len(t) >= 3 for t in positive):
            engine = "fts_tri"
            source_sql = f"SELECT rowid AS rid, bm25(fts_tri, {weights}) AS score FROM fts_tri WHERE fts_tri MATCH ?"
            source_params = [match]
        elif cjk:
            # Trigram needs 3+ characters; short Japanese terms fall back to LIKE.
            engine = "like"
            like_terms = positive
        else:
            engine = "fts_word"
            source_sql = f"SELECT rowid AS rid, bm25(fts_word, {weights}) AS score FROM fts_word WHERE fts_word MATCH ?"
            source_params = [match]
            if _substring_instead(path, p, terms, match):
                # No word starts with what was typed: look for it inside words ("dit" in "audit").
                engine = "fts_tri"
                tri = build_match({**p, "exact_terms": True}, terms)
                source_sql = f"SELECT rowid AS rid, bm25(fts_tri, {weights}) AS score FROM fts_tri WHERE fts_tri MATCH ?"
                source_params = [tri]
                match = tri
    elif negative:
        engine = "all"
        source_sql = ("SELECT rowid AS rid, 0.0 AS score FROM docs WHERE rowid NOT IN "
                      "(SELECT rowid FROM fts_word WHERE fts_word MATCH ?)")
        source_params = [" OR ".join(_quote(t) for t in negative)]

    def base(exclude: str | None = None, extra: str | None = None) -> tuple[str, list]:
        where, params = _filters(p, exclude)
        if like_terms:
            joiner = " AND " if p.get("operator") == "AND" else " OR "
            parts = []
            for term in like_terms:
                parts.append("(" + " OR ".join(f"d.{f} LIKE ?" for f in schema.TEXT_FIELDS) + ")")
                params.extend([f"%{term}%"] * len(schema.TEXT_FIELDS))
            where.append("(" + joiner.join(parts) + ")")
        if extra:
            where.append(extra)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        sql = f"FROM ({source_sql}) m JOIN docs d ON d.rowid = m.rid {clause}"
        return sql, [*source_params, *params]

    order = SORTS.get(p.get("sort_val") or "score desc", SORTS["score desc"])
    if engine in {"all", "like"} and order.startswith("score"):
        order = SORTS["last_modified desc"]
    rows, start = int(p.get("rows") or 10), int(p.get("start") or 0)

    result = {
        "docs": [], "groups": [], "grouped": False, "num_found": 0, "total_pages": 0,
        "page": p.get("page", 1), "rows": rows, "start": start, "facets": {}, "highlighting": {},
        "debug": {}, "error": None, "notices": notices_for(p) + (
            ["Không có từ nào bắt đầu như vậy; đã tìm cả chuỗi nằm giữa từ."] if engine == "fts_tri" and not any(
                highlight.has_cjk(t) for t in positive) else []), "engine": engine,
        "q": match or ("*" if not like_terms else " ".join(like_terms)), "params": {},
    }
    try:
        with closing(_connect(path)) as db:
            sql, params = base()
            group_by = p.get("group_by") if p.get("group_by") in schema.GROUP_FIELDS else None
            if group_by:
                matched = db.execute(f"SELECT d.*, m.score {sql} ORDER BY {order} LIMIT {GROUP_SCAN_LIMIT}", params).fetchall()
                groups: dict[str, dict] = {}
                for row in matched:
                    key = row[group_by] or "(không có)"
                    group = groups.setdefault(key, {"key": key, "count": 0, "docs": []})
                    group["count"] += 1
                    if len(group["docs"]) < GROUP_LIMIT:
                        group["docs"].append(_doc(row))
                ordered = list(groups.values())
                page_groups = ordered[start:start + rows]
                result.update(grouped=True, groups=page_groups, num_found=len(ordered),
                              total_pages=math.ceil(len(ordered) / rows) if rows else 1)
                shown = [d for g in page_groups for d in g["docs"]]
            else:
                total = db.execute(f"SELECT COUNT(*) {sql}", params).fetchone()[0]
                found = db.execute(f"SELECT d.*, m.score {sql} ORDER BY {order} LIMIT ? OFFSET ?", [*params, rows, start]).fetchall()
                shown = [_doc(r) for r in found]
                result.update(docs=shown, num_found=total, total_pages=math.ceil(total / rows) if rows else 1)

            for field in schema.FACET_FIELDS:
                fsql, fparams = base(exclude=field, extra=f"d.{field} IS NOT NULL")
                pairs = db.execute(
                    f"SELECT d.{field} AS v, COUNT(*) AS n {fsql} GROUP BY d.{field} ORDER BY n DESC, v LIMIT 20",
                    fparams,
                ).fetchall()
                result["facets"][field] = [(r["v"], r["n"]) for r in pairs]

            if p.get("hl_enabled", True) and positive:
                for doc in shown:
                    hl = {}
                    title = highlight.whole(doc.get("title"), positive)
                    if title:
                        hl["title"] = [title]
                    for field in ("content", "source_code_content", "image_orc_text"):
                        if field == "source_code_content":  # keep lines and indentation: rendered as a code block
                            parts = highlight.code_snippets(doc.get(field), positive)
                        else:
                            parts = highlight.snippets(doc.get(field), positive)
                        if parts:
                            hl[field] = parts
                    result["highlighting"][doc["id"]] = hl
            if p.get("debug_mode"):
                result["debug"] = {"engine": engine, "match": match, "order": order, "sql": sql}
                result["params"] = {"filters": params[len(source_params):]}
    except sqlite3.OperationalError as error:
        result["error"] = f"Không hiểu câu truy vấn: {error}"
    return result
