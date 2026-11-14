"""Docs module: each markdown folder becomes a site (no MCP)."""
from pathlib import Path

from viewer_hub.app.modules import Module


def _register(app) -> None:
    from viewer_hub.docs.routes import bp

    app.register_blueprint(bp, url_prefix="/docs")


MODULE = Module(
    key="docs", label="Docs", icon="menu_book", prefix="/docs",
    summary="Đọc một thư mục tài liệu markdown như một trang web có menu",
    stat=lambda hub: f"{hub.db.one('SELECT COUNT(*) FROM sites')[0]} site",
    register=_register, guide=Path(__file__).with_name("GUIDE.md"),
)
