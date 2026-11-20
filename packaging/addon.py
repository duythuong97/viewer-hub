"""Build an addon zip on the author's machine (docs/addons.md): SDK files, build, check, signature, zip.

    just addon <dir>                                        python packaging/addon.py build <dir>
    just addon-sdk-sync [<dir>…]                            python packaging/addon.py sync <dir>…

An addon project is an SDK folder (what Cài đặt → Addon → Tải SDK gives: .sdk/, AGENTS.md, package.json, and your
addon/, src/, web/). The build first brings its SDK files up to this Hub's (sync: .sdk/, AGENTS.md, package.json
scripts and devDependencies; never its own README.md, code or page), then runs the SDK's own builder
(``node .sdk/build.mjs build``: assembles the package in ``build/<id>/``, the layout of docs/addons.md §2), so an
author's ``npm run zip`` and this command build the same way. Then viewer_hub/addons/pack.py (the same packer as
`viewer-hub addon pack build/<id>`: check, zip) with a signature by the unlock-code key when it is on this machine
(else: an unsigned addon, "provided by the admin").

Install it: Cài đặt → Addon on the web, `viewer-hub addon install <zip>`, or make it a default addon shipped in
every release: `just addon-default <zip>` (python packaging/addon.py default <zip>: checks it, copies it to addons/).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "packaging"))

from viewer_hub.addons import signature  # noqa: E402
from viewer_hub.addons.manifest import AddonError  # noqa: E402
from viewer_hub.addons.pack import pack  # noqa: E402


# package.json scripts a project may define for itself; sync keeps them (the SDK only fills them in when missing).
OWN_SCRIPTS = {"test"}


def build(folder: Path, out_dir: Path, key: Path | None, ui: bool) -> Path:
    folder = folder.resolve()
    if not (folder / "package.json").is_file():
        raise SystemExit(f"{folder.name}: không phải project SDK (thiếu package.json); tạo từ SDK: Cài đặt → Addon → Tải SDK")
    if ui:
        sync(folder)
        build_sources(folder)
    manifest = folder / "addon" / "addon.json"
    if not manifest.is_file():
        raise SystemExit(f"{folder.name}: thiếu addon/addon.json")
    package = folder / "build" / json.loads(manifest.read_text(encoding="utf-8"))["id"]
    private = _key(key)

    def sign(stage: Path, result) -> None:
        signature.sign(stage, result.addon.id, result.addon.version, private)

    try:
        out = pack(package, out_dir, sign=sign if private else None)
    except AddonError as error:
        raise SystemExit(f"{folder.name}: {error}") from error
    if not private:
        print("CHƯA KÝ: không có khoá ký trên máy này")
    return out


def _npm() -> tuple[str, str]:
    node, npm = shutil.which("node"), shutil.which("npm")
    if not node or not npm:
        raise SystemExit("Cần Node.js (node, npm) để build addon; chạy `just setup` trước")
    return node, npm


def build_sources(folder: Path) -> None:
    """The SDK's own build in the addon folder (its node_modules; npm install the first time)."""
    node, npm = _npm()
    if not (folder / "node_modules").is_dir():
        print(f"+ npm install ({folder.name})")
        subprocess.run([npm, "install", "--no-audit", "--no-fund"], cwd=folder, check=True)
    print(f"+ node .sdk/build.mjs build ({folder.name})")
    subprocess.run([node, ".sdk/build.mjs", "build"], cwd=folder, check=True)


