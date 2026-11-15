"""Installed addons as modules (docs/addons.md §2, §6): read from ``<data>/addons/`` each time the folder changes,
so installing or removing one needs no restart.

Each valid addon becomes an app/modules.py ``Module`` (prefix ``/x/<id>``): menu, home card, /help, the MCP table and
the MCP gateway (gateway.py) take it like a builtin module. A folder that fails its checks is listed as broken on
the Settings page and nowhere else.
"""
from __future__ import annotations

import hmac
import logging
import threading
from typing import Callable

from viewer_hub.addons import deps, signature
from viewer_hub.addons.install import BUILTIN_COMMANDS
from viewer_hub.addons.manifest import MANIFEST, Addon, AddonError, load
from viewer_hub.addons.runner import Daemon, External, Managed, managed
from viewer_hub.core import atomic
from viewer_hub.core.paths import HubPaths

logger = logging.getLogger(__name__)



def _noop(_app) -> None:
    """Addons add no routes of their own: one blueprint serves every addon (routes.py)."""


def as_module(addon: Addon):
    from viewer_hub.app.modules import McpServer, Module

    mcp = None
    if addon.mcp:
        tools = list(addon.mcp.tools)
        mcp = McpServer(f"{addon.prefix}/mcp", addon.mcp.command, scope=addon.mcp.scope, tools=lambda: tools)
    return Module(key=addon.id, label=addon.label, icon=addon.icon, prefix=addon.prefix, summary=addon.summary,
                  register=_noop, guide=addon.guide if addon.guide.is_file() else None, mcp=mcp,
                  premium=addon.premium, addon=addon)


