"""Feature modules: what each one adds to Viewer Hub, declared once in ``<package>/module.py`` (AGENTS.md).

Everything that lists features reads this registry, so a new module only declares itself:

* the app factory registers its routes and its menu entry (app/factory.py, GET /api/app for the React shell);
* its page is web/src/modules/<key>/index.jsx, found by key;
* the user guide (/help) takes its ``GUIDE.md`` section, in menu order (help/__init__.py);
* the guide's "AI / MCP" table and the MCP gateway addons (MCP Bridge) take its ``mcp`` (addons/gateway.py);
* tests check that every tool its MCP lists is documented in its ``GUIDE.md`` (tests/test_modules.py).

Installed addons (viewer_hub/addons) become modules too (addons/registry.py), after the builtin ones in the menu.
An addon may be premium (``premium="<name>"`` in addon.json, set on its Module): locked until an unlock code opens that
name (core/unlock.py), its routes answer 404 and its name never reaches a page until then. Builtin modules never are.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from viewer_hub.core.config import premium_enabled

# Menu order. Each entry is a package with a module.py that defines MODULE.
PACKAGES = (
    "viewer_hub.codemap",
    "viewer_hub.fsearch",
    "viewer_hub.csv",
    "viewer_hub.docs",
    "viewer_hub.monitor",
)


@dataclass(frozen=True)
class McpServer:
    """A module's MCP server (read-only tools for AI agents)."""

    path: str                          # HTTP endpoint on Viewer Hub, e.g. "/csv/mcp"
    command: str                       # stdio: `viewer-hub mcp <command>`
    scope: str = ""                    # what AI can see, shown in the guide, e.g. "chỉ repo đã thêm"
    tools: Callable[[], list[str]] = lambda: []  # tools AI sees by default (each one documented in GUIDE.md)

    @property
    def bridge_name(self) -> str:
        """Name of the builtin server in MCP Bridge."""
        return "viewer-" + self.command


@dataclass(frozen=True)
class Module:
    key: str                           # short id, also the package name
    label: str                         # menu and guide title
    icon: str                          # Material Symbols name
    prefix: str                        # URL prefix: marks the menu entry as current
    summary: str                       # one line: what it is for (guide intro table)
    register: Callable                 # register(app): add blueprints / routes to the main app
    guide: Path | None = None          # GUIDE.md: the user guide section ("## <label>" …), with its AI tools
    mcp: McpServer | None = None
    mounts: Callable | None = None     # mounts(hub) -> {prefix: wsgi app}, for a module that is its own Flask app
    premium: str | None = None         # premium key (locked until unlocked); None = always on
    stat: Callable | None = None       # stat(hub) -> short count for its home card, e.g. "3 repo"
    addon: object | None = None        # addons/manifest.py Addon, for a module that is an installed addon


def all_modules() -> list[Module]:
    """Every builtin module (addons: Hub.every_module). A builtin module is never premium: a premium feature is an
    addon (docs/addons.md), locked by addons/routes.py."""
    found = [importlib.import_module(package + ".module").MODULE for package in PACKAGES]
    for module in found:
        if module.premium:
            raise RuntimeError(f"builtin module {module.key} is premium: make it an addon")
    return found


def is_enabled(module: Module, config: dict) -> bool:
    return module.premium is None or premium_enabled(config, module.premium)
