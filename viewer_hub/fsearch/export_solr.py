"""Export a Solr core to search.sqlite (runs on the author's machine, design.md §6.2).

Reads every stored field with cursorMark paging (sort=id asc), so the result
holds the full data and Solr is no longer needed. Uses only the standard
library (urllib), so nothing extra is installed for it.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterator

from viewer_hub.fsearch import schema

logger = logging.getLogger(__name__)


def _get(url: str, params: dict, timeout: int) -> dict:
    query = urllib.parse.urlencode(params, doseq=True)
    request = urllib.request.Request(f"{url}?{query}", headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 (author-supplied Solr URL)
        return json.loads(response.read().decode("utf-8"))


def iter_docs(solr_url: str, rows: int = 500, timeout: int = 60) -> Iterator[tuple[int, dict]]:
    select = solr_url.rstrip("/") + "/select"
    cursor = "*"
    while True:
        data = _get(select, {"q": "*:*", "fl": "*", "sort": "id asc", "rows": rows, "cursorMark": cursor, "wt": "json"}, timeout)
        total = data["response"]["numFound"]
        for doc in data["response"]["docs"]:
            yield total, doc
        next_cursor = data.get("nextCursorMark")
        if not next_cursor or next_cursor == cursor:
            return
        cursor = next_cursor


def _first(value):
    if isinstance(value, list):
        return value[0] if value else None
    return value


def _text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return "\n".join(str(v) for v in value if v is not None)
    return str(value)


def to_row(doc: dict) -> list:
    doc = {schema.FIELD_ALIASES.get(k, k): v for k, v in doc.items() if not k.startswith("_")}
    known = set(schema.COLUMNS)
    row = {"id": str(_first(doc.get("id")))}
    for field in schema.TEXT_FIELDS:
        row[field] = _text(doc.get(field))
    for field in schema.STRING_FIELDS:
        row[field] = None if doc.get(field) is None else str(_first(doc.get(field)))
    tags = doc.get("tags")
    row["tags"] = json.dumps(tags if isinstance(tags, list) else ([tags] if tags else []), ensure_ascii=False)
    row["extra"] = json.dumps({k: v for k, v in doc.items() if k not in known}, ensure_ascii=False)
    return [row[c] for c in schema.COLUMNS]


def write(target: Path, docs: Iterator[tuple[int, dict]], source: str) -> int:
    temp = target.with_name(target.name + ".tmp")
    temp.unlink(missing_ok=True)
    db = sqlite3.connect(temp)
    count = 0
    try:
        db.execute("PRAGMA journal_mode=OFF")
        schema.create(db)
        insert = f"INSERT OR REPLACE INTO docs ({', '.join(schema.COLUMNS)}) VALUES ({', '.join('?' for _ in schema.COLUMNS)})"
        batch, total = [], 0
        for total, doc in docs:
            batch.append(to_row(doc))
            if len(batch) == 1000:
                db.executemany(insert, batch)
                count += len(batch)
                batch.clear()
                logger.info("exported %s / %s", count, total)
        if batch:
            db.executemany(insert, batch)
            count += len(batch)
        if total and count != total:
            raise RuntimeError(f"Solr reported {total} documents but {count} were read")
        schema.rebuild_fts(db)
        meta = {"schema": schema.SCHEMA, "source": source, "exportedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "docCount": count}
        db.executemany("INSERT INTO meta VALUES (?, ?)", [(k, str(v)) for k, v in meta.items()])
        db.commit()
    except BaseException:
        db.close()
        temp.unlink(missing_ok=True)
        raise
    db.close()
    temp.replace(target)
    return count


def export(solr_url: str, out: Path, rows: int = 500, timeout: int = 60) -> int:
    count = write(out, iter_docs(solr_url, rows, timeout), solr_url)
    print(f"{count} tài liệu → {out}")
    return count
