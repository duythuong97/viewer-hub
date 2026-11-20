"""Source layout rules from AGENTS.md that no other check enforces: layers, UI building blocks, language, repo commands.

Each rule reads the source as text, so it runs in milliseconds and needs no extra tool. A failure names the file, the
line and the rule; fix the code, or (rarely) extend the allow-list here with a comment saying why.
"""
from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "viewer_hub"
WEB = ROOT / "web" / "src"

_VIETNAMESE = re.compile(r"[ăâđêôơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]", re.IGNORECASE)
_QUOTED = re.compile(r"\"[^\"]*\"|“[^”]*”|`[^`]*`|'[^']*'|\([^)]*\)")


def _rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _python_files():
    return sorted(path for path in APP.rglob("*.py") if "__pycache__" not in path.parts)


def _web_files():
    return sorted(path for path in WEB.rglob("*") if path.suffix in {".js", ".jsx", ".mjs"} and "tests" not in path.parts)


def _is_vietnamese(text: str) -> bool:
    """Prose written in Vietnamese. Quoted UI terms ("Luồng chạy", `Chờ duyệt`) are allowed inside English text."""
    words = _QUOTED.sub(" ", text).split()
    if len(words) < 4:
        return False
    return sum(1 for word in words if _VIETNAMESE.search(word)) / len(words) > 0.3


# --------------------------------------------------------------------------- layers


def test_stores_do_not_import_flask():
    """store.py holds data access only (AGENTS.md "Cấu trúc"): it is used by MCP stdio servers that have no Flask app."""
    bad = []
    for path in APP.glob("*/store.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) else []
            bad += [f"{_rel(path)}:{node.lineno}: imports {name}" for name in names if name.split(".")[0] == "flask"]
    assert not bad, "store.py must not import Flask:\n" + "\n".join(bad)


def test_core_does_not_import_feature_modules():
    """core/ is shared by every module and addon: it must not depend on one of them."""
    from viewer_hub.app.modules import PACKAGES

    features = {name.split(".")[1] for name in PACKAGES}
    bad = []
    for path in (APP / "core").rglob("*.py"):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = re.match(r"\s*(?:from|import)\s+viewer_hub\.(\w+)", line)
            if match and match.group(1) in features:
                bad.append(f"{_rel(path)}:{number}: {line.strip()}")
    assert not bad, "core/ imports a feature module:\n" + "\n".join(bad)


# --------------------------------------------------------------------------- web UI

# Module pages build on the shared design system and app frame only (AGENTS.md step 6). Packages beyond React are
# listed here on purpose: each one is a dependency every page could pull in.
_WEB_PACKAGES = {"react", "react-dom", "react-dom/client", "@xyflow/react", "mermaid"}
_SHARED = ("md/", "app/", "sdk/")


def test_module_pages_use_the_shared_ui_only():
    imports = re.compile(r"""^\s*(?:import|export)\b[^'"]*?from\s+["']([^"']+)["']|^\s*import\s+["']([^"']+)["']""", re.M)
    lazy = re.compile(r"""import\(\s*["']([^"']+)["']\s*\)""")
    bad = []
    for path in _web_files():
        rel = path.relative_to(WEB).as_posix()
        if not rel.startswith("modules/"):
            continue
        own = (WEB / "modules" / rel.split("/")[1]).resolve()
        text = path.read_text(encoding="utf-8")
        specs = [(m.start(), m.group(1) or m.group(2)) for m in imports.finditer(text)]
        specs += [(m.start(), m.group(1)) for m in lazy.finditer(text)]
        for start, spec in specs:
            line = text.count("\n", 0, start) + 1
            if not spec.startswith("."):
                package = spec if spec in _WEB_PACKAGES else "/".join(spec.split("/")[:2 if spec.startswith("@") else 1])
                if package not in _WEB_PACKAGES and not spec.startswith("@fontsource/"):
                    bad.append(f"web/src/{rel}:{line}: package {spec!r} (add it to _WEB_PACKAGES if it is meant for pages)")
                continue
            target = (path.parent / spec).resolve()
            if target.is_relative_to(own):
                continue
            shared = target.relative_to(WEB.resolve()).as_posix() if target.is_relative_to(WEB.resolve()) else ""
            if not shared.startswith(_SHARED):
                bad.append(f"web/src/{rel}:{line}: {spec} (a page imports another module's files; move it to app/ or md/)")
    assert not bad, "module page imports outside its folder and the shared UI:\n" + "\n".join(bad)


# Existing HTML injections: each renders HTML the server built and escaped (guides from Markdown, search highlights).
_HTML_ALLOWED = {"app/pages/Help.jsx", "app/pages/Addon.jsx", "modules/fsearch/Results.jsx"}


def test_no_html_injection_with_data():
    """Data is drawn with JSX, never as HTML (AGENTS.md "Giao diện")."""
    bad = []
    for path in _web_files():
        rel = path.relative_to(WEB).as_posix()
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"dangerouslySetInnerHTML|\.innerHTML\s*=|insertAdjacentHTML|document\.write\(", text):
            if rel not in _HTML_ALLOWED:
                bad.append(f"web/src/{rel}:{text.count(chr(10), 0, match.start()) + 1}: {match.group(0)}")
    assert not bad, "HTML injection in the UI (draw data with JSX):\n" + "\n".join(bad)


