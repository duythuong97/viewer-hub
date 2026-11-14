"""Packs shipped inside the release zip (ViewerHub-<version>/packs/*.sapack).

On start, every bundled pack whose id+version is not imported yet is imported
and activated unless it is older than the version in use, so users unzip one file and have the author's data ready. A new
release with newer packs brings the new data the same way; user notes are
keyed by pack id, not version, so they carry over (design.md §7.4).
"""
from __future__ import annotations

import json
import logging
import os
import zipfile
from pathlib import Path

import viewer_hub
from viewer_hub.core.db import HubDB
from viewer_hub.core.paths import HubPaths
from viewer_hub.packs.importer import PackError, import_pack

logger = logging.getLogger(__name__)


def bundled_dir() -> Path:
    configured = os.environ.get("VIEWER_HUB_BUNDLED_PACKS")
    if configured:
        return Path(configured)
    package = Path(viewer_hub.__file__).resolve().parent
    # Release: <root>/app/viewer_hub → <root>/packs. Source checkout: <repo>/viewer_hub → <repo>/packs.
    root = package.parent.parent if package.parent.name == "app" else package.parent
    return root / "packs"


def _manifest(file: Path) -> dict | None:
    try:
        with zipfile.ZipFile(file) as archive:
            return json.loads(archive.read("pack.json").decode("utf-8"))
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return None


def import_bundled(paths: HubPaths, db: HubDB, folder: Path | None = None) -> list[str]:
    folder = folder or bundled_dir()
    if not folder.is_dir():
        return []
    done = []
    for file in sorted(folder.glob("*.sapack")):
        manifest = _manifest(file)
        if not manifest:
            logger.warning("bundled pack unreadable: %s", file.name)
            continue
        if db.one("SELECT 1 FROM packs WHERE id = ? AND version = ?", (manifest.get("id"), manifest.get("version"))):
            continue
        try:
            result = import_pack(paths, db, file, activate="auto")
            done.append(f"{manifest['id']} {manifest['version']}" + ("" if result["activated"] else " (cũ hơn bản đang dùng, chưa bật)"))
        except PackError as error:
            logger.error("bundled pack %s rejected: %s", file.name, error)
    return done
