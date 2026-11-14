"""Starts a Python addon inside its own process (runner.py runs ``python -I -c <boot> <folder> serve --port N``).

The Hub's embedded Python ignores the script's folder (its ._pth fixes sys.path), so the addon is not run as
``python main.py``: this puts the addon folder and its ``lib/`` (vendored pure-Python dependencies) on sys.path, then
runs the entry as ``__main__`` with the remaining arguments. viewer_hub itself is importable (viewer_hub.addons.sdk,
viewer_hub.core.mcp), as the parent passed its own sys.path.
"""
from __future__ import annotations

import os
import runpy
import sys
import threading
from pathlib import Path


def watch_parent() -> None:
    """Exit when the Hub that started this addon is gone: its stdin pipe closes (runner.py, VIEWER_HUB_PARENT_PIPE)."""
    if os.environ.get("VIEWER_HUB_PARENT_PIPE") != "1" or sys.stdin is None:
        return

    def wait() -> None:
        try:
            while sys.stdin.buffer.read(4096):
                pass
        except (OSError, ValueError):
            pass
        os._exit(0)  # the Hub is gone: nobody can reach or stop this process any more

    threading.Thread(target=wait, name="parent-watch", daemon=True).start()


def main(argv: list[str]) -> int:
    from viewer_hub.core.text import utf8_output

    utf8_output()  # print() of Vietnamese / Japanese into the log pipe: -I ignores PYTHONIOENCODING
    if not argv:
        print("usage: host <addon folder> serve --port N", file=sys.stderr)
        return 2
    from viewer_hub.addons.manifest import AddonError, load

    folder = Path(argv[0]).resolve()
    try:
        addon = load(folder)
    except AddonError as exc:
        print(f"addon: {exc}", file=sys.stderr)
        return 2
    watch_parent()
    sys.path[:0] = [str(folder), str(folder / "lib")]
    sys.argv = [str(addon.main), *argv[1:]]
    runpy.run_path(str(addon.main), run_name="__main__")
    return 0
