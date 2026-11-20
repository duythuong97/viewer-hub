"""Docs sites on disk.

workspace/docs/<id>/
  site.json   title, source info, build status          (source data)
  src/        the uploaded markdown folder, untouched     (source data)
  site/       HTML built by mkdocs                        (derived data)
"""
from __future__ import annotations

import io
import logging
import re
import shutil
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml

from viewer_hub.core.atomic import read_json, write_json
from viewer_hub.csv.store import slugify

logger = logging.getLogger(__name__)
SCHEMA = 1
# Bump when the generated mkdocs config changes; sites built with an older profile are
# rebuilt from src/ on next view (site/ is derived data, design.md §3).
BUILD_PROFILE = 3
ALLOWED = {".md", ".markdown", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".pdf", ".css", ".yml", ".yaml", ".txt", ".csv", ".json"}
MAX_FILES = 5000
MAX_BYTES = 300 * 1024 * 1024
# Only these mkdocs plugins may run: plugins and hooks execute Python code (GUIDELINE §5).
ALLOWED_PLUGINS = {"search"}
ALLOWED_MARKDOWN_EXTENSIONS = {
    "toc", "tables", "fenced_code", "admonition", "attr_list", "def_list", "footnotes", "md_in_html", "abbr", "meta",
    "pymdownx.details", "pymdownx.superfences", "pymdownx.tabbed", "pymdownx.highlight", "pymdownx.inlinehilite",
    "pymdownx.tasklist", "pymdownx.mark", "pymdownx.tilde", "pymdownx.caret", "pymdownx.keys", "pymdownx.smartsymbols",
    "pymdownx.emoji", "pymdownx.betterem", "pymdownx.critic",
}


class SiteError(ValueError):
    pass


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def safe_relative(name: str) -> PurePosixPath | None:
    """A relative path inside the site, or None for anything that could escape it."""
    parts = PurePosixPath(name.replace("\\", "/")).parts
    if not parts or any(p in ("", ".", "..") or ":" in p for p in parts) or name.startswith(("/", "\\")):
        return None
    if any(p.startswith(".") for p in parts):  # .git, .DS_Store, ...
        return None
    return PurePosixPath(*parts)


@dataclass
class Site:
    folder: Path
    meta: dict
    readonly: bool = False  # shipped in a data pack (already built): never rebuilt or deleted

    @property
    def id(self) -> str:
        return self.meta["id"]

    @property
    def title(self) -> str:
        return self.meta.get("title") or self.id

    @property
    def src(self) -> Path:
        return self.folder / "src"

    @property
    def html(self) -> Path:
        return self.folder / "site"

    @property
    def built(self) -> bool:
        return (self.html / "index.html").is_file()

    def save(self) -> None:
        if self.readonly:
            raise PermissionError("Site thuộc data pack, chỉ đọc")
        self.meta["updatedAt"] = _now()
        write_json(self.folder / "site.json", self.meta)


class SiteStore:
    def __init__(self, root: Path, tmp: Path, packs: list[tuple[str, str, Path]] | None = None):
        self.root = root
        self.tmp = tmp
        self.packs = packs or []  # (pack_id, pack title, <pack>/docs) of active data packs

    @staticmethod
    def _pack_site(pack_id: str, title: str, folder: Path) -> Site | None:
        meta = read_json(folder / "site.json")
        if not meta or not (folder / "site" / "index.html").is_file():
            return None
        meta = {**meta, "id": f"{pack_id}--{meta.get('id') or folder.name}", "pack": {"id": pack_id, "title": title}}
        return Site(folder, meta, readonly=True)

    def list(self) -> list[Site]:
        out = []
        if self.root.is_dir():
            for folder in self.root.iterdir():
                meta = read_json(folder / "site.json")
                if meta:
                    out.append(Site(folder, meta))
        out.sort(key=lambda s: s.meta.get("updatedAt", ""), reverse=True)
        for pack_id, title, root in self.packs:
            for folder in sorted(p for p in root.iterdir() if p.is_dir()):
                site = self._pack_site(pack_id, title, folder)
                if site:
                    out.append(site)
        return out

    def get(self, site_id: str) -> Site | None:
        if not re.fullmatch(r"[a-z0-9-]{1,130}", site_id or ""):
            return None
        if "--" in site_id:  # <pack_id>--<site id>: from a data pack
            pack_id, local = site_id.split("--", 1)
            for pid, title, root in self.packs:
                if pid == pack_id and re.fullmatch(r"[a-z0-9-]{1,64}", local) and (root / local).is_dir():
                    return self._pack_site(pid, title, root / local)
            return None
        meta = read_json(self.root / site_id / "site.json")
        return Site(self.root / site_id, meta) if meta else None

    def _new_id(self, title: str) -> str:
        base = slugify(title).replace("--", "-")  # "--" is reserved for pack items
        candidate, n = base, 2
        while (self.root / candidate).exists():
            candidate, n = f"{base}-{n}", n + 1
        return candidate

    def create(self, title: str, files: list[tuple[str, bytes]], site_id: str | None = None) -> Site:
        """``files`` are (relative path, content). A single .zip is unpacked."""
        files = _expand_zip(files)
        site_id = site_id or self._new_id(title)
        work = self.tmp / f"site-{site_id}-{int(time.time() * 1000)}"
        src = work / "src"
        count = _write_files(src, files)
        if not any(p.suffix.lower() in {".md", ".markdown"} for p in src.rglob("*")):
            shutil.rmtree(work, ignore_errors=True)
            raise SiteError("Không có file markdown (.md) nào.")
        _flatten_single_root(src)
        meta = {"schema": SCHEMA, "id": site_id, "title": title.strip() or site_id, "files": count,
                "createdAt": _now(), "updatedAt": _now(), "builtAt": None, "pages": 0, "buildError": None}
        write_json(work / "site.json", meta)
        target = self.root / site_id
        self.root.mkdir(parents=True, exist_ok=True)
        if target.exists():  # replace the source of an existing site, keep nothing stale
            old = self.tmp / f"replaced-{site_id}-{int(time.time())}"
            previous = read_json(target / "site.json", {}) or {}
            meta["createdAt"] = previous.get("createdAt", meta["createdAt"])
            write_json(work / "site.json", meta)
            target.rename(old)
            work.rename(target)
            shutil.rmtree(old, ignore_errors=True)
        else:
            work.rename(target)
        return Site(target, meta)

    def delete(self, site: Site) -> None:
        if site.readonly:
            raise PermissionError("Site thuộc data pack, chỉ đọc")
        trash = self.tmp / f"deleted-site-{site.id}-{int(time.time())}"
        site.folder.rename(trash)
        shutil.rmtree(trash, ignore_errors=True)


