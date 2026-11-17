"""Build the Windows release zip on the author's machine (GUIDELINE §8).

    python packaging/build_release.py --python-embed python-3.12.10-embed-amd64.zip

The embeddable Python zip is downloaded by the author from python.org and
passed in (this script never downloads anything). Output:

    dist/ViewerHub-<version>/   python/  app/viewer_hub  app/vendor  viewer-hub.cmd  setup.cmd  launcher/
                                packs/*.sapack  addons/*.zip  justfile  input/ (README.md, pack.yaml)
    dist/ViewerHub-<version>.zip + SHA256SUMS.txt + SBOM.json

Native extension modules of third-party packages (*.pyd, *.so) are removed:
every runtime dependency has a pure-Python fallback, so the only binaries in
the release are the ones python.org signed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "packaging" / "windows"
PURE_IMPORTS = ["yaml", "markupsafe", "chardet", "charset_normalizer", "flask", "waitress", "mkdocs.commands.build", "material"]


def run(*cmd: str, cwd: Path | None = None) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)  # argument list, no shell


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prune_vendor(vendor: Path) -> None:
    """Strip native binaries, console scripts, and massive unused asset libraries from vendor/.

    mkdocs-material ships with 14,000+ loose SVG files in .icons (fontawesome, octicons, simple, material).
    babel ships with 1,000+ locale data files. On Windows NTFS, extracting 18,000+ small files causes
    extreme I/O overhead and real-time antivirus scanning delays. Pruning unused assets reduces file count
    by ~75% without affecting functionality.
    """
    removed = [p for p in vendor.rglob("*") if p.suffix in {".pyd", ".so", ".dll", ".exe"}]
    for path in removed:
        path.unlink()
    print(f"removed {len(removed)} native files from vendor/")
    # pip's console-script shims (flask, mkdocs, ...): never used, the Hub runs `python -m viewer_hub`.
    shutil.rmtree(vendor / "bin", ignore_errors=True)

    pruned_count = 0
    # 1. Prune unused icon families from mkdocs-material (.icons/fontawesome, octicons, simple).
    icons_dir = vendor / "material" / "templates" / ".icons"
    if icons_dir.is_dir():
        for family in ("fontawesome", "octicons", "simple"):
            target = icons_dir / family
            if target.is_dir():
                count = sum(1 for p in target.rglob("*") if p.is_file())
                shutil.rmtree(target, ignore_errors=True)
                pruned_count += count

        # In material/, keep template-referenced and common doc icons, drop the rest of the 7,000+ SVGs.
        mat_icons = icons_dir / "material"
        if mat_icons.is_dir():
            keep_prefixes = (
                "account", "alert", "arrow", "book", "bookmark", "brightness", "bug", "calendar", "chart",
                "check", "chevron", "clock", "close", "code", "cog", "console", "content-copy", "database",
                "download", "eye", "file", "filter", "fire", "folder", "format", "github", "gitlab", "help",
                "information", "lightning", "link", "magnify", "menu", "note", "open-in-new", "pencil",
                "play", "plus", "refresh", "search", "share", "star", "sync", "table", "tag", "upload",
                "view", "warning", "wrench",
            )
            for svg in list(mat_icons.glob("*.svg")):
                if not any(svg.stem.startswith(px) for px in keep_prefixes):
                    svg.unlink()
                    pruned_count += 1

    # 2. Prune unused locale data files from babel (keep vi, en, global, root).
    babel_locales = vendor / "babel" / "locale-data"
    if babel_locales.is_dir():
        for dat in list(babel_locales.glob("*.dat")):
            if not (dat.stem.startswith(("vi", "en")) or dat.stem in {"global", "root"}):
                dat.unlink()
                pruned_count += 1

    print(f"pruned {pruned_count} unused asset files from vendor/")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python-embed", type=Path, required=True, help="python-3.12.x-embed-amd64.zip from python.org")
    parser.add_argument("--skip-web", action="store_true", help="Reuse viewer_hub/static/dist")
    parser.add_argument("--pack", type=Path, action="append", default=[],
                        help="Data pack (.sapack) to ship inside the zip; imported automatically on first start")
    parser.add_argument("--addons-dir", type=Path, default=ROOT / "addons",
                        help="Addon zips to ship (default: addons/, the default addons); installed on first start")
    args = parser.parse_args(argv)

    sys.path.insert(0, str(ROOT))
    from viewer_hub import __version__

    if not args.skip_web:
        run("npm", "ci", cwd=ROOT / "web")
        run("npm", "run", "build", cwd=ROOT / "web")
    if not (ROOT / "viewer_hub" / "static" / "dist" / "md.js").is_file():
        raise SystemExit("viewer_hub/static/dist is missing; run npm run build in web/")

    out = ROOT / "dist" / f"ViewerHub-{__version__}"
    shutil.rmtree(out, ignore_errors=True)
    (out / "app").mkdir(parents=True)

    # 1. Python (python.org embeddable) with a ._pth that adds app\ and app\vendor.
    with zipfile.ZipFile(args.python_embed) as archive:
        archive.extractall(out / "python")
    pth = next((out / "python").glob("python3*._pth"))
    stem = pth.stem.replace("python", "python") + ".zip"
    pth.write_text(f"{stem}\n.\n..\\app\n..\\app\\vendor\n", encoding="ascii")

    # 2. App source.
    shutil.copytree(ROOT / "viewer_hub", out / "app" / "viewer_hub",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    # 3. Dependencies for Windows, then strip native extensions and bloat.
    run(sys.executable, "-m", "pip", "install", "--quiet", "--no-compile", "--target", str(out / "app" / "vendor"),
        "--platform", "win_amd64", "--python-version", "3.12", "--only-binary=:all:", "--implementation", "cp",
        "-r", str(ROOT / "packaging" / "requirements.lock"))
    prune_vendor(out / "app" / "vendor")

    # 4. Bundled data packs (imported on start, see viewer_hub/packs/bundled.py).
    if args.pack:
        (out / "packs").mkdir()
        for pack in args.pack:
            shutil.copy2(pack, out / "packs" / pack.name)

    # 4b. Default addons (addons/*.zip, e.g. the MCP Bridge from my-bridge): checked here as an install would, shipped as zips,
    # installed into the data dir on start (viewer_hub/addons/install.py install_bundled). A premium one stays locked.
    from viewer_hub.addons.install import AddonError, check, unpack

    addon_report = []
    for zip_path in sorted(args.addons_dir.glob("*.zip")) if args.addons_dir.is_dir() else []:
        work = out / "tmp-addon"
        try:
            result = check(unpack(zip_path, work))
        except AddonError as error:
            raise SystemExit(f"addon {zip_path.name}: {error}") from error
        finally:
            shutil.rmtree(work, ignore_errors=True)
        (out / "addons").mkdir(exist_ok=True)
        shutil.copy2(zip_path, out / "addons" / zip_path.name)
        addon_report.append({"id": result.addon.id, "version": result.addon.version, "zip": zip_path.name,
                             "trust": result.trust, "sha256": sha256(zip_path)})
        print(f"addon {result.addon.id} {result.addon.version} ({result.trust}) ← {zip_path.name}")

    # 5. Launchers.
    shutil.copy2(WINDOWS / "viewer-hub.cmd", out / "viewer-hub.cmd")
    shutil.copy2(WINDOWS / "setup.cmd", out / "setup.cmd")
    # The user guide lives in the app (Hướng dẫn); no separate copy in the release.
    launcher = out / "viewer-hub.sh"  # macOS/Linux: same app, the system's python3 (3.12+)
    shutil.copy2(ROOT / "packaging" / "unix" / "viewer-hub.sh", launcher)
    launcher.chmod(0o755)
    shutil.copy2(ROOT / "packaging" / "viewer-hub.yaml", out / "viewer-hub.yaml")
    shutil.copytree(WINDOWS / "launcher", out / "launcher")
    # `just` in the release folder: serve, pack (input/ → .sapack), import, addon, backup… without the source.
    shutil.copy2(ROOT / "packaging" / "release.justfile", out / "justfile")
    # input/: how to lay out data for `just pack` (README.md) and a pack.yaml to fill in; never the author's own data.
    shutil.copytree(ROOT / "packaging" / "input", out / "input")

    # 6. SBOM: every vendored distribution with version and license.
    sbom = []
    for meta in sorted((out / "app" / "vendor").glob("*.dist-info/METADATA")):
        fields = {}
        for line in meta.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                break
            key, _, value = line.partition(": ")
            if key in {"Name", "Version", "License", "License-Expression"} and key not in fields:
                fields[key] = value
        sbom.append(fields)
    (out / "SBOM.json").write_text(json.dumps({"viewerHub": __version__, "packages": sbom, "addons": addon_report}, indent=2), encoding="utf-8")

    # 7. Zip + checksum.
    archive_path = out.parent / f"{out.name}.zip"
    shutil.make_archive(str(out), "zip", out.parent, out.name)
    digest = sha256(archive_path)
    sums = out.parent / "SHA256SUMS.txt"
    lines = [l for l in (sums.read_text(encoding="ascii").splitlines() if sums.is_file() else []) if not l.endswith(f"  {archive_path.name}")]
    sums.write_text("\n".join([*lines, f"{digest}  {archive_path.name}"]) + "\n", encoding="ascii")
    print(f"{archive_path}\nsha256 {digest}")
    print("On Windows, check the pure-Python fallbacks with:")
    print(f'  {out.name}\\python\\python.exe -I -c "import ' + ", ".join(PURE_IMPORTS) + '"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