class Registry:
    def __init__(self, paths: HubPaths, reserved: set[str] = frozenset()) -> None:
        self.paths = paths
        self.reserved = set(reserved)  # builtin module keys: an addon may not take one
        self._addons: dict[str, Addon] = {}
        self.broken: dict[str, str] = {}
        self._trust: dict[tuple[str, str], str] = {}
        self._runners: dict[str, Managed | Daemon | External] = {}
        self._stamp: tuple | None = None
        self._lock = threading.RLock()
        self.hub_port: Callable[[], int] = lambda: 0       # the Hub's port once it serves (factory.py)
        self.premium_ok: Callable[[str], bool] = lambda _p: True  # is a premium name unlocked (factory.py)

    # ── what is installed ────────────────────────────────────────────────────────────────────────────────────
    def _current_stamp(self) -> tuple:
        root = self.paths.addons
        if not root.is_dir():
            return ()
        return tuple(sorted((p.name, (p / MANIFEST).stat().st_mtime_ns if (p / MANIFEST).is_file() else 0)
                            for p in root.iterdir() if p.is_dir()))

    def refresh(self, force: bool = False) -> None:
        with self._lock:
            stamp = self._current_stamp()
            if stamp == self._stamp and not force:
                return
            self._stamp = stamp
            found: dict[str, Addon] = {}
            broken: dict[str, str] = {}
            commands: dict[str, str] = {}
            for name, _mtime in stamp:
                folder = self.paths.addons / name
                try:
                    addon = load(folder)
                    if addon.id in self.reserved:
                        raise AddonError(f"id {addon.id} trùng một mục có sẵn của Viewer Hub")
                    if addon.mcp and (addon.mcp.command in BUILTIN_COMMANDS or addon.mcp.command in commands):
                        raise AddonError(f"mcp.command {addon.mcp.command} đã có")
                except AddonError as exc:
                    broken[name] = str(exc)
                    continue
                if addon.mcp:
                    commands[addon.mcp.command] = addon.id
                found[addon.id] = addon
            self._addons, self.broken = found, broken
            for addon_id in [i for i in self._runners if i not in found or self._runners[i].addon != found[i]]:
                old = self._runners.pop(addon_id)
                if isinstance(old, Managed) and old.running():
                    old.stop()

    def addons(self) -> list[Addon]:
        self.refresh()
        return sorted(self._addons.values(), key=lambda a: a.label.lower())

    def get(self, addon_id: str) -> Addon | None:
        self.refresh()
        return self._addons.get(addon_id)

    def installed(self) -> dict[str, Addon]:
        self.refresh()
        return dict(self._addons)

    def statuses(self) -> dict[str, deps.Status]:
        """ok / degraded / broken of every addon by what it uses (deps.statuses), as installed and unlocked now."""
        installed = {i: a for i, a in self.installed().items() if not a.premium or self.premium_ok(a.premium)}
        return deps.statuses(installed, self.premium_ok)

    def caller(self, token: str) -> Addon | None:
        """The running managed addon whose per-run caller token this is (routes.py call), else None."""
        if not token:
            return None
        with self._lock:
            for runner in self._runners.values():
                if isinstance(runner, Managed) and runner.caller_token and runner.running() \
                        and hmac.compare_digest(runner.caller_token, token):
                    return self._addons.get(runner.addon.id)
        return None

    def by_command(self, command: str) -> Addon | None:
        return next((a for a in self.addons() if a.mcp and a.mcp.command == command), None)

    def modules(self) -> list:
        return [as_module(addon) for addon in self.addons()]

    def trust(self, addon: Addon) -> str:
        """"signed", "unsigned" or "modified" (signed, but a file changed after install)."""
        key = (addon.id, addon.version)
        if key not in self._trust:
            try:
                self._trust[key] = signature.verify(addon.folder, addon.id, addon.version)
            except AddonError:
                self._trust[key] = "modified"
        return self._trust[key]

    def forget(self, addon_id: str) -> tuple[bool, str]:
        """Stop and drop the runner (before an update or uninstall replaces the folder). A daemon is asked even when
        this Hub never started it (it outlives the Hub): (False, why) when it is still running."""
        with self._lock:
            runner = self._runners.pop(addon_id, None)
            addon = self._addons.get(addon_id)
            if runner is None and addon is not None and addon.daemon:
                runner = Daemon(addon, self.paths.addon_data(addon.id), self.paths.logs)
            self._trust = {k: v for k, v in self._trust.items() if k[0] != addon_id}
            if runner is None or not runner.running():
                return True, ""
            return runner.stop()

    # ── running ──────────────────────────────────────────────────────────────────────────────────────────────
    def runner(self, addon: Addon) -> Managed | Daemon | External:
        with self._lock:
            current = self._runners.get(addon.id)
            if current is None or current.addon != addon:
                data = self.paths.addon_data(addon.id)
                if addon.daemon:
                    current = Daemon(addon, data, self.paths.logs)
                elif addon.external:
                    current = External(addon, data, self.paths.logs)
                else:
                    current = managed(addon, data, self.paths.logs)
                    current.hub_url = self._hub_url
                self._runners[addon.id] = current
            return current

    def _hub_url(self) -> str:
        port = self.hub_port()
        return f"http://127.0.0.1:{port}" if port else ""

    def stop_all(self) -> None:
        for runner in list(self._runners.values()):
            if isinstance(runner, Managed):
                runner.stop()

    # ── settings (the form on the addon's page) ─────────────────────────────────────────────────────────────
    def settings(self, addon: Addon) -> dict:
        saved = atomic.read_json(self.paths.addon_data(addon.id) / "settings.json", {}) or {}
        values = {}
        for setting in addon.settings:
            default = setting.default
            if default is None:
                default = {"switch": False, "list": []}.get(setting.type, "")
            values[setting.key] = saved.get(setting.key, default) if isinstance(saved, dict) else default
        return values

    def save_settings(self, addon: Addon, values: dict) -> dict:
        """Checks the values against addon.json, writes settings.json (atomic); returns what was saved."""
        clean = {}
        for setting in addon.settings:
            if setting.key not in values:
                continue
            value = values[setting.key]
            if setting.type == "switch":
                value = bool(value)
            elif setting.type == "list":
                items = value.splitlines() if isinstance(value, str) else value
                if not isinstance(items, list):
                    raise AddonError(f"{setting.label}: cần danh sách")
                value = [str(item).strip() for item in items if str(item).strip()]
            else:
                value = "" if value is None else str(value).strip()
                if setting.type == "select" and value and value not in setting.options:
                    raise AddonError(f"{setting.label}: chọn một trong " + ", ".join(setting.options))
                if len(value) > 4000:
                    raise AddonError(f"{setting.label}: quá dài")
            clean[setting.key] = value
        merged = {**self.settings(addon), **clean}
        target = self.paths.addon_data(addon.id) / "settings.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic.write_json(target, merged)
        return merged

