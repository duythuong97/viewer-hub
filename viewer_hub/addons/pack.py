"""Pack a built addon package into the zip Viewer Hub installs (docs/addons.md §8): ``viewer-hub addon pack <package>``.

    <package>/addon.json, GUIDE.md, ui/, app/, assets/, legal/      (the layout of docs/addons.md §2)

The package folder is what the SDK's build leaves in ``build/<id>/`` (npm run build): this does not build anything and
does not touch the project's sources. Steps: check addon.json, the GUIDE.md tool table, the layout and the security
rules exactly as an install does; optionally sign (packaging/addon.py, the author's key); zip to
``<out>/<id>-<version>.zip`` with the package under one top folder ``<id>/``.
"""
from __future__ import annotations

import re
import tempfile
import shutil
import zipfile
from pathlib import Path
from typing import Callable

from viewer_hub.addons.install import Installed, check
from viewer_hub.addons.manifest import GUIDE, AddonError, parse, read


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


def pack(package: Path, out_dir: Path, *, sign: Callable[[Path, Installed], None] | None = None,
         log: Callable[[str], None] = print) -> Path:
    """The checked (and signed, if ``sign``) zip of a built addon package."""
    package = package.resolve()
    addon = parse(read(package))
    if package.name != addon.id:
        raise AddonError(f"thư mục gói {package.name} phải trùng id {addon.id} (SDK: build/<id>/)")
    with tempfile.TemporaryDirectory(prefix="addon-") as work:
        stage = Path(work) / addon.id
        shutil.copytree(package, stage, ignore=shutil.ignore_patterns("signature.json", ".DS_Store", "__pycache__", "*.pyc"))
        check_guide(stage)
        result = check(stage)
        for note in result.notes:
            log(f"  lưu ý: {note}")
        if sign:
            sign(stage, result)
            result = check(stage)  # the signature checks out as an install will see it
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{addon.id}-{addon.version}.zip"
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in sorted(stage.rglob("*")):
                if path.is_file():
                    archive.write(path, f"{addon.id}/{path.relative_to(stage).as_posix()}")
    log(f"{out}  ({'đã ký' if result.trust == 'signed' else 'chưa ký'})")
    return out
