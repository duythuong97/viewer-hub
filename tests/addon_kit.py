"""Test helpers for addons: install a copy of the test addon (tests/fixtures/example) under another id, as a test needs."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parent / "fixtures" / "example"


def install(paths, addon_id: str = "example", *, label: str | None = None, premium: str | None = None,
            command: str | None = None, files: dict[str, str] | None = None, **fields) -> Path:
    """<data>/addons/<addon_id>: the example addon with these manifest changes and extra files."""
    target = paths.addons / addon_id
    shutil.copytree(EXAMPLE, target, ignore=shutil.ignore_patterns("__pycache__"))
    manifest = json.loads((target / "addon.json").read_text(encoding="utf-8"))
    manifest.update(id=addon_id, premium=premium, **fields)
    if label:
        manifest["menu"]["label"] = label
        guide = (target / "GUIDE.md").read_text(encoding="utf-8").replace("## Ví dụ addon", f"## {label}", 1)
        (target / "GUIDE.md").write_text(guide, encoding="utf-8")
    if manifest.get("mcp"):
        manifest["mcp"]["command"] = command or addon_id
    (target / "addon.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    for name, text in (files or {}).items():
        (target / name).parent.mkdir(parents=True, exist_ok=True)
        (target / name).write_text(text, encoding="utf-8")
    return target


def zip_folder(folder: Path, out: Path, top: str | None = None) -> Path:
    import zipfile

    with zipfile.ZipFile(out, "w") as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                archive.write(path, f"{top or folder.name}/{path.relative_to(folder).as_posix()}")
    return out
