"""Premium unlock codes, on the author's machine only (GUIDELINE §4.5).

    python packaging/unlock.py keygen               # once: make the signing key, print the public key
    python packaging/unlock.py issue bridge         # a new random code that unlocks premium "bridge" (MCP Bridge)
    python packaging/unlock.py check <code>         # what a code unlocks
    python packaging/unlock.py issue | check        # without arguments: asks (used by `just unlock` / `just unlock-check`)

The private key lives outside the repo (default ~/.viewer-hub/unlock-signing.key, or --key / VIEWER_HUB_SIGNING_KEY)
and never ships. The app holds only the public key (viewer_hub/core/unlock.py PUBLIC_KEY), so reading the app's
code is not enough to make a code. Every `issue` gives a different code (random part); all of them stay valid.
Keep a backup of the key: without it no new code can be made, and a new key invalidates every code given out.
The same key signs addons (packaging/addon.py).

A code carries feature names: any name works, also one of an addon made later. The names this repo knows (the
``premium`` of each addons/*.zip) are offered when none is given.
"""
from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from viewer_hub.core import ed25519, unlock  # noqa: E402

DEFAULT_KEY = Path.home() / ".viewer-hub" / "unlock-signing.key"


def _key_path(arg: Path | None) -> Path:
    return arg or Path(os.environ.get("VIEWER_HUB_SIGNING_KEY") or DEFAULT_KEY)


def known_features() -> dict[str, str]:
    """Premium name → label, from the default addons (addons/*.zip). Any other name works too (an addon not
    shipped here): the code just carries it."""
    from viewer_hub.addons.install import AddonError, peek

    found = {}
    for zip_path in sorted((ROOT / "addons").glob("*.zip")):
        try:
            addon = peek(zip_path)
        except AddonError:
            continue
        if addon.premium:
            found[addon.premium] = addon.label
    return found


def read_key(path: Path) -> bytes:
    try:
        private = bytes.fromhex(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError) as error:
        raise SystemExit(f"Không đọc được khoá ký {path}: {error} (chạy `keygen` trước)") from error
    if len(private) != 32:
        raise SystemExit(f"Khoá ký {path} không hợp lệ")
    if ed25519.public_key(private) != unlock.PUBLIC_KEY:
        raise SystemExit(f"Khoá ký {path} không khớp PUBLIC_KEY trong viewer_hub/core/unlock.py")
    return private


def keygen(path: Path, force: bool) -> int:
    if path.exists() and not force:
        raise SystemExit(f"{path} đã có. Tạo khoá mới làm mọi mã đã phát mất hiệu lực; muốn vậy thì thêm --force.")
    private = secrets.token_bytes(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(private.hex() + "\n", encoding="ascii")
    path.chmod(0o600)
    print(f"Khoá ký: {path}  (giữ bí mật, sao lưu cẩn thận)")
    print(f'Dán vào viewer_hub/core/unlock.py:\nPUBLIC_KEY = bytes.fromhex("{ed25519.public_key(private).hex()}")')
    return 0


def _ask(prompt: str) -> str:
    try:
        return input(f"{prompt}: ").strip()
    except EOFError:
        return ""


def _ask_features(known: dict[str, str]) -> list[str]:
    """Pick features by number (several: "1 2") or type a name; Enter alone takes the only one when there is one."""
    names = sorted(known)
    print("Mã mở tính năng nào?")
    for index, name in enumerate(names, start=1):
        print(f"  {index}) {known[name]} ({name})")
    default = "1" if len(names) == 1 else ""
    answer = _ask("Chọn số hoặc gõ tên, cách nhau bằng dấu cách" + (f" [{default}]" if default else "")) or default
    tokens = answer.replace(",", " ").split()
    picked = [names[int(t) - 1] if t.isdigit() and 1 <= int(t) <= len(names) else t for t in tokens]
    if not picked or not all(unlock.NAME_RE.match(name) for name in picked):
        raise SystemExit(f"Lựa chọn không hợp lệ: {answer!r}")
    return picked


def main(argv: list[str] | None = None) -> int:
    known = known_features()
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--key", type=Path, help=f"Signing key file (default {DEFAULT_KEY})")
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("keygen", help="Make the signing key")
    gen.add_argument("--force", action="store_true")
    issue = sub.add_parser("issue", help="Make an unlock code")
    issue.add_argument("features", nargs="*", metavar="FEATURE", help=f"premium names, e.g. {', '.join(known) or 'bridge'} (default: ask)")
    check = sub.add_parser("check", help="What a code unlocks")
    check.add_argument("code", nargs="?", help="default: ask")
    args = parser.parse_args(argv)
    path = _key_path(args.key)
    if args.command == "keygen":
        return keygen(path, args.force)
    if args.command == "issue":
        bad = [name for name in args.features if not unlock.NAME_RE.match(name)]
        if bad:
            parser.error(f"tên không hợp lệ: {', '.join(bad)} (chữ thường, số, dấu -)")
        for name in sorted(set(args.features) - set(known)):
            print(f"Lưu ý: {name!r} không thuộc addon mặc định nào trong addons/ (vẫn tạo mã: addon cài tay có premium này cũng mở)", file=sys.stderr)
        private = read_key(path)
        print(unlock.issue(private, set(args.features or _ask_features(known))))
        return 0
    try:
        features = unlock.features(args.code or _ask("Dán mã cần kiểm tra"))
    except unlock.UnlockError as error:
        print(f"Mã không hợp lệ: {error}")
        return 1
    print("Mở: " + ", ".join(f"{known[k]} ({k})" if k in known else k for k in sorted(features)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
