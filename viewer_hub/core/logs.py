"""Rotating log file under the data dir. Never log document text, CSV cell values or tokens."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from viewer_hub.core.paths import HubPaths


def configure(paths: HubPaths, verbose: bool = False) -> Path:
    log_file = paths.logs / "viewer-hub.log"
    handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    return log_file
