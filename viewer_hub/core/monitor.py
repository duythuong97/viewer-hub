"""Monitoring: every MCP tool call AI makes (builtin modules and addons, HTTP and stdio), addon life events and
process samples, in ``monitor.db`` under the data dir. Read by the Giám sát page (viewer_hub/monitor).

Capture points (nothing else needs to know about this module):

* ``core/mcp.dispatch`` — every builtin server (Code map, F-Search, CSV, Giám sát), HTTP or stdio;
* ``addons/proxy.mcp_call`` — every addon MCP, through the Hub's HTTP route or ``viewer-hub mcp <addon>``;
* ``addons/runner`` — addon start / stop / crash; ``monitor/sampler.py`` — CPU and memory every 30 s.

A process records only after ``configure(paths, transport)`` (``viewer-hub serve`` and ``viewer-hub mcp``); tests and
the addon SDK (which reuses ``dispatch`` inside an addon) record nothing. Writes go through one background thread so a
call never waits on the disk, and a failing write is dropped, never raised. Several processes share the file (WAL).

Privacy (core/logs.py rule: no document text, cell values or tokens): by default a call keeps only the names and sizes
of its arguments; "full" (a setting, for debugging) keeps the values, cut to ARGS_FULL_MAX characters. Results are never
kept, only their size.
"""
from __future__ import annotations

import atexit
import contextvars
import json
import logging
import math
import queue
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

DB_NAME = "monitor.db"
ARGS_MODES = ("keys", "full", "off")
ARGS_FULL_MAX = 2000
ERROR_MAX = 300
DEFAULTS = {"enabled": "1", "args": "keys", "retention_days": "14"}
HOURLY_DAYS = 90
EVENT_DAYS = 30
SAMPLE_HOURS = 24
MAX_DB_BYTES = 50 * 1024 * 1024
SETTINGS_REFRESH = 30.0
MAINTAIN_EVERY = 600.0

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
  id INTEGER PRIMARY KEY, at REAL NOT NULL, server TEXT NOT NULL, tool TEXT NOT NULL,
  client TEXT NOT NULL DEFAULT '', transport TEXT NOT NULL DEFAULT '', via TEXT NOT NULL DEFAULT '',
  ms REAL NOT NULL, ok INTEGER NOT NULL, error TEXT NOT NULL DEFAULT '', args TEXT NOT NULL DEFAULT '',
  out_chars INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS calls_at ON calls(at);
CREATE INDEX IF NOT EXISTS calls_tool ON calls(server, tool, at);
CREATE TABLE IF NOT EXISTS hourly (
  hour INTEGER NOT NULL, server TEXT NOT NULL, tool TEXT NOT NULL, calls INTEGER NOT NULL, errors INTEGER NOT NULL,
  ms_sum REAL NOT NULL, ms_max REAL NOT NULL, out_chars INTEGER NOT NULL, PRIMARY KEY (hour, server, tool));
CREATE TABLE IF NOT EXISTS clients (
  client TEXT NOT NULL, transport TEXT NOT NULL, via TEXT NOT NULL, first_at REAL NOT NULL, last_at REAL NOT NULL,
  calls INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (client, transport, via));
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY, at REAL NOT NULL, source TEXT NOT NULL, kind TEXT NOT NULL, level TEXT NOT NULL,
  message TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS events_at ON events(at);
CREATE TABLE IF NOT EXISTS samples (
  at REAL NOT NULL, source TEXT NOT NULL, rss INTEGER, cpu REAL, PRIMARY KEY (source, at));
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def db_path(home: Path) -> Path:
    return Path(home) / DB_NAME


def connect(path: Path, timeout: float = 2.0) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=timeout, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.executescript(SCHEMA)
    return db


# ── what a call looks like ──────────────────────────────────────────────────────────────────────────────────────

def server_key(name: str) -> str:
    """A builtin server's name ("viewer-hub-csv") → its MCP command ("csv"), the key the page shows."""
    return name[len("viewer-hub-"):] if name.startswith("viewer-hub-") else name


def _shape(value: Any) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return f"text({len(value)})"
    if isinstance(value, list):
        return f"list({len(value)})"
    if isinstance(value, dict):
        return f"object({len(value)})"
    return "null" if value is None else type(value).__name__


