"""signature.json of an addon: sha256 of every file, signed by the author (docs/addons.md §7).

    {"schema": "viewer-hub/addon-signature", "id": "...", "version": "...",
     "files": {"addon.json": "<sha256>", "ui/ui.js": "<sha256>", ...}, "signature": "<ed25519 hex>"}

The signature covers CONTEXT + the canonical JSON of {id, version, files}. The key is the one of premium unlock codes
(core/unlock.py PUBLIC_KEY): one root of trust, one private key on the author's machine (packaging/unlock.py keygen).
An addon without signature.json installs as "unsigned" (the UI says the admin provided it); a signature that does
not match refuses the install.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from viewer_hub.addons.manifest import AddonError
from viewer_hub.core import ed25519

FILE = "signature.json"
SCHEMA = "viewer-hub/addon-signature"
CONTEXT = b"viewer-hub addon\x00"


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def digests(folder: Path) -> dict[str, str]:
    return {p.relative_to(folder).as_posix(): _sha(p) for p in sorted(folder.rglob("*"))
            if p.is_file() and p.relative_to(folder).as_posix() != FILE}


def _message(addon_id: str, version: str, files: dict[str, str]) -> bytes:
    body = json.dumps({"id": addon_id, "version": version, "files": files}, sort_keys=True, separators=(",", ":"))
    return CONTEXT + body.encode("utf-8")


def sign(folder: Path, addon_id: str, version: str, private: bytes) -> dict:
    files = digests(folder)
    data = {"schema": SCHEMA, "id": addon_id, "version": version, "files": files,
            "signature": ed25519.sign(private, _message(addon_id, version, files)).hex()}
    (folder / FILE).write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    return data


def verify(folder: Path, addon_id: str, version: str) -> str:
    """"signed" or "unsigned"; AddonError when signature.json exists but does not match the files or the key."""
    from viewer_hub.core.unlock import PUBLIC_KEY

    path = folder / FILE
    if not path.is_file():
        return "unsigned"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        signature = bytes.fromhex(data["signature"])
        files = data["files"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise AddonError(f"{FILE} hỏng: {exc}") from exc
    if data.get("schema") != SCHEMA or data.get("id") != addon_id or data.get("version") != version:
        raise AddonError(f"{FILE} không phải của {addon_id} {version}")
    if not ed25519.verify(PUBLIC_KEY, _message(addon_id, version, files), signature):
        raise AddonError("chữ ký không đúng (không phải khoá của tác giả)")
    actual = digests(folder)
    changed = sorted(set(actual) ^ set(files) | {name for name in actual if files.get(name) != actual[name]})
    if changed:
        raise AddonError("file khác với bản đã ký: " + ", ".join(changed[:5]))
    return "signed"
