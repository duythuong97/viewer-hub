"""Every addon's URLs (docs/addons.md §5, §6), one blueprint for all, so installing one needs no restart:

    /x/<id>, /x/<id>/<subpath>      the React app (its page: ui/ui.js of the addon, or the Hub's own addon page)
    /x/<id>/ui/<file>               the addon's built UI (no-cache, so a rebuild shows on F5)
    /x/<id>/api/<path>              relayed to the addon: HTTP with its token (managed), its admin channel (daemon),
                                    or HTTP to the user's own program on 127.0.0.1:<port setting> (external)
    /x/<id>/mcp                     MCP JSON-RPC, read-only tools only
    /api/addons[/<id>[/<action>]]   the Hub's control: list, install (upload), remove, start / stop, settings,
                                    status (poll), log (the whole log of the addon's output)
    /api/addons/sdk                 the kit for writing addons (zip)

The browser never reaches an addon process. Writes need the page's own header X-Viewer-Hub (a cross-site form or
fetch cannot send it without a CORS preflight, which is refused) and, when the browser sends one, an Origin of this
app. A locked premium addon does not exist: 404, its page goes to /premium.
"""
from __future__ import annotations

import json
import secrets
from urllib.parse import urlparse

from flask import Blueprint, Response, abort, g, jsonify, redirect, request, send_from_directory, stream_with_context

from viewer_hub.addons import channel, gateway, proxy
from viewer_hub.addons.install import AddonError, install_zip, peek, uninstall
from viewer_hub.addons.manifest import Addon
from viewer_hub.addons import limits
from viewer_hub.addons.runner import AddonUnavailable, Daemon, External
from viewer_hub.app import spa
from viewer_hub.core.config import premium_enabled
from viewer_hub.core import monitor
from viewer_hub.core.mcp import ALLOWED_ORIGIN_HOSTS, MAX_HTTP_BODY

bp = Blueprint("addons", __name__)
HEADER = "X-Viewer-Hub"
MAX_BODY = 8 * 1024 * 1024


def _guard() -> None:
    if request.method != "GET":
        if request.headers.get(HEADER) != "1":
            abort(403)
        origin = request.headers.get("Origin")
        if origin and urlparse(origin).netloc != request.host:
            abort(403)


def _find(addon_id: str) -> Addon:
    addon = g.hub.addons.get(addon_id)
    if addon is None or (addon.premium and not premium_enabled(g.hub.config, addon.premium)):
        abort(404)
    return addon


def _unavailable(addon: Addon, exc: Exception):
    return spa.error("addon_not_running", f"{addon.name} chưa chạy: {exc}", 503)


def _ensure(runner) -> tuple[int, str]:
    port, token = runner.ensure()
    if isinstance(runner, External) and port == _port():
        raise AddonUnavailable("cổng của chương trình trùng cổng của Viewer Hub")
    return port, token


def _port() -> int:
    if g.hub.port:
        return g.hub.port
    try:
        return int(request.environ.get("SERVER_PORT") or 0) or 8700
    except ValueError:
        return 8700


# ── pages and files ─────────────────────────────────────────────────────────────────────────────────────────────

@bp.get("/x/<addon_id>")
@bp.get("/x/<addon_id>/")
@bp.get("/x/<addon_id>/<path:_sub>")
def page(addon_id: str, _sub: str = ""):
    addon = g.hub.addons.get(addon_id)
    if addon and addon.premium and not premium_enabled(g.hub.config, addon.premium):
        return redirect("/premium")
    if addon is None:
        abort(404)
    return spa.page()


@bp.get("/x/<addon_id>/ui/<path:name>")
def ui_file(addon_id: str, name: str):
    addon = _find(addon_id)
    if not addon.script:
        abort(404)
    response = send_from_directory(addon.folder / "ui", name, max_age=0)
    response.headers["Cache-Control"] = "no-cache"
    return response


# ── relay to the addon ──────────────────────────────────────────────────────────────────────────────────────────