def summarize_args(arguments: Any, mode: str) -> str:
    """keys: {"repo": "text(4)", "start_line": "number"}; full: the JSON, cut; off: ''."""
    if mode == "off" or not isinstance(arguments, dict) or not arguments:
        return ""
    if mode == "full":
        text = json.dumps(arguments, ensure_ascii=False, default=str)
        return text if len(text) <= ARGS_FULL_MAX else text[:ARGS_FULL_MAX] + "…"
    return json.dumps({str(k): _shape(v) for k, v in arguments.items()}, ensure_ascii=False)


def result_info(result: Any) -> tuple[bool, str, int]:
    """(ok, error text, characters returned) of a JSON-RPC reply item to tools/call."""
    if not isinstance(result, dict):
        return False, "không có trả lời", 0
    if "error" in result:
        error = result.get("error") or {}
        return False, str(error.get("message") if isinstance(error, dict) else error)[:ERROR_MAX], 0
    body = result.get("result") if isinstance(result.get("result"), dict) else {}
    texts = [str(item.get("text", "")) for item in body.get("content") or [] if isinstance(item, dict)]
    chars = sum(len(t) for t in texts)
    if body.get("isError"):
        return False, (texts[0] if texts else "isError")[:ERROR_MAX], chars
    return True, "", chars


# ── who calls ──────────────────────────────────────────────────────────────────────────────────────────────────

_request: contextvars.ContextVar[dict | None] = contextvars.ContextVar("viewer_hub_monitor_request", default=None)
_clients: dict[str, str] = {}  # connection key → "name version" from initialize (HTTP: per client header / UA)
_clients_lock = threading.Lock()


def http_context(headers) -> contextvars.Token:
    """Set by an HTTP MCP endpoint around one request: which client this is (a bridge says so in X-MCP-Client)."""
    via = str(headers.get("X-MCP-Client") or "")[:80]
    agent = str(headers.get("User-Agent") or "")[:120]
    key = via or agent or "http"
    return _request.set({"transport": "http", "via": via, "key": key, "agent": agent})


def reset_context(token: contextvars.Token) -> None:
    _request.reset(token)


def _context() -> dict:
    found = _request.get()
    if found is not None:
        return found
    rec = _recorder
    return {"transport": rec.transport if rec else "", "via": "", "key": "stdio", "agent": ""}


def initialized(params: Any) -> None:
    """``initialize`` names the client (clientInfo); later calls on the same connection carry that name."""
    rec = _recorder
    if rec is None or not isinstance(params, dict):
        return
    info = params.get("clientInfo") if isinstance(params.get("clientInfo"), dict) else {}
    name = " ".join(str(x) for x in (info.get("name"), info.get("version")) if x)[:80]
    ctx = _context()
    if name:
        with _clients_lock:
            _clients[ctx["key"]] = name
    rec.note_client(name or _fallback_client(ctx), ctx)


def _fallback_client(ctx: dict) -> str:
    if ctx.get("via"):
        return ctx["via"]
    agent = ctx.get("agent") or ""
    return agent.split(" ")[0][:60] if agent else ("stdio" if ctx.get("transport") == "stdio" else "không rõ")


def client_name(ctx: dict | None = None) -> str:
    ctx = ctx or _context()
    with _clients_lock:
        known = _clients.get(ctx["key"])
    return known or _fallback_client(ctx)


# ── the recorder ───────────────────────────────────────────────────────────────────────────────────────────────

