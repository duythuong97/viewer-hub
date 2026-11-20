"""Code map module: page on the main app, API + MCP as its own Flask app mounted at /code-map (mount.py)."""
from pathlib import Path

from viewer_hub.app.modules import Exports, McpServer, Module


def _register(app) -> None:
    from viewer_hub.codemap.mount import register_page

    register_page(app)


def _mounts(hub) -> dict:
    from viewer_hub.codemap.mount import codemap_mounts

    return codemap_mounts(hub)


def _tools() -> list[str]:
    from viewer_hub.codemap.mcp.server import TOOLS

    return [tool.name for tool in TOOLS if not tool.write]  # write tools are only listed to the knowledge token


def _export(hub, name: str, params: dict) -> dict:
    from viewer_hub.codemap.exports import call

    return call(hub, name, params)


MODULE = Module(
    key="codemap", label="Code map", icon="account_tree", prefix="/code-map",
    summary="Xem một màn hình gọi API nào, API chạy code và procedure nào, đọc/ghi bảng nào, batch nào chạy; "
            "bảng và ma trận CRUD của từng tính năng",
    register=_register, mounts=_mounts, guide=Path(__file__).with_name("GUIDE.md"),
    mcp=McpServer("/code-map/mcp", "codemap", tools=_tools),
    # Read by addons (the erd addon): erd_model, db_objects, table_usage (exports.json, exports.py).
    exports=Exports(contract=Path(__file__).with_name("exports.json"), call=_export),
)
