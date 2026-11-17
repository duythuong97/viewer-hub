"""The rules of docs/GUIDELINE.md §5 as data: checked on the Hub's own source (packaging/check_security.py) and on
every addon when it is installed (viewer_hub/addons/install.py).

This file holds the patterns themselves, so check_security.py does not scan it.
"""
from __future__ import annotations

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
# signed), the runtime of a Node addon on Windows.
EXECUTABLE = {".pyd", ".so", ".dll", ".exe", ".node", ".dylib", ".ps1", ".bat", ".cmd", ".vbs", ".sh", ".com",
              ".scr", ".msi", ".jar"}
ADDON_RUNTIME = {"node/node.exe"}

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


def scan_addon(folder: Path) -> tuple[list[str], list[str]]:
    """(errors, notes) for an unpacked addon. Any error refuses the install; notes are shown to the admin."""
    errors: list[str] = []
    notes: list[str] = []
    for path in sorted(p for p in folder.rglob("*") if p.is_file()):
        rel = path.relative_to(folder).as_posix()
        suffix = path.suffix.lower()
        if suffix in EXECUTABLE and rel not in ADDON_RUNTIME:
            errors.append(f"{rel}: file thực thi / native")
            continue
        if suffix not in {".py", ".js", ".mjs", ".cjs", ".css", ".html"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if suffix == ".py":
            for pattern, message, _allowed in PY_RULES:
                for line in _matches(text, pattern, re.IGNORECASE):
                    (notes if message in _ADDON_NOTES_PY else errors).append(f"{rel}:{line}: {message}")
        elif rel.startswith("ui/") or suffix in {".css", ".html"}:
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
    return errors, notes
