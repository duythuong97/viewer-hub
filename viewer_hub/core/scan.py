"""The rules of docs/GUIDELINE.md §5 as data: checked on the Hub's own source (packaging/check_security.py) and on
every addon when it is installed (viewer_hub/addons/install.py).

This file holds the patterns themselves, so check_security.py does not scan it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# (pattern, message, Hub files allowed to match: paths relative to viewer_hub/)
PY_RULES = [
    (r"shell\s*=\s*True", "subprocess với shell=True", set()),
    (r"\bos\.system\(|\bos\.popen\(", "os.system / os.popen", set()),
    (r"\b(eval|exec)\(", "eval / exec", set()),
    (r"powershell|cmd(\.exe)?\s*/c", "gọi PowerShell / cmd /c", set()),
    # Network: the Solr export (author-only command, never runs on the user's machine), the addon proxy, which
    # only ever connects to 127.0.0.1 (an addon process the Hub started), and the addon SDK, which only connects to
    # the Hub on 127.0.0.1 (addon.call: one addon reading another through the Hub).
    (r"\b(urllib\.request|requests|httpx|http\.client|socket\.create_connection)\b", "gọi mạng",
     {"fsearch/export_solr.py", "addons/proxy.py", "addons/sdk.py"}),
    # explorer /select (opt-in); the addon runner (python / node of an installed addon; ps / tasklist for the
    # Giám sát page). Argument lists, no shell. (svn runs in the SVN addon, its own process.)
    (r"\bsubprocess\b", "chạy tiến trình", {"fsearch/routes.py", "addons/runner.py"}),
    # Sockets: a daemon addon's admin channel (named pipe / Unix socket of the same OS user, never a TCP port) and
    # the probe for a free local port (binds 127.0.0.1, connects nowhere).
    (r"\bsocket\.socket\(|\\\\\.\\pipe", "socket / named pipe", {"addons/channel.py", "addons/runner.py", "cli.py"}),
    (r"winreg|HKEY_|CurrentVersion\\\\Run", "registry / autostart", set()),
    (r"pickle\.loads?|marshal\.loads?", "giải tuần tự không an toàn", set()),
    (r"yaml\.load\((?!.*Loader=_SafeLoader)", "yaml.load không có SafeLoader", set()),
    (r"base64\.b64decode", "payload base64", set()),
]
WEB_RULES = [
    (r"https?://(fonts\.googleapis|fonts\.gstatic|cdn\.|unpkg|jsdelivr|cdnjs)", "tải từ CDN"),
    (r"\beval\(|new Function\(", "eval trong JS"),
    (r"innerHTML\s*=", "innerHTML (dùng textContent)"),
]
# An addon page that redraws what the Hub already draws above it (kit/AGENTS.md "Hub vẽ sẵn"): its own settings form,
# a "not configured" banner, run / stop / log buttons. Checked on the page bundle (ui/*.js) after decoding the \uXXXX
# escapes a bundler writes for Vietnamese text. Keep in step with UI_ERRORS in kit/sdk/build.mjs (tests check).
_HUB_DRAWS = ("Hub đã vẽ sẵn phần đầu trang addon (trạng thái, Cài đặt, Nhật ký, chạy / dừng) và banner khi thiếu "
              "setting: khai báo `settings` (kèm `required`) trong addon.json, mở hộp Cài đặt bằng useAddon().openSettings()")
UI_RULES = [
    (r"/api/addons\b", "trang addon gọi API quản lý addon của Hub. " + _HUB_DRAWS),
    (r"""["'`]/(settings?|config|configuration)(?:["'`/?])""", "trang addon tự đọc / ghi cấu hình qua API riêng. "
     + _HUB_DRAWS),
    (r"""["'`>]\s*(Cài đặt|Mở cài đặt|Lưu cài đặt|Nhật ký|Xem nhật ký|Xem log|Khởi động lại)\s*["'`<]""",
     "nút / nhãn trùng phần đầu trang của Hub. " + _HUB_DRAWS),
    (r"md-banner(?:(?!md-banner)[\s\S]){0,600}?(cấu hình|cài đặt|thiết lập|chưa nhập|chưa chọn|chưa điền)",
     "banner tự làm về cấu hình. " + _HUB_DRAWS),
]
_ESCAPE = re.compile(r"\\u\{([0-9a-fA-F]+)\}|\\u([0-9a-fA-F]{4})|\\x([0-9a-fA-F]{2})")


def decode_js_escapes(text: str) -> str:
    """"C\\xE0i \\u0111\\u1EB7t" → "Cài đặt": bundlers escape non-ASCII text, rules read it as written."""
    return _ESCAPE.sub(lambda m: chr(int(m.group(1) or m.group(2) or m.group(3), 16)), text)


def scan_ui(rel: str, text: str) -> list[str]:
    """Errors of UI_RULES in one page file (bundle or source)."""
    text = decode_js_escapes(text)
    return [f"{rel}:{line}: {message}" for pattern, message in UI_RULES
            for line in sorted(set(_matches(text, pattern, re.IGNORECASE)))]


# Files that run on their own. A Hub never ships one; an addon may only carry node/node.exe (python.org / nodejs.org
# signed), the runtime of a Node addon on Windows, and, when it runs on .NET (addon.json "runtime": "dotnet"), managed
# assemblies (.dll): the program is published framework-dependent, the machine's own `dotnet` runs it, and no .exe
# (UseAppHost=false) or native library comes with it.
EXECUTABLE = {".pyd", ".so", ".dll", ".exe", ".node", ".dylib", ".ps1", ".bat", ".cmd", ".vbs", ".sh", ".com",
              ".scr", ".msi", ".jar"}
