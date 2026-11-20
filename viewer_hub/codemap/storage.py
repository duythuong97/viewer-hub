"""Opening a code-map pack and the user's knowledge database (ported from code-map codemap/storage.py).

``codemap.sqlite`` in the pack is opened read-only per use (``file:...?mode=ro``);
the knowledge database people write to lives under ``user/codemap/<pack_id>/`` and
is attached as ``kn`` with every schema created on first use. When the hub is
read-only the knowledge database is attached read-only too (or an empty in-memory
one when it does not exist yet), so pages still render.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from viewer_hub.codemap.business import KNOWLEDGE_SCHEMA as BUSINESS_SCHEMA
from viewer_hub.codemap.contract.serving import DATABASE_NAME as SERVING_DATABASE_NAME
from viewer_hub.codemap.contract.serving import SCHEMA_VERSION as SERVING_SCHEMA_VERSION

GRAPH_KNOWLEDGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS kn.graph_knowledge(knowledge_id INTEGER PRIMARY KEY,target_id TEXT NOT NULL,body TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN('draft','pending','approved','rejected')),
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  citations_json TEXT NOT NULL DEFAULT '[]',created_by TEXT NOT NULL DEFAULT '',
  edited_by TEXT NOT NULL DEFAULT '',fingerprint TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS kn.graph_knowledge_target ON graph_knowledge(target_id);
CREATE TABLE IF NOT EXISTS kn.semantic_mappings(target_id TEXT PRIMARY KEY,semantic_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK(status IN('approved','rejected')),source_kind TEXT NOT NULL DEFAULT 'USER',
  author_name TEXT NOT NULL DEFAULT '',confidence REAL NOT NULL DEFAULT 1.0,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE TEMP VIEW graph_knowledge AS SELECT * FROM kn.graph_knowledge;
-- A person's mapping wins over the dictionary's alias links for the same node.
CREATE TEMP VIEW graph_business_semantic_mappings AS
  SELECT target_id,semantic_id,status,source_kind,author_name,confidence,created_at,updated_at FROM kn.semantic_mappings
  UNION ALL
  SELECT l.target_id,l.semantic_id,'approved','DICTIONARY_ALIAS','',0.9,'',''
  FROM main.graph_business_semantic_links l
  WHERE NOT EXISTS (SELECT 1 FROM kn.semantic_mappings m WHERE m.target_id=l.target_id);
"""

# Every MCP tool call, so the team can see what agents ask and where the graph has no answer.
MCP_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS kn.mcp_calls(call_id INTEGER PRIMARY KEY,called_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  user_name TEXT NOT NULL DEFAULT '',client TEXT NOT NULL DEFAULT '',tool TEXT NOT NULL,arguments_json TEXT NOT NULL,
  result_chars INTEGER NOT NULL,empty INTEGER NOT NULL,error TEXT NOT NULL DEFAULT '',elapsed_ms REAL NOT NULL);
CREATE INDEX IF NOT EXISTS kn.mcp_calls_tool ON mcp_calls(tool, called_at);
"""

# Business rules, decisions and questions people own (web/backend/knowledge.py).
KNOWLEDGE_LAYER_SCHEMA = """
CREATE TABLE IF NOT EXISTS kn.biz_rules(rule_id TEXT PRIMARY KEY,domain TEXT NOT NULL,title TEXT NOT NULL,
  text TEXT NOT NULL DEFAULT '',status TEXT NOT NULL CHECK(status IN('draft','approved','needs_review','retired')),
  source TEXT NOT NULL CHECK(source IN('code','sme','doc','ai')),evidence TEXT NOT NULL DEFAULT '',
  node_ids TEXT NOT NULL DEFAULT '[]',requirement_refs TEXT NOT NULL DEFAULT '[]',test_refs TEXT NOT NULL DEFAULT '[]',
  fingerprint TEXT NOT NULL DEFAULT '',review_reason TEXT NOT NULL DEFAULT '',proposed_by TEXT NOT NULL DEFAULT '',
  approved_by TEXT NOT NULL DEFAULT '',approved_at TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,citations_json TEXT NOT NULL DEFAULT '[]');
CREATE TABLE IF NOT EXISTS kn.biz_decisions(decision_id TEXT PRIMARY KEY,title TEXT NOT NULL,context TEXT NOT NULL DEFAULT '',
  options_json TEXT NOT NULL DEFAULT '[]',decision TEXT NOT NULL DEFAULT '',reason TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL CHECK(status IN('proposed','accepted','rejected','superseded')),node_ids TEXT NOT NULL DEFAULT '[]',
  rule_ids TEXT NOT NULL DEFAULT '[]',superseded_by TEXT NOT NULL DEFAULT '',proposed_by TEXT NOT NULL DEFAULT '',
  decided_by TEXT NOT NULL DEFAULT '',decided_at TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,citations_json TEXT NOT NULL DEFAULT '[]');
