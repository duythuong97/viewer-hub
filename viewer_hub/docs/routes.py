"""Docs sites: the page (React, web/src/modules/docs), JSON API (list, create from a markdown folder or zip, rebuild,
delete) and the built sites, served sandboxed on the content origin."""
from __future__ import annotations

import mimetypes

from flask import Blueprint, abort, g, request, send_file, url_for

from viewer_hub.app import spa
from viewer_hub.app.origins import content_url

from viewer_hub.docs.store import BUILD_PROFILE, Site, SiteError, SiteStore, build, safe_relative

bp = Blueprint("docs", __name__)

# Site pages are user content. They are served only from the content origin
# (http://localhost:<port>, see app/origins.py), never the app origin, and may
# not load anything from another host.
CONTENT_CSP = (
    "default-src 'self' data: blob:; script-src 'self' 'unsafe-inline' blob:; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; worker-src 'self' blob:; "
    "frame-ancestors 'none'; form-action 'self'; base-uri 'self'"
)


def store() -> SiteStore:
    from viewer_hub.packs.content import pack_dirs

    return SiteStore(g.hub.paths.sites, g.hub.paths.tmp, packs=pack_dirs(g.hub, "docs"))


def _writable(site: Site) -> Site:
    if site.readonly:  # shipped in a data pack: rebuild/update/delete belong to the admin
        raise spa.ApiError("readonly_site", "Site trong data pack do admin cung cấp, chỉ đọc", 403)
    return site


def _site(site_id: str) -> Site:
    site = store().get(site_id)
    if not site:
        raise spa.ApiError("not_found", "Không có site này", 404)
    return site


def _json(site: Site) -> dict:
    m = site.meta
    return {"id": site.id, "title": site.title, "pages": m.get("pages") or 0, "files": m.get("files") or 0,
            "readonly": bool(site.readonly), "pack": (m.get("pack") or {}).get("title", ""),
            "buildError": m.get("buildError") or "", "built": bool(site.built), "builtAt": m.get("builtAt") or "",
            "src": "" if site.readonly else str(site.src),
            "viewUrl": content_url(url_for("docs.view", site_id=site.id)) if site.built else ""}


def _register(site: Site) -> None:
    m = site.meta
    with g.hub.db.write() as db:
        db.execute(
            """INSERT INTO sites (id, title, origin, schema, pages, needs_rebuild, build_error, built_at, created_at, updated_at)
               VALUES (?, ?, 'workspace', ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET title=excluded.title, pages=excluded.pages, needs_rebuild=excluded.needs_rebuild,
                 build_error=excluded.build_error, built_at=excluded.built_at, updated_at=excluded.updated_at""",
            (site.id, site.title, m["schema"], m.get("pages", 0), 0 if site.built else 1, m.get("buildError"),
             m.get("builtAt"), m["createdAt"], m["updatedAt"]),
        )


def _build(site: Site) -> tuple[bool, str]:
    try:
        pages = build(site, g.hub.paths.tmp)
        return True, f"Đã build {site.title}: {pages} trang"
    except SiteError as error:
        return False, str(error)
    finally:
        _register(site)


@bp.get("/")
@bp.get("/<site_id>/")
def index(site_id: str | None = None):
    return spa.page()


@bp.get("/api/sites")
def list_sites():
    return {"sites": [_json(site) for site in store().list()]}


@bp.post("/api/sites")
def create():
    """New site, or new sources for ``site_id``, from uploaded files (folder paths kept) or one .zip; then build."""
    title = (request.form.get("title") or "").strip()
    uploads = [f for f in request.files.getlist("file") if f and f.filename]
    if not uploads:
        raise spa.ApiError("no_files", "Chưa chọn thư mục hoặc file .zip")
    if not title:
        first = uploads[0].filename.replace("\\", "/")
        title = first.split("/")[0] if "/" in first else first.rsplit(".", 1)[0]
    site_id = request.form.get("site_id") or None
    if site_id:
        _writable(_site(site_id))
    try:
        site = store().create(title, [(f.filename, f.read()) for f in uploads], site_id=site_id)
    except SiteError as error:
        raise spa.ApiError("bad_site", str(error)) from error
    ok, message = _build(site)
    return {"site": _json(store().get(site.id) or site), "ok": ok, "message": message}


@bp.get("/api/sites/<site_id>")
def detail(site_id: str):
    return {"site": _json(_site(site_id))}


@bp.post("/api/sites/<site_id>/rebuild")
def rebuild(site_id: str):
    site = _writable(_site(site_id))
    ok, message = _build(site)
    return {"site": _json(store().get(site.id) or site), "ok": ok, "message": message}


@bp.delete("/api/sites/<site_id>")
def delete(site_id: str):
    site = _writable(_site(site_id))
    store().delete(site)
    with g.hub.db.write() as db:
        db.execute("DELETE FROM sites WHERE id = ?", (site.id,))
    return {"message": f"Đã xoá {site.title}"}


@bp.get("/<site_id>/view/", defaults={"path": "index.html"})
@bp.get("/<site_id>/view/<path:path>")
def view(site_id: str, path: str):
    site = _site(site_id)
    if site.meta.get("buildProfile") != BUILD_PROFILE and site.src.is_dir() and not g.hub.readonly and not site.readonly:
        try:  # built by an older version: rebuild once with the current menu layout
            build(site, g.hub.paths.tmp)
        except SiteError:
            pass  # keep serving the old build; the detail page shows the error
        _register(site)
    relative = safe_relative(path if not path.endswith("/") else path + "index.html")
    if relative is None:
        abort(404)
    target = site.html.joinpath(*relative.parts)
    if target.is_dir():
        target = target / "index.html"
    try:
        target.resolve().relative_to(site.html.resolve())
    except ValueError:
        abort(404)
    if not target.is_file():
        abort(404)
    response = send_file(target, mimetype=mimetypes.guess_type(target.name)[0] or "application/octet-stream",
                         max_age=0, conditional=True)
    response.headers["Content-Security-Policy"] = CONTENT_CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
