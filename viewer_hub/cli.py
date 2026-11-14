"""viewer-hub command line: serve (default), backup, restore, repair, import, pack, addon, export-solr,
mcp (codemap | search | csv | monitor | <addon command>, e.g. svn), erd."""
from __future__ import annotations

import argparse
import logging
import os
import signal
import socket
import sys
import webbrowser
from pathlib import Path

from viewer_hub import __version__
from viewer_hub.core.paths import HubPaths

DEFAULT_PORT = 8700


def _free_port(host: str, preferred: int) -> int:
    """The preferred port unless another program listens on it, else the next free one.

    The probe allows address reuse like waitress does, so a port that only has connections from the last run
    in TIME_WAIT (the browser was still connected when it stopped) is not taken for busy: without it every
    restart within a minute moved to 8701, 8702… and broke links such as the MCP URL. On Windows that option
    would let two programs share a port, and TIME_WAIT does not block a bind there, so it is not set.
    """
    for port in [preferred, *range(preferred + 1, preferred + 20)]:
        with socket.socket() as probe:
            if os.name != "nt":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, port))
                return port
            except OSError:
                continue
    raise SystemExit(f"No free port from {preferred} to {preferred + 19}")


def _exit_on_signal(_signum, _frame) -> None:
    raise SystemExit(0)


