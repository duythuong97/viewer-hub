"""Pack an addon project into the zip Viewer Hub installs (docs/addons.md §8): ``viewer-hub addon pack <dir>``.

    <dir>/addon.json, GUIDE.md, main.py | main.mjs, lib/, ui/ (built: npm run build), web/ src/ … (development files, left out)

Steps: copy the project without its source folders and dotfiles (install.py SOURCE_DIRS); merge the top folder of
each ``include`` zip (a program built in another project, e.g. a daemon's release ``Name-1.2.3/``: its launcher
scripts are left out, its version becomes the addon's); check addon.json, the GUIDE.md tool
table and the security rules exactly as an install does; optionally sign (packaging/addon.py, the author's key);
zip to ``<out>/<id>-<version>.zip``. Never runs a build tool: the page is built beforehand (``npm run build``).
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable

from viewer_hub.addons.install import Installed, _source, check
from viewer_hub.addons.manifest import GUIDE, MANIFEST, AddonError, parse, read
from viewer_hub.core.scan import ADDON_RUNTIME, EXECUTABLE


def copy_project(source: Path, target: Path) -> None:
    for path in sorted(source.rglob("*")):
        rel = path.relative_to(source).as_posix()
        if path.is_file() and not path.is_symlink() and not _source(rel):
            dest = target / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)


def newest_zip(path: Path) -> Path:
    """``path`` itself, or the newest .zip in it when it is a folder (e.g. a daemon project's dist/)."""
    if path.is_file():
        return path
    found = sorted(path.glob("*.zip"), key=lambda p: p.stat().st_mtime) if path.is_dir() else []
    if not found:
        raise AddonError(f"không có file .zip trong {path}")
    return found[-1]


VERSION_IN_NAME = re.compile(r"-(\d+\.\d+\.\d+(?:[.-][0-9A-Za-z.-]+)?)$")


def merge(zip_path: Path, target: Path) -> str:
    """Unpack the top folder of a program zip into the addon; returns its version ("" if it names none): the
    ``version`` of an addon.json at its top, else the end of the folder name (``McpBridge-0.4.0``)."""
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        if not names:
            raise AddonError(f"{zip_path.name} rỗng")
        top = names[0].split("/", 1)[0]
        found = VERSION_IN_NAME.search(top)
        version = found.group(1) if found else ""
        for info in archive.infolist():
            rel = info.filename[len(top) + 1:]
            parts = PurePosixPath(rel).parts
            if not rel or info.is_dir() or ".." in parts or rel.startswith("/") or "\\" in rel or _source(rel):
                continue
            if rel == MANIFEST:
                version = json.loads(archive.read(info)).get("version", "") or version
                continue
            if PurePosixPath(rel).suffix.lower() in EXECUTABLE and rel not in ADDON_RUNTIME:
                continue  # launchers of the program on its own (bridge.cmd…): the Hub runs it
            dest = target.joinpath(*parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, open(dest, "wb") as out:
                shutil.copyfileobj(source, out)
    return version


def check_guide(folder: Path) -> None:
    """GUIDE.md starts with "## <menu label>" and documents every MCP tool in "### Tool cho AI"."""
    addon = parse(read(folder))
    guide = folder / GUIDE
    if not guide.is_file():
        raise AddonError(f"thiếu {GUIDE}: mục hướng dẫn \"## {addon.label}\" cho user")
    text = guide.read_text(encoding="utf-8")
    if not text.startswith(f"## {addon.label}"):
        raise AddonError(f"{GUIDE} phải bắt đầu bằng \"## {addon.label}\"")
    if addon.mcp:
        table = re.search(r"(?ms)^### Tool cho AI\n(.*?)(?=^#{2,3} |\Z)", text)
        documented = set(re.findall(r"(?m)^\| `([a-z0-9_]+)` \|", table.group(1))) if table else set()
        missing = set(addon.mcp.tools) - documented
        if missing:
            raise AddonError(f"{GUIDE}: thiếu dòng cho tool {', '.join(sorted(missing))} trong \"### Tool cho AI\"")


def _ui_hint(project: Path, data: dict) -> str:
    """Why the page is missing or stale ("" when fine)."""
    script = (data.get("ui") or {}).get("script")
    source = project / "web"
    if not script or not source.is_dir():
        return ""
    built = project / script
    if not built.is_file():
        return f"thiếu {script}: build giao diện trước (npm run build)"
    newest = max((p.stat().st_mtime for p in source.rglob("*") if p.is_file()), default=0)
    return f"lưu ý: {script} cũ hơn web/ — build lại (npm run build)" if newest > built.stat().st_mtime else ""


def pack(project: Path, out_dir: Path, includes: list[Path] = (), *,
         sign: Callable[[Path, Installed], None] | None = None, log: Callable[[str], None] = print) -> Path:
    """The checked (and signed, if ``sign``) zip of an addon project."""
    project = project.resolve()
    data = read(project)
    parse(data)
    hint = _ui_hint(project, data)
    if hint.startswith("thiếu"):
        raise AddonError(hint)
    if hint:
        log(hint)
    with tempfile.TemporaryDirectory(prefix="addon-") as work:
        stage = Path(work) / parse(data).id
        copy_project(project, stage)
        for include in map(newest_zip, includes):
            log(f"+ {include}")
            version = merge(include, stage)
            if version and version != data["version"]:
                log(f"version {data['version']} → {version} (theo {include.name})")
                data["version"] = version
        (stage / MANIFEST).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        check_guide(stage)
        result = check(stage)
        for note in result.notes:
            log(f"  lưu ý: {note}")
        if sign:
            sign(stage, result)
            result = check(stage)  # the signature checks out as an install will see it
        addon = result.addon
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{addon.id}-{addon.version}.zip"
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    archive.write(path, f"{addon.id}/{path.relative_to(stage).as_posix()}")
    log(f"{out}  ({'đã ký' if result.trust == 'signed' else 'chưa ký'})")
    return out
