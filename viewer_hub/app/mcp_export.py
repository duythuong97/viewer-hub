"""Connect GitHub Copilot to this Hub without hand-writing config: one MCP config block and one skill per MCP server.

* ``config``: the ``mcp.json`` VS Code reads (``.vscode/mcp.json`` of a folder, or the user-level file). URLs use the
  address of the request, so the port is the one the Hub is running on right now.
* ``skills_zip``: ``viewer-<command>/SKILL.md`` for each server, to unpack into ``.github/skills/``. A skill's
  description is all an agent keeps in context until the task needs it; the tool table comes from the module's
  ``GUIDE.md`` ("### Tool cho AI"), so a new module or addon gets its skill with no extra work.

Both read only the module declarations (the same ``hub.modules`` as /api/mcp), so a locked premium feature is never named.
"""
from __future__ import annotations

import io
import json
import re
import zipfile

# In every SKILL.md the Hub writes: how folder sync (copilot_sync.py) tells its skills from the user's own.
MARKER = "<!-- viewer-hub: tự sinh, sửa ở đây sẽ bị ghi đè khi Viewer Hub đồng bộ -->"
_TOOLS = re.compile(r"(?ms)^### Tool cho AI\s*\n(.*?)(?=^#{2,3} |\Z)")
_NAME = re.compile(r"[^a-z0-9-]+")


def server_name(module) -> str:
    """The key in mcp.json and the skill name: the builtin MCP name, e.g. ``viewer-csv``."""
    return module.mcp.bridge_name


def config(modules, base_url: str) -> dict:
    """mcp.json for VS Code / GitHub Copilot: every MCP server of this Hub over HTTP."""
    base = base_url.rstrip("/")
    return {"servers": {server_name(m): {"type": "http", "url": base + m.mcp.path} for m in modules if m.mcp}}


def tool_section(module) -> str:
    """The "Tool cho AI" part of the module's guide, or a list of tool names when the guide has none."""
    if module.guide and module.guide.is_file():
        found = _TOOLS.search(module.guide.read_text(encoding="utf-8"))
        if found and found.group(1).strip():
            return found.group(1).strip()
    return "\n".join(f"- `{name}`" for name in module.mcp.tools())


def skill(module) -> str:
    """SKILL.md of one MCP server. The description says when to load it, since that is all the agent sees up front."""
    name = skill_name(module)
    scope = f" Phạm vi: {module.mcp.scope}." if module.mcp.scope else ""
    description = f"{module.summary.rstrip('.')}.{scope} Dùng khi cần tra cứu dữ liệu này qua MCP `{server_name(module)}`."
    return (
        f"---\nname: {name}\ndescription: {json.dumps(description, ensure_ascii=False)}\n---\n{MARKER}\n\n"
        f"# {module.label}\n\n"
        f"{module.summary.rstrip('.')}. Dữ liệu chạy trên máy người dùng qua Viewer Hub; MCP `{server_name(module)}` "
        f"chỉ **đọc**.{scope}\n\n"
        f"Chỉ gọi các tool dưới đây. Nếu tool báo lỗi kết nối thì Viewer Hub chưa chạy: nhờ người dùng mở nó, "
        f"đừng đoán dữ liệu.\n\n## Tool\n\n{tool_section(module)}\n"
    )


def skill_name(module) -> str:
    return _NAME.sub("-", server_name(module).lower()).strip("-")


def skills(modules) -> dict[str, str]:
    """``{skill folder name: SKILL.md}`` for every MCP server."""
    return {skill_name(module): skill(module) for module in modules if module.mcp}


def skills_zip(modules) -> bytes:
    """A zip of ``<name>/SKILL.md`` for every MCP server, ready to unpack into ``.github/skills/``."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in skills(modules).items():
            archive.writestr(f"{name}/SKILL.md", text)
    return buffer.getvalue()
