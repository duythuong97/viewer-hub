"""Where Viewer Hub keeps its data (design.md §7.1).

The data dir is never inside the app folder, so unzipping a new version
cannot overwrite user data. Precedence: --data-dir > $VIEWER_HUB_HOME > default.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def default_home() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "ViewerHub"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "ViewerHub"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "viewer-hub"


@dataclass(frozen=True)
class HubPaths:
    home: Path

    @classmethod
    def resolve(cls, data_dir: str | os.PathLike | None = None) -> "HubPaths":
        value = data_dir or os.environ.get("VIEWER_HUB_HOME")
        home = Path(value).expanduser() if value else default_home()
        return cls(home.resolve())

    @property
    def db(self) -> Path:
        return self.home / "hub.db"

    @property
    def lock(self) -> Path:
        return self.home / "hub.lock"

    @property
    def config(self) -> Path:
        return self.home / "config.yaml"

    @property
    def packs(self) -> Path:
        return self.home / "packs"

    @property
    def workspace(self) -> Path:
        return self.home / "workspace"

    @property
    def csv(self) -> Path:
        return self.workspace / "csv"

    @property
    def sites(self) -> Path:
        return self.workspace / "docs"

    @property
    def user(self) -> Path:
        return self.home / "user"

    @property
    def backups(self) -> Path:
        return self.home / "backups"

    @property
    def logs(self) -> Path:
        return self.home / "logs"

    @property
    def tmp(self) -> Path:
        return self.home / "tmp"

    @property
    def addons(self) -> Path:
        """Installed addons (viewer_hub/addons): one folder per addon, its code, replaced on update."""
        return self.home / "addons"

    def addon_data(self, addon_id: str) -> Path:
        """An addon's own data and settings.json (under user/, so backups keep its SQLite files)."""
        return self.user / "addons" / addon_id

    def ensure(self) -> "HubPaths":
        for path in (self.home, self.packs, self.csv, self.sites, self.user, self.backups, self.logs, self.tmp,
                     self.addons):
            path.mkdir(parents=True, exist_ok=True)
        return self

    def clean_tmp(self) -> None:
        """tmp/ only holds half-written files; anything left there is from a crash."""
        if not self.tmp.is_dir():
            return
        for child in self.tmp.iterdir():
            if child.is_dir():
                _rmtree(child)
            else:
                child.unlink(missing_ok=True)


def _rmtree(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)
