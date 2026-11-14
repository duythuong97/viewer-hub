"""Build a .sapack: on the author's machine, or on any machine with a release (no source needed).

    viewer-hub pack --input input --out dist     # one folder laid out as below (build_from_input)
    just pack                                    # the same, from the repo or from a release folder

input/ (any part may be missing; README):
    pack.yaml            id, title (and optional version)
    codemap/             output folder of `codemap extract` (codemap.sqlite, graph.sqlite, manifest.json)
    search.sqlite        from `viewer-hub export-solr`
    csv/*.csv            CSV files
    docs/<site>/         one folder of markdown per docs site

Or every part by hand:

    python -m viewer_hub.packs.builder --id core-system --title "Core System" \
        --codemap path/to/code-map/output --search search.sqlite \
        --csv danh-muc.csv --csv nhan-vien.csv --docs ./spec-docs --out core-system.sapack

CSV and docs are prepared here (columns detected, SQLite index built, mkdocs site built), so on
users' PCs they open instantly, read-only, and never mix with what users uploaded themselves.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import zipfile
from pathlib import Path

CODEMAP_FILES = ("codemap.sqlite", "graph.sqlite", "manifest.json", "graph-index.json")


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


SKIP_SITE_FILES = {".gz"}  # mkdocs sitemap.xml.gz: not needed offline, not an allowed pack file type


def _viewer_config(sources: list[Path]) -> dict[str, dict]:
    """The old csv-viewer config.json next to the CSV files, keyed by file name: {"fileA": {"path": "data/fileA.csv",
    "visibleCols": [...], "filterCol": [{"name": "=="}]}} → {"fileA.csv": entry}."""
    import json

    for folder in {source.parent for source in sources}:
        config = folder / "config.json"
        if config.is_file():
            data = json.loads(config.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict):
                raise SystemExit(f"{config}: phải là object {{tên: cấu hình}} như csv-viewer cũ")
            return {Path(entry.get("path") or f"{name}.csv").name: {**entry, "title": name}
                    for name, entry in data.items() if isinstance(entry, dict)}
    return {}


def _add_csv(work: Path, files: dict[str, Path], sources: list[Path]) -> list[dict]:
    """Analyse + index every CSV now, so users get a ready data.sqlite (nothing is built on their PC).
    A csv-viewer config.json beside the files sets each dataset's name, visible columns and default filters."""
    import shutil

    from viewer_hub.csv.store import CsvStore

    store = CsvStore(work / "csv", work / "tmp")
    (work / "tmp").mkdir(parents=True, exist_ok=True)
    config = _viewer_config(sources)
    entries = []
    for source in sources:
        copy = work / "tmp" / source.name
        shutil.copy2(source, copy)
        entry = config.get(source.name)
        # In a pack, files are for everyone, AI included, unless config.json says "mcp": false.
        dataset = store.create(copy, source.name, entry["title"] if entry else None, mcp=True)
        if entry:
            dataset.apply_viewer_config(entry)
            dataset.save()
        if not dataset.description:
            print(f"  ! {source.name} chưa có mô tả (\"description\" trong csv/config.json): AI chỉ thấy tên file và tên cột",
                  file=sys.stderr)
        for item in sorted(dataset.folder.rglob("*")):
            if item.is_file():
                files[f"csv/{item.relative_to(work / 'csv').as_posix()}"] = item
        entries.append({"id": dataset.id, "title": dataset.title, "schema": dataset.meta["schema"], "rows": dataset.meta["rows"]})
    return entries


def _add_docs(work: Path, files: dict[str, Path], folders: list[Path]) -> list[dict]:
    """Build each markdown folder into a site now; the pack carries only site.json + site/."""
    import logging

    from viewer_hub.docs.store import SiteStore, build as build_site

    logging.getLogger("mkdocs").setLevel(logging.ERROR)  # link warnings of the docs are not build errors

    store = SiteStore(work / "docs", work / "tmp")
    (work / "tmp").mkdir(parents=True, exist_ok=True)
    entries = []
    for folder in folders:
        sources = [(p.relative_to(folder).as_posix(), p.read_bytes()) for p in sorted(folder.rglob("*")) if p.is_file()]
        site = store.create(folder.name, sources)
        pages = build_site(site, work / "tmp")
        for item in sorted((site.folder / "site").rglob("*")):
            if item.is_file() and item.suffix not in SKIP_SITE_FILES:
                files[f"docs/{site.id}/site/{item.relative_to(site.folder / 'site').as_posix()}"] = item
        files[f"docs/{site.id}/site.json"] = site.folder / "site.json"
        entries.append({"id": site.id, "title": site.title, "schema": site.meta["schema"], "pages": pages})
    return entries


def build(out: Path, pack_id: str, title: str, version: str | None = None, *, codemap: Path | None = None,
          search: Path | None = None, csv: list[Path] | None = None, docs: list[Path] | None = None) -> dict:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="sapack-") as tmp:
        return _build(out, pack_id, title, version, Path(tmp), codemap=codemap, search=search, csv=csv or [], docs=docs or [])


