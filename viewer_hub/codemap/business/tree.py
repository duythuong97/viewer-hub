"""The menu / feature / flow tree derived from the graph, merged with what people edited."""
from __future__ import annotations

import re
import sqlite3
from typing import Any


from .common import MAX_FEATURE_NODES, MAX_UNASSIGNED, STRANDED_MENU, UNSORTED_MENU, _json
from .graph import GraphIndex, ref_name, screen_actions


def _route_of(node: dict[str, Any]) -> str:
    return str(node["properties"].get("route") or node["technical_name"]).strip("/")


def _menu_key(route: str) -> str:
    for segment in route.split("/"):
        if segment and not segment.startswith(":") and not segment.startswith("{"):
            return segment
    return "root"


def _title(text: str) -> str:
    words = re.sub(r"[-_]+", " ", text).strip()
    return words[:1].upper() + words[1:] if words else text


def _items(db: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    return {row["item_id"]: dict(row) for row in db.execute("SELECT * FROM kn.biz_items")}


def _docs(db: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    return {
        row["flow_id"]: {"feature_id": row["feature_id"], "doc": _json(row["doc_json"], {}), "updated_at": row["updated_at"]}
        for row in db.execute("SELECT flow_id,feature_id,doc_json,updated_at FROM kn.biz_flows")
    }


def _parts(doc: dict[str, Any]) -> list[str]:
    if not doc:
        return []
    statuses = [doc.get("summary", {}).get("status", "ai")]
    statuses += [step.get("status", "ai") for step in doc.get("steps", [])]
    if doc.get("edge_cases", {}).get("items"):
        statuses.append(doc["edge_cases"].get("status", "ai"))
    return statuses


# Features people reach the system through; their flows win over the per-object features (API, routine).
ENTRY_FEATURE_TYPES = frozenset({"SCREEN", "JOB_NETWORK", "EXECUTABLE"})

# Branches under each system, in this order (docs/IMPROVEMENT_PLAN.md, giai đoạn 6).
TREE_GROUPS = (
    ("screens", "Màn hình"), ("api", "API"), ("batch", "Batch / Job"), ("plsql", "PL/SQL"),
    ("sql", "SQL / Loader / Mapper"), ("data", "Dữ liệu"), ("integration", "Tích hợp"),
)
_GROUP_ORDER = {key: position for position, (key, _) in enumerate(TREE_GROUPS)}
_API_PREFIXES = frozenset({"api", "v1", "v2", "v3", "rest", "public"})


def _api_section(technical_name: str) -> str:
    """Grouping key of an endpoint: the first route segment after api/, v1/ and the like."""
    route = technical_name.split(" ", 1)[-1]
    for segment in route.split("/"):
        if segment and segment.lower() not in _API_PREFIXES and not segment.startswith("{"):
            return segment
    return "root"


def _qualified_part(node: dict[str, Any], index_from_end: int, default: str) -> str:
    parts = node["qualified_name"].split("(", 1)[0].split(".")
    return parts[-index_from_end] if len(parts) >= index_from_end else default


def build_tree(db: sqlite3.Connection, index: GraphIndex) -> dict[str, Any]:
    items, docs = _items(db), _docs(db)
    menus: dict[str, dict[str, Any]] = {}
    features: dict[str, dict[str, Any]] = {}

    def menu(menu_id: str, name: str, source: str, parent: str | None = None, order: int = 0) -> dict[str, Any]:
        return menus.setdefault(menu_id, {"id": menu_id, "kind": "menu", "name": name, "source": source, "children": [],
                                          "parent": parent, "order": order})

    def place(system: str, group: str, section: str | None = None, section_name: str | None = None) -> str:
        """Menu id for system > group [> section], creating the menus on the way."""
        system_id = f"menu:sys:{system}"
        menu(system_id, system, "system")
        group_id = f"{system_id}:{group}"
        menu(group_id, dict(TREE_GROUPS)[group], "group", system_id, _GROUP_ORDER[group])
        if section is None:
            return group_id
        section_id = f"{group_id}:{section}"
        menu(section_id, section_name or _title(section), "section", group_id)
        return section_id

    def add_feature(node_id: str, parent: str, flow_entries: list[str], *, batch: bool = False, route: str = "") -> None:
        node = index.nodes[node_id]
        features[f"feature:{node_id}"] = {
            "id": f"feature:{node_id}", "kind": "feature", "name": node["display_name"] if node["node_type"] != "SCREEN" else _title(node["display_name"] or route),
            "route": route or node["technical_name"], "entry_node_id": node_id, "entry_type": node["node_type"], "batch": batch,
            "parent_id": parent, "flow_entries": flow_entries,
        }

    for screen_id in index.by_type.get("SCREEN", []):
        node = index.nodes[screen_id]
        route = _route_of(node)
        if "**" in route:
            continue  # the not-found wildcard is not a screen of the application
        key = _menu_key(route)
        add_feature(screen_id, place(node["owner"], "screens", key), screen_actions(index, screen_id) or [screen_id], route=route)
    for network_id in index.by_type.get("JOB_NETWORK", []):
        add_feature(network_id, place(index.nodes[network_id]["owner"], "batch"),
                    index.children(network_id, "CONTAINS", "JOB") or [network_id], batch=True)
    for executable_id in index.by_type.get("EXECUTABLE", []):
        add_feature(executable_id, place(index.nodes[executable_id]["owner"], "batch", "executables", "Executable"),
                    [executable_id], batch=True)
    for api_id in index.by_type.get("API_OPERATION", []):
        node = index.nodes[api_id]
        add_feature(api_id, place(node["owner"], "api", _api_section(node["technical_name"])), [api_id])
    for kind in ("PROCEDURE", "FUNCTION"):
        for routine_id in index.by_type.get(kind, []):
            node = index.nodes[routine_id]
            package = _qualified_part(node, 2, "STANDALONE")
            add_feature(routine_id, place(node["owner"], "plsql", package, "Độc lập" if package == "STANDALONE" else package), [routine_id])
    for trigger_id in index.by_type.get("TRIGGER", []):
        add_feature(trigger_id, place(index.nodes[trigger_id]["owner"], "plsql", "triggers", "Trigger"), [trigger_id])
    for kind in ("SQL_FILE", "LOADER_CONTROL"):
        for file_id in index.by_type.get(kind, []):
            statements = index.children(file_id, "CONTAINS", "INLINE_SQL")
            add_feature(file_id, place(index.nodes[file_id]["owner"], "sql"), statements or [file_id])
    for kind in ("TABLE", "VIEW", "MATERIALIZED_VIEW"):
        for table_id in index.by_type.get(kind, []):
            node = index.nodes[table_id]
            add_feature(table_id, place(node["system"], "data", _qualified_part(node, 2, "default")), [])
    for reference_id in index.by_type.get("UNRESOLVED_REFERENCE", []):
        if ":TABLE:" in reference_id:
            node = index.nodes[reference_id]
            database = reference_id.split(":", 2)[1]
            add_feature(reference_id, place(database, "data", "uncatalogued", "Chưa có trong catalog"), [])
    for kind in ("MESSAGE_TOPIC", "EXTERNAL_API_OPERATION"):
        for node_id in index.by_type.get(kind, []):
            add_feature(node_id, place(index.nodes[node_id]["owner"], "integration"), [node_id])
    entry_kinds = ENTRY_FEATURE_TYPES

    # Entry points people attached to a feature (item "entry:<node>" with that parent).
    extra_entries: dict[str, list[str]] = {}
    for item_id, item in items.items():
        if item_id.startswith("entry:") and item.get("parent_id") in features and item_id[6:] in index.nodes:
            extra_entries.setdefault(item["parent_id"], []).append(item_id[6:])

    reached: set[str] = set()
    for feature in features.values():
        feature["extra_entries"] = extra_entries.get(feature["id"], [])
        if feature["entry_type"] in entry_kinds or feature["extra_entries"]:
            reached.update(index.reach([feature["entry_node_id"], *feature["extra_entries"]], MAX_FEATURE_NODES))

    # A UI action or job shared by two screens/jobnets is one flow with one owner: the feature its document
    # was saved under, otherwise the first feature by id. The other features do not list it.
    owners: dict[str, str] = {}
    # Screens, jobs and entries people assigned own a shared flow before the API/routine's own feature.
    for feature_id in sorted(features, key=lambda value: (
            features[value]["entry_type"] not in entry_kinds and not features[value]["extra_entries"], value)):
        for entry in [*features[feature_id]["flow_entries"], *features[feature_id]["extra_entries"]]:
            flow_id = f"flow:{entry}"
            stored = docs.get(flow_id)
            if stored and stored["feature_id"] == feature_id:
                owners[flow_id] = feature_id
            else:
                owners.setdefault(flow_id, feature_id)
    for feature in features.values():
        flows = []
        for entry in dict.fromkeys([*feature["flow_entries"], *feature["extra_entries"]]):
            flow_id = f"flow:{entry}"
            if owners.get(flow_id) != feature["id"]:
                continue
            stored = docs.pop(flow_id, None)
            flows.append(_flow_item(flow_id, (stored or {}).get("doc") or None, index.nodes[entry], feature["id"]))
        feature["children"] = flows

    # Flows imported for a feature under an id the graph no longer proposes; documents whose feature is gone
    # after a re-extract are kept reachable under their own menu so nobody's text is lost.
    stranded = []
    for flow_id, stored in docs.items():
        if stored["feature_id"] in features:
            features[stored["feature_id"]]["children"].append(_flow_item(flow_id, stored["doc"], None, stored["feature_id"]))
        else:
            stranded.append(_flow_item(flow_id, stored["doc"], None, stored["feature_id"]))

    assigned = {node_id for entries in extra_entries.values() for node_id in entries}
    unassigned = sorted(
        (node_id for node_id in index.by_type.get("API_OPERATION", []) if node_id not in reached and node_id not in assigned),
        key=lambda value: index.nodes[value]["technical_name"],
    )
    # A large system can have thousands; the tree lists the first ones, search finds the rest.
    orphans = []
    for node_id in unassigned[:MAX_UNASSIGNED]:
        orphan = {"id": f"entry:{node_id}", "kind": "entry", "name": ref_name(index.nodes[node_id]), "node_id": node_id,
                  "node_type": index.nodes[node_id]["node_type"]}
        _apply_item(orphan, items.get(orphan["id"]))
        orphans.append(orphan)

    for feature in features.values():
        _apply_item(feature, items.get(feature["id"]))
        parent = feature["parent_id"]
        if parent not in menus:
            menu(parent, _title(parent.split(":", 1)[-1]), "user")
        menus[parent]["children"].append(feature)
    for menu_item in list(menus.values()):
        _apply_item(menu_item, items.get(menu_item["id"]))
        if menu_item["parent"] in menus:
            menus[menu_item["parent"]]["children"].append(menu_item)
    for menu_item in menus.values():
        # Groups keep their fixed order; sections, features and menus people made sort by name.
        menu_item["children"].sort(key=lambda child: (
            child["kind"] != "menu", child.get("sort_order") or 0, child.get("order", 0), child["name"].lower()))
    # Systems by name, so renaming a menu does not move it.
    ordered = sorted((m for m in menus.values() if m["parent"] not in menus),
                     key=lambda m: (m.get("sort_order") or 0, m["id"]))
    if stranded:
        ordered.append({"id": STRANDED_MENU, "kind": "menu", "name": "Tài liệu không còn tính năng", "source": "graph",
                        "stranded": True, "children": stranded})
    ordered.append({"id": UNSORTED_MENU, "kind": "menu", "name": "API chưa có màn hình / job gọi tới", "source": "graph",
                    "unsorted": True, "children": orphans, "total": len(unassigned)})
    for item in ordered:
        _summarize(item)
    return {"menus": ordered, "graph_nodes": len(index.nodes)}


def _flow_item(flow_id: str, doc: dict[str, Any] | None, entry: dict[str, Any] | None, feature_id: str) -> dict[str, Any]:
    name = (doc or {}).get("name") or (entry["display_name"] if entry else flow_id)
    return {
        "id": flow_id, "kind": "flow", "name": name, "feature_id": feature_id, "has_doc": bool(doc),
        "entry_node_id": entry["node_id"] if entry else None, "parts": _parts(doc or {}),
        "summary": ((doc or {}).get("summary") or {}).get("text", ""),
    }


def _apply_item(target: dict[str, Any], item: dict[str, Any] | None) -> None:
    target.setdefault("description", "")
    target.setdefault("status", None)
    if not item:
        return
    for key in ("name", "description", "status", "reviewed_by", "sort_order"):
        if item.get(key) not in (None, ""):
            target[key] = item[key]
    if item.get("parent_id") and target["kind"] == "feature":
        target["parent_id"] = item["parent_id"]


def _summarize(item: dict[str, Any]) -> None:
    flows = list(_flows_under(item))
    item["flow_count"] = len(flows)
    item["parts"] = [status for flow in flows for status in (flow["parts"] or ["none"])]
    for child in item.get("children", []):
        if child["kind"] in {"menu", "feature"}:
            _summarize(child)


def _flows_under(item: dict[str, Any]):
    if item["kind"] == "flow":
        yield item
    for child in item.get("children", []):
        yield from _flows_under(child)


def find_item(tree: dict[str, Any], item_id: str) -> dict[str, Any] | None:
    stack = list(tree["menus"])
    while stack:
        item = stack.pop()
        if item["id"] == item_id:
            return item
        stack.extend(item.get("children", []))
    return None
