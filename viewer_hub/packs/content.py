"""CSV datasets and docs sites shipped inside data packs (design.md §5).

They are built on the admin's machine (packs/builder.py), so the pack already holds
dataset.json + data.sqlite and the built site/. On the user's machine they are listed next to
the user's own items, read-only, with ids ``<pack_id>--<item_id>`` so they can never collide
with (or overwrite) anything the user uploaded.
"""
from __future__ import annotations

import json
from pathlib import Path


def pack_dirs(hub, kind: str) -> list[tuple[str, str, Path]]:
    """(pack_id, pack title, folder) of the ``kind`` ("csv" | "docs") part of every active pack."""
    out = []
    try:
        rows = hub.db.query("SELECT id, version, title, components FROM packs WHERE active = 1 ORDER BY title")
    except Exception:  # noqa: BLE001  (a broken registry must not take the page down)
        return out
    for row in rows:
        try:
            components = json.loads(row["components"] or "{}")
        except ValueError:
            continue
        if not components.get(kind):
            continue
        folder = (hub.paths.packs / row["id"] / row["version"] / kind).resolve()
        if folder.is_dir() and folder.is_relative_to(hub.paths.packs.resolve()):
            out.append((row["id"], row["title"] or row["id"], folder))
    return out