@bp.route("/x/<addon_id>/api/<path:sub>", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def relay(addon_id: str, sub: str):
    addon = _find(addon_id)
    _guard()
    if request.content_length and request.content_length > MAX_BODY:
        abort(413)
    runner = g.hub.addons.runner(addon)
    wants_events = request.method == "GET" and "text/event-stream" in request.headers.get("Accept", "")
    if isinstance(runner, Daemon):
        return _relay_daemon(addon, runner, sub, wants_events)
    try:
        if wants_events:
            held = limits.take(addon.id, "stream")
            try:
                port, token = _ensure(runner)
                status, headers, chunks = proxy.stream(port, token, f"/api/{sub}", request.args.to_dict(flat=False))
            except BaseException:
                held.release()
                raise
            return Response(stream_with_context(_released(chunks, held)), status=status,
                            headers={**headers, "X-Accel-Buffering": "no"})
        with limits.slot(addon.id):
            port, token = _ensure(runner)
            status, headers, data = proxy.request(port, token, request.method, f"/api/{sub}",
                                                  query=request.args.to_dict(flat=False), body=request.get_data() or None,
                                                  headers={"Content-Type": request.content_type or "application/json"})
    except (AddonUnavailable, proxy.Unavailable) as exc:
        return _unavailable(addon, exc)
    return Response(data, status=status, headers=headers or {"Content-Type": "application/json"})


def _released(chunks, held):
    """A stream that gives its slot back when the page goes away (or the addon ends it)."""
    try:
        yield from chunks
    finally:
        held.release()


def _relay_daemon(addon: Addon, runner: Daemon, sub: str, wants_events: bool):
    if wants_events or sub == "events":
        return _events(addon, runner)
    body = request.get_json(silent=True) if request.method != "GET" and request.content_length else None
    try:
        with limits.slot(addon.id):
            status, reply = runner.request(request.method, f"/api/{sub}", query=request.args.to_dict(), body=body)
    except (channel.Unavailable, OSError, ValueError, AddonUnavailable) as exc:
        return _unavailable(addon, exc)
    return Response(json.dumps(reply, ensure_ascii=False), status=status, mimetype="application/json")


def _events(addon: Addon, runner: Daemon):
    """Server-sent events relayed from the daemon (the page reconnects when the daemon restarts)."""
    try:
        held = limits.take(addon.id, "stream")
    except AddonUnavailable as exc:
        return _unavailable(addon, exc)
    try:
        stream = runner.events()
        first = next(stream)
    except (channel.Unavailable, OSError, StopIteration) as exc:
        held.release()
        return _unavailable(addon, exc)

    def generate():
        try:
            yield "retry: 3000\n\n"
            for item in _chain(first, stream):
                if item.get("event") == "keepalive":
                    yield ": keepalive\n\n"
                    continue
                yield f"event: {item.get('event')}\ndata: {json.dumps(item.get('data') or {}, ensure_ascii=False)}\n\n"
        finally:
            held.release()

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


def _chain(first, rest):
    yield first
    yield from rest


@bp.route("/x/<addon_id>/mcp", methods=["GET", "POST"])
def mcp(addon_id: str):
    addon = _find(addon_id)
    if not addon.mcp:
        abort(404)
    if request.method != "POST":
        return Response(status=405, headers={"Allow": "POST"})
    origin = request.headers.get("Origin")
    if origin and (urlparse(origin).hostname or "").lower() not in ALLOWED_ORIGIN_HOSTS:
        return jsonify(jsonrpc="2.0", id=None, error={"code": -32600, "message": "Origin not allowed"}), 403
    if request.content_length is None or request.content_length > MAX_HTTP_BODY:
        return jsonify(jsonrpc="2.0", id=None, error={"code": -32600, "message": "Bounded JSON body required"}), 413
    try:
        message = json.loads(request.get_data(as_text=True))
    except ValueError:
        return jsonify(jsonrpc="2.0", id=None, error={"code": -32700, "message": "Parse error"}), 400
    runner = g.hub.addons.runner(addon)
    try:
        with limits.slot(addon.id):
            port, token = _ensure(runner)
            context = monitor.http_context(request.headers)
            try:
                status, reply = proxy.mcp_call(port, token, message, runner.read_only_tools, addon.mcp.command)
            finally:
                monitor.reset_context(context)
    except (AddonUnavailable, proxy.Unavailable) as exc:
        return jsonify(jsonrpc="2.0", id=message.get("id") if isinstance(message, dict) else None,
                       error={"code": -32603, "message": str(exc)}), 503
    if reply is None:
        return Response(status=202)
    return Response(json.dumps(reply, ensure_ascii=False), status=200 if status < 300 else status,
                    mimetype="application/json")


# ── the Hub's control of addons ─────────────────────────────────────────────────────────────────────────────────

def _info(addon: Addon, detail: bool = False) -> dict:
    hub = g.hub
    runner = hub.addons.runner(addon)
    problem = runner.problem()
    running = not problem and runner.running()
    info = {"id": addon.id, "name": addon.name, "version": addon.version, "label": addon.label, "icon": addon.icon,
            "summary": addon.summary, "lifecycle": addon.lifecycle, "runtime": addon.runtime, "path": addon.prefix,
            "trust": hub.addons.trust(addon), "running": running, "problem": problem, "ui": bool(addon.script),
            "mcp": {"path": f"{addon.prefix}/mcp", "command": addon.mcp.command, "scope": addon.mcp.scope,
                    "tools": list(addon.mcp.tools)} if addon.mcp else None}
    if not detail:
        return info
    info.update(settings=[s.public() for s in addon.settings], values=hub.addons.settings(addon))
    if addon.external:
        info["port"] = runner.port()
    if addon.daemon:
        info.update(autostart=gateway.autostart_enabled(hub.db, addon.id),
                    gateway=gateway.gateway_enabled(hub.db, addon.id) if gateway.PROVIDES in addon.provides else None)
    if addon.guide.is_file():
        from viewer_hub.help import render_markdown

        info["guide"] = render_markdown(addon.guide.read_text(encoding="utf-8"))
    return info


@bp.get("/api/addons")
def list_addons():
    hub = g.hub
    shown, locked = [], 0
    for addon in hub.addons.addons():
        if addon.premium and not premium_enabled(hub.config, addon.premium):
            locked += 1  # never named while locked
            continue
        shown.append(_info(addon))
    broken = [{"folder": name, "error": error} for name, error in sorted(hub.addons.broken.items())]
    return {"addons": shown, "broken": broken, "locked": locked, "folder": str(hub.paths.addons)}


@bp.get("/api/addons/sdk")
def sdk():
    """The kit for writing addons (sdk_kit.py): AGENTS.md for an AI, templates, the page build script."""
    from viewer_hub.addons import sdk_kit

    return Response(sdk_kit.build(), mimetype="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{sdk_kit.file_name()}"', "Cache-Control": "no-store"})


@bp.post("/api/addons")
def install():
    _guard()
    hub = g.hub
    upload = request.files.get("file")
    if not upload or not upload.filename.lower().endswith(".zip"):
        raise spa.ApiError("bad_file", "Chọn file addon .zip")
    temp = hub.paths.tmp / f"addon-upload-{secrets.token_hex(6)}.zip"
    hub.paths.tmp.mkdir(parents=True, exist_ok=True)
    upload.save(temp)
    try:
        wanted = peek(temp)
        old = hub.addons.get(wanted.id)
        was_running = bool(old) and hub.addons.runner(old).running()

        def stop_old(_checked) -> None:  # a running program keeps files open: stop it, but only for a good zip
            stopped, why = hub.addons.forget(wanted.id)
            if not stopped:
                raise AddonError(why)

        result = install_zip(hub.paths, temp, reserved=hub.addons.reserved, before_swap=stop_old)
    except (AddonError, OSError) as error:
        raise spa.ApiError("install_failed", f"Không cài được addon: {error}") from error
    finally:
        temp.unlink(missing_ok=True)
    hub.addons.refresh(force=True)
    addon = result.addon
    message = f"Đã cài {addon.name} {addon.version}" + (f" (thay bản {result.replaced})" if result.replaced else "")
    if result.trust == "unsigned":
        message += ". Addon chưa ký: chỉ dùng addon do admin cung cấp"
    if was_running and addon.daemon:
        ok, started = hub.addons.runner(addon).start(hub.addons.settings(addon))
        message += f". {started}"
    unlocked = not addon.premium or premium_enabled(hub.config, addon.premium)
    return {"message": message, "notes": result.notes, "trust": result.trust,
            "path": addon.prefix + "/" if unlocked else "/premium"}


@bp.delete("/api/addons/<addon_id>")
def remove(addon_id: str):
    _guard()
    hub = g.hub
    addon = _find(addon_id)
    stopped, why = hub.addons.forget(addon.id)
    if not stopped:
        raise spa.ApiError("remove_failed", f"Không gỡ được: {why}")
    try:
        uninstall(hub.paths, addon.id)
    except (AddonError, OSError) as error:
        raise spa.ApiError("remove_failed", f"Không gỡ được: {error}") from error
    hub.addons.refresh(force=True)
    return {"message": f"Đã gỡ {addon.name}. Dữ liệu của addon vẫn giữ trong {hub.paths.addon_data(addon.id)}"}


@bp.get("/api/addons/<addon_id>")
def detail(addon_id: str):
    return _info(_find(addon_id), detail=True)


@bp.get("/api/addons/<addon_id>/status")
def status(addon_id: str):
    """Cheap poll for the page: is it running (the full detail reloads only when this changes)."""
    runner = g.hub.addons.runner(_find(addon_id))
    problem = runner.problem()
    return {"running": not problem and runner.running(), "problem": problem}


@bp.get("/api/addons/<addon_id>/log")
def log(addon_id: str):
    """The addon's whole log (runner.py: its output, rotated at LOG_MAX), as text."""
    runner = g.hub.addons.runner(_find(addon_id))
    return {"text": runner.log_text(), "file": str(runner.log_file)}


@bp.put("/api/addons/<addon_id>/settings")
def save_settings(addon_id: str):
    _guard()
    hub = g.hub
    addon = _find(addon_id)
    values = (request.get_json(silent=True) or {}).get("values")
    if not isinstance(values, dict):
        raise spa.ApiError("bad_settings", "Thiếu values")
    try:
        saved = hub.addons.save_settings(addon, values)
    except AddonError as error:
        raise spa.ApiError("bad_settings", str(error)) from error
    message = "Đã lưu"
    runner = hub.addons.runner(addon)
    if addon.daemon and any(s.arg for s in addon.settings) and runner.running():
        ok, text = runner.stop()  # its arguments come from these settings: run it again with the new ones
        if ok:
            ok, text = runner.start(saved)
        message += f". {text}"
    return {"message": message, "values": saved}


@bp.post("/api/addons/<addon_id>/<action>")
def control(addon_id: str, action: str):
    _guard()
    hub = g.hub
    addon = _find(addon_id)
    body = request.get_json(silent=True) or {}
    runner = hub.addons.runner(addon)
    if action in {"autostart", "gateway"}:
        if not addon.daemon or (action == "gateway" and gateway.PROVIDES not in addon.provides):
            abort(404)
        on = bool(body.get("on"))
        gateway.set_flag(hub.db, gateway.autostart_key(addon.id) if action == "autostart" else gateway.gateway_key(addon.id), on)
        reply = {"ok": True, action: on}
        if action == "gateway" and on:
            gateway.forget_registered(hub.db, addon.id)  # switched on again: every Hub server, also removed ones
            if runner.running():
                reply["ok"], reply["message"] = gateway.register(runner, _port(), hub.modules, hub.db)
        return reply
    if action not in {"start", "stop", "restart"} or addon.external:
        abort(404)  # an external program is the user's: the Hub never starts or stops it
    if action != "stop" and runner.problem():
        return jsonify(ok=False, message=runner.problem()), 409
    ok, message = True, ""
    if action in {"stop", "restart"}:
        ok, message = runner.stop()
    if ok and action != "stop":
        ok, message = runner.start(hub.addons.settings(addon)) if addon.daemon else runner.start()
    if ok and action != "stop" and addon.daemon and gateway.PROVIDES in addon.provides \
            and gateway.gateway_enabled(hub.db, addon.id):
        message = f"{message}. {gateway.register(runner, _port(), hub.modules, hub.db)[1]}"
    reply = {"ok": ok, "message": message, "running": runner.running()}
    if not ok:
        reply["log"] = runner.log_tail()
    return jsonify(reply), (200 if ok else 500)
