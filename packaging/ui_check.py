"""UI check: open every page of a throwaway Hub with very long text and report what overflows its frame.

    uv run python packaging/ui_check.py [--demo <code-map output>] [--widths 1600,1200,760] [--out var/ui-check]

1. A Hub starts on a free port with an empty data folder (nothing of the user's is touched).
2. If the code-map demo output exists (``--demo``, ``$CODEMAP_DEMO`` or ``../code-map/var/output/demo``), it is
   installed as a pack, and one feature and flow get very long text through the AI import: names, steps, rules, paths
   and identifiers without spaces. That text is what broke the pages before (2026-11-20).
3. ``web/scripts/ui-check.mjs`` drives the Chrome / Edge installed on the machine (headless, DevTools protocol, no
   extra package). It opens each page at each width and lists every element that runs past its frame, text cut
   without an ellipsis, and horizontal page scroll. Screenshots go to ``<out>/`` for a human or an agent to review.

Exit code 1 when something overflows. Build the UI first (``just web``).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import quote

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from viewer_hub.app.factory import create_wsgi  # noqa: E402
from viewer_hub.core.migrate import open_hub  # noqa: E402
from viewer_hub.core.paths import HubPaths  # noqa: E402

PACK_FILES = ("codemap.sqlite", "graph.sqlite", "manifest.json", "quality-report.json")
API = "/code-map/api/graph"

# Long text the way real projects write it: Vietnamese prose around identifiers, file names and paths with no spaces.
WORD = "AESActionHistoryCandidateDeleteForIndividualCustomersAndCorporateAccounts"
TABLE = "TIFL259_INDIVIDUAL_CUSTOMER_ACTION_HISTORY_TODAY_AND_PREVIOUS_DAY_COMPARISON_RESULT"
PATH = "itg2_career_batch/BAKS/Batch/EXE/AESDataCoordinationDR/sql/very/deep/folder/" + WORD + ".sql"
PROSE = (f"Batch chạy {WORD}.sql truy vấn kết nối AES cho lịch sử hành vi của khách hàng cá nhân (OR) {TABLE} "
         "rồi so sánh với dữ liệu ngày trước để tìm các bản ghi cần xoá.")


def demo_folder(arg: str | None) -> Path | None:
    for candidate in (arg, os.environ.get("CODEMAP_DEMO"), str(ROOT.parent / "code-map" / "var" / "output" / "demo")):
        if candidate and (Path(candidate) / "codemap.sqlite").is_file():
            return Path(candidate)
    return None


def install_pack(app, paths: HubPaths, demo: Path) -> None:
    folder = paths.packs / "demo" / "ui-check"
    (folder / "codemap").mkdir(parents=True)
    for name in PACK_FILES:
        if (demo / name).is_file():
            shutil.copy2(demo / name, folder / "codemap" / name)
    components = {"codemap": {"path": "codemap/", "schema": 3, "contractVersion": "3.0"}}
    (folder / "pack.json").write_text(json.dumps({"format": 1, "id": "demo", "version": "ui-check", "title": "Demo",
                                                  "components": components}), encoding="utf-8")
    with app.extensions["hub"].db.write() as db:
        db.execute("INSERT INTO packs (id, version, title, format, components, imported_at, active) VALUES (?,?,?,?,?,?,1)",
                   ("demo", "ui-check", "Demo", 1, json.dumps(components), "2026-11-20T00:00:00"))


def _flows(tree: dict):
    stack = list(tree.get("menus") or [])
    while stack:
        item = stack.pop(0)
        if item.get("kind") == "flow":
            yield item
        stack.extend(item.get("children") or [])


def seed_long_text(client, base: str) -> dict:
    """Write long text into the flow with the most steps; return the code map pages to check."""
    def get(path):
        return client.get(path + ("&" if "?" in path else "?") + "pack=demo", base_url=base).get_json()

    def post(path, body):
        return client.post(path + ("&" if "?" in path else "?") + "pack=demo", json=body, base_url=base).get_json()

    loaded = [get(f"{API}/business/flows/{quote(flow['id'], safe='')}") for flow in _flows(get(f"{API}/business/tree"))]
    loaded = [flow for flow in loaded if flow and flow.get("flow")]
    if not loaded:
        return {}
    flow = max(loaded, key=lambda item: len(item["flow"].get("steps") or []))
    flow_id, feature_id = flow["flow"]["id"], flow["feature_id"]
    exported = yaml.safe_load(post(f"{API}/business/features/{quote(feature_id, safe='')}/ai-export?instructions=0", {})["text"])
    steps = []
    for number, step in enumerate(next(item for item in exported["flows"] if item["id"] == flow_id)["steps"], 1):
        steps.append({
            "id": step["id"], "nodes": step["nodes"],
            "name": f"Bước {number}: so sánh lịch sử hành vi hôm nay với ngày trước ({TABLE})",
            "actor": f"Batch liên kết dữ liệu AES ({WORD}_Synchronizer)",
            "text": PROSE + "\n\n" + PROSE,
            "rules": [{"title": f"Truy vấn chỉ đọc, không tự xoá bản ghi trong {TABLE}", "evidence": f"{PATH}:112",
                       "status": "warn", "text": PROSE}] if number == 1 else [],
        })
    pack = {"export": {"id": exported["export"]["id"]},
            "feature": {"name": f"Đăng ký đơn hàng và đồng bộ lịch sử hành vi khách hàng ({WORD})", "description": PROSE * 3},
            "flows": [{"id": flow_id, "name": f"So sánh lịch sử hành vi để tìm các bản ghi {WORD} cần xoá",
                       "summary": {"text": PROSE * 2}, "steps": steps,
                       "edge_cases": {"items": [PROSE, f"{TABLE}_WITHOUT_ANY_SPACES rỗng thì không làm gì."]}}],
            "links": []}
    result = post(f"{API}/business/features/{quote(feature_id, safe='')}/ai-import", {"text": yaml.safe_dump(pack, allow_unicode=True)})
    if not result or "applied" not in result:
        raise SystemExit(f"could not write the long sample text: {result}")
    path = get(f"{API}/business/items/{quote(feature_id, safe='')}").get("path") or []
    menu_id = path[-2]["id"] if len(path) > 1 else None
    if menu_id:
        client.patch(f"{API}/business/items/{quote(menu_id, safe='')}?pack=demo", base_url=base,
                     json={"name": f"Hệ thống liên kết dữ liệu AES ({WORD})", "description": PROSE * 2})
    node = (flow["flow"]["steps"][0].get("nodes") or [None])[0]
    if node:
        post(f"{API}/business/rules", {"title": f"Quy tắc rất dài về {TABLE}", "text": PROSE, "evidence": f"{PATH}:7",
                                       "nodes": [node]})
        post(f"{API}/business/notes", {"node": node, "text": PROSE + "\n\n" + PATH})
    pages = {"codemap-home": "/code-map/#/", "codemap-feature": f"/code-map/#/feature/{quote(feature_id, safe='')}",
             "codemap-flow": f"/code-map/#/flow/{quote(flow_id, safe='')}",
             # the flow's "Dữ liệu" view: the runner clicks the second button of the view switch
             "codemap-flow-data": {"url": f"/code-map/#/flow/{quote(flow_id, safe='')}",
                                   "click": ".cm-stage__bar .cm-seg__btn:nth-child(2)"},
             "codemap-rules": "/code-map/#/knowledge", "codemap-kb": "/code-map/#/kb",
             "codemap-gaps": "/code-map/#/gaps"}
    if menu_id:
        pages["codemap-menu"] = f"/code-map/#/feature/{quote(menu_id, safe='')}"
    if node:
        pages["codemap-node"] = f"/code-map/#/node/{quote(node, safe='')}"
    return pages


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--demo", help="code-map output folder (codemap.sqlite, graph.sqlite)")
    parser.add_argument("--widths", default="1600,1200,760")
    parser.add_argument("--out", default=str(ROOT / "var" / "ui-check"))
    parser.add_argument("--only", default="", help="check only pages whose name contains this text")
    args = parser.parse_args()
    if not (ROOT / "viewer_hub" / "static" / "dist").is_dir():
        print("Chưa build giao diện: chạy `just web` trước.", file=sys.stderr)
        return 2
    out = Path(args.out)
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)

    from waitress import create_server

    with tempfile.TemporaryDirectory(prefix="viewer-hub-ui-check-") as temp:
        paths = HubPaths(Path(temp) / "data").ensure()
        state = open_hub(paths)
        app = create_wsgi(paths, state)
        demo = demo_folder(args.demo)
        server = create_server(app, host="127.0.0.1", port=0, threads=8, ident="viewer-hub-ui-check")
        port = server.effective_port
        app.extensions["hub"].port = port
        def serve():
            try:
                server.run()
            except OSError:
                pass  # the socket closed under the loop when the check ended

        threading.Thread(target=serve, daemon=True).start()
        base = f"http://127.0.0.1:{port}"
        client = app.test_client()

        pages = {"home": "/", "settings": "/settings", "help": "/help"}
        pages.update({f"module-{module.key}": module.prefix + "/" for module in app.extensions["hub"].modules
                      if module.key != "codemap"})
        if demo:
            install_pack(app, paths, demo)
            pages.update(seed_long_text(client, base))
        else:
            print("! Không thấy dữ liệu demo của code-map (--demo / CODEMAP_DEMO): bỏ qua các trang Code map.")
        if args.only:
            pages = {name: url for name, url in pages.items() if args.only in name}
        config = {"base": base, "pages": [{"name": name, **(url if isinstance(url, dict) else {"url": url})}
                                            for name, url in pages.items()],
                  "widths": [int(width) for width in args.widths.split(",") if width.strip()], "out": str(out)}
        (out / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        node = shutil.which("node")
        if not node:
            print("Cần Node.js 22+ (`node` trong PATH).", file=sys.stderr)
            return 2
        try:
            code = subprocess.run([node, str(ROOT / "web" / "scripts" / "ui-check.mjs"), str(out / "config.json")],
                                  check=False).returncode
        finally:
            server.close()
            state.db.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
