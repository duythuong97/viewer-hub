"""The addon SDK users download (Cài đặt → Addon → Tải SDK, ``viewer-hub addon sdk``): everything needed to write an
addon without the Viewer Hub source, next to an AI agent.

    my-addon/                      the folder IS the addon (one layout for managed and daemon, AGENTS.md §2):
      AGENTS.md, README.md         the rules (for the AI) and the steps (for people); {{hub}} = this Hub's command
      package.json                 npm run new | build | watch | check | zip
      .gitignore
      .sdk/build.mjs, new.mjs      build (src/main.mjs → main.mjs, web/ → ui/), the install checks, the zip
      .sdk/templates/simple|daemon a managed Python addon with a page and MCP tools; a Node daemon with a page and SSE
      .sdk/python/viewer_hub/      this Hub's Python SDK (addons/sdk.py and what it imports): read it, and put it on
                                   PYTHONPATH to test or run an addon without a Hub

The user renames the folder, runs ``npm run new -- simple <id>``, writes the addon, ``npm run zip`` and uploads.

Files come from ``kit/`` beside this module; keep AGENTS.md in step with manifest.py, sdk.py, runner.py, channel.py,
core/scan.py and web/src/sdk/ when they change (tests/test_addon_sdk.py checks the parts it can).
"""
from __future__ import annotations

import io
import sys
import zipfile
from pathlib import Path

from viewer_hub.addons.manifest import SDK_VERSION

KIT = Path(__file__).with_name("kit")
TOP = "my-addon"
TEXT = {".md", ".json"}
# addons/sdk.py and everything it imports (standard library only past these): an addon's tests import the real SDK.
PYTHON_SDK = ("__init__.py", "core/__init__.py", "core/mcp.py", "core/monitor.py", "core/text.py", "addons/__init__.py", "addons/sdk.py")
GITIGNORE = "node_modules/\ndist/\n__pycache__/\n.pytest_cache/\n"


def file_name() -> str:
    return f"viewer-hub-addon-sdk-{SDK_VERSION}.zip"


def hub_command() -> str:
    """How to run this Viewer Hub's CLI from a terminal: the release launcher (quoted if needed), else viewer-hub."""
    from viewer_hub.core.config import release_root

    launcher = release_root() / ("viewer-hub.cmd" if sys.platform == "win32" else "viewer-hub.sh")
    if not launcher.is_file():
        return "viewer-hub"
    text = str(launcher)
    command = f'"{text}"' if " " in text else text
    return f"& {command}" if sys.platform == "win32" and command.startswith('"') else command


def build() -> bytes:
    from viewer_hub import __version__

    values = {"{{sdk}}": SDK_VERSION, "{{version}}": __version__, "{{hub}}": hub_command()}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(KIT.rglob("*")):
            rel = path.relative_to(KIT).as_posix()
            if not path.is_file() or any(part.startswith(".") or part in {"node_modules", "__pycache__", "ui"}
                                         for part in rel.split("/")):
                continue
            if rel.startswith("sdk/"):
                rel = "." + rel  # the SDK's own files: hidden, so the addon folder shows only the addon
            if path.suffix in TEXT:
                text = path.read_text(encoding="utf-8")
                for key, value in values.items():
                    text = text.replace(key, value)
                archive.writestr(f"{TOP}/{rel}", text)
            else:
                archive.write(path, f"{TOP}/{rel}")
        archive.writestr(f"{TOP}/.gitignore", GITIGNORE)
        package = Path(__file__).resolve().parents[1]
        for rel in PYTHON_SDK:
            archive.write(package / rel, f"{TOP}/.sdk/python/viewer_hub/{rel}")
    return buffer.getvalue()
