"""Core pages (home, settings, help, premium) and GET /api/app: what the React shell needs to draw this build."""
from __future__ import annotations

import secrets

from flask import Blueprint, g, redirect, request, url_for

from viewer_hub import __version__
from viewer_hub.app import spa
from viewer_hub.core import backup

bp = Blueprint("portal", __name__)


def _count(sql: str) -> int:
    row = g.hub.db.one(sql)
    return int(row[0]) if row else 0


@bp.get("/")
@bp.get("/settings")
@bp.get("/help")
def page():
    return spa.page()


@bp.get("/favicon.ico")
def favicon():
    return "", 204  # no icon file; avoids a 404 in every browser console


@bp.get("/api/app")
def app_info():
    """Menu and contents of this build. Locked premium features are never named: only a "Premium" entry."""
    from viewer_hub.core.config import any_locked

    hub = g.hub
    modules = hub.modules
    nav = [{"key": "home", "label": "Trang chủ", "icon": "home", "path": "/", "module": False}]
    nav += [{"key": m.key, "label": m.label, "icon": m.icon, "path": m.prefix, "module": True, "summary": m.summary,
             "addon": m.addon is not None,
             "mcp": {"path": m.mcp.path, "command": m.mcp.command} if m.mcp else None}
            for m in modules]
    locked = any_locked(hub.config, hub.every_module)
    if locked:
        nav.append({"key": "premium", "label": "Premium", "icon": "workspace_premium", "path": "/premium", "module": False})
    # An addon's page is its own built file (addons/routes.py), named here only while it is installed and unlocked.
    scripts = {m.key: f"{m.prefix}/{m.addon.script}" for m in modules if m.addon is not None and m.addon.script}
    styles = {m.key: f"{m.prefix}/{m.addon.style}" for m in modules if m.addon is not None and m.addon.style}
    return {"version": __version__, "readonly": bool(hub.readonly), "reason": hub.state.reason if hub.readonly else "",
            "nav": nav, "scripts": scripts, "styles": styles, "locked": locked}


@bp.get("/api/home")
def home():
    hub = g.hub
    packs = hub.db.query("SELECT id, version, title FROM packs WHERE active = 1 ORDER BY title")
    stats = {}
    for module in hub.modules:
        if module.stat:
            try:
                stats[module.key] = module.stat(hub)
            except Exception:  # a broken count never hides the home page
                pass
    return {"stats": stats, "packs": [dict(p) for p in packs], "alerts": _monitor_alerts(hub)}


def _monitor_alerts(hub) -> list[dict]:
    """What the Giám sát page warns about (failing MCP, crashing addon), for the home banner."""
    from viewer_hub.core.monitor import Reader

    try:
        with Reader(hub.paths.home) as reader:
            alerts = reader.alerts()
    except Exception:  # noqa: BLE001  (monitoring never hides the home page)
        return []
    from viewer_hub.monitor import labels

    names = labels(hub)
    return [{**a, "label": names.get(a["source"], a["source"])} for a in alerts]


@bp.get("/api/settings")
def settings():
    hub = g.hub
    packs = hub.db.query("SELECT id, version, title, imported_at, active FROM packs ORDER BY id, imported_at DESC")
    return {"home": str(hub.paths.home), "schema": hub.db.schema_version,
            "packs": [{**dict(p), "active": bool(p["active"])} for p in packs],
            "backups": [{"name": item.name, "path": str(item)} for item in backup.list_backups(hub.paths)]}


@bp.post("/api/settings/backup")
def backup_now():
    folder = backup.create(g.hub.paths, "manual", __version__)
    return {"message": f"Đã sao lưu: {folder.name}"}


@bp.post("/api/settings/import")
def import_pack_upload():
    from viewer_hub.packs.importer import PackError, import_pack

    upload = request.files.get("file")
    if not upload or not upload.filename.lower().endswith(".sapack"):
        raise spa.ApiError("bad_file", "Chọn một file .sapack")
    temp = g.hub.paths.tmp / f"import-{secrets.token_hex(6)}.sapack"
    upload.save(temp)
    try:
        manifest = import_pack(g.hub.paths, g.hub.db, temp, activate="auto")
    except (PackError, OSError, ValueError) as error:
        raise spa.ApiError("import_failed", f"Không import được: {error}") from error
    finally:
        temp.unlink(missing_ok=True)
    return {"message": f"Đã import {manifest.get('title') or manifest['id']} ({manifest['version']})"
                       + (f". {manifest['reason']}" if manifest.get("reason") else ". CSV, Docs và ghi chú của bạn giữ nguyên.")}


@bp.post("/api/settings/packs/activate")
def activate_pack():
    from viewer_hub.packs.importer import PackError, set_active

    body = request.get_json(silent=True) or {}
    pack_id, version = str(body.get("id", "")), str(body.get("version", ""))
    try:
        set_active(g.hub.db, g.hub.paths, pack_id, version)
    except PackError as error:
        raise spa.ApiError("pack", str(error)) from error
    return {"message": f"Đang dùng {pack_id} {version}"}


@bp.get("/api/help")
def help_page():
    from viewer_hub import help as guide
    from viewer_hub.core.config import any_locked

    html, toc, title = guide.render(g.hub.modules, locked=any_locked(g.hub.config, g.hub.every_module))
    return {"html": html, "toc": toc, "title": title}


@bp.post("/api/premium/unlock")
def unlock_premium():
    """Check an unlock code, keep it and open its features now (core/unlock.py). Names only what it opened."""
    from viewer_hub.core import config as app_config
    from viewer_hub.core import unlock

    hub = g.hub
    code = str((request.get_json(silent=True) or {}).get("code", ""))
    try:
        names = unlock.save(hub.db, code)
    except unlock.UnlockError as error:
        raise spa.ApiError("bad_code", f"Mã mở khoá không đúng: {error}.") from error
    fresh = {n for n in names if not app_config.premium_enabled(hub.config, n)}
    app_config.unlock(hub.config, names)
    opened = [m for m in hub.modules if m.premium in names]
    # What `viewer-hub serve` does at start for unlocked daemon addons (autostart, MCP gateway).
    from viewer_hub.addons import gateway

    gateway.autostart_in_background(hub, only={m.key for m in opened if m.addon is not None and m.premium in fresh})
    if not opened:  # a valid code for a feature this machine does not have (yet): it opens once the addon is installed
        return {"message": "Đã lưu mã. Tính năng của mã này chưa được cài trên máy; cài addon là dùng được.",
                "path": "/"}
    return {"message": "Đã mở khoá: " + ", ".join(m.label for m in opened), "path": opened[0].prefix + "/"}


@bp.get("/premium")
@bp.get("/premium/")
def premium():
    """The unlock page, never naming what is locked. Once everything is unlocked (an old bookmark), it goes to the
    first premium module; with no premium module installed it stays, so a code can be saved before its addon."""
    from viewer_hub.core.config import any_locked

    if not any_locked(g.hub.config, g.hub.every_module):
        target = next((m for m in g.hub.modules if m.premium), None)
        if target:
            return redirect(target.prefix + "/")
    return spa.page()
