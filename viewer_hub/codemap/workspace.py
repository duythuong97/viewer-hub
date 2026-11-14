"""What one MCP server or API request reads: a pack's codemap folder and the user's knowledge database.

Ported from code-map codemap/workspace.py. The original compared the extract with
the working tree (file hashes, VCS log); a pack is a frozen snapshot with no working
tree, so ``stale()`` reports the extract time and commits recorded in the pack and
says freshness cannot be checked. No child process, no reading outside the pack.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import closing, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from viewer_hub.codemap.contract.serving import DATABASE_NAME
from viewer_hub.codemap.retriever import Retriever
from viewer_hub.codemap.storage import GraphNotReady, open_knowledge, open_search, open_web

SNAPSHOT_REASON = "pack snapshot: the extract is not compared with a working tree"


@dataclass
class Workspace:
    output: Path
    knowledge: Path | None = None
    source_root: Path | None = None
    readonly: bool = False
    _snapshot: tuple[tuple[int, int], dict[str, Any]] | None = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @contextmanager
    def retriever(self) -> Iterator[Retriever]:
        with open_search(self.output, self.knowledge) as db:
            yield Retriever(db)

    @contextmanager
    def web(self) -> Iterator[sqlite3.Connection | None]:
        """codemap.sqlite + knowledge db, or None when either is missing (tools then skip business docs)."""
        if self.knowledge is None:
            yield None
            return
        try:
            with open_web(self.output, self.knowledge, self.readonly) as db:
                yield db
        except GraphNotReady:
            yield None

    @contextmanager
    def knowledge_db(self) -> Iterator[sqlite3.Connection | None]:
        if self.knowledge is None:
            yield None
            return
        with open_knowledge(self.knowledge, self.readonly) as db:
            yield db

    @property
    def serving_path(self) -> Path:
        return self.output / DATABASE_NAME

    def stale(self) -> dict[str, Any]:
        """Same shape as code-map's stale report; ``fresh`` is None because a pack has no working tree."""
        stamp = _stamp(self.serving_path)
        with self._lock:
            if self._snapshot and self._snapshot[0] == stamp:
                return self._snapshot[1]
        report = snapshot_report(self.serving_path)
        with self._lock:
            self._snapshot = (stamp, report)
        return report

    def status_line(self) -> str:
        return summary_line(self.stale())

    def changed_files(self) -> set[str]:
        return set()

    def quality(self) -> dict[str, Any]:
        path = self.output / "quality-report.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}


def snapshot_report(path: Path) -> dict[str, Any]:
    """Extract time and recorded commits from codemap.sqlite ``meta``."""
    report: dict[str, Any] = {
        "generated_at": "", "source_root": "", "fresh": None, "reason": SNAPSHOT_REASON,
        "changed": [], "deleted": [], "added": [], "revisions": [], "sources_with_new_commits": [], "affected_nodes": [],
    }
    if not path.is_file():
        report["reason"] = f"{DATABASE_NAME} not found"
        return report
    try:
        with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as db:
            meta = dict(db.execute("SELECT key, value FROM meta").fetchall())
    except sqlite3.Error as exc:
        report["reason"] = str(exc)
        return report
    report["generated_at"] = meta.get("graph_generated_at") or meta.get("generated_at") or ""
    try:
        revisions = json.loads(meta.get("source_revisions") or "{}")
    except ValueError:
        revisions = {}
    if isinstance(revisions, dict):
        report["revisions"] = [
            {"source": name, "vcs": item.get("vcs", ""), "commit": item.get("commit", ""), "branch": item.get("branch", ""),
             "dirty_at_extract": bool(item.get("dirty")), "commits_since": None}
            for name, item in sorted(revisions.items()) if isinstance(item, dict)
        ]
    return report


def summary_line(report: dict[str, Any]) -> str:
    """One line for the top of an AI answer: when and from what the graph was built (code-map stale.summary_line)."""
    revisions = report.get("revisions") or []
    commits = sorted({str(item.get("commit", ""))[:8] for item in revisions if item.get("commit")})
    built = f"KB built {report.get('generated_at') or '?'}" + (f" @ {', '.join(commits)}" if commits else "")
    return f"{built} · freshness unknown ({report.get('reason', '')})"


def _stamp(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
        return stat.st_size, stat.st_mtime_ns
    except OSError:
        return 0, 0


_WORKSPACES: dict[tuple[str, str, bool], Workspace] = {}
_WORKSPACES_LOCK = threading.Lock()
MAX_WORKSPACES = 16


def workspace_for(output: Path, knowledge: Path | None, *, source_root: Path | None = None,
                  readonly: bool = False) -> Workspace:
    """One Workspace per (output, knowledge) so the snapshot report is read once per pack."""
    key = (str(output), str(knowledge), readonly)
    with _WORKSPACES_LOCK:
        workspace = _WORKSPACES.get(key)
        if workspace is None:
            while len(_WORKSPACES) >= MAX_WORKSPACES:
                _WORKSPACES.pop(next(iter(_WORKSPACES)))
            workspace = _WORKSPACES[key] = Workspace(
                output=Path(output), knowledge=Path(knowledge) if knowledge else None,
                source_root=source_root, readonly=readonly,
            )
    return workspace


def for_source(source) -> Workspace:
    """The Workspace of a packs.CodemapSource."""
    return workspace_for(source.output, source.knowledge, source_root=source.source_root, readonly=source.readonly)