ADDON_RUNTIME = {"app/node/node.exe"}  # the Node an addon may bring (Windows, no Node installed)
# What an addon package holds at its root (docs/addons.md §2): the manifest, the guide, the signature, and four folders.
PACKAGE_FILES = ("addon.json", "GUIDE.md", "signature.json")
PACKAGE_DIRS = ("ui", "app", "assets", "legal")


def is_managed_assembly(path: Path) -> bool:
    """True for a .NET assembly: a PE file whose CLR header (data directory 14) is set. A plain native DLL has none.
    (A mixed-mode C++/CLI assembly has one too: this keeps out ordinary native libraries, it is not a sandbox.)"""
    try:
        with path.open("rb") as file:
            head = file.read(64)
            if head[:2] != b"MZ" or len(head) < 64:
                return False
            offset = int.from_bytes(head[0x3C:0x40], "little")
            file.seek(offset)
            pe = file.read(24 + 240)
    except OSError:
        return False
    if len(pe) < 24 + 96 or pe[:4] != b"PE\0\0":
        return False
    optional = 24
    magic = int.from_bytes(pe[optional:optional + 2], "little")
    if magic not in (0x10B, 0x20B):  # PE32 / PE32+
        return False
    directories = optional + (96 if magic == 0x10B else 112)
    count = int.from_bytes(pe[directories - 4:directories], "little")
    entry = directories + 14 * 8
    if count <= 14 or len(pe) < entry + 8:
        return False
    return int.from_bytes(pe[entry:entry + 4], "little") != 0 and int.from_bytes(pe[entry + 4:entry + 8], "little") != 0


def addon_runtime(folder: Path) -> str:
    """The "runtime" of the addon.json in an unpacked addon ("" when unreadable: the manifest check reports that)."""
    try:
        data = json.loads((folder / "addon.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(data.get("runtime") or "") if isinstance(data, dict) else ""

# What an addon process may do but the admin should know about (shown at install, never refused): the Hub rules
# that only allow-listed Hub files may break.
_ADDON_NOTES_PY = {"gọi mạng", "chạy tiến trình", "socket / named pipe", "payload base64"}
_ADDON_JS_ERRORS = [
    (r"shell\s*:\s*true", "child_process với shell: true"),
]
_ADDON_JS_NOTES = [  # a bundle names these for many reasons (a deny-list of shells, a dependency's fast path)
    (r"\bchild_process\b", "chạy tiến trình (child_process)"),
    (r"\beval\(|new Function\(", "eval trong JS"),
    (r"powershell|cmd(\.exe)?\s*/c", "nhắc tới PowerShell / cmd"),
]


def line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _matches(text: str, pattern: str, flags: int = 0) -> list[int]:
    lines = text.splitlines()
    out = []
    for match in re.finditer(pattern, text, flags):
        line = line_of(text, match.start())
        if "noqa: security" not in (lines[line - 1] if line <= len(lines) else ""):
            out.append(line)
    return out


def layout_errors(folder: Path) -> list[str]:
    """What stands at the package root outside the layout (PACKAGE_FILES, PACKAGE_DIRS): each name is one error."""
    errors = []
    for entry in sorted(folder.iterdir(), key=lambda p: p.name):
        if entry.is_dir() and entry.name in PACKAGE_DIRS or entry.is_file() and entry.name in PACKAGE_FILES:
            continue
        errors.append(f"{entry.name}{'/' if entry.is_dir() else ''}: không thuộc cấu trúc gói addon")
    if errors:
        errors.append("gốc gói chỉ có addon.json, GUIDE.md, signature.json và thư mục " + ", ".join(f"{d}/" for d in PACKAGE_DIRS)
                      + " (chương trình nằm trong app/)")
    return errors


def scan_addon(folder: Path) -> tuple[list[str], list[str]]:
    """(errors, notes) for an unpacked addon. Any error refuses the install; notes are shown to the admin."""
    errors: list[str] = layout_errors(folder)
    notes: list[str] = []
    dotnet = addon_runtime(folder) == "dotnet"
    assemblies = 0
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        rel = path.relative_to(folder).as_posix()
        suffix = path.suffix.lower()
        top = rel.split("/", 1)[0]
        if dotnet and suffix == ".dll" and top == "app" and is_managed_assembly(path):
            assemblies += 1
            continue
        if suffix in EXECUTABLE and rel not in ADDON_RUNTIME:
            errors.append(f"{rel}: file thực thi / native" + (" (addon .NET chỉ được kèm assembly .NET)" if dotnet and suffix == ".dll" else ""))
            continue
        if suffix not in {".py", ".js", ".mjs", ".cjs", ".css", ".html"} or top in ("assets", "legal"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if suffix == ".py":
            for pattern, message, _allowed in PY_RULES:
                for line in _matches(text, pattern, re.IGNORECASE):
                    (notes if message in _ADDON_NOTES_PY else errors).append(f"{rel}:{line}: {message}")
        elif top == "ui" or suffix in {".css", ".html"}:
            for pattern, message in WEB_RULES:
                errors += [f"{rel}:{line}: {message}" for line in _matches(text, pattern)]
            if suffix in {".js", ".mjs"}:
                errors += scan_ui(rel, text)
        else:  # the addon's own Node program
            for pattern, message in _ADDON_JS_ERRORS:
                errors += [f"{rel}:{line}: {message}" for line in _matches(text, pattern, re.IGNORECASE)]
            for pattern, message in _ADDON_JS_NOTES:
                if _matches(text, pattern):
                    notes.append(f"{rel}: {message}")
    if assemblies:  # compiled code cannot be read by the rules above: the admin decides whether to trust the author
        notes.append(f"chạy chương trình .NET đã biên dịch ({assemblies} assembly): Viewer Hub không đọc được nội dung, "
                     "chỉ cài khi tin người làm addon (nên là addon đã ký)")
    return errors, notes
