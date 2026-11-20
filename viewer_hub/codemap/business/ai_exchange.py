"""AI export / import: the YAML pack an AI fills in, checked against the graph before it is kept."""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable

import yaml

from viewer_hub.codemap.knowledge import safe_citations
from viewer_hub.codemap.levels import keeps
from .common import (
    BusinessError, CONDITION_KINDS, INSTRUCTIONS, MAX_CONDITIONS_PER_NODE, MAX_EVIDENCE_CHARS,
    MAX_FEATURE_NODES, MAX_FLOW_NODES, RULE_STATUSES, TERMINAL_TYPES, _BlockDumper, _json, _now,
)
from .edits import _begin, _save_flow, _stored_or_skeleton
from .flows import _chunks, _path, node_facts
from .graph import GraphIndex, apply_links, feature_labels, graph_hash, ref_name, ref_of
from .links import check_link, create_link
from .resolve import names
from .tree import find_item


def _graph_sqlite(web_path: Path) -> Path:
    return web_path.parent / "graph.sqlite"


def _engine_extras(web_path: Path, node_ids: list[str]) -> tuple[dict[str, list[dict]], dict[str, list[str]]]:
    """Conditions from semantic trees and source comments, which only graph.sqlite has."""
    conditions: dict[str, list[dict]] = {}
    comments: dict[str, list[str]] = {}
    path = _graph_sqlite(web_path)
    if not path.is_file() or not node_ids:
        return conditions, comments
    try:
        with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as graph:
            for chunk in _chunks(node_ids, 400):
                marks = ",".join("?" * len(chunk))
                for stable_id, properties in graph.execute(
                    f"SELECT stable_id,properties_json FROM nodes WHERE stable_id IN ({marks})", chunk
                ):
                    found = _conditions(_json(properties, {}).get("semantic_tree"))
                    if found:
                        conditions[stable_id] = found
                for stable_id, text in graph.execute(
                    f"""SELECT n.stable_id,c.normalized_text FROM comments c JOIN nodes n ON n.node_id=c.owner_node_id
                        WHERE n.stable_id IN ({marks}) ORDER BY c.start_line""", chunk,
                ):
                    if text and text.strip():
                        comments.setdefault(stable_id, []).append(text.strip()[:400])
    except sqlite3.Error:
        return {}, {}
    return conditions, comments


