"""AI export / import for menus (systems, groups, sections) and the code map's first page: names and overviews.

Written bottom up: a menu's overview summarises what its features and sub-menus already say, never the code. The file
is small (no node, no code): each menu with its sub-menus and features, their overviews (or a mark that a feature has
none yet, so the AI does not make one up) and their flows' names. The AI fills ``items: [{id, name, description}]``;
the import writes them as AI text (``biz_items.status='ai'``) and keeps what a person wrote.
"""
from __future__ import annotations

import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import yaml

from .common import STRANDED_MENU, UNSORTED_MENU, BusinessError, _BlockDumper, _now
from .edits import ITEM_LOCKED, MAX_ITEM_DESCRIPTION, MAX_ITEM_NAME, _begin, ai_item, documented_item, refresh_sigs
from .graph import GraphIndex, graph_hash

ROOT = "root"
MAX_FEATURES_PER_MENU = 80
MAX_OVERVIEW_CHARS = 600

OVERVIEW_INSTRUCTIONS = """Bạn là chuyên gia phân tích nghiệp vụ. Viết **tên nghiệp vụ** và **tổng quan** cho các menu (hệ
thống, nhóm, mục) của một hệ thống phần mềm, từ tổng quan đã có của các tính năng và menu con bên dưới.

# Cách làm
1. Đi **từ dưới lên**: viết menu sâu nhất trước, menu cha tóm tắt menu con.
2. `name`: tên nghiệp vụ ngắn (vd "Xử lý đơn hàng"), thay cho tên kỹ thuật (`PKG_ORDER`, `menu:sys:…`). Giữ tên
   hệ thống / sản phẩm nếu đó đã là tên người dùng gọi.
3. `description`: 1–3 đoạn: nhóm này gồm những việc nghiệp vụ gì, ai dùng (hoặc batch nào chạy), các tính năng chính
   và kết quả, dữ liệu chính. Chỉ dựa vào `context`; không đoán thêm.
4. Tính năng ghi `overview: (chưa có)`: chỉ dựa vào tên và tên các luồng, nói rõ phần đó chưa có tài liệu. Đừng bịa
   chi tiết.

# Quy tắc bắt buộc
1. Không sửa mục có `locked: true` (người đã viết); không trả về mục đó.
2. Không sửa `export`, giữ nguyên `id` của từng mục.
3. Viết tiếng Việt, câu ngắn. Các đoạn cách nhau bằng một dòng trống; dùng `|` cho đoạn nhiều dòng.
4. Chỉ trả về MỘT khối YAML: khối ở phần "Định dạng trả về" (`export`, `items`) đã điền.
"""


def _scope(tree: dict[str, Any], item_id: str) -> tuple[list[dict[str, Any]], str]:
    """The menus to write (deepest first) and the title of the scope; ``root`` is every menu of the code map."""
    if item_id in ("", ROOT):
        tops, title = [menu for menu in tree["menus"] if _documented(menu)], "Toàn bộ code map"
    else:
        item = documented_item(tree, item_id)
        if item["kind"] != "menu":
            raise BusinessError("invalid_business", "Overview export is for menus; a feature has its own AI export")
        tops, title = [item], item["name"]
    ordered: list[dict[str, Any]] = []

    def walk(menu: dict[str, Any]) -> None:
        for child in menu.get("children", []):
            if child["kind"] == "menu" and _documented(child):
                walk(child)
        ordered.append(menu)

    for menu in tops:
        walk(menu)
    return ordered, title


def _documented(item: dict[str, Any]) -> bool:
    return item["kind"] == "menu" and item["id"] not in {UNSORTED_MENU, STRANDED_MENU} and not item.get("unsorted")


def _short(text: str) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= MAX_OVERVIEW_CHARS else text[:MAX_OVERVIEW_CHARS].rsplit(" ", 1)[0] + " …"


def _menu_context(menu: dict[str, Any]) -> dict[str, Any]:
    entry: dict[str, Any] = {"id": menu["id"], "name": menu["name"]}
    if menu.get("status") in ITEM_LOCKED:
        entry["locked"] = True
    if menu.get("description"):
        entry["overview"] = _short(menu["description"])
    submenus = [child for child in menu.get("children", []) if _documented(child)]
    features = [child for child in menu.get("children", []) if child["kind"] == "feature"]
    if submenus:
        entry["menus"] = [{"id": child["id"], "name": child["name"], **({"overview": _short(child["description"])}
                                                                       if child.get("description") else {})}
                          for child in submenus]
    if features:
        entry["features"] = [{
            "name": feature["name"],
            "overview": _short(feature.get("description") or "") or "(chưa có)",
            "flows": [flow["name"] for flow in feature.get("children", []) if flow["kind"] == "flow"][:12],
        } for feature in features[:MAX_FEATURES_PER_MENU]]
        if len(features) > MAX_FEATURES_PER_MENU:
            entry["more_features"] = len(features) - MAX_FEATURES_PER_MENU
    return entry


