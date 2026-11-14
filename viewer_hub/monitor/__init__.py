"""Giám sát module (module.py); the recording itself is core/monitor.py."""


def labels(hub) -> dict:
    """Server key (MCP command) / addon id → the name shown to the user."""
    out = {"hub": "Viewer Hub"}
    for module in hub.modules:  # not locked premium ones: their names stay hidden
        if module.addon is not None:
            out[module.addon.id] = module.label
        if module.mcp:
            out[module.mcp.command] = module.label
    return out
