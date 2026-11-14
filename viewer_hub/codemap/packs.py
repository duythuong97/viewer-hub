"""Which code-map data a request reads (design.md §6.1, §7.4).

Settings are resolved per request, never cached at import: every active row of
hub.db ``packs`` whose ``components`` JSON has ``codemap`` is a source, read from
``packs/<id>/<version>/<component path>`` (default ``codemap/``). For development
a plain extract output folder at ``<home>/codemap/`` is served too (pack id
``local``), like ocr-search serves ``<home>/search/search.sqlite``.

What people write about a pack (notes, rules, flow documents, MCP call log) goes to
``user/codemap/<pack_id>/knowledge.sqlite``: keyed by pack id, not version, so it
survives a pack update, and never inside the pack.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from viewer_hub.codemap.contract.serving import DATABASE_NAME

logger = logging.getLogger(__name__)

LOCAL_ID = "local"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
KNOWLEDGE_TOKEN_KEY = "codemap.knowledgeToken"


@dataclass(frozen=True)
class CodemapSource:
    pack_id: str
    title: str
    version: str
    output: Path  # folder with codemap.sqlite (+ graph.sqlite, quality-report.json)
    knowledge: Path  # user/codemap/<pack_id>/knowledge.sqlite
    source_root: Path | None  # source files for /api/snippet, only when the pack ships them
    readonly: bool = False

    @property
    def has_source(self) -> bool:
        return self.source_root is not None

    def describe(self) -> dict:
        return {"id": self.pack_id, "title": self.title, "version": self.version, "source": self.has_source}


def _within(child: Path, parent: Path) -> bool:
    try:
        return child.resolve().is_relative_to(parent.resolve())
    except OSError:
        return False


def _source_root(*candidates: Path) -> Path | None:
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    return None


def sources(hub) -> list[CodemapSource]:
    """Active code-map packs (by title), then the dev folder ``<home>/codemap``."""
    found: list[CodemapSource] = []
    seen: set[str] = set()
    knowledge_root = hub.paths.user / "codemap"
    try:
        rows = hub.db.query("SELECT id, version, title, components FROM packs WHERE active = 1 ORDER BY title, id")
    except Exception:  # noqa: BLE001  (a broken registry must not take the page down)
        logger.warning("cannot read packs from hub.db", exc_info=True)
        rows = []
    for row in rows:
        pack_id = str(row["id"])
        if pack_id in seen or not _SAFE_ID.match(pack_id) or pack_id == LOCAL_ID:
            continue
        try:
            components = json.loads(row["components"] or "{}")
        except ValueError:
            continue
        component = components.get("codemap") if isinstance(components, dict) else None
        if not component:
            continue
        folder = hub.paths.packs / pack_id / str(row["version"])
        relative = str((component.get("path") if isinstance(component, dict) else None) or "codemap/")
        output = folder / relative
        if not _within(output, folder) or not output.is_dir():
            continue
        seen.add(pack_id)
        found.append(CodemapSource(
            pack_id=pack_id,
            title=str(row["title"] or pack_id),
            version=str(row["version"]),
            output=output.resolve(),
            knowledge=knowledge_root / pack_id / "knowledge.sqlite",
            source_root=_source_root(folder / "source", output / "source"),
            readonly=bool(hub.readonly),
        ))
    local = hub.paths.home / "codemap"
    if (local / DATABASE_NAME).is_file():
        found.append(CodemapSource(
            pack_id=LOCAL_ID,
            title="codemap (local)",
            version="",
            output=local.resolve(),
            knowledge=knowledge_root / LOCAL_ID / "knowledge.sqlite",
            source_root=_source_root(local / "source"),
            readonly=bool(hub.readonly),
        ))
    return found


def pick(hub, pack_id: str | None = None) -> CodemapSource | None:
    """The source ``pack_id`` names, else the first one; None when no code-map data is installed."""
    available = sources(hub)
    if pack_id:
        for source in available:
            if source.pack_id == pack_id:
                return source
        return None
    return available[0] if available else None


def knowledge_token(hub) -> str:
    """Token that unlocks writes from outside the browser (HTTP MCP propose_* tools, POST /knowledge).

    Set in hub.db settings (``codemap.knowledgeToken``) or $CODE_MAP_KNOWLEDGE_TOKEN; none means no such writes.
    """
    import os

    try:
        token = hub.db.setting(KNOWLEDGE_TOKEN_KEY)
    except Exception:  # noqa: BLE001
        token = ""
    return token or os.environ.get("CODE_MAP_KNOWLEDGE_TOKEN", "")