def test_one_page_template_and_no_loose_scripts():
    """React draws every page: one template, and static/ holds only the build output (AGENTS.md "Giao diện")."""
    templates = sorted(p.name for p in (APP / "templates").iterdir() if p.is_file())
    assert templates == ["app.html"], f"only templates/app.html is allowed, found {templates}"
    loose = [_rel(p) for p in (APP / "static").rglob("*")
             if p.is_file() and "dist" not in p.relative_to(APP / "static").parts and p.suffix in {".js", ".mjs", ".css", ".html"}]
    assert not loose, f"files outside static/dist (put the code in web/src): {loose}"


def test_every_module_page_has_a_folder():
    from viewer_hub.app.modules import PACKAGES

    keys = {name.split(".")[1] for name in PACKAGES}
    folders = {path.name for path in (WEB / "modules").iterdir() if path.is_dir()}
    assert keys <= folders, f"modules without web/src/modules/<key>/index.jsx: {sorted(keys - folders)}"
    assert all((WEB / "modules" / key / "index.jsx").is_file() for key in keys)


# --------------------------------------------------------------------------- language


def test_python_comments_and_docstrings_are_english():
    """Code, comments and docstrings are English; Vietnamese is for the UI and GUIDE.md (AGENTS.md "Ngôn ngữ")."""
    bad = []
    for path in _python_files():
        source = path.read_text(encoding="utf-8")
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT and _is_vietnamese(token.string.lstrip("#")):
                bad.append(f"{_rel(path)}:{token.start[0]}: {token.string.strip()[:80]}")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc and _is_vietnamese(doc.split("\n\n")[0]):
                    bad.append(f"{_rel(path)}:{getattr(node, 'lineno', 1)}: docstring {doc.strip()[:60]!r}")
    assert not bad, "Vietnamese comments / docstrings (write them in English):\n" + "\n".join(bad)


def test_web_comments_are_english():
    comment = re.compile(r"(?<![:\"'`\w])//([^\n]*)|/\*([\s\S]*?)\*/")
    bad = []
    for path in [*_web_files(), *WEB.rglob("*.css")]:
        text = path.read_text(encoding="utf-8")
        for match in comment.finditer(text):
            body = match.group(1) or match.group(2) or ""
            if _is_vietnamese(body):
                bad.append(f"{_rel(path)}:{text.count(chr(10), 0, match.start()) + 1}: {body.strip()[:80]}")
    assert not bad, "Vietnamese comments in web/src (write them in English):\n" + "\n".join(bad)


def test_language_check_reads_quoted_terms_as_english():
    assert not _is_vietnamese('the "Luồng chạy" view keeps its options (Mức chi tiết, Cách vẽ) on the right')
    assert _is_vietnamese("bảng nào được ghi thì đứng trước trong danh sách")


# --------------------------------------------------------------------------- repo commands


def test_every_just_recipe_is_documented_and_grouped():
    """Repo commands live in the justfile, each with a one-line comment and a group (AGENTS.md "Kiểm tra")."""
    lines = (ROOT / "justfile").read_text(encoding="utf-8").splitlines()
    bad = []
    for number, line in enumerate(lines):
        if not re.match(r"^[a-z][\w-]*(\s+[^:=]*)?:(\s|$)", line) or line.startswith(("set ", "export ")):
            continue
        above = [lines[i] for i in range(number - 1, -1, -1)][:3]
        attributes = [item for item in above if item.startswith("[")]
        if "[private]" in attributes:
            continue
        has_group = any(item.startswith("[group(") for item in attributes)
        comment = next((item for item in above if not item.startswith("[")), "")
        if not has_group or not comment.startswith("# "):
            bad.append(f"justfile:{number + 1}: {line.split(':')[0]}")
    assert not bad, "recipes without a `# comment` line and a [group(...)]:\n" + "\n".join(bad)


# Launchers shipped inside the release (they start the app on the user's machine); everything else is a just recipe.
_SCRIPTS_ALLOWED = {"packaging/unix/viewer-hub.sh", "packaging/windows/launcher/viewer-hub.cmd",
                    "packaging/windows/setup.cmd", "packaging/windows/viewer-hub.cmd"}


def test_no_loose_shell_scripts():
    scripts = {_rel(p) for ext in ("*.sh", "*.cmd", "*.bat", "*.ps1") for p in ROOT.rglob(ext)
               if not {"node_modules", ".venv", "var", "dist", "build", ".git"} & set(p.relative_to(ROOT).parts)}
    extra = sorted(scripts - _SCRIPTS_ALLOWED)
    assert not extra, f"add a just recipe instead of a script: {extra}"