def _build(out: Path, pack_id: str, title: str, version: str | None, work: Path, *, codemap, search, csv, docs) -> dict:
    files: dict[str, Path] = {}
    components: dict = {}
    if codemap:
        for name in CODEMAP_FILES:
            if (codemap / name).is_file():
                files[f"codemap/{name}"] = codemap / name
        if "codemap/codemap.sqlite" not in files:
            raise SystemExit(f"{codemap} không có codemap.sqlite")
        contract = json.loads((codemap / "manifest.json").read_text(encoding="utf-8")).get("contractVersion") if (codemap / "manifest.json").is_file() else None
        components["codemap"] = {"path": "codemap/", "schema": 1, "contractVersion": contract}
    if search:
        import sqlite3

        with sqlite3.connect(f"{search.resolve().as_uri()}?mode=ro", uri=True) as db:
            meta = dict(db.execute("SELECT key, value FROM meta").fetchall())
            count = db.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
        files["search/search.sqlite"] = search
        components["search"] = {"path": "search/search.sqlite", "schema": int(meta.get("schema", 1)), "docCount": count}
    if csv:
        components["csv"] = _add_csv(work, files, csv)
    if docs:
        components["docs"] = _add_docs(work, files, docs)
    if not components:
        raise SystemExit("Cần ít nhất một trong --codemap, --search, --csv, --docs")
    manifest = {
        "format": 1,
        "id": pack_id,
        "version": version or time.strftime("%Y.%m.%d-%H%M"),
        "title": title,
        "builtAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "components": components,
        "sha256": {name: _sha(path) for name, path in files.items()},
    }
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr("pack.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for name, path in files.items():
            archive.write(path, name)
    return manifest


class InputError(ValueError):
    """The input folder cannot make a pack (no pack.yaml id / title, or nothing in it)."""


def _input_parts(input_dir: Path) -> tuple[dict, dict]:
    import yaml

    info_file = input_dir / "pack.yaml"
    info = yaml.safe_load(info_file.read_text(encoding="utf-8")) if info_file.is_file() else {}
    codemap, search = input_dir / "codemap", input_dir / "search.sqlite"
    parts = {
        "codemap": codemap if (codemap / "codemap.sqlite").is_file() else None,
        "search": search if search.is_file() else None,
        "csv": sorted((input_dir / "csv").glob("*.csv")) if (input_dir / "csv").is_dir() else [],
        "docs": sorted(p for p in (input_dir / "docs").iterdir() if p.is_dir()) if (input_dir / "docs").is_dir() else [],
    }
    return (info if isinstance(info, dict) else {}), parts


def describe_input(input_dir: Path) -> str:
    """What a pack from this folder would hold, for the admin before it is built."""
    info, parts = _input_parts(input_dir)
    found = [name for name, key in (("code map", "codemap"), ("F-Search", "search")) if parts[key]]
    if parts["csv"]:
        found.append(f"{len(parts['csv'])} file CSV")
    if parts["docs"]:
        found.append(f"{len(parts['docs'])} site docs")
    return (f"Dữ liệu trong {input_dir}: " + (", ".join(found) or "(trống)") + "\n"
            f"Pack: {info.get('id', '?')} · {info.get('title', '?')}" + (f" · version {info['version']}" if info.get("version") else ""))


def build_from_input(input_dir: Path, out_dir: Path, version: str | None = None) -> Path:
    """``<out_dir>/<id>-<version>.sapack`` from an input folder (layout in the module docstring)."""
    if not input_dir.is_dir():
        raise InputError(f"Không có thư mục {input_dir}")
    info, parts = _input_parts(input_dir)
    if not info.get("id") or not info.get("title"):
        raise InputError(f"{input_dir / 'pack.yaml'} phải có id và title, vd.\n  id: core-system\n  title: Core System")
    if not any(parts.values()):
        raise InputError(f"{input_dir} chưa có dữ liệu (codemap/, search.sqlite, csv/, docs/)")
    version = str(version or info.get("version") or time.strftime("%Y.%m.%d-%H%M"))
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{info['id']}-{version}.sapack"
    build(out, str(info["id"]), str(info["title"]), version, **parts)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--id", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--version")
    parser.add_argument("--codemap", type=Path, help="Thư mục output của code-map extract")
    parser.add_argument("--search", type=Path, help="search.sqlite từ export-solr")
    parser.add_argument("--csv", type=Path, action="append", default=[], help="File CSV (lặp lại được); cột và index được tạo sẵn")
    parser.add_argument("--docs", type=Path, action="append", default=[], help="Thư mục markdown (lặp lại được); site được build sẵn")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = build(args.out, args.id, args.title, args.version, codemap=args.codemap, search=args.search,
                     csv=args.csv, docs=args.docs)
    print(f"{args.out}: {manifest['id']} {manifest['version']} {list(manifest['components'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
