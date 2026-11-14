"""Daemon addons that gather MCP servers (``provides: ["mcp-servers"]``, e.g. the MCP Bridge): the Hub registers its
own MCP servers there, and starts such daemons with the Hub.

The contract on the daemon's admin channel (my-bridge api/openapi.yaml): ``GET /api/servers`` → {"servers": [{name,
url, tools: {total}}]}, ``POST /api/servers`` {"servers": [{name, transport: "http", url, startMode}]},
``POST /api/servers/<name>/refresh``. Every module with an MCP (builtin or addon) is registered as
``viewer-<command>`` at ``http://127.0.0.1:<port><path>``, read-only tools only.

The user's choices in the daemon win: a server is only added or pointed at the Hub's port (its on/off switch and tool
permissions stay with the daemon), and one the user removed there is not added back at the next start (the Hub
remembers what it registered; switching "Đăng ký MCP của Viewer Hub" off and on again adds them all back).
"""
from __future__ import annotations

import json
import threading
import time

from viewer_hub.addons import channel, proxy
from viewer_hub.addons.runner import Daemon

PROVIDES = "mcp-servers"
VIEWER_WAIT = 30.0


def _flag(db, key: str) -> bool:
    return db.setting(key, "1") != "0"


def autostart_key(addon_id: str) -> str:
    return f"addon.{addon_id}.autostart"


def gateway_key(addon_id: str) -> str:
    return f"addon.{addon_id}.gateway"


def autostart_enabled(db, addon_id: str) -> bool:
    return _flag(db, autostart_key(addon_id))


def gateway_enabled(db, addon_id: str) -> bool:
    return _flag(db, gateway_key(addon_id))


def set_flag(db, key: str, on: bool) -> None:
    db.set_setting(key, "1" if on else "0")


def registered_key(addon_id: str) -> str:
    return f"addon.{addon_id}.gateway.registered"


def _registered(db, addon_id: str) -> set[str]:
    if db is None:
        return set()
    try:
        names = json.loads(db.setting(registered_key(addon_id), "[]"))
    except ValueError:
        return set()
    return {n for n in names if isinstance(n, str)} if isinstance(names, list) else set()


def forget_registered(db, addon_id: str) -> None:
    """Register every Hub server again next time, also those the user removed in the daemon."""
    db.set_setting(registered_key(addon_id), "[]")


def hub_servers(modules) -> list[tuple[str, str]]:
    """(name in the gateway, HTTP path) of every module with an MCP."""
    return [(m.mcp.bridge_name, m.mcp.path) for m in modules if m.mcp]


def register(runner: Daemon, port: int, modules, db=None) -> tuple[bool, str]:
    """Adds the Hub's MCP servers to the running daemon, or points them at this port; asks for their tools when it
    has none yet (it may have started before the Hub answered). Other servers are left alone, and so is one the
    Hub registered before that the user has since removed (``db`` keeps the list).

    Returns (done, message): done once they are registered and the daemon reached the Hub on this port."""
    wanted = hub_servers(modules)
    if not wanted:
        return True, "Viewer Hub không có MCP nào để đăng ký"
    try:
        status, body = runner.request("GET", "/api/servers")
        if status != 200 or not isinstance(body, dict):
            return False, f"{runner.addon.name} không trả danh sách server"
        existing = {s.get("name"): s for s in body.get("servers", [])}
        before = _registered(db, runner.addon.id)
        if not before & set(existing):
            before = set()  # none of them there: a fresh daemon (reinstalled, data wiped), not the user's choice
        removed = {name for name, _ in wanted if name in before and name not in existing}  # the user's choice
        wanted = [(name, path) for name, path in wanted if name not in removed]
        changed = []
        for name, path in wanted:
            url = f"http://127.0.0.1:{port}{path}"
            if (existing.get(name) or {}).get("url") != url:
                changed.append({"name": name, "transport": "http", "url": url, "startMode": "lazy"})
        if changed:
            status, body = runner.request("POST", "/api/servers", body={"servers": changed})
            if status >= 300:
                return False, str(body.get("message") if isinstance(body, dict) else body)
        missing = []
        for name, _ in wanted:
            server = existing.get(name) or {}
            if name in {c["name"] for c in changed} or not (server.get("tools") or {}).get("total"):
                status, _body = runner.request("POST", f"/api/servers/{name}/refresh")
                if status != 200:
                    missing.append(name)
    except (channel.Unavailable, OSError, ValueError) as exc:
        return False, f"Chưa đăng ký được MCP của Viewer Hub: {exc}"
    if db is not None:
        db.set_setting(registered_key(runner.addon.id), json.dumps(sorted(before | {name for name, _ in wanted})))
    if not wanted:
        return True, "Không đăng ký lại MCP của Viewer Hub mà bạn đã xoá khỏi " + runner.addon.name
    if len(missing) == len(wanted):  # none answered: the Hub is not serving yet
        return False, f"{runner.addon.name} chưa gọi được Viewer Hub trên cổng {port}"
    added = [c["name"] for c in changed]
    message = ("Đã đăng ký " + ", ".join(added)) if added else "MCP của Viewer Hub đã có sẵn"
    if removed:
        message += "; bỏ qua " + ", ".join(sorted(removed)) + " (bạn đã xoá)"
    if missing:  # e.g. Code map without a code-map pack: its tools come once the daemon refreshes it later
        message += "; chưa lấy được tool của " + ", ".join(missing) + " (chưa có dữ liệu?)"
    return True, message


def hub_serving(port: int) -> bool:
    """The Hub answers on its own port (127.0.0.1 only, proxy.py)."""
    try:
        return proxy.request(port, "", "GET", "/api/app", timeout=2)[0] == 200
    except proxy.Unavailable:
        return False


def register_when_ready(hub, runner: Daemon) -> str:
    deadline = time.monotonic() + VIEWER_WAIT  # the Hub starts serving right after the start-up thread starts
    # Register only once the Hub serves: a server the daemon adds is started at once, and one that cannot reach the
    # Hub yet is marked failed until someone refreshes it.
    while not hub_serving(hub.port) and time.monotonic() < deadline:
        time.sleep(0.5)
    while True:
        ok, message = register(runner, hub.port, hub.modules, hub.db)
        if ok or time.monotonic() > deadline:
            return message
        time.sleep(1.0)


def autostart_in_background(hub, only: set[str] | None = None) -> None:
    """When the Hub opens (or a code unlocks them): start each daemon addon that runs here (premium unlocked) and
    has autostart on, unless it runs already; then register the Hub's MCP servers in those that gather them."""
    if not hub.port:
        return
    daemons = [m.addon for m in hub.modules if m.addon is not None and m.addon.daemon
               and (only is None or m.addon.id in only)]

    def work() -> None:
        for addon in daemons:
            runner = hub.addons.runner(addon)
            try:
                if not runner.running():
                    if not autostart_enabled(hub.db, addon.id):
                        continue
                    ok, message = runner.start(hub.addons.settings(addon))
                    print(f"{addon.name}: {message}", flush=True)
                    if not ok:
                        continue
                if PROVIDES in addon.provides and gateway_enabled(hub.db, addon.id):
                    print(f"{addon.name}: {register_when_ready(hub, runner)}", flush=True)
            except Exception as exc:  # noqa: BLE001  (a broken addon never stops the Hub)
                print(f"{addon.name}: {exc}", flush=True)

    if daemons:
        threading.Thread(target=work, name="addon-autostart", daemon=True).start()
