"""One command for the admin: files in input/ → data pack → Windows release zip in dist/.

    just build        python packaging/build.py               # everything from input/, web UI rebuilt
    just build-fast   python packaging/build.py --skip-web    # same, reusing viewer_hub/static/dist
    just pack         viewer-hub pack                         # only dist/<id>-<version>.sapack (update data)

input/ layout: viewer_hub/packs/builder.py (also `viewer-hub pack` in a release, no source needed).
Default addons (addons/*.zip, addons/README.md) ship inside the release and install on start.
python.org embeddable zip: packaging/python-3.12.*-embed-amd64.zip (downloaded once by the admin)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _pack(input_dir: Path, out_dir: Path) -> Path | None:
    from viewer_hub.packs.builder import InputError, build_from_input

    try:
        out = build_from_input(input_dir, out_dir)
    except InputError as error:
        print(f"Không đóng data pack: {error}")
        return None
    print(f"data pack: {out.name}")
    return out


def summary(input_dir: Path, release: bool) -> list[str]:
    """What this build takes from input/ (and addons/ for a release), printed before it starts."""
    from viewer_hub.packs.builder import describe_input

    lines = describe_input(input_dir).splitlines()
    if release:
        lines.append("Bản phát hành: ViewerHub-<phiên bản>.zip, gửi cho mọi người; premium khoá, mở bằng `just unlock`")
        addons = sorted((ROOT / "addons").glob("*.zip"))
        lines.append("Addon mặc định (addons/, tự cài khi mở): " + (", ".join(a.name for a in addons)
                     or "không có — chép zip addon vào addons/ (addons/README.md)"))
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=ROOT / "input")
    parser.add_argument("--pack-only", action="store_true", help="Only build the .sapack (send it to users to import)")
    parser.add_argument("--python-embed", type=Path, help="Default: packaging/python-3.12.*-embed-amd64.zip")
    parser.add_argument("--skip-web", action="store_true", help="Reuse viewer_hub/static/dist (faster)")
    parser.add_argument("--addons-dir", type=Path, help="Addon zips shipped in the release (default: addons/)")
    args = parser.parse_args(argv)
    print("\n".join(["", *summary(args.input, not args.pack_only), ""]))
    pack = _pack(args.input, ROOT / "dist")
    if args.pack_only:
        return 0 if pack else 1
    embed = args.python_embed or next(iter(sorted((ROOT / "packaging").glob("python-3.12.*-embed-amd64.zip"))), None)
    if not embed:
        raise SystemExit("Thiếu packaging/python-3.12.x-embed-amd64.zip (tải từ python.org, xem README)")
    from packaging_build_release import main as release  # noqa: E402  (loaded below)

    release_args = ["--python-embed", str(embed)]
    if args.skip_web:
        release_args.append("--skip-web")
    if pack:
        release_args += ["--pack", str(pack)]
    if args.addons_dir:
        release_args += ["--addons-dir", str(args.addons_dir)]
    return release(release_args)


if __name__ == "__main__":
    import importlib.util

    spec = importlib.util.spec_from_file_location("packaging_build_release", ROOT / "packaging" / "build_release.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sys.modules["packaging_build_release"] = module
    raise SystemExit(main())
