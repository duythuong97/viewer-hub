"""addon.json: what an addon is and how to run it (docs/addons.md §3). Reading and checking only.

    {"schema": "viewer-hub/addon", "schemaVersion": 1, "sdk": "1",
     "id": "jira-reader", "name": "Jira Reader", "version": "0.1.0",
     "runtime": "python", "entry": "main.py", "lifecycle": "managed",
     "menu": {"label": "Jira", "icon": "bug_report", "summary": "Đọc ticket Jira cho AI và trên web"},
     "ui": {"script": "ui/ui.js", "style": "ui/ui.css"},
     "mcp": {"command": "jira", "scope": "chỉ project đã thêm", "tools": ["jira_search", "jira_read"]},
     "settings": [{"key": "baseUrl", "label": "Địa chỉ Jira", "type": "text"}],
     "premium": null}

An ``external`` addon runs nothing: its program (any language, .NET, Java…) is installed and started by the user
and serves the managed HTTP contract (/health, /api/*, /mcp) on 127.0.0.1; addon.json has ``"service": {"port": N}``
instead of runtime / entry, and the Hub adds a "port" setting (default N) so the user can point it elsewhere.

A ``daemon`` addon also has ``commands`` (init / start / status, runner.py), may declare ``provides: ["mcp-servers"]``
(it gathers MCP servers: the Hub registers its own there, gateway.py) and ``minNode``. Its settings may carry ``arg``
and ``on``: passed to that command as ``<arg> <value>``.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA = "viewer-hub/addon"
SCHEMA_VERSION = 1
SDK_VERSION = "1"  # major version of the addon SDK (sdk.py, web/src/sdk): bump on a breaking change
MANIFEST = "addon.json"
GUIDE = "GUIDE.md"
ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,40}$")
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+([.-][0-9A-Za-z.-]+)?$")
ARG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._=-]*$|^--?[A-Za-z0-9][A-Za-z0-9-]*$")
FILE_RE = re.compile(r"^[A-Za-z0-9._-]+$")
UI_RE = re.compile(r"^ui/[A-Za-z0-9._-]+\.(js|css)$")
ICON_RE = re.compile(r"^[a-z0-9_]{1,40}$")
COMMAND_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
TOOL_RE = re.compile(r"^[a-z0-9_]{1,64}$")
COMMANDS = ("init", "start", "status")
SETTING_TYPES = ("text", "folder", "list", "switch", "select")
LIFECYCLES = ("managed", "daemon", "external")
PORT_SETTING = "port"  # external: the setting the Hub adds (the program's port on 127.0.0.1)
RUNTIMES = {"python": re.compile(r"^[A-Za-z0-9._-]+\.py$"), "node": re.compile(r"^[A-Za-z0-9._-]+\.m?js$")}


class AddonError(ValueError):
    """addon.json is missing or does not follow the schema."""


@dataclass(frozen=True)
class Setting:
    key: str
    label: str
    type: str = "text"
    options: tuple[str, ...] = ()    # select
    default: object = None
    help: str = ""
    arg: str = ""                    # daemon: passed to the `on` command as <arg> <value>
    on: str = "init"
    required: bool = False           # the page shows "fill this in first" until it has a value

    def public(self) -> dict:
        return {"key": self.key, "label": self.label, "type": self.type, "options": list(self.options),
                "default": self.default, "help": self.help, "required": self.required}


@dataclass(frozen=True)
class Mcp:
    command: str
    scope: str = ""
    tools: tuple[str, ...] = ()


@dataclass(frozen=True)
class Addon:
    id: str
    name: str
    version: str
    runtime: str
    entry: str
    lifecycle: str
    label: str
    icon: str
    summary: str
    script: str = ""                 # ui/ui.js; "" = the Hub's own page (status, settings, guide)
    style: str = ""
    mcp: Mcp | None = None
    settings: tuple[Setting, ...] = ()
    premium: str | None = None
    commands: dict[str, tuple[str, ...]] = field(default_factory=dict)
    provides: tuple[str, ...] = ()
    min_node: str = ""
    port: int = 0                    # external: the program's default port on 127.0.0.1
    folder: Path = field(default=Path("."), compare=False)

    @property
    def prefix(self) -> str:
        return f"/x/{self.id}"

    @property
    def main(self) -> Path:
        return self.folder / self.entry

    @property
    def guide(self) -> Path:
        return self.folder / GUIDE

    @property
    def daemon(self) -> bool:
        return self.lifecycle == "daemon"

    @property
    def external(self) -> bool:
        return self.lifecycle == "external"


def _args(value, where: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(a, str) and ARG_RE.match(a) for a in value):
        raise AddonError(f"{where}: cần danh sách tham số đơn giản (chữ, số, -, ., =)")
    return tuple(value)


def _text(data: dict, key: str, where: str = "", required: bool = True, limit: int = 200) -> str:
    value = data.get(key)
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > limit:
        raise AddonError(f"thiếu {where}{key} (chuỗi, tối đa {limit} ký tự)")
    return value.strip()


def _settings(raw_list, lifecycle: str) -> tuple[Setting, ...]:
    if not isinstance(raw_list, list):
        raise AddonError("settings phải là danh sách")
    out, keys = [], set()
    for raw in raw_list:
        if not isinstance(raw, dict):
            raise AddonError("mỗi setting là một object")
        key = _text(raw, "key", "setting.")
        if not re.match(r"^[A-Za-z][A-Za-z0-9_]{0,40}$", key) or key in keys:
            raise AddonError(f"setting {key}: key không hợp lệ hoặc bị trùng")
        keys.add(key)
        kind = raw.get("type") or "text"
        if kind not in SETTING_TYPES:
            raise AddonError(f"setting {key}: type phải là " + "/".join(SETTING_TYPES))
        options = raw.get("options") or []
        if kind == "select" and (not isinstance(options, list) or not options
                                 or not all(isinstance(o, str) for o in options)):
            raise AddonError(f"setting {key}: select cần options (danh sách chuỗi)")
        arg = raw.get("arg") or ""
        if arg and (lifecycle != "daemon" or not isinstance(arg, str) or not ARG_RE.match(arg)):
            raise AddonError(f"setting {key}: arg chỉ dùng cho daemon, dạng --ten")
        on = raw.get("on") or "init"
        if on not in COMMANDS:
            raise AddonError(f"setting {key}: on phải là " + "/".join(COMMANDS))
        required = raw.get("required", False)
        if not isinstance(required, bool):
            raise AddonError(f"setting {key}: required là true / false")
        out.append(Setting(key, _text(raw, "label", "setting."), kind, tuple(options), raw.get("default"),
                           _text(raw, "help", "setting.", required=False, limit=400), arg, on, required))
    return tuple(out)


def parse(data: object, folder: Path = Path(".")) -> Addon:
    """A checked Addon from the decoded addon.json, or AddonError naming the first problem."""
    if not isinstance(data, dict):
        raise AddonError(f"{MANIFEST} phải là một object")
    if data.get("schema") != SCHEMA or data.get("schemaVersion") != SCHEMA_VERSION:
        raise AddonError(f"{MANIFEST} không phải {SCHEMA} v{SCHEMA_VERSION}")
    if str(data.get("sdk")) != SDK_VERSION:
        raise AddonError(f"addon cần SDK {data.get('sdk')!r}, Viewer Hub này có SDK {SDK_VERSION}")
    addon_id = data.get("id")
    if not isinstance(addon_id, str) or not ID_RE.match(addon_id):
        raise AddonError("id phải là chữ thường, số, dấu - (vd. jira-reader)")
    version = data.get("version")
    if not isinstance(version, str) or not VERSION_RE.match(version):
        raise AddonError("version phải dạng 1.2.3")
    lifecycle = data.get("lifecycle")
    if lifecycle not in LIFECYCLES:
        raise AddonError("lifecycle phải là managed, daemon hoặc external")
    port = 0
    if lifecycle == "external":
        if data.get("runtime") or data.get("entry"):
            raise AddonError("addon external không có runtime / entry: chương trình do người dùng tự chạy")
        service = data.get("service")
        port = service.get("port") if isinstance(service, dict) else None
        if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535:
            raise AddonError('external cần "service": {"port": <cổng 1024-65535 trên 127.0.0.1>}')
        runtime, entry = "external", ""
    else:
        runtime = data.get("runtime")
        if runtime not in RUNTIMES:
            raise AddonError("runtime phải là python hoặc node")
        entry = data.get("entry")
        if not isinstance(entry, str) or not RUNTIMES[runtime].match(entry):
            raise AddonError(f"entry phải là một file {'.py' if runtime == 'python' else '.mjs/.js'} ở thư mục gốc addon")
        if data.get("service"):
            raise AddonError("service chỉ dành cho addon external")
    menu = data.get("menu")
    if not isinstance(menu, dict):
        raise AddonError("thiếu menu (label, icon, summary)")
    icon = _text(menu, "icon", "menu.", limit=40)
    if not ICON_RE.match(icon):
        raise AddonError("menu.icon phải là tên Material Symbols (vd. bug_report)")
    ui = data.get("ui") or {}
    if not isinstance(ui, dict):
        raise AddonError("ui phải là object {script, style}")
    script, style = ui.get("script") or "", ui.get("style") or ""
    for name, value, ext in (("script", script, ".js"), ("style", style, ".css")):
        if value and (not isinstance(value, str) or not UI_RE.match(value) or not value.endswith(ext)):
            raise AddonError(f"ui.{name} phải là file {ext} trong thư mục ui/ (vd. ui/ui{ext})")
    if style and not script:
        raise AddonError("ui.style cần ui.script")
    mcp = None
    if data.get("mcp"):
        raw = data["mcp"]
        if lifecycle == "daemon" or not isinstance(raw, dict):
            raise AddonError("mcp chỉ dành cho addon managed / external: {command, scope, tools}")
        command = _text(raw, "command", "mcp.", limit=30)
        tools = raw.get("tools") or []
        if not COMMAND_RE.match(command):
            raise AddonError("mcp.command phải là chữ thường, số, dấu -")
        if not isinstance(tools, list) or not tools or not all(isinstance(t, str) and TOOL_RE.match(t) for t in tools):
            raise AddonError("mcp.tools phải là danh sách tên tool (chữ thường, số, _)")
        mcp = Mcp(command, _text(raw, "scope", "mcp.", required=False), tuple(tools))
    premium = data.get("premium")
    if premium is not None and (not isinstance(premium, str) or not ID_RE.match(premium)):
        raise AddonError("premium phải là null hoặc tên tính năng (chữ thường, số, -)")
    commands: dict[str, tuple[str, ...]] = {}
    if lifecycle == "daemon":
        raw = data.get("commands")
        if not isinstance(raw, dict) or any(name not in raw for name in COMMANDS):
            raise AddonError("daemon cần commands: " + ", ".join(COMMANDS))
        commands = {name: _args(raw[name], f"commands.{name}") for name in COMMANDS}
    elif data.get("commands"):
        raise AddonError("commands chỉ dành cho addon daemon")
    provides = data.get("provides") or []
    if not isinstance(provides, list) or not all(isinstance(p, str) for p in provides):
        raise AddonError("provides phải là danh sách chuỗi")
    min_node = str(data.get("minNode") or "")
    if min_node and not re.match(r"^\d+(\.\d+){0,2}$", min_node):
        raise AddonError("minNode phải dạng 22.13")
    settings = _settings(data.get("settings") or [], lifecycle)
    if lifecycle == "external" and not any(s.key == PORT_SETTING for s in settings):
        settings = (Setting(PORT_SETTING, "Cổng của chương trình", "text", default=str(port),
                            help=f"Chương trình chạy ở http://127.0.0.1:<cổng> (mặc định {port})"), *settings)
    return Addon(addon_id, _text(data, "name", limit=80), version, runtime, entry, lifecycle,
                 _text(menu, "label", "menu.", limit=40), icon, _text(menu, "summary", "menu.", limit=300),
                 script, style, mcp, settings, premium, commands, tuple(provides), min_node, port, folder)


def read(folder: Path) -> dict:
    try:
        return json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    except OSError as exc:
        raise AddonError(f"không đọc được {MANIFEST}: {exc}") from exc
    except ValueError as exc:
        raise AddonError(f"{MANIFEST} không phải JSON: {exc}") from exc


def load(folder: Path) -> Addon:
    """The addon in an unpacked folder, with its entry and ui files present."""
    addon = parse(read(folder), folder)
    if folder.name != addon.id:
        raise AddonError(f"thư mục {folder.name} phải trùng id {addon.id}")
    for name in (addon.entry, addon.script, addon.style):
        if name and not (folder / name).is_file():
            raise AddonError(f"thiếu {name}")
    return addon
