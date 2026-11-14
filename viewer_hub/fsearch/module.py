"""F-Search module: full-text search over search.sqlite."""
from pathlib import Path

from viewer_hub.app.modules import McpServer, Module


def _register(app) -> None:
    from viewer_hub.fsearch.routes import bp

    app.register_blueprint(bp, url_prefix="/ocr-search")


def _tools() -> list[str]:
    from viewer_hub.fsearch.mcp import TOOLS

    return [tool["name"] for tool in TOOLS]


def _count(hub) -> str:
    from viewer_hub.fsearch.store import SearchStore

    return f"{SearchStore.for_hub(hub).count()} tài liệu"


MODULE = Module(
    key="fsearch", label="F-Search", icon="manage_search", prefix="/ocr-search",
    summary="Full-text search: tìm trong tài liệu, code và ảnh scan (OCR)",
    stat=_count,
    register=_register, guide=Path(__file__).with_name("GUIDE.md"),
    mcp=McpServer("/ocr-search/mcp", "search", tools=_tools),
)
