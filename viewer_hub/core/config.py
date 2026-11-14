"""App configuration and premium feature flags.

Settings are layered: DEFAULTS < viewer-hub.yaml next to viewer-hub.cmd < config.yaml in the data dir.

Premium flags are not settings: a module or addon that declares ``premium="<name>"`` is locked until an unlock code
(core/unlock.py) opens that name, from source or from a release alike. The app factory adds the names of the codes
saved on this machine to ``config["premium"]``; ``premium:`` in a config file is ignored.
"""
from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any

import yaml

import viewer_hub
from viewer_hub.core.paths import HubPaths

logger = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    "premium": {},  # unlocked feature names; only unlock codes add to it (app factory)
}
RELEASE_FILE = "viewer-hub.yaml"


def release_root() -> Path:
    package = Path(viewer_hub.__file__).resolve().parent
    return package.parent.parent if package.parent.name == "app" else package.parent


def _merge(base: dict, extra: dict) -> dict:
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = value
    return base


def _read(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as error:
        logger.error("config %s ignored: %s", path, error)
        return {}
    if not isinstance(value, dict):
        logger.error("config %s ignored: not a mapping", path)
        return {}
    return value


def load(paths: HubPaths, release_dir: Path | None = None) -> dict:
    config = copy.deepcopy(DEFAULTS)
    for layer in (_read((release_dir or release_root()) / RELEASE_FILE), _read(paths.config)):
        if "premium" in layer:
            logger.warning("premium flags in config files are ignored; premium opens with an unlock code")
            layer = {k: v for k, v in layer.items() if k != "premium"}
        _merge(config, layer)
    config["premium"] = {}
    return config


def unlock(config: dict, names: set[str]) -> None:
    """Turn on the premium features an unlock code opened (core/unlock.py)."""
    for name in names:
        config["premium"][name] = True


def premium_enabled(config: dict, feature: str) -> bool:
    return bool((config.get("premium") or {}).get(feature, False))


def any_locked(config: dict, modules) -> bool:
    """True while some module (builtin or addon) is still locked: the anonymous "Premium" entry shows."""
    return any(m.premium and not premium_enabled(config, m.premium) for m in modules)
