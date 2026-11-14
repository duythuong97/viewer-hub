"""How much of the Hub one addon may hold: a slow, hung or crashing addon must never take the Hub down with it.

The Hub serves every page from a small pool of threads (waitress, cli.py). Each request relayed to an addon holds one
until the addon answers (or the timeout), and a live event stream holds one for as long as the page is open. So per
addon at most CALLS calls and STREAMS streams at a time; one more waits WAIT seconds for a slot, then gets
"addon đang bận" (503) at once, while the Hub and the other addons go on.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

from viewer_hub.addons.runner import AddonUnavailable

CALLS = 4
STREAMS = 2
WAIT = 5.0

_lock = threading.Lock()
_slots: dict[tuple[str, str], threading.BoundedSemaphore] = {}


class Busy(AddonUnavailable):
    """Every slot of this addon is taken (it answers slowly or not at all)."""


def _semaphore(addon_id: str, kind: str) -> threading.BoundedSemaphore:
    with _lock:
        key = (addon_id, kind)
        if key not in _slots:
            _slots[key] = threading.BoundedSemaphore(CALLS if kind == "call" else STREAMS)
        return _slots[key]


def take(addon_id: str, kind: str = "call") -> threading.BoundedSemaphore:
    """A held slot (release it yourself, e.g. when a stream ends); Busy if none frees up in time."""
    semaphore = _semaphore(addon_id, kind)
    if not semaphore.acquire(timeout=WAIT if kind == "call" else 0.5):
        what = "luồng sự kiện" if kind == "stream" else "yêu cầu"
        raise Busy(f"addon đang bận: đã có {CALLS if kind == 'call' else STREAMS} {what} chưa xong, thử lại sau")
    return semaphore


@contextmanager
def slot(addon_id: str, kind: str = "call") -> Iterator[None]:
    semaphore = take(addon_id, kind)
    try:
        yield
    finally:
        semaphore.release()