def sync(folder: Path) -> list[str]:
    """Bring an addon project's SDK files up to this Hub's SDK (sdk_kit.build). Returns what changed."""
    import io
    import json
    import zipfile

    from viewer_hub.addons import sdk_kit

    top = sdk_kit.TOP + "/"
    changed: list[str] = []
    with zipfile.ZipFile(io.BytesIO(sdk_kit.build())) as kit:
        files = {name[len(top):]: kit.read(name) for name in kit.namelist() if name.startswith(top) and not name.endswith("/")}
    sdk_files = {rel: data for rel, data in files.items() if rel.startswith(".sdk/")}
    current = {p.relative_to(folder).as_posix() for p in (folder / ".sdk").rglob("*") if p.is_file()} \
        if (folder / ".sdk").is_dir() else set()
    for rel in sorted(current - set(sdk_files)):
        if rel.startswith(".sdk/addons/"):
            continue  # contracts of other addons (npm run exports): the project's, not the kit's
        (folder / rel).unlink()
        changed.append(f"- {rel}")
    for rel, data in {**sdk_files, "AGENTS.md": files["AGENTS.md"]}.items():
        target = folder / rel
        if not target.is_file() or target.read_bytes() != data:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            changed.append(f"~ {rel}")
    if not (folder / ".gitignore").is_file():
        (folder / ".gitignore").write_bytes(files[".gitignore"])
        changed.append("+ .gitignore")
    kit_pkg = json.loads(files["package.json"])
    pkg_file = folder / "package.json"
    pkg = json.loads(pkg_file.read_text(encoding="utf-8")) if pkg_file.is_file() else {"name": folder.name, "private": True}
    # The SDK's scripts win, except a project's own `test` (a .NET addon runs `dotnet test`; the SDK test refuses it).
    own = {name: command for name, command in pkg.get("scripts", {}).items() if name in OWN_SCRIPTS}
    wanted = {**pkg, "type": "module", "scripts": {**pkg.get("scripts", {}), **kit_pkg["scripts"], **own},
              "devDependencies": {**pkg.get("devDependencies", {}), **kit_pkg["devDependencies"]}}
    if wanted != pkg:
        pkg_file.write_text(json.dumps(wanted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        changed.append("~ package.json (npm install nếu devDependencies đổi)")
    for line in changed:
        print(f"  sdk {folder.name}: {line}")
    return changed


def make_default(zip_path: Path) -> int:
    """addons/<id>-<version>.zip: checked as an install would; older zips of the same addon removed."""
    import tempfile

    from viewer_hub.addons.install import check, peek, unpack

    try:
        wanted = peek(zip_path)
        with tempfile.TemporaryDirectory() as work:
            result = check(unpack(zip_path, Path(work)))
    except AddonError as error:
        raise SystemExit(f"{zip_path.name}: {error}") from error
    folder = ROOT / "addons"
    folder.mkdir(exist_ok=True)
    for old in folder.glob("*.zip"):
        try:
            if peek(old).id == wanted.id:
                old.unlink()
                print(f"- {old.name}")
        except AddonError:
            continue
    target = folder / f"{wanted.id}-{wanted.version}.zip"
    shutil.copy2(zip_path, target)
    print(f"+ {target.relative_to(ROOT)}  ({'đã ký' if result.trust == 'signed' else 'chưa ký'}; đi kèm mọi `just build`)")
    return 0


def _key(path: Path | None) -> bytes | None:
    from unlock import DEFAULT_KEY, read_key  # packaging/unlock.py

    chosen = path or Path(os.environ.get("VIEWER_HUB_SIGNING_KEY") or DEFAULT_KEY)
    if not chosen.is_file():
        if path:
            raise SystemExit(f"Không có khoá ký {path}")
        return None
    return read_key(chosen)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    cmd = sub.add_parser("build", help="Build, check, sign and zip one addon")
    cmd.add_argument("folder", type=Path, help="Addon project (has addon/addon.json and package.json)")
    cmd.add_argument("--out", type=Path, default=ROOT / "dist" / "addons")
    cmd.add_argument("--key", type=Path, help="Signing key (default: the unlock-code key, ~/.viewer-hub/…)")
    cmd.add_argument("--no-ui", action="store_true", help="Reuse the built files (no SDK sync, no node build)")
    synced = sub.add_parser("sync", help="Bring addon projects' SDK files (.sdk/, AGENTS.md, package.json) up to this Hub")
    synced.add_argument("folders", type=Path, nargs="+")
    default = sub.add_parser("default", help="Check an addon zip and make it a default addon (addons/)")
    default.add_argument("zip", type=Path)
    args = parser.parse_args(argv)
    if args.command == "default":
        return make_default(args.zip)
    if args.command == "sync":
        for folder in args.folders:
            if not (folder / "addon" / "addon.json").is_file():
                raise SystemExit(f"{folder}: không có addon/addon.json")
            if not sync(folder.resolve()):
                print(f"  sdk {folder.name}: đã mới nhất")
        return 0
    build(args.folder, args.out, args.key, ui=not args.no_ui)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