class Recorder:
    """One per process: a queue of writes and the thread that runs them."""

    def __init__(self, home: Path, transport: str, maintain: bool = False) -> None:
        self.path = db_path(home)
        self.transport = transport
        self.maintain = maintain
        self._queue: queue.Queue = queue.Queue(maxsize=10_000)
        self._settings = dict(DEFAULTS)
        self._settings_at = 0.0
        self._thread = threading.Thread(target=self._work, name="monitor-writer", daemon=True)
        self._thread.start()

    # settings (read from monitor.db, refreshed now and then: the page may change them from another process)
    def setting(self, key: str) -> str:
        if time.monotonic() - self._settings_at > SETTINGS_REFRESH:
            self._settings_at = time.monotonic()
            try:
                db = connect(self.path)
                try:
                    self._settings = {**DEFAULTS, **{r["key"]: r["value"] for r in db.execute("SELECT key, value FROM settings")}}
                finally:
                    db.close()
            except sqlite3.Error:
                pass
        return self._settings.get(key, DEFAULTS.get(key, ""))

    @property
    def enabled(self) -> bool:
        return self.setting("enabled") != "0"

    def _put(self, job: Callable[[sqlite3.Connection], None]) -> None:
        try:
            self._queue.put_nowait(job)
        except queue.Full:
            pass  # a flood of calls: drop, never slow the agent down

    def call(self, server: str, tool: str, arguments: Any, ms: float, ok: bool, error: str = "", out_chars: int = 0,
             ctx: dict | None = None) -> None:
        if not self.enabled:
            return
        ctx = ctx or _context()
        row = (time.time(), server, str(tool)[:120], client_name(ctx), ctx.get("transport") or self.transport,
               ctx.get("via", ""), round(ms, 2), 1 if ok else 0, (error or "")[:ERROR_MAX],
               summarize_args(arguments, self.setting("args")), int(out_chars))

        def job(db: sqlite3.Connection) -> None:
            at = row[0]
            db.execute("INSERT INTO calls(at, server, tool, client, transport, via, ms, ok, error, args, out_chars) "
                       "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", row)
            db.execute("INSERT INTO hourly(hour, server, tool, calls, errors, ms_sum, ms_max, out_chars) "
                       "VALUES (?, ?, ?, 1, ?, ?, ?, ?) ON CONFLICT(hour, server, tool) DO UPDATE SET "
                       "calls = calls + 1, errors = errors + excluded.errors, ms_sum = ms_sum + excluded.ms_sum, "
                       "ms_max = max(ms_max, excluded.ms_max), out_chars = out_chars + excluded.out_chars",
                       (int(at // 3600), server, row[2], 0 if ok else 1, row[6], row[6], row[10]))
            db.execute("INSERT INTO clients(client, transport, via, first_at, last_at, calls) VALUES (?, ?, ?, ?, ?, 1) "
                       "ON CONFLICT(client, transport, via) DO UPDATE SET last_at = excluded.last_at, calls = calls + 1",
                       (row[3], row[4], row[5], at, at))
        self._put(job)

    def note_client(self, name: str, ctx: dict) -> None:
        if not self.enabled:
            return
        at, transport, via = time.time(), ctx.get("transport") or self.transport, ctx.get("via", "")
        self._put(lambda db: db.execute(
            "INSERT INTO clients(client, transport, via, first_at, last_at, calls) VALUES (?, ?, ?, ?, ?, 0) "
            "ON CONFLICT(client, transport, via) DO UPDATE SET last_at = excluded.last_at", (name, transport, via, at, at)))

    def event(self, source: str, kind: str, level: str, message: str = "") -> None:
        row = (time.time(), source, kind, level, (message or "")[:500])
        self._put(lambda db: db.execute("INSERT INTO events(at, source, kind, level, message) VALUES (?, ?, ?, ?, ?)", row))

    def sample(self, source: str, rss: int | None, cpu: float | None) -> None:
        row = (time.time(), source, rss, cpu)
        self._put(lambda db: db.execute("INSERT OR REPLACE INTO samples(at, source, rss, cpu) VALUES (?, ?, ?, ?)", row))

    def flush(self, timeout: float = 2.0) -> None:
        done = threading.Event()
        self._put(lambda _db: done.set())
        done.wait(timeout)

    def _work(self) -> None:
        db = None
        last_maintain = 0.0
        while True:
            try:
                job = self._queue.get(timeout=MAINTAIN_EVERY if self.maintain else None)
            except queue.Empty:
                job = None
            try:
                if db is None:
                    db = connect(self.path)
                if job is not None:
                    with db:
                        job(db)
                if self.maintain and time.monotonic() - last_maintain > MAINTAIN_EVERY:
                    last_maintain = time.monotonic()
                    prune(db, int(self.setting("retention_days") or 14))
            except sqlite3.Error as exc:
                logger.debug("monitor write dropped: %s", exc)
                if db is not None:
                    try:
                        db.close()
                    except sqlite3.Error:
                        pass
                db = None
            except Exception:  # noqa: BLE001  (monitoring never breaks the Hub)
                logger.debug("monitor job failed", exc_info=True)


_recorder: Recorder | None = None


def configure(home: Path, transport: str, maintain: bool = False) -> Recorder:
    """Start recording in this process (``viewer-hub serve``: http + maintain; ``viewer-hub mcp``: stdio)."""
    global _recorder
    _recorder = Recorder(Path(home), transport, maintain)
    atexit.register(_recorder.flush)
    return _recorder


def recorder() -> Recorder | None:
    return _recorder


def disable() -> None:
    global _recorder
    _recorder = None


def call(server: str, tool: str, arguments: Any, ms: float, reply: Any) -> None:
    """Record one tools/call from its JSON-RPC reply (no-op when this process does not record)."""
    rec = _recorder
    if rec is None:
        return
    try:
        ok, error, chars = result_info(reply)
        rec.call(server, tool, arguments, ms, ok, error, chars)
    except Exception:  # noqa: BLE001
        logger.debug("monitor call failed", exc_info=True)


def event(source: str, kind: str, level: str = "info", message: str = "") -> None:
    rec = _recorder
    if rec is not None:
        rec.event(source, kind, level, message)


# ── upkeep ─────────────────────────────────────────────────────────────────────────────────────────────────────

def prune(db: sqlite3.Connection, retention_days: int) -> None:
    now = time.time()
    with db:
        db.execute("DELETE FROM calls WHERE at < ?", (now - max(1, retention_days) * 86400,))
        db.execute("DELETE FROM hourly WHERE hour < ?", (int((now - HOURLY_DAYS * 86400) // 3600),))
        db.execute("DELETE FROM events WHERE at < ?", (now - EVENT_DAYS * 86400,))
        db.execute("DELETE FROM samples WHERE at < ?", (now - SAMPLE_HOURS * 3600,))
        db.execute("DELETE FROM clients WHERE last_at < ?", (now - HOURLY_DAYS * 86400,))
    pages = db.execute("PRAGMA page_count").fetchone()[0] * db.execute("PRAGMA page_size").fetchone()[0]
    if pages > MAX_DB_BYTES:  # too big: drop the oldest tenth of the calls (hourly totals stay)
        total = db.execute("SELECT COUNT(*) FROM calls").fetchone()[0]
        with db:
            db.execute("DELETE FROM calls WHERE id IN (SELECT id FROM calls ORDER BY id LIMIT ?)", (max(1, total // 10),))
        db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        db.execute("VACUUM")


# ── reading (the page, the MCP tools) ──────────────────────────────────────────────────────────────────────────

def percentile(values: list[float], share: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(share * len(ordered)) - 1))
    return ordered[index]


class Reader:
    """Queries over monitor.db for one request (opened per use; the writer may live in another process)."""

    def __init__(self, home: Path) -> None:
        self.db = connect(db_path(home))

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "Reader":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def settings(self) -> dict:
        return {**DEFAULTS, **{r["key"]: r["value"] for r in self.db.execute("SELECT key, value FROM settings")}}

    def save_settings(self, values: dict) -> dict:
        clean = {}
        if "enabled" in values:
            clean["enabled"] = "1" if values["enabled"] in (True, "1", 1, "true") else "0"
        if values.get("args") in ARGS_MODES:
            clean["args"] = values["args"]
        if "retention_days" in values:
            try:
                clean["retention_days"] = str(min(90, max(1, int(values["retention_days"]))))
            except (TypeError, ValueError):
                pass
        with self.db:
            for key, value in clean.items():
                self.db.execute("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET "
                                "value = excluded.value", (key, value))
        return self.settings()

    def clear(self) -> None:
        with self.db:
            for table in ("calls", "hourly", "clients", "events", "samples"):
                self.db.execute(f"DELETE FROM {table}")  # noqa: S608  (fixed names)

    def calls(self, *, since_id: int = 0, before_id: int = 0, limit: int = 200, server: str = "", tool: str = "",
              client: str = "", errors: bool = False, hours: float = 0) -> list[dict]:
        where, params = ["1 = 1"], []
        if since_id:
            where.append("id > ?"); params.append(since_id)
        if before_id:
            where.append("id < ?"); params.append(before_id)
        if server:
            where.append("server = ?"); params.append(server)
        if tool:
            where.append("tool = ?"); params.append(tool)
        if client:
            where.append("client = ?"); params.append(client)
        if errors:
            where.append("ok = 0")
        if hours:
            where.append("at >= ?"); params.append(time.time() - hours * 3600)
        rows = self.db.execute(f"SELECT * FROM calls WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT ?",  # noqa: S608
                               (*params, max(1, min(limit, 1000)))).fetchall()
        return [_call_row(r) for r in rows]

    def tools(self, hours: float = 24) -> list[dict]:
        since = time.time() - hours * 3600
        stats: dict[tuple[str, str], dict] = {}
        for r in self.db.execute("SELECT server, tool, ms, ok, out_chars, at FROM calls WHERE at >= ?", (since,)):
            item = stats.setdefault((r["server"], r["tool"]), {"server": r["server"], "tool": r["tool"], "calls": 0,
                                                                "errors": 0, "ms": [], "out": 0, "last": 0.0})
            item["calls"] += 1
            item["errors"] += 0 if r["ok"] else 1
            item["ms"].append(r["ms"])
            item["out"] += r["out_chars"]
            item["last"] = max(item["last"], r["at"])
        out = []
        for item in stats.values():
            ms = item.pop("ms")
            out.append({**item, "avgMs": round(sum(ms) / len(ms), 1), "p50Ms": round(percentile(ms, 0.5), 1),
                        "p95Ms": round(percentile(ms, 0.95), 1), "maxMs": round(max(ms), 1),
                        "avgOut": round(item["out"] / item["calls"]), "tokens": round(item.pop("out") / 4)})
        return sorted(out, key=lambda x: (-x["calls"], x["server"], x["tool"]))

    def series(self, hours: int = 24) -> list[dict]:
        """Calls and errors per hour (oldest first), every hour present."""
        now_hour = int(time.time() // 3600)
        first = now_hour - hours + 1
        rows = self.db.execute("SELECT hour, server, SUM(calls) AS calls, SUM(errors) AS errors FROM hourly "
                               "WHERE hour >= ? GROUP BY hour, server", (first,)).fetchall()
        by_hour = {h: {"hour": h * 3600, "calls": 0, "errors": 0, "servers": {}} for h in range(first, now_hour + 1)}
        for r in rows:
            slot = by_hour.get(r["hour"])
            if slot is None:
                continue
            slot["calls"] += r["calls"]
            slot["errors"] += r["errors"]
            slot["servers"][r["server"]] = slot["servers"].get(r["server"], 0) + r["calls"]
        return list(by_hour.values())

    def totals(self, hours: float = 24) -> dict:
        since = time.time() - hours * 3600
        ms = [r[0] for r in self.db.execute("SELECT ms FROM calls WHERE at >= ?", (since,))]
        row = self.db.execute("SELECT COUNT(*) AS calls, SUM(1 - ok) AS errors, SUM(out_chars) AS out, "
                              "COUNT(DISTINCT client) AS clients FROM calls WHERE at >= ?", (since,)).fetchone()
        calls = row["calls"] or 0
        return {"calls": calls, "errors": row["errors"] or 0, "errorRate": round((row["errors"] or 0) / calls, 4) if calls else 0,
                "p50Ms": round(percentile(ms, 0.5), 1), "p95Ms": round(percentile(ms, 0.95), 1),
                "tokens": round((row["out"] or 0) / 4), "clients": row["clients"] or 0}

    def by_server(self, hours: float = 24) -> list[dict]:
        since = time.time() - hours * 3600
        rows = self.db.execute("SELECT server, COUNT(*) AS calls, SUM(1 - ok) AS errors, AVG(ms) AS avg_ms, "
                               "SUM(out_chars) AS out, MAX(at) AS last FROM calls WHERE at >= ? GROUP BY server "
                               "ORDER BY calls DESC", (since,)).fetchall()
        return [{"server": r["server"], "calls": r["calls"], "errors": r["errors"] or 0, "avgMs": round(r["avg_ms"] or 0, 1),
                 "tokens": round((r["out"] or 0) / 4), "last": r["last"]} for r in rows]

    def clients(self, days: int = 30) -> list[dict]:
        rows = self.db.execute("SELECT * FROM clients WHERE last_at >= ? ORDER BY last_at DESC",
                               (time.time() - days * 86400,)).fetchall()
        return [{"client": r["client"], "transport": r["transport"], "via": r["via"], "first": r["first_at"],
                 "last": r["last_at"], "calls": r["calls"]} for r in rows]

    def events(self, limit: int = 50, source: str = "", hours: float = 0) -> list[dict]:
        where, params = ["1 = 1"], []
        if source:
            where.append("source = ?"); params.append(source)
        if hours:
            where.append("at >= ?"); params.append(time.time() - hours * 3600)
        rows = self.db.execute(f"SELECT * FROM events WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT ?",  # noqa: S608
                               (*params, limit)).fetchall()
        return [{"id": r["id"], "at": r["at"], "source": r["source"], "kind": r["kind"], "level": r["level"],
                 "message": r["message"]} for r in rows]

    def samples(self, hours: float = 6) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for r in self.db.execute("SELECT at, source, rss, cpu FROM samples WHERE at >= ? ORDER BY at",
                                 (time.time() - hours * 3600,)):
            out.setdefault(r["source"], []).append({"at": r["at"], "rss": r["rss"], "cpu": r["cpu"]})
        return out

    def alerts(self) -> list[dict]:
        """What needs the user now: failing servers, slow tools, addons that keep crashing or use much memory."""
        now = time.time()
        out = []
        for r in self.db.execute("SELECT server, COUNT(*) AS n, SUM(1 - ok) AS bad FROM calls WHERE at >= ? "
                                 "GROUP BY server", (now - 900,)):
            if r["n"] >= 5 and (r["bad"] or 0) / r["n"] >= 0.2:
                out.append({"level": "error", "source": r["server"], "kind": "errors",
                            "message": f"{r['bad']}/{r['n']} lời gọi lỗi trong 15 phút qua"})
        slow: dict[tuple[str, str], list[float]] = {}
        for r in self.db.execute("SELECT server, tool, ms FROM calls WHERE at >= ?", (now - 3600,)):
            slow.setdefault((r["server"], r["tool"]), []).append(r["ms"])
        for (server, tool), ms in slow.items():
            p95 = percentile(ms, 0.95)
            if len(ms) >= 3 and p95 > 10_000:
                out.append({"level": "warning", "source": server, "kind": "slow",
                            "message": f"{tool} chậm: p95 {p95 / 1000:.1f} s trong 1 giờ qua"})
        for r in self.db.execute("SELECT source, COUNT(*) AS n, MAX(at) AS last FROM events WHERE kind = 'crash' "
                                 "AND at >= ? GROUP BY source", (now - 3600,)):
            recent = self.db.execute("SELECT COUNT(*) FROM events WHERE kind = 'crash' AND source = ? AND at >= ?",
                                     (r["source"], now - 600)).fetchone()[0]
            if recent >= 3:
                out.append({"level": "error", "source": r["source"], "kind": "crash-loop",
                            "message": f"dừng bất thường {recent} lần trong 10 phút"})
            else:
                out.append({"level": "warning", "source": r["source"], "kind": "crash",
                            "message": f"dừng bất thường {r['n']} lần trong 1 giờ qua"})
        for r in self.db.execute("SELECT source, MAX(message) AS message FROM events WHERE kind = 'log-flood' "
                                 "AND at >= ? GROUP BY source", (now - 3600,)):
            out.append({"level": "error", "source": r["source"], "kind": "log-flood", "message": "ghi log quá nhiều, đã bị dừng"})
        for r in self.db.execute("SELECT source, rss FROM samples s WHERE at = (SELECT MAX(at) FROM samples WHERE "
                                 "source = s.source) AND at >= ?", (now - 180,)):
            if r["rss"] and r["rss"] > 1536 * 1024 * 1024:
                out.append({"level": "warning", "source": r["source"], "kind": "memory",
                            "message": f"dùng {r['rss'] / 1024 / 1024 / 1024:.1f} GB RAM"})
        return sorted(out, key=lambda a: (a["level"] != "error", a["source"]))

    def calls_today(self) -> int:
        start = time.mktime(time.localtime()[:3] + (0, 0, 0, 0, 0, -1))
        return self.db.execute("SELECT COUNT(*) FROM calls WHERE at >= ?", (start,)).fetchone()[0]


def _call_row(r: sqlite3.Row) -> dict:
    return {"id": r["id"], "at": r["at"], "server": r["server"], "tool": r["tool"], "client": r["client"],
            "transport": r["transport"], "via": r["via"], "ms": r["ms"], "ok": bool(r["ok"]), "error": r["error"],
            "args": r["args"], "outChars": r["out_chars"], "tokens": round(r["out_chars"] / 4)}
