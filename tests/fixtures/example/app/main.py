"""Template addon (docs/addons.md §8): an API for its page and one read-only MCP tool, nothing else.

Runs in its own process; Viewer Hub starts it on first use (python -I, viewer_hub/addons/host.py) and relays
/x/example/api/* and /x/example/mcp to it.
"""
from viewer_hub.addons.sdk import Addon, ApiError, ToolError

addon = Addon("example", title="Example addon", instructions="Greets the names set on the addon's page.")


def _greet(name: str) -> str:
    return f"{addon.settings().get('greeting') or 'Xin chào'}, {name}!"


@addon.get("/greetings")
def greetings(_request):
    return {"greetings": [_greet(name) for name in addon.settings().get("names") or []]}


@addon.get("/greetings/<name>")
def greeting(request):
    if request.params["name"] not in (addon.settings().get("names") or []):
        raise ApiError("unknown_name", "Tên này chưa có trong cài đặt", 404)
    return {"greeting": _greet(request.params["name"])}


@addon.tool("example_greet", "Greeting for one of the names set on the addon's page.",
            {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]})
def example_greet(arguments):
    name = str(arguments.get("name") or "")
    if name not in (addon.settings().get("names") or []):
        raise ToolError(f"unknown name: {name}")
    return _greet(name)


if __name__ == "__main__":
    addon.run()
