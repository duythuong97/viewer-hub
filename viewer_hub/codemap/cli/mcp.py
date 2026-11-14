"""stdio MCP over the active code-map pack: ``viewer-hub mcp codemap [--pack ID] [--self-test]``.

Ported from code-map codemap/mcp/__main__.py: one JSON-RPC message per line on
stdin, replies on stdout, logs on stderr. The pack comes from hub.db (or the dev
folder ``<home>/codemap``); nothing is read from .env or an extractor config.
"""
from __future__ import annotations

import argparse
import logging
import sys

from viewer_hub.codemap import packs
from viewer_hub.codemap.mcp.server import CallContext, McpServer
from viewer_hub.core import mcp
from viewer_hub.codemap.workspace import for_source


class _Hub:
    """What packs.sources needs: paths, hub.db and the read-only flag."""

    def __init__(self, paths, db, readonly: bool):
        self.paths, self.db, self.readonly = paths, db, readonly


def main(argv: list[str], paths) -> int:
    parser = argparse.ArgumentParser(prog="viewer-hub mcp codemap", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pack", help="Pack id (default: the first active code-map pack).")
    parser.add_argument("--user", default="", help="Name recorded on proposals and in the call log.")
    parser.add_argument("--allow-write", action="store_true",
                        help="Offer the propose_* tools (they only add drafts to the review queue).")
    parser.add_argument("--list", action="store_true", help="List the code-map packs and exit.")
    parser.add_argument("--self-test", action="store_true",
                        help="Print what the server sees (codemap_status) and exit.")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")

    from viewer_hub.core.db import HubDB
    from viewer_hub.core.migrate import hub_schema

    readonly = False
    db = None
    if paths.db.is_file():
        # Read the registry only (a running hub owns it); a newer schema means this version must not write.
        db = HubDB(paths.db, readonly=True)
        readonly = db.schema_version > hub_schema()
    hub = _Hub(paths, db if db is not None else _NoDB(), readonly)
    try:
        available = packs.sources(hub)
        if args.list:
            for source in available:
                sys.stdout.write(f"{source.pack_id}\t{source.version}\t{source.title}\t{source.output}\n")
            return 0
        source = packs.pick(hub, args.pack)
        if source is None:
            what = f"pack '{args.pack}'" if args.pack else "an active code-map pack"
            sys.stderr.write(f"viewer-hub mcp codemap: no {what} in {paths.home} (import a .sapack with codemap)\n")
            return 2
        server = McpServer(for_source(source))
        context = CallContext(user=args.user, allow_write=args.allow_write and not source.readonly)
        if args.self_test:
            reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                   "params": {"name": "codemap_status", "arguments": {"detail": "brief"}}}, context)
            result = reply.get("result", {})
            tools = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, context)["result"]["tools"]
            sys.stdout.write(result.get("content", [{}])[0].get("text", str(reply)) + "\n\n")
            sys.stdout.write(f"pack: {source.pack_id} {source.version} ({source.output})\n")
            sys.stdout.write(f"{len(tools)} tools: {', '.join(tool['name'] for tool in tools)}\n")
            sys.stdout.write(f"knowledge db: {source.knowledge}\n")
            return 1 if result.get("isError") else 0
        mcp.serve_stdio(lambda message: server.handle(message, context))
        return 0
    finally:
        if db is not None:
            db.close()


class _NoDB:
    """No hub.db yet: only the dev folder can be served."""

    def query(self, *_args, **_kwargs):
        return []

    def one(self, *_args, **_kwargs):
        return None
