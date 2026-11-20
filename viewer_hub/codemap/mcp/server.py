"""The code map's MCP server: its tools, prompts and call log, on the hub's shared JSON-RPC plumbing
(core/mcp.py), used by the stdio and HTTP transports.

Tools that write knowledge are only listed when the caller may write (``--allow-write`` on stdio, the knowledge
token over HTTP); what they write is in use at once, marked as written by AI (there is no approval step).
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from viewer_hub.core import mcp
from viewer_hub.codemap.storage import QUERY_SECONDS, GraphNotReady, timed_out

from . import erd_tool  # noqa: F401  (registers codemap_erd in TOOLS)
from . import write_tools  # noqa: F401  (registers the get/propose tools in TOOLS)
from . import doc_tools  # noqa: F401  (registers gaps / resolve and the document-based propose tools)
from .prompts import PROMPTS, render_prompt
from .tools import TOOLS, Tool, ToolError
from viewer_hub.codemap.workspace import Workspace

SERVER_NAME = "codemap"
SERVER_VERSION = "0.2.0"
INSTRUCTIONS = (
    "Code Map knows the whole system across repositories: screens, APIs, .NET code, PL/SQL, SQL files, tables, "
    "batch jobs, the business dictionary and business documentation written by people and AI. Use codemap_impact before changing "
    "a table, API, procedure or job; codemap_current_behavior before writing or reviewing a requirement; "
    "codemap_trace_flow to follow a business flow across systems; codemap_erd for the foreign keys around a table "
    "(which tables reference it, ON DELETE rules) or a Mermaid/DBML diagram of a schema. Cite facts by their ids ([N3], [E2], [D1]). "
    "Read the first line of every answer: if the graph is stale for the files involved, say so. Never present a "
    "business rule as confirmed by a person when it is marked written by AI or CODE CHANGED; turn every gap into a "
    "question for a person."
)
logger = logging.getLogger("code_map.mcp")


@dataclass
class CallContext:
    user: str = ""
    client: str = ""
    allow_write: bool = False


class McpServer:
    def __init__(self, workspace: Workspace, *, tools: list[Tool] | None = None) -> None:
        self.workspace = workspace
        self.tools = {tool.name: tool for tool in (tools if tools is not None else TOOLS)}
        self.prompts = mcp.Prompts([prompt.describe() for prompt in PROMPTS], _get_prompt)

    def handle(self, message: Any, context: CallContext | None = None) -> Any:
        """One JSON-RPC message or a batch; None when nothing is to be sent back (notifications)."""
        context = context or CallContext()
        visible = [tool for tool in self.tools.values() if context.allow_write or not tool.write]

        def noted(params: dict) -> None:
            info = params.get("clientInfo") or {}
            if isinstance(info, dict) and info.get("name"):
                context.client = str(info["name"])[:100]

        return mcp.dispatch(message, name=SERVER_NAME, title="Code Map", instructions=INSTRUCTIONS,
                                tools=[tool.describe() for tool in visible], version=SERVER_VERSION,
                                run=lambda name, arguments: self._call(self.tools[name], arguments, context),
                                prompts=self.prompts, on_initialize=noted)

    def _call(self, tool: Tool, arguments: dict[str, Any], context: CallContext) -> mcp.ToolResult:
        started = time.perf_counter()
        error = ""
        try:
            if tool.write:
                arguments = {**arguments, "_user": context.user or context.client or "agent"}
            text = tool.handler(self.workspace, arguments)
            is_error = False
        except ToolError as exc:
            text, is_error, error = f"Invalid arguments: {exc}", True, str(exc)
        except GraphNotReady as exc:
            text, is_error, error = (
                f"The code map has no extract yet ({exc}). Run the extract and point the server at its output folder.",
                True,
                str(exc),
            )
        except sqlite3.OperationalError as exc:
            if not timed_out(exc):
                raise
            text, is_error, error = (
                f"The lookup took longer than {QUERY_SECONDS:g}s and was stopped. Ask about a more specific name "
                "(exact table, API route or Class.Method) or with detail=brief.",
                True,
                "timeout",
            )
        elapsed = (time.perf_counter() - started) * 1000
        self._log(tool.name, arguments, text, error, elapsed, context)
        return mcp.ToolResult(text, is_error)

    def _log(self, tool: str, arguments: dict[str, Any], text: str, error: str, elapsed: float, context: CallContext) -> None:
        empty = int("Nothing in the graph matched" in text or "No graph node matches" in text or "declares nothing" in text)
        logger.info("mcp tool=%s chars=%s empty=%s elapsed_ms=%.1f", tool, len(text), empty, elapsed)
        try:
            with self.workspace.knowledge_db() as db:
                if db is None:
                    return
                db.execute(
                    "INSERT INTO kn.mcp_calls(user_name,client,tool,arguments_json,result_chars,empty,error,elapsed_ms) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (
                        context.user,
                        context.client,
                        tool,
                        json.dumps({k: v for k, v in arguments.items() if not k.startswith("_")}, ensure_ascii=False)[:4000],
                        len(text),
                        empty,
                        error[:500],
                        round(elapsed, 1),
                    ),
                )
                db.commit()
        except Exception:  # noqa: BLE001  (logging must never fail a call)
            logger.warning("could not log mcp call", exc_info=True)


def _get_prompt(name: str, arguments: dict[str, str]) -> dict[str, Any]:
    prompt = next((item for item in PROMPTS if item.name == name), None)
    if prompt is None:
        raise ValueError(f"Unknown prompt: {name}")
    return render_prompt(prompt, arguments)
