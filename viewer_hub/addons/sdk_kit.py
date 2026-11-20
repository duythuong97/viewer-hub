"""The addon SDK users download (Cài đặt → Addon → Tải SDK, ``viewer-hub addon sdk``): everything needed to write an
addon without the Viewer Hub source, next to an AI agent.

    my-addon/                      the SDK project (one layout for managed and daemon, AGENTS.md §2):
      AGENTS.md, README.md         the rules (for the AI) and the steps (for people); {{hub}} = this Hub's command
      package.json                 npm run new | build | watch | check | test | zip
      .gitignore
      addon/addon.json, GUIDE.md   what the package says about itself (the template writes them)
      src/                         the program (Python: main.py + lib/; Node: main.mjs; .NET: the project)
      web/                         the page (index.jsx)
      test/                        tests
      .sdk/build.mjs, new.mjs      build (assembles build/<id>/), the install checks, the zip
      .sdk/templates/simple|daemon|external   starters laid out as above
      .sdk/python/viewer_hub/      this Hub's Python SDK (addons/sdk.py and what it imports): read it, and put it on
                                   PYTHONPATH to test or run an addon without a Hub
      .sdk/node/hub_client.mjs     calling other addons from a Node addon (the Hub passes its own copy at run time)
      .sdk/addons/<id>.json, .md   what each addon installed on this Hub lets others read (``exports``): the
                                   contract ``uses`` is built against (json) and its description for the AI (md)
      build/<id>/, dist/           generated: the package (what Viewer Hub installs) and its zip

The user renames the folder, runs ``npm run new -- simple <id>``, writes the addon, ``npm run zip`` and uploads.

Files come from ``kit/`` beside this module; keep AGENTS.md in step with manifest.py, sdk.py, runner.py, channel.py,
core/scan.py and web/src/sdk/ when they change (tests/test_addon_sdk.py checks the parts it can).
"""
from __future__ import annotations

import io
import json
import sys
import zipfile
from pathlib import Path

from viewer_hub.addons.manifest import SDK_VERSION

KIT = Path(__file__).with_name("kit")
TOP = "my-addon"
TEXT = {".md", ".json"}
# addons/sdk.py and everything it imports (standard library only past these): an addon's tests import the real SDK.
PYTHON_SDK = ("__init__.py", "core/__init__.py", "core/mcp.py", "core/monitor.py", "core/text.py", "addons/__init__.py",
              "addons/contract.py", "addons/sdk.py")
NODE_SDK = "addons/hub_client.mjs"  # → .sdk/node/hub_client.mjs (the Hub passes its own copy in VIEWER_HUB_NODE_SDK)
GITIGNORE = "node_modules/\nbuild/\ndist/\n__pycache__/\n.pytest_cache/\n"


def file_name() -> str:
    return f"viewer-hub-addon-sdk-{SDK_VERSION}.zip"


def hub_command() -> str:
    """How to run this Viewer Hub's CLI from a terminal: the release launcher (quoted if needed), else viewer-hub."""
    from viewer_hub.core.config import release_root

    launcher = release_root() / ("viewer-hub.cmd" if sys.platform == "win32" else "viewer-hub.sh")
    if not launcher.is_file():
        return "viewer-hub"
    text = str(launcher)
    command = f'"{text}"' if " " in text else text
    return f"& {command}" if sys.platform == "win32" and command.startswith('"') else command


def contract_files(contracts: list[dict]) -> dict[str, str]:
    """{".sdk/addons/<id>.json": …, ".sdk/addons/<id>.md": …} of the contracts /api/addons/contracts lists."""
    out = {}
    for item in contracts:
        out[f".sdk/addons/{item['id']}.json"] = json.dumps(item, ensure_ascii=False, indent=2) + "\n"
        out[f".sdk/addons/{item['id']}.md"] = contract_markdown(item)
    return out


