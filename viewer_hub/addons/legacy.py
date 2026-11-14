"""Features that moved from the Hub into an addon keep their data and their addresses.

SVN was a builtin module (``/svn``, repositories in hub.db setting ``svn.repos``) and is now the addon ``svn``
(repo viewer-hub-addons/svn, shipped as a default addon): its list is copied once into the addon's data folder, and
the old addresses (an AI configured with ``http://…/svn/mcp``) answer with a redirect to ``/x/svn/…``.
"""
from __future__ import annotations

import json
import logging

from flask import Blueprint, redirect, request

from viewer_hub.core import atomic
from viewer_hub.core.paths import HubPaths

logger = logging.getLogger(__name__)
bp = Blueprint("legacy", __name__)


def migrate_svn(paths: HubPaths, db) -> bool:
    """hub.db ``svn.repos`` → ``user/addons/svn/repos.json`` when the addon has no list yet (the addon's
    svn_repos.py reads it). The setting stays in hub.db (backups, going back to an older Hub)."""
    target = paths.addon_data("svn") / "repos.json"
    if target.exists():
        return False
    try:
        repos = json.loads(db.setting("svn.repos", "[]"))
    except ValueError:
        return False
    if not isinstance(repos, list) or not repos:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic.write_json(target, [r for r in repos if isinstance(r, dict)])
    logger.info("SVN: %s repo copied to the svn addon", len(repos))
    return True


@bp.route("/svn", defaults={"rest": ""}, methods=["GET", "POST", "DELETE"])
@bp.route("/svn/<path:rest>", methods=["GET", "POST", "PUT", "DELETE"])
def svn(rest: str):
    """308 keeps the method and body, so an MCP client posting to /svn/mcp reaches /x/svn/mcp."""
    query = request.query_string.decode()
    return redirect(f"/x/svn/{rest}" + (f"?{query}" if query else ""), code=308)
