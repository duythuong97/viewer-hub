"""ERD of the active code-map pack on the command line.

    viewer-hub erd [--pack ID] (--table NAME | --schema DB.SCHEMA | --system NAME) [--depth 1|2]
                   [--format mermaid|dbml|json] [--keys-only] [--out FILE]

Reads the pack read-only (like ``viewer-hub mcp codemap``); writes the diagram to stdout or ``--out``.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from viewer_hub.codemap import erd, packs
from viewer_hub.codemap.cli.mcp import _Hub, _NoDB
from viewer_hub.codemap.storage import GraphNotReady, open_search


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--pack", help="Pack id (mặc định: pack code-map đang bật đầu tiên).")
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--table", help="Bảng trung tâm: TABLE, SCHEMA.TABLE, DB.SCHEMA.TABLE hoặc node id.")
    scope.add_argument("--schema", help="Mọi bảng của một schema, vd. DB1.APP.")
    scope.add_argument("--system", help="Mọi bảng của một hệ thống.")
    parser.add_argument("--depth", type=int, choices=[1, 2], default=1, help="Số bước khoá ngoại quanh bảng (mặc định 1).")
    parser.add_argument("--format", choices=["mermaid", "dbml", "json"], default="mermaid")
    parser.add_argument("--keys-only", action="store_true", help="Chỉ cột PK/FK.")
    parser.add_argument("--max-tables", type=int, default=erd.MAX_TABLES, help=f"Tối đa số bảng (≤ {erd.MAX_TABLES}).")
    parser.add_argument("--out", help="Ghi ra file thay vì stdout.")


def main(argv: list[str], paths) -> int:
    parser = argparse.ArgumentParser(prog="viewer-hub erd", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    add_arguments(parser)
    return run(parser.parse_args(argv), paths)


def run(args: argparse.Namespace, paths) -> int:
    from viewer_hub.core.db import HubDB

    db = HubDB(paths.db, readonly=True) if paths.db.is_file() else None
    try:
        source = packs.pick(_Hub(paths, db if db is not None else _NoDB(), True), args.pack)
        if source is None:
            what = f"pack '{args.pack}'" if args.pack else "pack code-map đang bật"
            sys.stderr.write(f"viewer-hub erd: không có {what} trong {paths.home}\n")
            return 2
        try:
            with open_search(source.output) as graph:
                model = erd.build(graph, table=args.table or "", schema=args.schema or "", system=args.system or "",
                                  depth=args.depth, limit=args.max_tables)
        except erd.ErdError as exc:
            sys.stderr.write(f"viewer-hub erd: {exc.message}\n")
            return 1
        except GraphNotReady as exc:
            sys.stderr.write(f"viewer-hub erd: {exc.message or exc}\n")
            return 2
        text = erd.render(model, args.format, keys_only=args.keys_only)
        if args.out:
            Path(args.out).write_text(text, encoding="utf-8")
            sys.stderr.write(f"{model['summary']}\n→ {args.out}\n")
        else:
            sys.stdout.write(text)
            sys.stderr.write(f"{model['summary']}\n")
        return 0
    finally:
        if db is not None:
            db.close()
