"""CSV module: upload a CSV, look rows up by column filters."""
from pathlib import Path

from viewer_hub.app.modules import McpServer, Module


def _register(app) -> None:
    from viewer_hub.csv.routes import bp

    app.register_blueprint(bp, url_prefix="/csv")


def _tools() -> list[str]:
    from viewer_hub.csv.mcp import TOOLS

    return [tool["name"] for tool in TOOLS]


MODULE = Module(
    key="csv", label="CSV", icon="table_view", prefix="/csv",
    summary="Tra cứu file CSV bằng bộ lọc theo cột",
    stat=lambda hub: f"{hub.db.one('SELECT COUNT(*) FROM datasets')[0]} bộ dữ liệu",
    register=_register, guide=Path(__file__).with_name("GUIDE.md"),
    mcp=McpServer("/csv/mcp", "csv", scope="chỉ file đã bật **Cho AI đọc**", tools=_tools),
)