def contract_markdown(item: dict) -> str:
    """One addon's exports for the AI writing another addon: what to put in ``uses`` and what each call returns."""
    names = [e["name"] for e in item["exports"]]
    base = item["version"].split("-")[0]
    # A builtin module's version is the Hub's: ^0.3.2 would refuse the next Hub minor, so ask for "at least".
    wanted = f">={base}" if item.get("builtin") else f"^{base}"
    kind = (f"mục có sẵn của Viewer Hub, version là version của Hub, luôn có mặt; nên `\"optional\": true` "
            "nếu addon vẫn chạy được khi chưa có dữ liệu") if item.get("builtin") else ""
    lines = [f"# {item['name']} (`{item['id']}` {item['version']}): dữ liệu cho addon khác", "", item.get("summary", ""), "",
             *([f"*{kind}*", ""] if kind else []),
             "Khai trong addon/addon.json, chỉ giữ export cần dùng; `npm run build` tự điền `built`:", "",
             "```json", json.dumps({"uses": {item["id"]: {"version": wanted,
                                                           "exports": names}}}, ensure_ascii=False, indent=2),
             "```", "",
             "Gọi: Python `addon.call(\"" + item["id"] + "\", \"<export>\", {...})`, Node "
             "`await hub.call(\"" + item["id"] + "\", \"<export>\", {...})` (AGENTS.md, mục Dùng dữ liệu addon khác).", ""]
    for export in item["exports"]:
        lines += [f"## `{export['name']}`", "", export["description"], ""]
        props = export["params"].get("properties", {})
        required = set(export["params"].get("required", []))
        if props:
            lines += ["| Tham số | Kiểu | Bắt buộc | Ghi chú |", "|---|---|---|---|"]
            for name, schema in props.items():
                note = schema.get("description", "")
                if "default" in schema:
                    note += f" (mặc định `{json.dumps(schema['default'], ensure_ascii=False)}`)"
                if "enum" in schema:
                    note += f" (một trong {', '.join(f'`{v}`' for v in schema['enum'])})"
                lines.append(f"| `{name}` | {schema['type']} | {'có' if name in required else ''} | {note.strip()} |")
            lines.append("")
        else:
            lines += ["Không có tham số.", ""]
        lines += ["Kết quả (schema `returns`; có thể có thêm trường mới, bỏ qua trường lạ):", "", "```json",
                  json.dumps(export["returns"], ensure_ascii=False, indent=2), "```", "", "Ví dụ:", "", "```json",
                  json.dumps(export["example"], ensure_ascii=False, indent=2), "```", ""]
    return "\n".join(lines)


def build(contracts: list[dict] | None = None) -> bytes:
    """The kit as a zip; ``contracts``: the exports of the addons installed on this Hub (routes.py sdk)."""
    from viewer_hub import __version__

    values = {"{{sdk}}": SDK_VERSION, "{{version}}": __version__, "{{hub}}": hub_command()}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(KIT.rglob("*")):
            rel = path.relative_to(KIT).as_posix()
            if not path.is_file() or any(part.startswith(".") or part in {"node_modules", "__pycache__", "ui"}
                                         for part in rel.split("/")):
                continue
            if rel.startswith("sdk/"):
                rel = "." + rel  # the SDK's own files: hidden, so the addon folder shows only the addon
            if path.suffix in TEXT:
                text = path.read_text(encoding="utf-8")
                for key, value in values.items():
                    text = text.replace(key, value)
                archive.writestr(f"{TOP}/{rel}", text)
            else:
                archive.write(path, f"{TOP}/{rel}")
        archive.writestr(f"{TOP}/.gitignore", GITIGNORE)
        package = Path(__file__).resolve().parents[1]
        for rel in PYTHON_SDK:
            archive.write(package / rel, f"{TOP}/.sdk/python/viewer_hub/{rel}")
        archive.write(package / NODE_SDK, f"{TOP}/.sdk/node/hub_client.mjs")
        for rel, text in contract_files(contracts or []).items():
            archive.writestr(f"{TOP}/{rel}", text)
    return buffer.getvalue()
