"""Flask app factory (design.md §1).

Feature modules (app/modules.py, each declared in <package>/module.py) add their
routes and menu entry here; installed addons (viewer_hub/addons) are read from the data dir
and served by one blueprint, so installing one needs no restart. Every page is the React app
(templates/app.html, web/src/app) with one Material 3 bundle (/static/dist). Apps that are
their own Flask app (code-map) are mounted beside it with DispatcherMiddleware.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from flask import Flask, g
from werkzeug.middleware.dispatcher import DispatcherMiddleware

from viewer_hub.core.migrate import StartupState
from viewer_hub.core.paths import HubPaths

PACKAGE = Path(__file__).resolve().parents[1]
logger = logging.getLogger(__name__)


@dataclass
class Hub:
    """What every request can reach: paths, hub.db, startup state."""

    paths: HubPaths
    state: StartupState
    config: dict = field(default_factory=dict)
    builtin_modules: list = field(default_factory=list)  # app/modules.py Module of PACKAGES (never premium)
    port: int | None = None  # set by `viewer-hub serve` once it has a port
    addons: object = None  # addons/registry.py Registry

    @property
    def every_module(self) -> list:
        """Builtin modules, then installed addons; locked ones too."""
        return [*self.builtin_modules, *(self.addons.modules() if self.addons else [])]

    @property
    def modules(self) -> list:
        """Modules this machine runs now: every regular one, premium ones once unlocked."""
        from viewer_hub.app.modules import is_enabled

        return [m for m in self.every_module if is_enabled(m, self.config)]

    @property
    def db(self):
        return self.state.db

    @property
    def readonly(self) -> bool:
        return self.state.readonly


def create_app(paths: HubPaths, state: StartupState) -> Flask:
    app = Flask(
        "viewer_hub",
        root_path=str(PACKAGE),
        template_folder=str(PACKAGE / "templates"),
        static_folder=str(PACKAGE / "static"),
        static_url_path="/static",
    )
    app.config["MAX_CONTENT_LENGTH"] = 512 * 1024 * 1024  # uploads (CSV, markdown zip)
    app.json.ensure_ascii = False
    from viewer_hub.core import config as app_config

    from viewer_hub.core import unlock

    hub = Hub(paths, state, app_config.load(paths))
    app_config.unlock(hub.config, unlock.unlocked(state.db))  # codes saved on this machine
    app.extensions["hub"] = hub

    from viewer_hub.addons import legacy, routes as addon_routes
    from viewer_hub.addons.install import RESERVED_PAGES
    from viewer_hub.addons.registry import Registry
    from viewer_hub.app import modules, portal, spa

    app.register_blueprint(portal.bp)
    app.register_blueprint(addon_routes.bp)
    app.register_blueprint(legacy.bp)  # /svn → /x/svn (SVN became an addon)
    spa.register(app)
    # Builtin modules are never premium (modules.all_modules refuses one): premium features are addons, which check
    # their own lock (addons/routes.py), so an unlock code opens them without a restart.
    hub.builtin_modules = modules.all_modules()
    hub.addons = Registry(paths, reserved={m.key for m in hub.builtin_modules} | RESERVED_PAGES)
    hub.addons.hub_port = lambda: hub.port or 0  # where a managed addon calls another one's exports (routes.call)

    def _premium_ok(name: str) -> bool:
        from viewer_hub.core.config import premium_enabled

        return premium_enabled(hub.config, name)

    hub.addons.premium_ok = _premium_ok
    for module in hub.builtin_modules:  # each feature declares itself in <package>/module.py (AGENTS.md)
        module.register(app)

    @app.before_request
    def _hub():
        g.hub = hub
        return origins.enforce()

    from viewer_hub.app import origins

    @app.after_request
    def _headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if response.mimetype == "text/html" and "Content-Security-Policy" not in response.headers:
            # Everything is served locally; nothing may load from or talk to another host.
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                "font-src 'self'; script-src 'self'; connect-src 'self'; "
                "frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
            )
        return response

    return app


def create_wsgi(paths: HubPaths, state: StartupState):
    """The Flask app with mounted sub-apps (code-map) on their prefixes."""
    app = create_app(paths, state)
    hub = app.extensions["hub"]
    mounts = {}
    for module in hub.builtin_modules:
        if module.mounts and module in hub.modules:
            mounts.update(module.mounts(hub))
    app.wsgi_app = DispatcherMiddleware(app.wsgi_app, mounts)
    return app