def cmd_serve(args, paths: HubPaths) -> int:
    from waitress import serve

    from viewer_hub.core.lock import AlreadyRunning, InstanceLock
    from viewer_hub.core.migrate import open_hub
    from viewer_hub.core.logs import configure
    from viewer_hub.app.factory import create_wsgi

    paths.ensure()
    log_file = configure(paths, args.verbose)
    lock = InstanceLock(paths.lock)
    try:
        lock.acquire({"version": __version__})
    except AlreadyRunning as running:
        url = running.info.get("url")
        print(f"Viewer Hub đang chạy: {url or '(chưa rõ địa chỉ)'}")
        if url and not args.no_browser:
            webbrowser.open(url)
        return 0
    try:
        paths.clean_tmp()
        state = open_hub(paths)
        if state.readonly:
            print(f"! {state.reason}", file=sys.stderr)
        elif state.migrated_from is not None:
            print(f"Đã nâng cấp dữ liệu từ schema {state.migrated_from}; sao lưu: {state.backup_path}")
        if not state.readonly:
            from viewer_hub.packs.bundled import import_bundled

            for name in import_bundled(paths, state.db):
                print(f"Đã nạp data pack đi kèm: {name}")
            from viewer_hub.addons.install import install_bundled

            for name in install_bundled(paths):
                print(f"Đã cài addon đi kèm: {name}")
            from viewer_hub.addons.legacy import migrate_svn

            if migrate_svn(paths, state.db):
                print("Đã chuyển danh sách repo SVN sang addon SVN")
        app = create_wsgi(paths, state)
        port = _free_port(args.host, args.port)
        hub = app.extensions["hub"]
        hub.port = port
        from viewer_hub.addons import gateway

        from viewer_hub.core import monitor
        from viewer_hub.monitor import sampler

        monitor.configure(paths.home, "http", maintain=True)  # MCP calls, addon events (Giám sát)
        sampler.start(hub)
        gateway.autostart_in_background(hub)  # daemon addons unlocked here (MCP Bridge): start them with the Hub
        url = f"http://{args.host}:{port}/"
        lock.update(url=url)
        print(f"Viewer Hub {__version__}: {url}\nDữ liệu: {paths.home}\nLog: {log_file}", flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        signal.signal(signal.SIGTERM, _exit_on_signal)  # `kill`: close like Ctrl+C, so addons are stopped (atexit)
        serve(app, host=args.host, port=port, threads=16, ident="viewer-hub")  # addons: at most a few each (addons/limits.py)
    finally:
        lock.release()
    return 0


def cmd_backup(args, paths: HubPaths) -> int:
    from viewer_hub.core import backup

    print(backup.create(paths.ensure(), "manual", __version__))
    return 0


def cmd_restore(args, paths: HubPaths) -> int:
    from viewer_hub.core import backup
    from viewer_hub.core.lock import AlreadyRunning, InstanceLock

    lock = InstanceLock(paths.lock)
    try:
        lock.acquire({"version": __version__, "task": "restore"})
    except AlreadyRunning:
        print("Hãy tắt Viewer Hub trước khi khôi phục.", file=sys.stderr)
        return 1
    try:
        folder = Path(args.backup)
        if not folder.is_absolute():
            folder = paths.backups / folder
        safety = backup.restore(paths, folder, __version__)
        print(f"Đã khôi phục {folder.name}. Trạng thái trước đó được lưu ở {safety}")
    finally:
        lock.release()
    return 0


def cmd_repair(args, paths: HubPaths) -> int:
    from viewer_hub.core.repair import repair

    print(repair(paths.ensure()))
    return 0


def cmd_import(args, paths: HubPaths) -> int:
    from viewer_hub.core.migrate import open_hub
    from viewer_hub.packs.importer import import_pack

    state = open_hub(paths)
    if state.readonly:
        print(state.reason, file=sys.stderr)
        return 1
    result = import_pack(paths, state.db, Path(args.file), activate=False if args.no_activate else "auto")
    print(f"Đã import {result['id']} {result['version']}" + (f" — {result['reason']}" if result.get("reason") else ""))
    return 0


def cmd_export_solr(args, paths: HubPaths) -> int:
    from viewer_hub.fsearch.export_solr import export

    export(args.solr_url, Path(args.out), rows=args.rows, timeout=args.timeout)
    return 0


MCP_BUILTIN = ["codemap", "search", "csv", "monitor"]


def cmd_mcp(args, paths: HubPaths) -> int:
    """stdio MCP for AI agents (Copilot, Claude): reads the active packs, never writes them."""
    if paths.home.is_dir():  # the Giám sát page sees these calls too (monitor.db, its own file)
        from viewer_hub.core import monitor

        monitor.configure(paths.home, "stdio")
    if args.server == "search":
        return _search_mcp(args.rest, paths)
    if args.server == "csv":
        return _csv_mcp(args.rest, paths)
    if args.server == "monitor":
        from viewer_hub.monitor import mcp as monitor_mcp

        argparse.ArgumentParser(prog="viewer-hub mcp monitor").parse_args(args.rest)
        logging.getLogger().handlers[:] = [logging.StreamHandler(sys.stderr)]  # stdout is the protocol
        return monitor_mcp.serve_stdio(paths.home)
    if args.server == "codemap":
        from viewer_hub.codemap.cli.mcp import main as codemap_mcp

        return codemap_mcp(args.rest, paths)
    return _addon_mcp(args.server, paths)


def _addon_mcp(command: str, paths: HubPaths) -> int:
    """An addon's MCP over stdio: runs the addon process and relays each line to its /mcp (read-only tools only)."""
    from viewer_hub.addons import proxy
    from viewer_hub.addons.registry import Registry
    from viewer_hub.addons.runner import AddonUnavailable
    from viewer_hub.core import mcp

    logging.getLogger().handlers[:] = [logging.StreamHandler(sys.stderr)]  # stdout is the protocol
    registry = Registry(paths)
    addon = registry.by_command(command)
    if addon is None:
        known = MCP_BUILTIN + [a.mcp.command for a in registry.addons() if a.mcp]
        print(f"Không có MCP '{command}'. Có: {', '.join(known)}", file=sys.stderr)
        return 2
    if addon.premium:
        from viewer_hub.core import unlock
        from viewer_hub.core.db import HubDB

        if not paths.db.is_file() or addon.premium not in unlock.unlocked(HubDB(paths.db, readonly=True)):
            print(f"Không có MCP '{command}'.", file=sys.stderr)  # a locked feature is never named
            return 2
    runner = registry.runner(addon)
    try:
        port, token = runner.ensure()
    except AddonUnavailable as exc:
        print(str(exc), file=sys.stderr)
        return 1
    try:
        def handle(message):
            try:
                return proxy.mcp_call(port, token, message, runner.read_only_tools, addon.mcp.command)[1]
            except proxy.Unavailable as exc:
                return {"jsonrpc": "2.0", "id": message.get("id") if isinstance(message, dict) else None,
                        "error": {"code": -32603, "message": str(exc)}}

        return mcp.serve_stdio(handle)
    finally:
        runner.stop()


def _search_mcp(rest: list[str], paths: HubPaths) -> int:
    from types import SimpleNamespace

    from viewer_hub.fsearch import mcp
    from viewer_hub.fsearch.store import SearchStore

    parser = argparse.ArgumentParser(prog="viewer-hub mcp search")
    parser.add_argument("--pack", help="Pack id (default: the first active pack with documents)")
    options = parser.parse_args(rest)
    logging.getLogger().handlers[:] = [logging.StreamHandler(sys.stderr)]  # stdout is the protocol
    # Read-only, like `mcp codemap`: an MCP process started by an agent or the bridge must never
    # migrate or write hub.db while the web app may be running on the same data dir.
    from viewer_hub.core.db import HubDB

    if not paths.db.is_file():
        print("Chưa có dữ liệu (hub.db); mở Viewer Hub một lần trước.", file=sys.stderr)
        return 2
    hub = SimpleNamespace(paths=paths, db=HubDB(paths.db, readonly=True))

    def resolve():
        source = SearchStore.for_hub(hub).pick(options.pack)
        return source[2] if source else None

    return mcp.serve_stdio(resolve)


def _csv_mcp(rest: list[str], paths: HubPaths) -> int:
    """CSV files shared with AI, read-only (hub.db is opened read-only, as for `mcp search`)."""
    from types import SimpleNamespace

    from viewer_hub.core.db import HubDB
    from viewer_hub.csv import mcp
    from viewer_hub.csv.store import CsvStore
    from viewer_hub.packs.content import pack_dirs

    argparse.ArgumentParser(prog="viewer-hub mcp csv").parse_args(rest)
    logging.getLogger().handlers[:] = [logging.StreamHandler(sys.stderr)]  # stdout is the protocol
    if not paths.db.is_file():
        print("Chưa có dữ liệu (hub.db); mở Viewer Hub một lần trước.", file=sys.stderr)
        return 2
    hub = SimpleNamespace(paths=paths, db=HubDB(paths.db, readonly=True))
    return mcp.serve_stdio(lambda: CsvStore(paths.csv, paths.tmp, packs=pack_dirs(hub, "csv")))


def cmd_pack(args, paths: HubPaths) -> int:
    """input/ (code map, search.sqlite, csv/, docs/, pack.yaml) → one .sapack; works from a release, no source."""
    from viewer_hub.packs.builder import InputError, build_from_input, describe_input

    source = Path(args.input).resolve()
    print(describe_input(source))
    try:
        out = build_from_input(source, Path(args.out).resolve(), version=args.version)
    except InputError as error:
        print(error, file=sys.stderr)
        return 1
    print(f"Data pack: {out}\nGửi file này cho mọi người: Cài đặt → Import .sapack (hoặc viewer-hub import <file>).")
    if args.install:
        args.file, args.no_activate = str(out), False
        return cmd_import(args, paths)
    return 0


def cmd_addon(args, paths: HubPaths) -> int:
    """Install / list / remove addons in the data dir (the web: Cài đặt → Addon), pack an addon project, write the
    SDK. Stop Viewer Hub first on Windows when updating an addon that is running."""
    from viewer_hub.addons.install import AddonError, install_zip, uninstall
    from viewer_hub.addons.registry import Registry

    if args.action == "pack":
        from viewer_hub.addons.pack import pack

        if not args.target:
            print("Cần thư mục addon: viewer-hub addon pack <thư mục>", file=sys.stderr)
            return 2
        try:
            pack(Path(args.target), Path(args.out or "dist"), [Path(p) for p in args.include])
        except (AddonError, OSError) as error:
            print(f"Không đóng gói được: {error}", file=sys.stderr)
            return 1
        return 0
    if args.action == "sdk":
        from viewer_hub.addons import sdk_kit

        out = Path(args.out or ".") / sdk_kit.file_name()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(sdk_kit.build())
        print(out)
        return 0
    paths.ensure()
    if args.action == "install":
        try:
            result = install_zip(paths, Path(args.target))
        except (AddonError, OSError) as error:
            print(f"Không cài được: {error}", file=sys.stderr)
            return 1
        addon = result.addon
        print(f"Đã cài {addon.name} {addon.version} ({'đã ký' if result.trust == 'signed' else 'chưa ký'})"
              + (f", thay bản {result.replaced}" if result.replaced else "") + f" → {addon.folder}")
        for note in result.notes:
            print(f"  lưu ý: {note}")
        return 0
    registry = Registry(paths)
    if args.action == "remove":
        try:
            uninstall(paths, args.target)
        except (AddonError, OSError) as error:
            print(f"Không gỡ được: {error}", file=sys.stderr)
            return 1
        print(f"Đã gỡ {args.target}; dữ liệu giữ ở {paths.addon_data(args.target)}")
        return 0
    for addon in registry.addons():
        print(f"{addon.id:<20} {addon.version:<10} {addon.lifecycle:<8} {registry.trust(addon):<9} {addon.label}"
              + (f"  (premium {addon.premium})" if addon.premium else ""))
    for name, error in registry.broken.items():
        print(f"{name:<20} LỖI: {error}")
    if not registry.addons() and not registry.broken:
        print(f"Chưa có addon trong {paths.addons}")
    return 0


def cmd_erd(args, paths: HubPaths) -> int:
    """ERD (Mermaid / DBML / JSON) of the active code-map pack; read-only."""
    from viewer_hub.codemap.cli.erd import run

    return run(args, paths)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="viewer-hub", description=__doc__)
    parser.add_argument("--data-dir", help="Thư mục dữ liệu (mặc định: $VIEWER_HUB_HOME hoặc %%LOCALAPPDATA%%\\ViewerHub)")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="Chạy web (mặc định)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--no-browser", action="store_true")
    serve.add_argument("-v", "--verbose", action="store_true")
    serve.set_defaults(func=cmd_serve)

    mcp = sub.add_parser("mcp", help="MCP server qua stdio cho AI agent (codemap | search | csv | monitor | lệnh của addon, vd. svn)")
    mcp.add_argument("server", help=", ".join(MCP_BUILTIN) + " hoặc mcp.command của một addon")
    mcp.add_argument("rest", nargs=argparse.REMAINDER, help="--pack, --list, --self-test, ...")
    mcp.set_defaults(func=cmd_mcp)

    from viewer_hub.codemap.cli.erd import add_arguments as erd_arguments

    erd = sub.add_parser("erd", help="ERD khoá ngoại của pack code-map (Mermaid, DBML, JSON)")
    erd_arguments(erd)
    erd.set_defaults(func=cmd_erd)

    sub.add_parser("backup", help="Sao lưu dữ liệu người dùng").set_defaults(func=cmd_backup)
    restore = sub.add_parser("restore", help="Khôi phục một bản sao lưu")
    restore.add_argument("backup", help="Tên hoặc đường dẫn thư mục trong backups/")
    restore.set_defaults(func=cmd_restore)
    sub.add_parser("repair", help="Dựng lại hub.db từ các file JSON cạnh dữ liệu").set_defaults(func=cmd_repair)

    imp = sub.add_parser("import", help="Import data pack (.sapack)")
    imp.add_argument("file")
    imp.add_argument("--no-activate", action="store_true")
    imp.set_defaults(func=cmd_import)

    pack = sub.add_parser("pack", help="Đóng data pack (.sapack) từ thư mục input/ (code map, search, CSV, docs)")
    pack.add_argument("--input", default="input", help="Thư mục dữ liệu (mặc định: input)")
    pack.add_argument("--out", default="dist", help="Nơi ghi file .sapack (mặc định: dist)")
    pack.add_argument("--version", help="Phiên bản pack (mặc định: trong pack.yaml, hoặc ngày giờ)")
    pack.add_argument("--install", action="store_true", help="Import luôn vào dữ liệu của máy này")
    pack.set_defaults(func=cmd_pack)

    addon = sub.add_parser("addon", help="Cài / liệt kê / gỡ / đóng gói addon, tải SDK viết addon")
    addon.add_argument("action", choices=["install", "list", "remove", "pack", "sdk"])
    addon.add_argument("target", nargs="?", default="",
                       help="install: file .zip; remove: id của addon; pack: thư mục addon (có addon.json)")
    addon.add_argument("--include", action="append", default=[],
                       help="pack: zip chương trình build ở project khác (vd. daemon) gộp vào addon; thư mục: zip mới nhất")
    addon.add_argument("--out", default="", help="pack / sdk: thư mục ghi file zip (mặc định: dist / thư mục hiện tại)")
    addon.set_defaults(func=cmd_addon)

    exp = sub.add_parser("export-solr", help="(Máy tác giả) Xuất Solr core ra search.sqlite")
    exp.add_argument("solr_url", help="vd. http://localhost:8983/solr/documents")
    exp.add_argument("--out", default="search.sqlite")
    exp.add_argument("--rows", type=int, default=500)
    exp.add_argument("--timeout", type=int, default=60)
    exp.set_defaults(func=cmd_export_solr)

    args = parser.parse_args(argv)
    if not args.command:
        args = parser.parse_args([*(argv or sys.argv[1:]), "serve"])
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return args.func(args, HubPaths.resolve(args.data_dir))


if __name__ == "__main__":
    raise SystemExit(main())