def _expand_zip(files: list[tuple[str, bytes]]) -> list[tuple[str, bytes]]:
    if len(files) != 1 or not files[0][0].lower().endswith(".zip"):
        return files
    out, total = [], 0
    with zipfile.ZipFile(io.BytesIO(files[0][1])) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            total += info.file_size
            if total > MAX_BYTES or len(out) >= MAX_FILES:
                raise SiteError("File zip quá lớn sau khi giải nén.")
            if info.compress_size and info.file_size / info.compress_size > 200:
                raise SiteError("File zip có tỉ lệ nén bất thường.")
            out.append((info.filename, archive.read(info)))
    return out


def _write_files(src: Path, files: list[tuple[str, bytes]]) -> int:
    count, total = 0, 0
    for name, data in files:
        relative = safe_relative(name)
        if relative is None or Path(relative.name).suffix.lower() not in ALLOWED:
            continue  # executables and anything unknown are dropped, not stored
        total += len(data)
        count += 1
        if count > MAX_FILES or total > MAX_BYTES:
            raise SiteError("Thư mục quá lớn (tối đa 5000 file / 300 MB).")
        target = src.joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return count


def _flatten_single_root(src: Path) -> None:
    """Folder uploads arrive as <folder>/...; use the folder's content as the site root."""
    children = [c for c in src.iterdir()]
    if len(children) == 1 and children[0].is_dir() and not (src / "mkdocs.yml").exists():
        inner = children[0]
        for item in list(inner.iterdir()):
            item.rename(src / item.name)
        inner.rmdir()


# ── Build ────────────────────────────────────────────────────────────────────────────

def _docs_dir(src: Path, user_cfg: dict) -> Path:
    configured = user_cfg.get("docs_dir")
    if isinstance(configured, str) and safe_relative(configured) and (src / configured).is_dir():
        return src / configured
    if (src / "docs").is_dir() and (src / "mkdocs.yml").exists():
        return src / "docs"
    return src


