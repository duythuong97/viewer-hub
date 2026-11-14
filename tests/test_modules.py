"""The module registry (app/modules.py): every module documents itself for users and for AI, and what lists features
(menu, /help, the MCP gateway) follows the registry, installed addons included."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.test_core import _client_with
from viewer_hub.app import modules

ALL = modules.all_modules()


def _tool_table(guide: str) -> set[str]:
    """Tool names in the guide's "### Tool cho AI" table."""
    match = re.search(r"(?ms)^### Tool cho AI\n(.*?)(?=^#{2,3} |\Z)", guide)
    return set(re.findall(r"(?m)^\| `([a-z0-9_]+)` \|", match.group(1))) if match else set()


def test_every_package_is_a_module():
    assert [m.key for m in ALL] == [p.rsplit(".", 1)[1] for p in modules.PACKAGES]
    assert len({m.prefix for m in ALL}) == len(ALL)


@pytest.mark.parametrize("module", ALL, ids=lambda m: m.key)
def test_module_has_a_user_guide(module):
    assert module.guide and module.guide.is_file(), f"{module.key}: thiếu GUIDE.md"
    text = module.guide.read_text(encoding="utf-8")
    assert text.startswith(f"## {module.label}"), f"{module.key}: GUIDE.md phải bắt đầu bằng '## {module.label}'"
    assert not re.search(r"(?m)^## \d+\.", text), "không đánh số mục; /help tự đánh"


@pytest.mark.parametrize("module", [m for m in ALL if m.mcp], ids=lambda m: m.key)
def test_every_mcp_tool_is_documented(module):
    tools = set(module.mcp.tools())
    documented = _tool_table(module.guide.read_text(encoding="utf-8"))
    assert tools, f"{module.key}: MCP không có tool nào"
    assert tools - documented == set(), f"{module.key}: tool chưa có trong '### Tool cho AI' của GUIDE.md"
    assert documented - tools == set(), f"{module.key}: GUIDE.md ghi tool không còn tồn tại"


def test_every_mcp_has_a_stdio_command():
    import viewer_hub.cli as cli

    assert {m.mcp.command for m in ALL if m.mcp} == set(cli.MCP_BUILTIN)


def test_gateway_registers_every_module_mcp(paths):
    from tests.addon_kit import install
    from viewer_hub.addons.gateway import hub_servers

    install(paths, "example")
    hub = _client_with(paths).application.extensions["hub"]
    names = dict(hub_servers(hub.modules))
    assert names == {f"viewer-{m.mcp.command}": m.mcp.path for m in hub.modules if m.mcp}
    assert {"viewer-codemap", "viewer-search", "viewer-csv", "viewer-monitor", "viewer-example"} <= set(names)
    assert names["viewer-example"] == "/x/example/mcp"


def test_menu_and_guide_follow_the_registry(paths):
    from tests.addon_kit import install

    install(paths, "example")
    client = _client_with(paths)
    nav = [item["key"] for item in client.get("/api/app").get_json()["nav"]]
    assert nav == ["home"] + [m.key for m in ALL] + ["example"]  # addons after the builtin modules
    guide = client.get("/api/help").get_json()["html"]
    assert ". Premium</h2>" not in guide  # nothing locked: no Premium section (the glossary still names it)
    assert "/csv/mcp" in guide and "csv_search" in guide and "codemap_search" in guide
    assert "/x/example/mcp" in guide and "example_greet" in guide
    assert re.search(r'<h2 id="[^"]*">1\. Thuật ngữ</h2>', guide)  # glossary first
    numbers = [int(n) for n in re.findall(r'<h2 id="[^"]*">(\d+)\. ', guide)]
    assert numbers == list(range(1, len(numbers) + 1)) and len(numbers) >= 10


def test_locked_addon_guide_is_anonymous(paths):
    from tests.addon_kit import install

    install(paths, "secret-tool", label="Công cụ bí mật", premium="secret")
    locked = _client_with(paths).get("/api/help").get_json()["html"]
    assert "Công cụ bí mật" not in locked and ". Premium</h2>" in locked
    unlocked = _client_with(paths, premium=True).get("/api/help").get_json()["html"]
    assert "Công cụ bí mật" in unlocked and ". Premium</h2>" not in unlocked
