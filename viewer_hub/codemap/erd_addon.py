"""The whole-database ERD lives in the ``erd`` addon (docs/solutions/codemap-redesign-solution.md §5.1): where it is.

Code map keeps only the ERD of the tables one feature touches; its buttons "Mở trong ERD" and the old ERD route
point at the addon when it is installed and not locked (a locked premium addon does not exist), else the page shows
how to get it.
"""
from __future__ import annotations

from urllib.parse import urlencode

ADDON_ID = "erd"


def addon_path(hub) -> str | None:
    """``/x/erd`` when the ERD addon is installed and usable, else None."""
    registry = getattr(hub, "addons", None)
    if registry is None:
        return None
    addon = registry.get(ADDON_ID)
    if addon is None or (addon.premium and not registry.premium_ok(addon.premium)):
        return None
    return addon.prefix


def addon_url(hub, **query: str) -> str | None:
    """The addon page with a deep link (``table=``, ``schema=``, ``system=``, ``pack=``), or None."""
    path = addon_path(hub)
    if path is None:
        return None
    wanted = {key: value for key, value in query.items() if value}
    return f"{path}/" + (f"?{urlencode(wanted)}" if wanted else "")
