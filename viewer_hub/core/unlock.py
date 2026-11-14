"""Premium unlock codes (GUIDELINE §4.5).

Every build carries every premium feature, locked: a builtin module or an addon (viewer_hub/addons) that declares
``premium: "<name>"``. The user types an unlock code on the Premium page; a valid code is kept in hub.db (settings
``premium.codes``) and unlocks its features at once, and on every later start.

A code is ``VH2-`` + base32 of ``payload || signature``:

    payload    b"VH" 0x02 | n (1 byte) | n bytes: feature names, comma-separated ASCII | 5 random bytes
    signature  Ed25519 (core/ed25519.py) over CONTEXT + payload, by the author's private key

Codes carry feature **names**, so an addon made after this build can be unlocked without a new Hub: the name in its
addon.json is all it takes. Only the public key is here; codes are made with packaging/unlock.py on the author's
machine. A code is not tied to a machine: whoever has it can unlock. The app is readable Python, so this stops
casual unlocking, not someone who edits the code.
"""
from __future__ import annotations

import base64
import binascii
import logging
import re
import secrets

from viewer_hub.core import ed25519

logger = logging.getLogger(__name__)

PUBLIC_KEY = bytes.fromhex("ff9b583dc5d3255a7f92826a0662d24e6139d22a70d71bb0b6d9ef1bffe79cbf")
CONTEXT = b"viewer-hub unlock code\x00"
PREFIX = "VH2-"
SETTING = "premium.codes"
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
_MAGIC = b"VH\x02"
_NONCE = 5
_SIG = 64


class UnlockError(ValueError):
    pass


def _raw(code: str) -> bytes:
    text = re.sub(r"[\s-]+", "", code.strip().upper())
    if text.startswith(PREFIX.rstrip("-")):
        text = text[len(PREFIX) - 1:]
    try:
        raw = base64.b32decode(text + "=" * (-len(text) % 8))
    except (binascii.Error, ValueError) as error:
        raise UnlockError("mã không đúng định dạng") from error
    if len(raw) < len(_MAGIC) + 1 + _NONCE + _SIG or not raw.startswith(_MAGIC):
        raise UnlockError("mã không đúng định dạng")
    if len(raw) != len(_MAGIC) + 1 + raw[len(_MAGIC)] + _NONCE + _SIG:
        raise UnlockError("mã không đúng định dạng")
    return raw


def features(code: str) -> set[str]:
    """Premium names a code unlocks; raises UnlockError when it is not a valid code."""
    raw = _raw(code)
    payload, signature = raw[:-_SIG], raw[-_SIG:]
    if not ed25519.verify(PUBLIC_KEY, CONTEXT + payload, signature):
        raise UnlockError("mã không hợp lệ")
    size = payload[len(_MAGIC)]
    names = payload[len(_MAGIC) + 1:len(_MAGIC) + 1 + size].decode("ascii", errors="replace").split(",")
    found = {name for name in names if NAME_RE.match(name)}
    if not found:
        raise UnlockError("mã không mở tính năng nào")
    return found


def issue(private: bytes, names: set[str]) -> str:
    """A new code for ``names`` (author only: needs the private key)."""
    bad = sorted(name for name in names if not NAME_RE.match(name))
    if not names or bad:
        raise UnlockError("tên tính năng phải là chữ thường, số, dấu - (vd. bridge): " + ", ".join(bad))
    text = ",".join(sorted(names)).encode("ascii")
    if len(text) > 255:
        raise UnlockError("quá nhiều tính năng trong một mã")
    payload = _MAGIC + bytes([len(text)]) + text + secrets.token_bytes(_NONCE)
    return _format(payload + ed25519.sign(private, CONTEXT + payload))


def _format(raw: bytes) -> str:
    text = base64.b32encode(raw).decode("ascii").rstrip("=")
    return PREFIX + "-".join(text[i:i + 8] for i in range(0, len(text), 8))


def stored(db) -> list[str]:
    return [line for line in db.setting(SETTING, "").splitlines() if line.strip()]


def unlocked(db) -> set[str]:
    """Features unlocked by the codes saved on this machine (a code that no longer checks out is skipped)."""
    names: set[str] = set()
    for code in stored(db):
        try:
            names |= features(code)
        except UnlockError as error:
            logger.warning("saved unlock code ignored: %s", error)
    return names


def save(db, code: str) -> set[str]:
    """Check ``code`` and keep it; returns the features it unlocks. Raises UnlockError, or ReadOnlyError."""
    names = features(code)
    normal = _format(_raw(code))  # one printed form, however it was typed
    codes = stored(db)
    if normal not in codes:
        db.set_setting(SETTING, "\n".join([*codes, normal]))
    return names
