"""Giám sát: what AI does with the Hub's MCP servers (builtin and addons) and how the addons are doing."""
from pathlib import Path

from viewer_hub.app.modules import McpServer, Module


def _register(app) -> None:
    from viewer_hub.monitor.routes import bp

    app.register_blueprint(bp, url_prefix="/monitor")


def _tools() -> list[str]:
    from viewer_hub.monitor.mcp import TOOLS

    return [tool["name"] for tool in TOOLS]


def _stat(hub) -> str:
    from viewer_hub.core.monitor import Reader

    with Reader(hub.paths.home) as reader:
        return f"{reader.calls_today()} lời gọi hôm nay"


MODULE = Module(
    key="monitor", label="Giám sát", icon="monitoring", prefix="/monitor",
    summary="Xem AI gọi MCP nào (cả addon), lỗi, độ chậm, token trả về và sức khoẻ của addon",
    register=_register, guide=Path(__file__).with_name("GUIDE.md"),
    mcp=McpServer("/monitor/mcp", "monitor", scope="chỉ số liệu giám sát (tên tool, thời gian, lỗi), không có nội dung",
                  tools=_tools),
    stat=_stat,
)