def export_overview(db: sqlite3.Connection, tree: dict[str, Any], web_path: Path, item_id: str,
                    *, include_instructions: bool = True) -> dict[str, Any]:
    menus, title = _scope(tree, item_id)
    if not menus:
        raise BusinessError("not_found", "No menu to describe", 404)
    scope = item_id or ROOT
    export_id = f"ovr-{uuid.uuid4().hex[:12]}"
    db.execute("INSERT INTO kn.biz_exports(export_id,feature_id,graph_hash,created_at) VALUES(?,?,?,?)",
               (export_id, scope, graph_hash(web_path), _now()))
    db.commit()
    context = [_menu_context(menu) for menu in menus]
    items = [{"id": menu["id"], "name": "" if menu.get("status") != "ai" else menu["name"],
              "description": menu.get("description", "") if menu.get("status") == "ai" else ""}
             for menu in menus if menu.get("status") not in ITEM_LOCKED]
    answer = {"export": {"id": export_id, "scope": scope}, "items": items}
    dump = lambda value: yaml.dump(value, Dumper=_BlockDumper, allow_unicode=True, sort_keys=False, width=100)  # noqa: E731
    missing = sum(1 for menu in menus for child in menu.get("children", [])
                  if child["kind"] == "feature" and not child.get("description"))
    slug = re.sub(r"[^a-z0-9]+", "-", scope.lower()).strip("-") or "root"
    if include_instructions:
        text = (f'# Hướng dẫn cho AI · tổng quan menu "{title}"\n\n{OVERVIEW_INSTRUCTIONS}\n'
                "# Dữ liệu\n\nChỉ để đọc, không trả về phần này. Menu sâu nhất đứng trước.\n\n"
                f"```yaml\n{dump({'context': {'menus': context}})}```\n\n"
                "# Định dạng trả về\n\nĐiền `name` và `description` của từng mục rồi trả về đúng một khối YAML này.\n\n"
                f"```yaml\n{dump(answer)}```\n")
        filename = f"{slug}.codemap-overview.md"
    else:
        text = f'# Code Map · tổng quan menu "{title}". `context` là dữ liệu; `items` là định dạng trả về.\n' + dump(
            {**answer, "context": {"menus": context}})
        filename = f"{slug}.codemap-overview.yaml"
    return {"export_id": export_id, "filename": filename, "text": text,
            "stats": {"menus": len(menus), "to_write": len(items), "features": sum(len(entry.get("features", [])) for entry in context),
                      "features_without_overview": missing}}


def _parse(text: Any) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise BusinessError("invalid_import", "Dán nội dung file AI trả về")
    text = text.replace("\r\n", "\n")
    for block in [*re.findall(r"```(?:ya?ml)?[ \t]*\n(.*?)```", text, flags=re.S), text]:
        try:
            doc = yaml.safe_load(block)
        except yaml.YAMLError:
            continue
        if isinstance(doc, dict) and isinstance(doc.get("items"), list):
            return doc
    raise BusinessError("invalid_import", "Không thấy phần items. Hãy dán toàn bộ khối YAML AI trả về.")


def _check(db: sqlite3.Connection, tree: dict[str, Any], scope: str, doc: dict[str, Any]):
    lines: list[dict[str, str]] = []
    export = doc.get("export") if isinstance(doc.get("export"), dict) else {}
    row = db.execute("SELECT feature_id FROM kn.biz_exports WHERE export_id=?", (str(export.get("id", "")),)).fetchone()
    blocking = False
    if not row:
        lines.append({"level": "error", "message": f"Không có lần xuất {export.get('id') or '(thiếu export.id)'} trong Code Map"})
        blocking = True
    elif row[0] != scope:
        lines.append({"level": "error", "message": f"File thuộc lần xuất {export['id']} của menu khác"})
        blocking = True
    else:
        lines.append({"level": "ok", "message": f"Đúng menu · lần xuất {export['id']}"})
    menus = {menu["id"]: menu for menu in _scope(tree, scope)[0]}
    usable, locked, unknown = [], [], []
    for raw in doc["items"][:500]:
        if not isinstance(raw, dict):
            continue
        item_id = str(raw.get("id") or "")
        name = raw.get("name").strip()[:MAX_ITEM_NAME] if isinstance(raw.get("name"), str) else ""
        description = raw.get("description").strip()[:MAX_ITEM_DESCRIPTION] if isinstance(raw.get("description"), str) else ""
        if not name and not description:
            continue
        if item_id not in menus:
            unknown.append(item_id or "(không có id)")
        elif menus[item_id].get("status") in ITEM_LOCKED:
            locked.append(menus[item_id]["name"])
        else:
            usable.append((item_id, {"name": name, "description": description}))
    if usable:
        lines.append({"level": "ok", "message": f"{len(usable)} menu được AI viết tên / tổng quan"})
    if locked:
        lines.append({"level": "ok", "message": f"{len(locked)} menu do người viết, giữ nguyên: {', '.join(locked[:10])}"})
    if unknown:
        lines.append({"level": "warn", "message": f"Bỏ qua {len(unknown)} mục không thuộc menu đã xuất: {', '.join(unknown[:10])}"})
    return {"ok": not blocking and bool(usable), "lines": lines}, usable


def check_overview(db: sqlite3.Connection, tree: dict[str, Any], item_id: str, text: Any) -> dict[str, Any]:
    return _check(db, tree, item_id or ROOT, _parse(text))[0]


def apply_overview(db: sqlite3.Connection, index: GraphIndex, tree: dict[str, Any], item_id: str, text: Any) -> dict[str, Any]:
    result, usable = _check(db, tree, item_id or ROOT, _parse(text))
    if not result["ok"]:
        reasons = "; ".join(line["message"] for line in result["lines"] if line["level"] == "error")
        raise BusinessError("invalid_import", "File chưa nhập được: " + (reasons or "không có nội dung mới"))
    _begin(db)
    written = [item for item, body in usable if ai_item(db, tree, item, body, commit=False) == "written"]
    db.commit()
    refresh_sigs(db, index, written)
    return {**result, "applied": {"items": len(written)}}
