"""User guide (/help, data from GET /api/help): the shared parts (help/parts/) plus each enabled module's GUIDE.md, in menu order.

    intro.md            title, {{modules}} table, then (after glossary.md) opening the app, main screen, search, filters
    glossary.md         Viewer Hub's own words, first section; "[if:<key>]" lines only for enabled modules
    <module>/GUIDE.md   one "## <label>" section per enabled module, with its "### Tool cho AI" table
    addons.md           what addons are: install / remove, trust, the three kinds, their page, troubles
    premium.md          only when a premium feature is locked (never names it)
    outro.md            settings, troubleshooting
    ai.md               {{mcp}}: the MCP address of every enabled module

Sections ("## …") are numbered here, so module guides carry no numbers. See AGENTS.md for what a module guide holds.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import markdown
PARTS = Path(__file__).with_name("parts")
_ICON = re.compile(r"\[icon:([a-z0-9_]+)\]")
_SECTION = re.compile(r"(?m)^## (?!\d+\. )")
_IF = re.compile(r"(?m)^\[if:([a-z0-9_-]+)\](.*\n)")  # glossary line shown only for that module key


def compose(modules, locked: bool) -> str:
    """The whole guide as markdown, for the modules of this build."""
    def part(name: str) -> str:
        return (PARTS / name).read_text(encoding="utf-8").strip() + "\n"

    table = "| Mục | Dùng để |\n|---|---|\n" + "".join(f"| **{m.label}** | {m.summary} |\n" for m in modules)
    servers = [(m, m.mcp) for m in modules if m.mcp]
    mcp = "| Dữ liệu | Địa chỉ MCP (HTTP) | Lệnh (stdio) |\n|---|---|---|\n" + "".join(
        f"| {m.label}{f' ({s.scope})' if s.scope else ''} | `http://127.0.0.1:<cổng>{s.path}` | `viewer-hub mcp {s.command}` |\n"
        for m, s in servers)
    # The glossary is the first numbered section: right after the intro's opening, before its own "## …" sections.
    intro = part("intro.md").replace("{{modules}}", table.strip())
    head, _, rest = intro.partition("\n## ")
    shown = {m.key for m in modules}
    glossary = _IF.sub(lambda m: m.group(2) if m.group(1) in shown else "", part("glossary.md"))
    pieces = [head.rstrip() + "\n", glossary, "## " + rest]
    pieces += [m.guide.read_text(encoding="utf-8").strip() + "\n" for m in modules if m.guide and m.guide.is_file()]
    pieces.append(part("addons.md"))
    if locked:
        pieces.append(part("premium.md"))
    pieces.append(part("outro.md"))
    if servers:
        pieces.append(part("ai.md").replace("{{mcp}}", mcp.strip()))
    text = "\n---\n\n".join(pieces)
    counter = iter(range(1, 1000))
    return _SECTION.sub(lambda _m: f"## {next(counter)}. ", text)


@lru_cache(maxsize=4)
def _render(text: str) -> tuple[str, str, str]:
    md = markdown.Markdown(extensions=["tables", "fenced_code", "toc", "sane_lists"],
                           extension_configs={"toc": {"toc_depth": "2-2"}})
    # The guide is our own files, not user content; icons become Material Symbols.
    title = "Hướng dẫn sử dụng"
    if text.startswith("# "):  # the "# …" line becomes the page header (PageHeader in web/src/app/ui.jsx), not a second title
        first, _, text = text.partition("\n")
        title = first[2:].strip() or title
    html = md.convert(text)
    html = _ICON.sub(lambda m: f'<md-icon class="md-help__icon" aria-hidden="true">{m.group(1)}</md-icon>', html)
    return html, md.toc, title


def render(modules, locked: bool) -> tuple[str, str, str]:
    """(html, toc html, title) of the guide for this build; served by GET /api/help (app/portal.py)."""
    return _render(compose(modules, locked))


def render_markdown(text: str) -> str:
    """One guide section (an addon's GUIDE.md on its own page) as HTML, icons included."""
    return _render(text.strip() + "\n")[0]