CREATE TABLE IF NOT EXISTS kn.biz_questions(question_id TEXT PRIMARY KEY,text TEXT NOT NULL,context TEXT NOT NULL DEFAULT '',
  options_json TEXT NOT NULL DEFAULT '[]',answer TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL CHECK(status IN('open','answered','dropped')),node_ids TEXT NOT NULL DEFAULT '[]',
  rule_ids TEXT NOT NULL DEFAULT '[]',flow_id TEXT NOT NULL DEFAULT '',asked_by TEXT NOT NULL DEFAULT '',
  answered_by TEXT NOT NULL DEFAULT '',answered_at TEXT,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  citations_json TEXT NOT NULL DEFAULT '[]',answer_json TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS kn.knowledge_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
"""

EXTRA_SCHEMAS: list[str] = [MCP_LOG_SCHEMA, KNOWLEDGE_LAYER_SCHEMA]

# Columns added after a table first shipped. ``CREATE TABLE IF NOT EXISTS`` leaves an older knowledge db as it
# is, so they are added here (ALTER TABLE ... ADD COLUMN keeps every row). Readers use row.get() for them,
# since a read-only hub cannot upgrade the file.
ADDED_COLUMNS: dict[str, tuple[tuple[str, str], ...]] = {
    "biz_items": (("children_sig", "TEXT NOT NULL DEFAULT ''"),),
    "biz_rules": (("citations_json", "TEXT NOT NULL DEFAULT '[]'"),),
    "biz_decisions": (("citations_json", "TEXT NOT NULL DEFAULT '[]'"),),
    "biz_questions": (("citations_json", "TEXT NOT NULL DEFAULT '[]'"), ("answer_json", "TEXT NOT NULL DEFAULT ''")),
    "biz_links": (("citations_json", "TEXT NOT NULL DEFAULT '[]'"),),
    "graph_knowledge": (("citations_json", "TEXT NOT NULL DEFAULT '[]'"), ("created_by", "TEXT NOT NULL DEFAULT ''"),
                        ("edited_by", "TEXT NOT NULL DEFAULT ''"), ("fingerprint", "TEXT NOT NULL DEFAULT ''")),
}

# Wall-clock seconds one request (web) or tool call (MCP) may spend in codemap.sqlite. Past it the next
# SQL step fails with "interrupted" instead of holding one of the server's few threads.
QUERY_SECONDS = 30.0
# SQLite steps between two looks at the clock.
PROGRESS_OPCODES = 10_000


def timed_out(exc: BaseException) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and str(exc) == "interrupted"


def set_deadline(db: sqlite3.Connection) -> None:
    """Interrupt SQL on ``db`` once QUERY_SECONDS have passed from now."""
    deadline = time.monotonic() + QUERY_SECONDS
    db.set_progress_handler(lambda: time.monotonic() > deadline, PROGRESS_OPCODES)


def clear_deadline(db: sqlite3.Connection) -> None:
    """No time limit on ``db`` (a load done once per pack, not per request)."""
    db.set_progress_handler(None, 0)


class GraphNotReady(Exception):
    def __init__(self, path: Path, message: str = "") -> None:
        super().__init__(message or f"{path} not found")
        self.message = message


def _has_table(db: sqlite3.Connection, name: str) -> bool:
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def upgrade_knowledge(db: sqlite3.Connection) -> list[str]:
    """Add the ADDED_COLUMNS an older ``kn`` lacks; returns ``table.column`` for each one added."""
    added = []
    for table, columns in ADDED_COLUMNS.items():
        present = {row[1] for row in db.execute(f"PRAGMA kn.table_info({table})")}
        if not present:
            continue  # this connection did not create the table (open_knowledge has no graph_knowledge)
        for name, definition in columns:
            if name not in present:
                db.execute(f"ALTER TABLE kn.{table} ADD COLUMN {name} {definition}")
                added.append(f"{table}.{name}")
    if added:
        db.commit()
    return added


def _attach_knowledge(db: sqlite3.Connection, knowledge: Path, readonly: bool, schema: str) -> None:
    """Attach the knowledge db as ``kn`` and create its tables (temp views go to the connection's temp schema)."""
    if not readonly:
        knowledge.parent.mkdir(parents=True, exist_ok=True)
        db.execute("ATTACH DATABASE ? AS kn", (str(knowledge),))
        db.executescript(schema)
        _drop_review_states(db)
        upgrade_knowledge(db)
        return
    if knowledge.is_file():
        db.execute("ATTACH DATABASE ? AS kn", (f"{knowledge.resolve().as_uri()}?mode=ro",))
        try:
            db.executescript(schema)  # no-op when every table exists
            return
        except sqlite3.OperationalError:
            db.execute("DETACH DATABASE kn")
    db.execute("ATTACH DATABASE ':memory:' AS kn")
    db.executescript(schema)


# Code map had an approval queue until 0.3.3: AI drafts and proposals waited for a person. There is no approval
# any more, so what waited is in use from now on (once per knowledge db, on its first writable open).
_NO_REVIEW_UPGRADE = """
UPDATE kn.biz_rules SET status='approved' WHERE status='draft';
UPDATE kn.biz_links SET status='approved' WHERE status='proposed';
INSERT OR REPLACE INTO kn.knowledge_meta(key,value) VALUES('no_review','1');
"""


def _drop_review_states(db: sqlite3.Connection) -> None:
    tables = {row[0] for row in db.execute("SELECT name FROM kn.sqlite_master WHERE type='table'")}
    if not {"biz_rules", "biz_links", "knowledge_meta"} <= tables:
        return
    if db.execute("SELECT 1 FROM kn.knowledge_meta WHERE key='no_review'").fetchone():
        return
    db.executescript("BEGIN;" + _NO_REVIEW_UPGRADE + "COMMIT;")


@contextmanager
def open_knowledge(knowledge: Path, readonly: bool = False) -> Iterator[sqlite3.Connection]:
    """The knowledge database alone (attached as ``kn`` like in open_web), for writes that need no graph."""
    db = sqlite3.connect(":memory:", uri=True)
    db.row_factory = sqlite3.Row
    try:
        _attach_knowledge(db, knowledge, readonly, BUSINESS_SCHEMA + "".join(EXTRA_SCHEMAS))
        yield db
    finally:
        db.close()


def _open_serving(output: Path) -> sqlite3.Connection:
    """codemap.sqlite read-only, refused when an older extract wrote it."""
    path = output / SERVING_DATABASE_NAME
    if not path.is_file():
        raise GraphNotReady(path, f"{output.name}/{SERVING_DATABASE_NAME} không có trong pack")
    db = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False)
    version = db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone() if _has_table(db, "meta") else None
    if not version or str(version[0]) != SERVING_SCHEMA_VERSION:
        db.close()
        raise GraphNotReady(path, f"{SERVING_DATABASE_NAME} của pack dùng schema cũ; cần build lại pack bằng extract mới")
    set_deadline(db)
    return db


@contextmanager
def open_web(output: Path, knowledge: Path, readonly: bool = False) -> Iterator[sqlite3.Connection]:
    """codemap.sqlite (read-only) with the knowledge database attached as ``kn``."""
    db = _open_serving(output)
    db.row_factory = sqlite3.Row
    try:
        _attach_knowledge(db, knowledge, readonly, GRAPH_KNOWLEDGE_SCHEMA + BUSINESS_SCHEMA + "".join(EXTRA_SCHEMAS))
        yield db
    finally:
        db.close()


@contextmanager
def open_search(output: Path, knowledge: Path | None = None) -> Iterator[sqlite3.Connection]:
    """codemap.sqlite (read-only) for the search index (search_* tables). With ``knowledge`` its file is
    attached read-only as ``kn`` when it exists, so walks can add the hand-made links (kn.biz_links)."""
    db = _open_serving(output)
    try:
        if knowledge is not None and knowledge.is_file():
            db.execute("ATTACH DATABASE ? AS kn", (f"{knowledge.resolve().as_uri()}?mode=ro",))
        yield db
    finally:
        db.close()


def manual_links(db: sqlite3.Connection, column: str, node_id: str) -> list[tuple[str, str, str, str]]:
    """Hand-made links (link_id, source, target, edge_type) leaving (``source_id``) or entering
    (``target_id``) a node; empty when no knowledge db is attached or it predates links."""
    if column not in {"source_id", "target_id"}:
        raise ValueError(column)
    try:
        return [tuple(row) for row in db.execute(
            f"SELECT link_id,source_id,target_id,edge_type FROM kn.biz_links WHERE {column}=?",
            (node_id,))]
    except sqlite3.OperationalError:
        return []
