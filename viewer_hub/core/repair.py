"""Rebuild hub.db from the JSON files next to the data (design.md §8.5)."""
from __future__ import annotations

import time

from viewer_hub import __version__
from viewer_hub.core import backup
from viewer_hub.core.atomic import read_json
from viewer_hub.core.paths import HubPaths


def repair(paths: HubPaths) -> str:
    from viewer_hub.core.migrate import open_hub
    from viewer_hub.packs.importer import register

    saved = None
    if paths.db.exists():
        try:
            saved = backup.create(paths, "before-repair", __version__)
        except Exception:  # a corrupt hub.db cannot be backed up with the sqlite API; keep the file itself
            broken = paths.home / f"hub.db.broken-{time.strftime('%Y%m%d-%H%M%S')}"
            paths.db.rename(broken)
            for side in ("-wal", "-shm"):
                (paths.home / f"hub.db{side}").unlink(missing_ok=True)
    if paths.db.exists():
        paths.db.unlink()
        for side in ("-wal", "-shm"):
            (paths.home / f"hub.db{side}").unlink(missing_ok=True)

    state = open_hub(paths)
    db = state.db
    counts = {"packs": 0, "datasets": 0, "sites": 0}
    from viewer_hub.packs.importer import version_key

    newest: dict[str, str] = {}
    manifests = [m for m in (read_json(f) for f in sorted(paths.packs.glob("*/*/pack.json"))) if m]
    for manifest in manifests:
        if manifest["id"] not in newest or version_key(manifest["version"]) > version_key(newest[manifest["id"]]):
            newest[manifest["id"]] = manifest["version"]
    for manifest in manifests:  # every version comes back; the newest of each pack is the one in use
        register(db, manifest, activate=newest[manifest["id"]] == manifest["version"])
        counts["packs"] += 1
    with db.write() as conn:
        for meta_file in paths.csv.glob("*/dataset.json"):
            m = read_json(meta_file)
            if not m:
                continue
            needs = 0 if (meta_file.parent / "data.sqlite").is_file() else 1
            conn.execute(
                "INSERT OR REPLACE INTO datasets (id, title, origin, schema, rows, needs_rebuild, created_at, updated_at) VALUES (?, ?, 'workspace', ?, ?, ?, ?, ?)",
                (m["id"], m.get("title") or m["id"], m.get("schema", 1), m.get("rows", 0), needs, m.get("createdAt", ""), m.get("updatedAt", "")),
            )
            counts["datasets"] += 1
        for meta_file in paths.sites.glob("*/site.json"):
            m = read_json(meta_file)
            if not m:
                continue
            built = (meta_file.parent / "site" / "index.html").is_file()
            conn.execute(
                "INSERT OR REPLACE INTO sites (id, title, origin, schema, pages, needs_rebuild, build_error, built_at, created_at, updated_at) VALUES (?, ?, 'workspace', ?, ?, ?, ?, ?, ?, ?)",
                (m["id"], m.get("title") or m["id"], m.get("schema", 1), m.get("pages", 0), 0 if built else 1,
                 m.get("buildError"), m.get("builtAt"), m.get("createdAt", ""), m.get("updatedAt", "")),
            )
            counts["sites"] += 1
    db.close()
    return f"Đã dựng lại hub.db: {counts}" + (f"; sao lưu trước đó: {saved}" if saved else "")