def _conditions(tree: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if len(found) >= MAX_CONDITIONS_PER_NODE:
            return
        if isinstance(value, dict):
            kind = value.get("type")
            if kind in CONDITION_KINDS:
                text = value.get("condition") or value.get("label") or value.get("text") or ""
                if isinstance(text, (dict, list)):
                    text = json.dumps(text, ensure_ascii=False)[:200]
                # The extractor writes `source: {path, line}`; older trees used `line`/`location`.
                source = value.get("source") if isinstance(value.get("source"), dict) else {}
                location = value.get("location") if isinstance(value.get("location"), dict) else {}
                line = value.get("line") or value.get("start_line") or source.get("line") or location.get("line")
                found.append({"kind": kind, "text": str(text)[:300], **({"line": line} if line else {})})
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(tree)
    return found


MAX_TRACE_LINES = 200


def flow_trace(index: GraphIndex, entry: str | None, labels: dict[str, tuple[str, str]], limit: int = MAX_TRACE_LINES) -> list[str]:
    """The call order of a flow, depth first from its entry: ``1.2.1 CALLS → procedure: PKG.X``.

    Steps are built from this order, so it is what lets an AI tell "first the screen sends, then the API checks,
    then the procedure writes" apart. A node met again is named once more with where it was first expanded.
    """
    if not entry or entry not in index.nodes:
        return []
    name = lambda node_id: labels[node_id][0] if node_id in labels else ref_of(index.nodes[node_id])  # noqa: E731
    lines: list[str] = []
    where: dict[str, str] = {}
    # (node, number, edge type, manual); the first child is on top so it is walked first.
    stack: list[tuple[str, str, str, bool]] = [(entry, "1", "", False)]
    while stack:
        if len(lines) >= limit:
            lines.append("… (cắt bớt)")
            break
        node_id, number, kind, manual = stack.pop()
        head = f"{number} {kind} → " if kind else f"{number} "
        tag = " [liên kết tay]" if manual else ""
        if node_id in where:
            lines.append(f"{head}{name(node_id)} (đã có ở {where[node_id]}){tag}")
            continue
        where[node_id] = number
        lines.append(f"{head}{name(node_id)}{tag}")
        if index.nodes[node_id]["node_type"] in TERMINAL_TYPES:
            continue
        children = [(target, edge_type, edge_id) for target, edge_type, edge_id in index.edges_from(node_id)
                    if index._ok(target, edge_type, edge_id)]
        for position, (target, edge_type, edge_id) in reversed(list(enumerate(children, start=1))):
            stack.append((target, f"{number}.{position}", edge_type, edge_id.startswith("link:")))
    return lines


def export_pack(db: sqlite3.Connection, index: GraphIndex, tree: dict[str, Any], web_path: Path, feature_id: str,
                *, include_code: bool = True, include_locked: bool = True, include_answers: bool = True,
                include_instructions: bool = True) -> dict[str, Any]:
    feature = find_item(tree, feature_id)
    if not feature or feature["kind"] != "feature":
        raise BusinessError("not_found", "Feature not found", 404)
    node_ids = index.reach([feature["entry_node_id"], *feature.get("extra_entries", [])], MAX_FEATURE_NODES)
    facts = node_facts(db, index, node_ids)
    labels = feature_labels(index, node_ids)
    for node_id, (ref, name) in labels.items():
        facts[node_id]["ref"], facts[node_id]["name"] = ref, name
    edges = index.edges_within(node_ids)
    evidence: dict[str, dict[str, str]] = {}
    if include_code:
        for chunk in _chunks(node_ids, 400):
            marks = ",".join("?" * len(chunk))
            for target, source_path, line, snippet in db.execute(
                f"""SELECT target_id,source_path,start_line,snippet FROM graph_evidence
                    WHERE target_type='NODE' AND target_id IN ({marks}) AND snippet<>'' ORDER BY evidence_id""", chunk,
            ):
                name = facts[target]["name"]
                if name not in evidence:
                    evidence[name] = {"at": f"{source_path}:{line}" if line else source_path, "code": snippet[:MAX_EVIDENCE_CHARS]}
    conditions, comments = _engine_extras(web_path, node_ids) if include_code else ({}, {})
    nodes = []
    for node_id in node_ids:
        fact = facts[node_id]
        entry = {"ref": fact["ref"]}
        if fact["file"]:
            entry["file"] = f"{fact['file']}:{fact['line']}" if fact["line"] else fact["file"]
        if fact["term"]:
            entry["term"] = fact["term"]
        for locale in ("ja", "en"):
            if fact["names"].get(locale):
                entry[locale] = fact["names"][locale]
        if node_id in conditions:
            entry["conditions"] = conditions[node_id]
        if node_id in comments:
            entry["comments"] = comments[node_id][:5]
        nodes.append(entry)

    flows, locked, answered, traces = [], 0, [], []
    for item in feature["children"]:
        doc = _stored_or_skeleton(db, index, item)
        exported, count = _export_flow(index, doc, item, include_locked, labels)
        locked += count
        flows.append(exported)
        trace = flow_trace(index, item.get("entry_node_id"), labels)
        if trace:
            traces.append({"flow": item["id"], "name": exported["name"] or item["name"], "path": trace})
        if include_answers:
            answered += [{"q": q["text"], "a": q["answer"]} for q in doc.get("questions", []) if q.get("answer")]

    count = db.execute("SELECT COUNT(*) FROM kn.biz_exports").fetchone()[0]
    export_id = f"exp-{count + 1:04d}-{uuid.uuid4().hex[:8]}"
    current_hash = graph_hash(web_path)
    db.execute("INSERT INTO kn.biz_exports(export_id,feature_id,graph_hash,created_at) VALUES(?,?,?,?)",
               (export_id, feature_id, current_hash, _now()))
    db.commit()
    path = " / ".join(step["name"] for step in _path(tree, feature_id))
    pack = {
        "export": {"id": export_id, "feature_id": feature_id, "feature": path, "graph_hash": current_hash, "generated": _now()},
        "context": {
            "feature": {"name": feature["name"], "route": feature["route"], "entry": labels[feature["entry_node_id"]][0],
                        "description": feature.get("description", "")},
            "traces": traces,
            "nodes": nodes,
            "edges": [[facts[e["source"]]["name"], e["edge_type"], facts[e["target"]]["name"], *(["tay"] if e.get("manual") else [])]
                      for e in edges],
            **({"evidence": evidence} if include_code else {}),
            **({"answered": answered} if answered else {}),
        },
        "flows": flows,
        "links": [],
    }
    slug = re.sub(r"[^a-z0-9]+", "-", feature["route"].lower()).strip("-") or "feature"
    dump = lambda value: yaml.dump(value, Dumper=_BlockDumper, allow_unicode=True, sort_keys=False, width=100)
    if include_instructions:
        # One instruction file: the guide, the data, and the YAML block the AI fills in and sends back.
        text = (f'# Hướng dẫn cho AI · viết tài liệu nghiệp vụ cho tính năng "{path}"\n\n{INSTRUCTIONS}\n'
                "# Dữ liệu\n\nChỉ để đọc, không trả về phần này.\n\n"
                f"```yaml\n{dump({'context': pack['context']})}```\n\n"
                "# Định dạng trả về\n\nĐiền các trường trống trong khối dưới đây và trả về đúng một khối YAML này.\n\n"
                f"```yaml\n{dump({'export': pack['export'], 'flows': pack['flows'], 'links': []})}```\n")
        filename = f"{slug}.codemap-ai.md"
    else:
        text = (f'# Code Map · tính năng "{feature["name"]}". `context` là dữ liệu; `flows` là định dạng trả về.\n'
                + dump(pack))
        filename = f"{slug}.codemap-ai.yaml"
    return {"export_id": export_id, "filename": filename, "text": text,
            "stats": {"nodes": len(nodes), "edges": len(edges), "evidence": len(evidence), "locked": locked, "flows": len(flows),
                      "trace_lines": sum(len(trace["path"]) for trace in traces)}}


def _export_flow(index: GraphIndex, doc: dict[str, Any], item: dict[str, Any], include_locked: bool,
                 labels: dict[str, tuple[str, str]]) -> tuple[dict, int]:
    locked = 0

    def part(source: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
        nonlocal locked
        if include_locked and source.get("status") in {"edited", "approved"}:
            locked += 1
            return {"locked": True, **body}
        return {key: [] if isinstance(value, list) else "" for key, value in body.items()}

    def names(node_ids: list[str]) -> list[str]:
        return [labels[node_id][0] if node_id in labels else ref_of(index.nodes[node_id]) for node_id in node_ids if node_id in index.nodes]

    summary = doc.get("summary") or {}
    steps = []
    for step in doc.get("steps", []):
        steps.append({"id": step["id"], "nodes": names(step.get("nodes", [])), **part(step, {
            "name": step.get("name", ""), "actor": step.get("actor", ""), "text": step.get("text", ""),
            "rules": [{**{key: rule.get(key, "") for key in ("title", "at", "evidence", "status", "text")},
                       "citations": rule.get("citations") or []} for rule in step.get("rules", [])],
            "citations": step.get("citations") or [],
        })})
    edge_cases = doc.get("edge_cases") or {}
    return {
        "id": item["id"], "name": doc.get("name") or ("" if not item["has_doc"] else item["name"]),
        "entry": names([item["entry_node_id"]])[0] if item.get("entry_node_id") in index.nodes else "",
        "summary": part(summary, {"text": summary.get("text", "")}),
        "steps": steps,
        "edge_cases": part(edge_cases, {"items": edge_cases.get("items", [])}) if edge_cases.get("items") else {"items": []},
        "questions": [],
    }, locked


_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
_SafeLoader = _YAML_LOADER  # the name packaging/check_security.py looks for


def _load_yaml(text: str) -> Any:
    """safe_load without anchors/aliases: an alias chain is a few bytes that expand to gigabytes once stored."""
    for event in yaml.parse(text, Loader=_SafeLoader):
        if isinstance(event, yaml.AliasEvent) or getattr(event, "anchor", None):
            raise BusinessError("invalid_import", "File dùng anchor/alias YAML (&, *). Hãy dán YAML thường.")
    return yaml.load(text, Loader=_SafeLoader)


def _parse_pack(text: Any) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise BusinessError("invalid_import", "Dán nội dung file AI trả về")
    text = text.replace("\r\n", "\n")
    for block in re.findall(r"```(?:ya?ml)?[ \t]*\n(.*?)```", text, flags=re.S):
        try:
            doc = _load_yaml(block)
        except yaml.YAMLError:
            continue
        if isinstance(doc, dict) and isinstance(doc.get("flows"), list):
            return doc
    try:
        doc = _load_yaml(text)
    except yaml.YAMLError as exc:
        first = str(exc).splitlines()[0] if str(exc) else "YAML error"
        raise BusinessError("invalid_import", f"YAML sai cú pháp: {first}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("flows"), list):
        raise BusinessError("invalid_import", "Không thấy phần flows. Hãy dán toàn bộ file AI trả về.")
    return doc


def _str(value: Any, limit: int) -> str:
    """Text the AI wrote; numbers are fine, anything structured is dropped rather than stringified."""
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (int, float)):
        value = str(value)
    return value.strip()[:limit] if isinstance(value, str) else ""


def _strs(value: Any, limit: int, most: int) -> list[str]:
    """A list of texts; a single text where a list was expected counts as a one-item list."""
    values = [value] if isinstance(value, str) else value if isinstance(value, list) else []
    return [text for text in (_str(item, limit) for item in values[:most]) if text]


def _resolver(index: GraphIndex, node_ids: list[str]):
    """ref → node of this feature: the labels the export used first, then the shared resolver (``resolve.py``),
    which also takes full names, the end of a name and close spellings. A node outside the feature is no match."""
    by_ref: dict[str, list[str]] = {}
    by_name: dict[str, list[str]] = {}
    for node_id, (ref, name) in feature_labels(index, node_ids).items():
        node = index.nodes[node_id]
        for key in {ref, ref_of(node)}:
            by_ref.setdefault(key, []).append(node_id)
        for key in {name, ref_name(node)}:
            by_name.setdefault(key, []).append(node_id)
    pool = set(node_ids)
    lookup = names(index)

    def resolve(value: Any) -> str | None:
        if isinstance(value, dict) and len(value) == 1:
            key, name = next(iter(value.items()))
            value = f"{key}: {name}"
        text = _str(value, 1000)
        matches = by_ref.get(text, [])
        if len(set(matches)) == 1:
            return matches[0]
        name = text.split(":", 1)[1].strip() if re.match(r"^[a-z_]+:\s", text) else text
        matches = by_name.get(name, [])
        if len(set(matches)) == 1:
            return matches[0]
        found = lookup.resolve(text, near=pool).node_id
        return found if found in pool else None

    return resolve


def check_import(db: sqlite3.Connection, index: GraphIndex, tree: dict[str, Any], web_path: Path, feature_id: str,
                 text: Any) -> dict[str, Any]:
    feature = find_item(tree, feature_id)
    if not feature or feature["kind"] != "feature":
        raise BusinessError("not_found", "Feature not found", 404)
    return _check(db, index, feature, web_path, _parse_pack(text))


def _check(db: sqlite3.Connection, index: GraphIndex, feature: dict[str, Any], web_path: Path, pack: dict[str, Any]) -> dict[str, Any]:
    feature_id = feature["id"]
    lines: list[dict[str, str]] = []
    blocking = False
    export = pack.get("export") if isinstance(pack.get("export"), dict) else {}
    row = db.execute("SELECT feature_id,graph_hash FROM kn.biz_exports WHERE export_id=?", (str(export.get("id", "")),)).fetchone()
    if not export.get("id"):
        lines.append({"level": "error", "message": "Thiếu export.id, không biết file thuộc lần xuất nào"}); blocking = True
    elif not row:
        lines.append({"level": "error", "message": f"Không có lần xuất {export['id']} trong Code Map"}); blocking = True
    elif row[0] != feature_id:
        lines.append({"level": "error", "message": f"File thuộc lần xuất {export['id']} của tính năng khác"}); blocking = True
    else:
        lines.append({"level": "ok", "message": f"Đúng tính năng · lần xuất {export['id']}"})
        if row[1] == graph_hash(web_path):
            lines.append({"level": "ok", "message": "Graph chưa đổi kể từ lúc xuất"})
        else:
            # Steps of a flow nobody saved yet are numbered from the current graph, so after a re-extract the
            # ids in the file may point at different steps. Those flows need a fresh export.
            unsaved = [item["name"] for item in feature["children"] if not item["has_doc"]
                       and any(isinstance(flow, dict) and flow.get("id") == item["id"] for flow in pack["flows"])]
            if unsaved:
                lines.append({"level": "error", "message": "Graph đã đổi kể từ lúc xuất và các luồng sau chưa từng được lưu, "
                              f"các bước có thể đã lệch: {', '.join(unsaved)}. Hãy xuất lại."}); blocking = True
            else:
                lines.append({"level": "warn", "message": "Graph đã đổi kể từ lúc xuất. Nên xuất lại để AI viết trên code mới."})

    node_ids = index.reach([feature["entry_node_id"], *feature.get("extra_entries", [])], MAX_FEATURE_NODES)
    names(index, db)  # built with the logical (ja / en) names of the search index when first used here
    resolve = _resolver(index, node_ids)
    known_flows = {item["id"] for item in feature["children"]}
    filled = kept = questions = 0
    bad: dict[str, None] = {}
    for flow in pack["flows"]:
        if not isinstance(flow, dict):
            continue
        if not isinstance(flow.get("id"), str) or flow["id"] not in known_flows:
            lines.append({"level": "warn", "message": f"Luồng {flow.get('id')!r} không thuộc tính năng này, sẽ bỏ qua"})
            continue
        questions += len(_strs(flow.get("questions"), 2000, 50))
        edge = flow.get("edge_cases") if isinstance(flow.get("edge_cases"), dict) else {}
        if not edge.get("locked") and _strs(edge.get("items"), 4000, 100):
            filled += 1
        steps = flow.get("steps") if isinstance(flow.get("steps"), list) else []
        for part in [flow.get("summary"), *steps]:
            if not isinstance(part, dict):
                continue
            if part.get("locked"):
                kept += 1
                continue
            rules = [rule for rule in part.get("rules") or [] if isinstance(rule, dict)] if isinstance(part.get("rules"), list) else []
            if _str(part.get("text"), 50_000) or _str(part.get("name"), 200) or rules:
                filled += 1
            for name in re.findall(r"\[\[(.+?)\]\]", _str(part.get("text"), 50_000)):
                if resolve(name) is None:
                    bad[name] = None
            for rule in rules:
                if rule.get("at") and resolve(rule["at"]) is None:
                    bad[_str(rule["at"], 400)] = None
                if not _str(rule.get("evidence"), 400):
                    lines.append({"level": "warn", "message": f"Quy tắc “{_str(rule.get('title'), 400)}” không có evidence, sẽ được đánh dấu “Cần xác nhận”"})
    lines.append({"level": "ok", "message": f"{filled} phần được AI điền"})
    if kept:
        lines.append({"level": "ok", "message": f"{kept} phần khoá được giữ nguyên"})
    if bad:
        lines.append({"level": "error", "message": f"{len(bad)} tham chiếu không có trong graph của tính năng: {', '.join(bad)}. Sẽ hiện là tham chiếu hỏng để bạn sửa."})
    if questions:
        lines.append({"level": "ok", "message": f"{questions} câu hỏi mới"})
    regrouped = [flow.get("id") for flow in pack["flows"] if isinstance(flow, dict) and flow.get("id") in known_flows
                 and isinstance(flow.get("steps"), list) and flow["steps"]
                 and all(isinstance(step, dict) and isinstance(step.get("nodes"), list) for step in flow["steps"])
                 and any(isinstance(step, dict) and not step.get("id") for step in flow["steps"])]
    if regrouped:
        lines.append({"level": "ok", "message": f"AI chia lại bước cho {len(regrouped)} luồng (luồng có bước đã khoá giữ cách chia cũ)"})
    links, bad_links = _ai_links(index, pack, resolve, node_ids)
    if links:
        lines.append({"level": "ok", "message": f"{len(links)} liên kết AI thêm, dùng ngay (đánh dấu AI thêm)"})
    for reason in bad_links[:10]:
        lines.append({"level": "warn", "message": f"Bỏ qua liên kết {reason}"})
    return {"ok": not blocking and filled + questions + len(links) > 0, "lines": lines}


def apply_import(db: sqlite3.Connection, index: GraphIndex, tree: dict[str, Any], web_path: Path, feature_id: str,
                 text: Any) -> dict[str, Any]:
    feature = find_item(tree, feature_id)
    if not feature or feature["kind"] != "feature":
        raise BusinessError("not_found", "Feature not found", 404)
    pack = _parse_pack(text)
    result = _check(db, index, feature, web_path, pack)
    if not result["ok"]:
        reasons = "; ".join(line["message"] for line in result["lines"] if line["level"] == "error")
        raise BusinessError("invalid_import", "File chưa nhập được: " + (reasons or "không có nội dung mới"))
    node_ids = index.reach([feature["entry_node_id"], *feature.get("extra_entries", [])], MAX_FEATURE_NODES)
    names(index, db)  # built with the logical (ja / en) names of the search index when first used here
    resolve = _resolver(index, node_ids)
    items = {item["id"]: item for item in feature["children"]}
    applied_parts = 0
    applied_flows = []
    _begin(db)
    for flow in pack["flows"]:
        if not isinstance(flow, dict) or not isinstance(flow.get("id"), str) or flow["id"] not in items:
            continue
        item = items[flow["id"]]
        doc = _stored_or_skeleton(db, index, item)
        pool = set(node_ids)
        if item.get("entry_node_id"):
            pool.update(index.reach([item["entry_node_id"]], MAX_FLOW_NODES))
        changed = _merge_flow(doc, flow, resolve, pool, index)
        if changed:
            doc["export_id"] = _str((pack.get("export") if isinstance(pack.get("export"), dict) else {}).get("id"), 100)
            doc["imported_at"] = _now()
            _save_flow(db, item["id"], feature_id, doc)
            applied_parts += changed
            applied_flows.append(item["id"])
    added = 0
    for link in _ai_links(index, pack, resolve, node_ids)[0]:

        try:
            create_link(db, index, link, "AI", origin="ai", commit=False)
            added += 1
        except BusinessError:
            continue  # already in the graph, or not a valid link: reported by the check
    db.commit()
    apply_links(db, index)
    return {**result, "applied": {"flows": applied_flows, "parts": applied_parts, "links": added}}


def _ai_links(index: GraphIndex, pack: dict[str, Any], resolve, near: Iterable[str] = ()) -> tuple[list[dict[str, Any]], list[str]]:
    """Links the AI proposes (``links:`` at the end of the file): usable ones, and why the others are not."""

    raw = pack.get("links") if isinstance(pack.get("links"), list) else []
    lookup = names(index)
    good, bad = [], []
    for link in raw[:200]:
        if not isinstance(link, dict):
            continue
        source_ref, target_ref = _str(link.get("from"), 400), _str(link.get("to"), 400)
        # A missing link often points outside the feature: the whole graph is searched, the feature's nodes first.
        ends = [resolve(ref) or lookup.resolve(ref, near=near) for ref in (source_ref, target_ref)]
        problems = [end.message() for end in ends if not isinstance(end, str) and end.status != "match"]
        if problems:
            bad.append(f"{source_ref} → {target_ref}: " + "; ".join(problems))
            continue
        source, target = (end if isinstance(end, str) else end.node_id for end in ends)
        edge_type = _str(link.get("type"), 40).upper() or "CALLS"
        try:
            check_link(index, source, target, edge_type)
        except BusinessError as exc:
            bad.append(f"{source_ref} → {target_ref}: {exc.message}")
            continue
        if any(t == target and kind == edge_type for t, kind, _ in index.out.get(source, ())):
            continue  # the graph has it already
        note = " · ".join(part for part in (_str(link.get("why"), 1000), _str(link.get("evidence"), 400)) if part)
        good.append({"source": source, "target": target, "edge_type": edge_type, "note": note})
    return good, bad


def _restructure(doc: dict[str, Any], incoming: list[Any], resolve, pool: set[str], index: GraphIndex | None) -> int | None:
    """The AI's own split of the flow into steps (each with ``nodes``), used when no step is locked.

    Returns the number of steps written, or None when the file keeps the graph's split (same steps, same nodes)
    or cannot be used, in which case the steps are filled in place."""
    locked = {"edited", "approved"}
    if any(step.get("status") in locked for step in doc.get("steps", [])):
        return None
    steps = [step for step in incoming if isinstance(step, dict)]
    if not steps or not all(isinstance(step.get("nodes"), list) for step in steps):
        return None
    built, taken = [], set()
    for step in steps:
        node_ids = []
        for ref in step["nodes"][:MAX_FLOW_NODES]:
            node_id = resolve(ref)
            if node_id and node_id in pool and node_id not in taken:
                taken.add(node_id)
                node_ids.append(node_id)
        rules = [rule for rule in step.get("rules") or [] if isinstance(rule, dict)] if isinstance(step.get("rules"), list) else []
        text, name = _str(step.get("text"), 50_000), _str(step.get("name"), 200)
        if not node_ids and not (text or name):
            continue
        built.append({"nodes": node_ids, "name": name, "actor": _str(step.get("actor"), 200), "text": text,
                      "rules": [_import_rule(rule, resolve) for rule in rules[:50]],
                      "citations": safe_citations(step.get("citations"))})
    if not built or not taken:
        return None
    current = [list(step.get("nodes", [])) for step in doc.get("steps", [])]
    if [step["nodes"] for step in built] == current:
        return None
    doc["steps"] = [{
        "id": f"s{position}",
        "system": index.nodes[step["nodes"][0]]["system"] if index and step["nodes"] else "",
        "status": "ai", **step,
    } for position, step in enumerate(built, start=1)]
    return len(built)


def _merge_flow(doc: dict[str, Any], flow: dict[str, Any], resolve, pool: set[str] | None = None,
                index: GraphIndex | None = None) -> int:
    """Write what AI produced for one flow into its document; parts a person edited stay as they are.
    With ``pool`` (the nodes the flow may use) the AI may also re-split the steps when none is locked.
    Returns the number of parts written."""
    locked = {"edited", "approved"}
    changed = 0
    summary_now = doc.setdefault("summary", {"text": "", "status": "ai"})
    if _str(flow.get("name"), 200) and summary_now.get("status") not in locked:
        doc["name"] = _str(flow.get("name"), 200)
    summary = flow.get("summary") if isinstance(flow.get("summary"), dict) else {}
    if _str(summary.get("text"), 50_000) and not summary.get("locked") and summary_now.get("status") not in locked:
        doc["summary"] = {"text": _str(summary.get("text"), 50_000), "status": "ai"}
        changed += 1
    raw_steps = flow.get("steps") if isinstance(flow.get("steps"), list) else []
    restructured = _restructure(doc, raw_steps, resolve, pool, index) if pool else None
    if restructured is not None:
        changed += restructured
    incoming = {} if restructured is not None else {
        step["id"]: step for step in raw_steps if isinstance(step, dict) and isinstance(step.get("id"), str)}
    for step in doc.get("steps", []):
        new = incoming.get(step["id"])
        if not new or new.get("locked") or step.get("status") in locked:
            continue
        rules = [rule for rule in new.get("rules") or [] if isinstance(rule, dict)] if isinstance(new.get("rules"), list) else []
        if not (_str(new.get("name"), 200) or _str(new.get("text"), 50_000) or rules):
            continue
        # The step's nodes come from the graph (or a person); the AI only writes about them.
        step.update({
            "name": _str(new.get("name"), 200) or step.get("name", ""),
            "actor": _str(new.get("actor"), 200) or step.get("actor", ""),
            "text": _str(new.get("text"), 50_000),
            "status": "ai",
            "rules": [_import_rule(rule, resolve) for rule in rules[:50]],
            "citations": safe_citations(new.get("citations")),
        })
        changed += 1
    edge = flow.get("edge_cases") if isinstance(flow.get("edge_cases"), dict) else {}
    edge_items = _strs(edge.get("items"), 4000, 100)
    if edge_items and not edge.get("locked") and doc.get("edge_cases", {}).get("status") not in locked:
        doc["edge_cases"] = {"items": edge_items, "status": "ai"}
        changed += 1
    existing = {q.get("text") for q in doc.get("questions", [])}
    for question in _strs(flow.get("questions"), 2000, 50):
        if question not in existing:
            existing.add(question)
            doc.setdefault("questions", []).append({"id": f"q{len(doc['questions']) + 1}", "text": question, "answer": ""})
            changed += 1
    return changed


def flow_document(db: sqlite3.Connection, index: GraphIndex, tree: dict[str, Any], flow_id: str) -> dict[str, Any]:
    """A flow as an agent fills it: the stored document (or the graph's skeleton) with step ids, node refs,
    and which parts are locked because a person edited them."""
    item = find_item(tree, flow_id)
    if not item or item["kind"] != "flow":
        raise BusinessError("not_found", "Flow not found", 404)
    doc = _stored_or_skeleton(db, index, item)
    node_ids = list(dict.fromkeys(node for step in doc.get("steps", []) for node in step.get("nodes", [])))
    labels = feature_labels(index, node_ids)
    exported, _ = _export_flow(index, doc, item, True, labels)
    return {"flow": exported, "feature_id": item["feature_id"], "has_doc": item["has_doc"]}


def propose_flow(db: sqlite3.Connection, index: GraphIndex, tree: dict[str, Any], flow_id: str, flow: Any,
                 who: str) -> dict[str, Any]:
    """An agent's draft for one flow (same shape as an exported flow), stored as "AI viết · chưa duyệt"."""
    item = find_item(tree, flow_id)
    if not item or item["kind"] != "flow":
        raise BusinessError("not_found", "Flow not found", 404)
    if not isinstance(flow, dict):
        raise BusinessError("invalid_business", "document must be an object with summary, steps, edge_cases, questions")
    _begin(db)
    doc = _stored_or_skeleton(db, index, item)
    node_ids = list(dict.fromkeys(node for step in doc.get("steps", []) for node in step.get("nodes", [])))
    if item.get("entry_node_id"):
        node_ids = list(dict.fromkeys([*node_ids, *index.reach([item["entry_node_id"]], MAX_FLOW_NODES)]))
    resolve = _resolver(index, node_ids)
    locked = [step.get("id") for step in doc.get("steps", []) if step.get("status") in {"edited", "approved"}]
    changed = _merge_flow(doc, {**flow, "id": flow_id}, resolve, set(node_ids), index)
    texts = [str((flow.get("summary") or {}).get("text") or "") if isinstance(flow.get("summary"), dict) else ""]
    texts += [str(step.get("text") or "") for step in flow.get("steps") or [] if isinstance(step, dict)]
    unresolved = sorted({name for text in texts for name in re.findall(r"\[\[(.+?)\]\]", text) if resolve(name) is None})
    no_evidence = sorted({str(rule.get("title") or "") for step in flow.get("steps") or [] if isinstance(step, dict)
                          for rule in step.get("rules") or [] if isinstance(rule, dict)
                          and not rule.get("evidence") and not safe_citations(rule.get("citations"))})
    if changed:
        doc["proposed_by"], doc["proposed_at"] = who, _now()
        _save_flow(db, flow_id, item["feature_id"], doc)
    db.commit()
    return {"flow_id": flow_id, "parts_written": changed, "locked_steps_kept": locked,
            "unresolved_citations": unresolved, "rules_without_evidence": no_evidence}


def _import_rule(rule: dict[str, Any], resolve) -> dict[str, Any]:
    at = _str(rule.get("at"), 400)
    evidence = _str(rule.get("evidence"), 400)
    cited = safe_citations(rule.get("citations"))
    status = rule.get("status") if isinstance(rule.get("status"), str) and rule.get("status") in RULE_STATUSES else "warn"
    if not evidence and not cited:
        status = "warn"
    item = {"title": _str(rule.get("title"), 400), "text": _str(rule.get("text"), 8000),
            "at": at, "at_node_id": resolve(at) if at else None, "evidence": evidence, "status": status}
    if cited:
        item["citations"] = cited
    return item