def _title_of(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    except OSError:
        pass
    return path.stem.replace("-", " ").replace("_", " ").strip().capitalize()


def _nav(folder: Path, docs: Path) -> list:
    items = []
    entries = sorted(folder.iterdir(), key=lambda p: (p.is_dir(), p.name.lower()))
    for entry in entries:
        if entry.is_dir():
            children = _nav(entry, docs)
            if children:
                items.append({entry.name.replace("-", " ").replace("_", " ").capitalize(): children})
        elif entry.suffix.lower() in {".md", ".markdown"}:
            items.append({_title_of(entry): entry.relative_to(docs).as_posix()})
    return items


def _sanitise(user_cfg: dict) -> dict:
    """Keep only content settings from a user's mkdocs.yml; never hooks, plugins, theme code."""
    keep = {}
    for key in ("site_name", "site_description", "copyright", "nav"):
        if key in user_cfg:
            keep[key] = user_cfg[key]
    extensions = []
    for item in user_cfg.get("markdown_extensions") or []:
        name = item if isinstance(item, str) else (next(iter(item)) if isinstance(item, dict) and item else None)
        if name in ALLOWED_MARKDOWN_EXTENSIONS:
            extensions.append(item)
    if extensions:
        keep["markdown_extensions"] = extensions
    return keep


class _SafeLoader(yaml.SafeLoader):
    """mkdocs.yml may contain !!python/name tags; read them as plain strings, never import anything."""


_SafeLoader.add_multi_constructor("", lambda loader, suffix, node: None)
_SafeLoader.add_multi_constructor("!", lambda loader, suffix, node: None)
_SafeLoader.add_multi_constructor("tag:yaml.org,2002:python/", lambda loader, suffix, node: None)


def build(site: Site, work_root: Path) -> int:
    """Build site/ from src/. Writes to a temp folder first, swaps when done."""
    from mkdocs.commands.build import build as mkdocs_build
    from mkdocs.config import load_config

    user_cfg = {}
    user_file = site.src / "mkdocs.yml"
    if user_file.is_file():
        try:
            user_cfg = yaml.load(user_file.read_text(encoding="utf-8", errors="replace"), Loader=_SafeLoader) or {}
        except yaml.YAMLError as error:
            raise SiteError(f"mkdocs.yml không hợp lệ: {error}") from None
        if not isinstance(user_cfg, dict):
            user_cfg = {}
    docs = _docs_dir(site.src, user_cfg)
    cfg = {
        "site_name": site.title,
        "docs_dir": str(docs),
        "use_directory_urls": False,  # works when opened as plain files too
        "strict": False,
        "theme": {
            "name": "material",
            "language": "vi",
            "font": False,  # never load Google Fonts from the internet
            # One menu: no top tabs, the page's headings (right TOC) are folded into the left
            # navigation tree, so sections → pages → headings form a single multi-level menu.
            "features": ["toc.integrate", "navigation.indexes", "navigation.top", "navigation.footer",
                         "search.highlight", "search.suggest", "content.code.copy"],
            "palette": [
                {"media": "(prefers-color-scheme: light)", "scheme": "default", "primary": "indigo",
                 "toggle": {"icon": "material/brightness-7", "name": "Giao diện tối"}},
                {"media": "(prefers-color-scheme: dark)", "scheme": "slate", "primary": "indigo",
                 "toggle": {"icon": "material/brightness-4", "name": "Giao diện sáng"}},
            ],
            "icon": {"logo": "material/book-open-page-variant"},
        },
        "plugins": ["search"],
        "extra": {"generator": False},  # no "Made with Material for MkDocs" link to an external site
        "markdown_extensions": [
            "toc", "tables", "admonition", "attr_list", "md_in_html", "def_list", "footnotes",
            {"pymdownx.highlight": {"anchor_linenums": True}}, "pymdownx.superfences", "pymdownx.details",
            "pymdownx.tabbed", "pymdownx.tasklist", "pymdownx.mark", "pymdownx.inlinehilite",
        ],
    }
    cfg.update(_sanitise(user_cfg))
    cfg["plugins"] = [p for p in cfg["plugins"] if p in ALLOWED_PLUGINS]
    cfg.pop("hooks", None)
    if "nav" not in cfg:
        index = next((p for p in ("index.md", "README.md", "readme.md") if (docs / p).is_file()), None)
        nav = _nav(docs, docs)
        if index:
            nav = [{"Trang chủ": index}, *[n for n in nav if list(n.values())[0] != index]]
        cfg["nav"] = nav

    out = work_root / f"build-{site.id}-{int(time.time() * 1000)}"
    config_file = work_root / f"mkdocs-{site.id}.yml"
    config_file.write_text(yaml.safe_dump({**cfg, "site_dir": str(out)}, allow_unicode=True), encoding="utf-8")
    try:
        mkdocs_build(load_config(config_file=str(config_file)))
        if not (out / "index.html").is_file():
            _write_index_redirect(out, cfg["nav"])
        pages = sum(1 for _ in out.rglob("*.html"))
        old = work_root / f"old-site-{site.id}-{int(time.time())}"
        if site.html.exists():
            site.html.rename(old)
        out.rename(site.html)
        shutil.rmtree(old, ignore_errors=True)
    except Exception as error:
        shutil.rmtree(out, ignore_errors=True)
        site.meta.update(buildError=str(error)[:2000])
        site.save()
        raise SiteError(f"Build lỗi: {error}") from error
    finally:
        config_file.unlink(missing_ok=True)
    site.meta.update(builtAt=_now(), pages=pages, buildError=None, buildProfile=BUILD_PROFILE)
    site.save()
    return pages


def _first_page(nav) -> str | None:
    for item in nav:
        for value in item.values():
            if isinstance(value, str):
                return value
            found = _first_page(value)
            if found:
                return found
    return None


def _write_index_redirect(out: Path, nav: list) -> None:
    first = _first_page(nav)
    if not first:
        return
    target = re.sub(r"\.(md|markdown)$", ".html", first)
    (out / "index.html").write_text(
        f'<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url={target}"><a href="{target}">{target}</a>',
        encoding="utf-8",
    )
