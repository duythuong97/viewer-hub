"""search.sqlite format, schema 1. Written by export_solr.py, read by store.py.

Field names follow the ocr-demo `main` Solr schema, including its spelling
``image_orc_text`` (``image_ocr_text`` from newer cores is mapped onto it).
"""
from __future__ import annotations

import sqlite3

SCHEMA = 1

TEXT_FIELDS = ["title", "content", "image_orc_text", "source_code_content", "author", "file_path"]
# bm25 weights, same order as TEXT_FIELDS (from QUERY_FIELDS in ocr-demo config.py).
WEIGHTS = [5.0, 1.0, 0.6, 1.5, 2.0, 1.0]
STRING_FIELDS = ["language", "file_type", "repository", "last_modified", "url", "repository_path"]
FACET_FIELDS = ["repository", "file_type"]
GROUP_FIELDS = ["file_path", "repository", "file_type", "author", "language"]
FIELD_ALIASES = {"image_ocr_text": "image_orc_text"}

COLUMNS = ["id", *TEXT_FIELDS, *STRING_FIELDS, "tags", "extra"]

DDL = [
    f"""CREATE TABLE docs (
        id TEXT PRIMARY KEY,
        {', '.join(f'{f} TEXT' for f in TEXT_FIELDS)},
        {', '.join(f'{f} TEXT' for f in STRING_FIELDS)},
        tags TEXT,   -- JSON array
        extra TEXT   -- JSON object: other stored fields (dynamic *_s, *_t, ...)
    )""",
    "CREATE INDEX docs_repository ON docs(repository)",
    "CREATE INDEX docs_file_type ON docs(file_type)",
    "CREATE INDEX docs_language ON docs(language)",
    "CREATE INDEX docs_last_modified ON docs(last_modified)",
    # Words: English / Vietnamese (diacritics folded, so "tieng viet" finds "tiếng việt").
    # "_" and "." separate tokens, so generate_token is found by "token" and by "generate_token" (as a phrase).
    f"""CREATE VIRTUAL TABLE fts_word USING fts5({', '.join(TEXT_FIELDS)},
        content='docs', content_rowid='rowid', tokenize="unicode61 remove_diacritics 2")""",
    # Trigram: Japanese and substrings (each term needs 3+ characters).
    f"""CREATE VIRTUAL TABLE fts_tri USING fts5({', '.join(TEXT_FIELDS)},
        content='docs', content_rowid='rowid', tokenize='trigram')""",
    "CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
]


def create(db: sqlite3.Connection) -> None:
    for statement in DDL:
        db.execute(statement)


def rebuild_fts(db: sqlite3.Connection) -> None:
    db.execute("INSERT INTO fts_word(fts_word) VALUES ('rebuild')")
    db.execute("INSERT INTO fts_tri(fts_tri) VALUES ('rebuild')")
    db.execute("INSERT INTO fts_word(fts_word) VALUES ('optimize')")
    db.execute("INSERT INTO fts_tri(fts_tri) VALUES ('optimize')")
