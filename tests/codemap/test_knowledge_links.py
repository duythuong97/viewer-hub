"""Hand-made links, the AI export's call trace / re-split steps / AI links (in use at once), the AI feature overview."""
from __future__ import annotations

import json
import sqlite3

import pytest
import yaml

from tests.codemap.test_codemap import API, _install_pack, needs_demo

pytestmark = needs_demo
WHO = {"X-Code-Map-User": "An"}


@pytest.fixture()
def pack(app, paths):
    return _install_pack(app, paths)


def _items(tree, kind):
    found, stack = [], list(tree["menus"])
    while stack:
        item = stack.pop()
        if item["kind"] == kind:
            found.append(item)
        stack.extend(item.get("children") or [])
    return found


def _flow_with_entry(client):
    tree = client.get(f"{API}/business/tree").get_json()
    for flow in _items(tree, "flow"):
        body = client.get(f"{API}/business/flows/{flow['id']}").get_json()
        if body["entry_node_id"] and len(body["nodes"]) > 2:
            return body
    pytest.skip("demo has no flow with an entry")


def _outside_node(client, flow):
    """A node the flow does not reach (target for a new CALLS link)."""
    inside = {node["node_id"] for node in flow["nodes"]}
    for query in ("procedure", "Service", "PKG", "api"):
        for hit in client.get(f"{API}/business/search?q={query}").get_json()["nodes"]:
            if hit["id"] not in inside:
                return hit["id"]
    pytest.skip("no node outside the flow")


def test_link_joins_a_node_into_the_flow(client, pack):
    flow = _flow_with_entry(client)
    source = flow["entry_node_id"]
    target = _outside_node(client, flow)

    bad = client.post(f"{API}/business/links", json={"source": source, "target": source, "edge_type": "CALLS"}, headers=WHO)
    assert bad.status_code == 400
    bad = client.post(f"{API}/business/links", json={"source": source, "target": target, "edge_type": "DROP_TABLE"}, headers=WHO)
    assert bad.status_code == 400

    created = client.post(f"{API}/business/links", json={"source": source, "target": target, "edge_type": "CALLS",
                                                         "note": "gọi qua tên động"}, headers=WHO)
    assert created.status_code == 200, created.get_data(as_text=True)
    link = created.get_json()["link"]
    assert link["status"] == "approved" and link["origin"] == "user" and link["created_by"] == "An"

    after = client.get(f"{API}/business/flows/{flow['flow']['id']}").get_json()
    assert target in {node["node_id"] for node in after["nodes"]}
    manual = [edge for edge in after["edges"] if edge.get("manual")]
    assert manual and manual[0]["source"] == source and manual[0]["target"] == target

    listed = client.get(f"{API}/business/links?node={target}").get_json()
    assert [row["link_id"] for row in listed["links"]] == [link["link_id"]]
    assert "CALLS" in listed["types"]["calls"]

    # No approval: a link has no status to change, only its note; deleting it is how it stops being walked.
    assert client.patch(f"{API}/business/links/{link['link_id']}", json={"status": "proposed"}, headers=WHO).status_code == 400
    noted = client.patch(f"{API}/business/links/{link['link_id']}", json={"note": "qua reflection"}, headers=WHO).get_json()
    assert noted["link"]["note"] == "qua reflection"

    assert client.delete(f"{API}/business/links/{link['link_id']}").status_code == 200
    again = client.get(f"{API}/business/flows/{flow['flow']['id']}").get_json()
    assert not any(edge.get("manual") for edge in again["edges"])
    assert client.get(f"{API}/business/links").get_json()["links"] == []
    assert client.delete(f"{API}/business/links/{link['link_id']}").status_code == 404


def _export(client, feature_id):
    response = client.post(f"{API}/business/features/{feature_id}/ai-export?instructions=0")
    assert response.status_code == 200, response.get_data(as_text=True)
    body = response.get_json()
    return body, yaml.safe_load(body["text"])


def test_ai_export_has_trace_and_import_resplits_steps(client, pack):
    flow = _flow_with_entry(client)
    feature_id = flow["feature_id"]
    body, data = _export(client, feature_id)
    assert data["links"] == []
    traces = {trace["flow"]: trace["path"] for trace in data["context"]["traces"]}
    path = traces[flow["flow"]["id"]]
    assert path[0].startswith("1 ") and any(line.startswith("1.1 ") for line in path)
    numbers = [line.split(" ", 1)[0] for line in path]
    assert numbers == sorted(numbers, key=lambda head: [int(part) for part in head.split(".")])
    assert body["stats"]["trace_lines"] >= len(path)

    refs = [node["ref"] for node in data["context"]["nodes"]]
    exported = next(item for item in data["flows"] if item["id"] == flow["flow"]["id"])
    flow_refs = [ref for step in exported["steps"] for ref in step["nodes"]]
    half = max(1, len(flow_refs) // 2)
    exported["name"] = "Luồng thử"
    exported["summary"] = {"text": "Tóm tắt."}
    exported["steps"] = [
        {"id": "", "nodes": flow_refs[:half], "name": "Bắt đầu", "actor": "Người dùng", "text": "Bước một.", "rules": []},
        {"id": "", "nodes": flow_refs[half:] or flow_refs[:1], "name": "Xử lý", "actor": "Hệ thống", "text": "Bước hai.", "rules": []},
    ]
    outside = next((ref for ref in refs if ref not in flow_refs), None)
    data["links"] = [{"from": flow_refs[0], "type": "CALLS", "to": "method: KhôngCó.Node", "why": "x"}]
    if outside:
        data["links"].append({"from": flow_refs[0], "type": "CALLS", "to": outside, "why": "gọi động", "evidence": "a.cs:1"})
    text = yaml.safe_dump({"export": data["export"], "flows": [exported], "links": data["links"]}, allow_unicode=True)

    check = client.post(f"{API}/business/features/{feature_id}/ai-import/check", json={"text": text}).get_json()
    messages = " | ".join(line["message"] for line in check["lines"])
    assert check["ok"], messages
    assert "chia lại bước" in messages and "KhôngCó.Node" in messages

    applied = client.post(f"{API}/business/features/{feature_id}/ai-import", json={"text": text}).get_json()
    saved = client.get(f"{API}/business/flows/{flow['flow']['id']}").get_json()["flow"]
    assert [step["name"] for step in saved["steps"]] == ["Bắt đầu", "Xử lý"]
    assert [step["id"] for step in saved["steps"]] == ["s1", "s2"]
    if outside:
        assert applied["applied"]["links"] == 1
        # In use at once, marked as added by AI.
        added = client.get(f"{API}/business/links").get_json()["links"]
        assert added and added[0]["origin"] == "ai" and added[0]["status"] == "approved" and "gọi động" in added[0]["note"]


def test_ai_writes_the_feature_name_and_overview(client, pack):
    flow = _flow_with_entry(client)
    feature_id = flow["feature_id"]
    _body, data = _export(client, feature_id)
    assert data["feature"] == {"name": "", "description": ""}
    data["feature"] = {"name": "Tạo đơn hàng", "description": "Nhân viên nhập đơn mới cho khách."}
    text = yaml.safe_dump({"export": data["export"], "feature": data["feature"], "flows": []}, allow_unicode=True)
    check = client.post(f"{API}/business/features/{feature_id}/ai-import/check", json={"text": text}).get_json()
    assert check["ok"] and any("tổng quan tính năng" in line["message"] for line in check["lines"])
    applied = client.post(f"{API}/business/features/{feature_id}/ai-import", json={"text": text}).get_json()
    assert applied["applied"]["feature"] is True
    item = client.get(f"{API}/business/items/{feature_id}").get_json()
    assert item["name"] == "Tạo đơn hàng" and item["description"].startswith("Nhân viên") and item["status"] == "ai"

    # The next export hands the AI text back to improve; once a person edits it, it is locked and kept.
    _body, again = _export(client, feature_id)
    assert again["feature"]["name"] == "Tạo đơn hàng" and "locked" not in again["feature"]
    client.patch(f"{API}/business/items/{feature_id}", json={"name": "Đặt hàng", "description": "Người viết."})
    _body, locked = _export(client, feature_id)
    assert locked["feature"] == {"locked": True, "name": "Đặt hàng", "description": "Người viết."}
    text = yaml.safe_dump({"export": locked["export"], "feature": {"name": "AI đè", "description": "x"}, "flows": []},
                          allow_unicode=True)
    client.post(f"{API}/business/features/{feature_id}/ai-import", json={"text": text})
    item = client.get(f"{API}/business/items/{feature_id}").get_json()
    assert (item["name"], item["description"], item["status"]) == ("Đặt hàng", "Người viết.", "edited")


def test_locked_step_keeps_the_graph_split(client, pack):
    flow = _flow_with_entry(client)
    step = flow["flow"]["steps"][0]
    client.patch(f"{API}/business/flows/{flow['flow']['id']}/parts/step:{step['id']}",
                 json={"name": "Do người viết", "text": "Sửa tay."}, headers=WHO)
    _body, data = _export(client, flow["feature_id"])
    exported = next(item for item in data["flows"] if item["id"] == flow["flow"]["id"])
    refs = [ref for item in exported["steps"] for ref in item["nodes"]]
    exported["steps"] = [{"id": "", "nodes": refs, "name": "Gộp hết", "actor": "", "text": "x", "rules": []}]
    exported["summary"] = {"text": "Tóm tắt."}
    text = yaml.safe_dump({"export": data["export"], "flows": [exported]}, allow_unicode=True)
    client.post(f"{API}/business/features/{flow['feature_id']}/ai-import", json={"text": text})
    saved = client.get(f"{API}/business/flows/{flow['flow']['id']}").get_json()["flow"]
    assert saved["steps"][0]["name"] == "Do người viết"
    assert len(saved["steps"]) == len(flow["flow"]["steps"])


def _mcp(client, name, arguments):
    from tests.codemap.test_codemap import _rpc

    body = _rpc(client, "tools/call", {"name": name, "arguments": arguments}).get_json()
    assert body["result"]["isError"] is False, body
    return body["result"]["content"][0]["text"]


def _node(client, query, node_type):
    hits = client.get(f"{API}/business/search?q={query}").get_json()["nodes"]
    return next(hit["id"] for hit in hits if hit["node_type"] == node_type)


def test_mcp_trace_and_impact_follow_links(client, pack):
    read = next(hit["id"] for hit in client.get(f"{API}/business/search?q=OrderController").get_json()["nodes"]
                if hit["id"].endswith("OrderController.Read(System.Int64)"))
    create = _node(client, "CREATE_ORDER", "PROCEDURE")
    before = _mcp(client, "codemap_trace_flow", {"entry": "GET /api/orders/{id}"})
    assert "liên kết tay" not in before and "INSERTS" not in before

    link = client.post(f"{API}/business/links", json={"source": read, "target": create, "edge_type": "CALLS"}, headers=WHO).get_json()["link"]
    trace = _mcp(client, "codemap_trace_flow", {"entry": "GET /api/orders/{id}"})
    assert "liên kết tay" in trace and "CREATE_ORDER" in trace
    assert "INSERTS" in trace  # the data the linked procedure writes is now reached

    impact = _mcp(client, "codemap_impact", {"target": "PKG_ORDER.CREATE_ORDER"})
    assert "liên kết tay" in impact

    # A deleted link is no longer walked.
    client.delete(f"{API}/business/links/{link['link_id']}")
    assert "liên kết tay" not in _mcp(client, "codemap_trace_flow", {"entry": "GET /api/orders/{id}"})


def _flow_call(client, node_id, mode, direction, lens):
    from urllib.parse import quote

    response = client.get(f"{API}/flow?node_id={quote(node_id)}&mode={mode}&direction={direction}&lens={lens}")
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def test_lenses_fold_types_and_open_them_on_demand(client, pack):
    method = next(hit["id"] for hit in client.get(f"{API}/business/search?q=OrderRepository.CreateOrder").get_json()["nodes"]
                  if hit["node_type"] == "METHOD")
    run = _flow_call(client, method, "1", "out", "run")
    assert not any(node["node_type"] == "CSHARP_TYPE" for node in run["nodes"])
    assert run["folded"][method]["count"] >= 1 and "CSHARP_TYPE" in run["folded"][method]["kinds"]

    deps = _flow_call(client, method, "1", "out", "deps")
    assert any(node["node_type"] == "CSHARP_TYPE" for node in deps["nodes"]) and deps["folded"] == {}

    opened = _flow_call(client, method, "U", "out", "run")
    assert opened["edges"] and {edge["edge_type"] for edge in opened["edges"]} <= {"USES", "MAPS_TO"}

    # Standing on the class itself, its users are the answer in every lens.
    type_id = next(node["node_id"] for node in deps["nodes"] if node["node_type"] == "CSHARP_TYPE")
    users = _flow_call(client, type_id, "1", "in", "run")
    assert any(edge["edge_type"] == "USES" for edge in users["edges"])

    data = _flow_call(client, method, "E", "out", "data")
    assert data["lens"] == "data" and "paths" in data  # the read/write walk
    assert client.get(f"{API}/flow?node_id=x&mode=E&lens=nope").status_code == 400


def test_flow_page_counts_folded_types(client, pack):
    tree = client.get(f"{API}/business/tree").get_json()
    folded = {}
    for flow in _items(tree, "flow"):
        folded.update(client.get(f"{API}/business/flows/{flow['id']}").get_json()["folded"])
    assert folded and all(entry["count"] > 0 for entry in folded.values())


def test_no_approval_rules_are_in_use_and_old_queue_is_upgraded(client, pack, tmp_path):
    """A rule is in use when saved (by a person or AI); what an older Hub left waiting is in use after the upgrade."""
    import sqlite3

    from viewer_hub.codemap import storage

    rule = client.post(f"{API}/business/rules", json={"title": "Đơn đã giao không được hủy", "evidence": "a.sql:1"},
                       headers=WHO).get_json()
    assert rule["status"] == "approved" and rule["source"] == "sme"
    assert client.get(f"{API}/business/review-queue").status_code == 404
    status = client.get(f"{API}/business/kb-status").get_json()
    assert set(status["open"]) == {"rules_needs_review"}

    knowledge = tmp_path / "old.sqlite"
    with storage.open_knowledge(knowledge) as db:
        db.execute("INSERT INTO kn.biz_rules(rule_id,domain,title,status,source) VALUES('RULE-GEN-001','GEN','x','draft','ai')")
        db.execute("INSERT INTO kn.biz_links(link_id,source_id,target_id,edge_type,status) VALUES('l1','a','b','CALLS','proposed')")
        db.execute("DELETE FROM kn.knowledge_meta WHERE key='no_review'")
        db.commit()
    with storage.open_knowledge(knowledge):
        pass
    raw = sqlite3.connect(knowledge)
    assert raw.execute("SELECT status FROM biz_rules").fetchone()[0] == "approved"
    assert raw.execute("SELECT status FROM biz_links").fetchone()[0] == "approved"
    raw.close()


def test_person_notes_on_a_node(client, pack):
    flow = _flow_with_entry(client)
    node = flow["entry_node_id"]
    created = client.post(f"{API}/business/notes", json={"node": node, "text": "Màn hình nhập đơn."}, headers=WHO).get_json()["note"]
    assert created["by_ai"] is False and created["edited_by"] == "An" and created["changed"] is False
    assert [note["text"] for note in client.get(f"{API}/business/notes?node={node}").get_json()["notes"]] == ["Màn hình nhập đơn."]
    edited = client.patch(f"{API}/business/notes/{created['id']}", json={"text": "Màn hình nhập đơn mới."}).get_json()["note"]
    assert edited["text"] == "Màn hình nhập đơn mới."
    assert client.post(f"{API}/business/notes", json={"node": "no-such-node", "text": "x"}).status_code == 404
    assert client.post(f"{API}/business/notes", json={"node": node, "text": "  "}).status_code == 400
    assert client.delete(f"{API}/business/notes/{created['id']}").get_json() == {"ok": True}
    assert client.get(f"{API}/business/notes?node={node}").get_json()["notes"] == []


def test_ai_file_writes_notes_and_keeps_a_persons(client, pack):
    flow = _flow_with_entry(client)
    feature_id = flow["feature_id"]
    _body, data = _export(client, feature_id)
    assert data["notes"] == [] and "notes" not in data["context"]
    first, second = data["context"]["nodes"][0]["ref"], data["context"]["nodes"][1]["ref"]
    ids = {}
    for item in flow["nodes"]:
        ids[item["node_id"]] = item
    by_ref = {}

    def import_notes(notes):
        text = yaml.safe_dump({"export": data["export"], "flows": [], "notes": notes}, allow_unicode=True)
        return client.post(f"{API}/business/features/{feature_id}/ai-import", json={"text": text}).get_json()

    check_text = yaml.safe_dump({"export": data["export"], "flows": [], "notes": [{"node": first, "text": "AI 1."},
                                                                                  {"node": "không có", "text": "x"}]}, allow_unicode=True)
    check = client.post(f"{API}/business/features/{feature_id}/ai-import/check", json={"text": check_text}).get_json()
    assert check["ok"] and any("ghi chú nghiệp vụ" in line["message"] for line in check["lines"])
    assert any(line["level"] == "warn" and "không có" in line["message"] for line in check["lines"])
    assert import_notes([{"node": first, "text": "AI 1."}, {"node": second, "text": "AI trên node thứ hai."}])["applied"]["notes"] == 2

    _body, again = _export(client, feature_id)
    by_ref = {note["node"]: note for note in again["context"]["notes"]}
    assert by_ref[first] == {"node": first, "by": "ai", "text": "AI 1."}
    # A second import rewords the AI's own note instead of adding a copy.
    assert import_notes([{"node": first, "text": "AI 2."}])["applied"]["notes"] == 1
    _body, third = _export(client, feature_id)
    assert [note["text"] for note in third["context"]["notes"] if note["node"] == first] == ["AI 2."]

    # Once a person edits the note it is theirs: the AI's next text is added beside it, never over it.
    rows = client.get(f"{API}/business/notes?node=" + next(
        node_id for node_id in ids if any(n["text"] == "AI 2." for n in client.get(f"{API}/business/notes?node={node_id}").get_json()["notes"])
    )).get_json()["notes"]
    client.patch(f"{API}/business/notes/{rows[0]['id']}", json={"text": "Người viết."})
    import_notes([{"node": first, "text": "AI 3."}])
    _body, fourth = _export(client, feature_id)
    texts = {(note["by"], note["text"]) for note in fourth["context"]["notes"] if note["node"] == first}
    assert texts == {("người", "Người viết."), ("ai", "AI 3.")}


def test_ai_names_and_describes_menus_bottom_up(client, pack):
    tree = client.get(f"{API}/business/tree").get_json()
    menus = [menu for menu in _items(tree, "menu") if not menu.get("unsorted") and menu["id"] not in {"menu:unsorted", "menu:stranded"}]
    system = next(menu for menu in tree["menus"] if menu in menus and any(child["kind"] == "menu" for child in menu["children"]))
    sub = next(child for child in system["children"] if child["kind"] == "menu")
    exported = client.post(f"{API}/business/overview/ai-export?item={system['id']}&instructions=0").get_json()
    data = yaml.safe_load(exported["text"])
    ids = [item["id"] for item in data["items"]]
    assert ids.index(sub["id"]) < ids.index(system["id"])  # deepest first
    assert "evidence" not in exported["text"] and data["context"]["menus"][-1]["id"] == system["id"]

    answer = {"export": data["export"], "items": [{"id": sub["id"], "name": "Dữ liệu đơn hàng", "description": "Các bảng của đơn."},
                                                  {"id": system["id"], "name": "Hệ thống đơn hàng", "description": "Nhận và xử lý đơn."},
                                                  {"id": "menu:khác", "name": "x", "description": "y"}]}
    text = yaml.safe_dump(answer, allow_unicode=True)
    check = client.post(f"{API}/business/overview/ai-import/check", json={"item": system["id"], "text": text}).get_json()
    assert check["ok"] and any(line["level"] == "warn" for line in check["lines"])
    applied = client.post(f"{API}/business/overview/ai-import", json={"item": system["id"], "text": text}).get_json()
    assert applied["applied"]["items"] == 2
    item = client.get(f"{API}/business/items/{system['id']}").get_json()
    assert (item["name"], item["status"]) == ("Hệ thống đơn hàng", "ai")

    # A person's edit locks the menu: the next file leaves it out and an import keeps it.
    client.patch(f"{API}/business/items/{system['id']}", json={"name": "Đơn hàng", "description": "Người viết."})
    again = yaml.safe_load(client.post(f"{API}/business/overview/ai-export?item={system['id']}&instructions=0").get_json()["text"])
    assert system["id"] not in [entry["id"] for entry in again["items"]]
    assert again["context"]["menus"][-1].get("locked") is True
    text = yaml.safe_dump({"export": again["export"], "items": [{"id": system["id"], "name": "AI đè", "description": "x"}]},
                          allow_unicode=True)
    assert client.post(f"{API}/business/overview/ai-import", json={"item": system["id"], "text": text}).status_code == 400
    assert client.get(f"{API}/business/items/{system['id']}").get_json()["name"] == "Đơn hàng"
    # The whole code map: every menu, from a file whose export belongs to it.
    root = client.post(f"{API}/business/overview/ai-export?instructions=0").get_json()
    assert yaml.safe_load(root["text"])["export"]["scope"] == "root" and root["stats"]["menus"] >= len(tree["menus"]) - 2
    wrong = yaml.safe_dump({"export": data["export"], "items": [{"id": sub["id"], "name": "x"}]}, allow_unicode=True)
    assert client.post(f"{API}/business/overview/ai-import/check", json={"item": "", "text": wrong}).get_json()["ok"] is False


def test_overview_shows_when_what_it_summarises_changed(client, pack):
    flow = _flow_with_entry(client)
    feature_id = flow["feature_id"]
    _body, data = _export(client, feature_id)
    exported = next(item for item in data["flows"] if item["id"] == flow["flow"]["id"])
    text = yaml.safe_dump({"export": data["export"], "feature": {"name": "Tạo đơn", "description": "Tổng quan."},
                           "flows": [{"id": exported["id"], "summary": {"text": "Tóm tắt AI."}}]}, allow_unicode=True)
    client.post(f"{API}/business/features/{feature_id}/ai-import", json={"text": text})
    item = client.get(f"{API}/business/items/{feature_id}").get_json()
    assert item["description"] == "Tổng quan." and not item.get("children_changed")  # written with its flows
    # A person rewrites the flow summary: the overview no longer matches what it summarises.
    client.patch(f"{API}/business/flows/{flow['flow']['id']}/parts/summary", json={"text": "Người viết lại tóm tắt."})
    assert client.get(f"{API}/business/items/{feature_id}").get_json()["children_changed"] is True
    confirmed = client.patch(f"{API}/business/items/{feature_id}", json={"confirm": True}).get_json()
    item = client.get(f"{API}/business/items/{feature_id}").get_json()
    assert not item.get("children_changed") and item["status"] == "ai", confirmed


def test_gaps_page_links_or_dismisses_a_gap(client, pack):
    body = client.get(f"{API}/business/gaps?limit=50").get_json()
    assert body["total"] >= 1 and body["types"]["calls"]
    assert all(gap["type"] != "TABLE_NOT_IMPORTED" for gap in body["items"])  # missing input is the admin's job
    gap = body["items"][0]
    assert gap["source"]["address"] and " › " in gap["source"]["address"]
    assert client.post(f"{API}/business/gaps/dismiss", json={"gap": gap["id"]}, headers=WHO).get_json() == {"ok": True}
    after = client.get(f"{API}/business/gaps?limit=50").get_json()
    assert gap["id"] not in {item["id"] for item in after["items"]} and after["total"] == body["total"] - 1
    client.post(f"{API}/business/gaps/dismiss", json={"gap": gap["id"], "undo": True})
    assert client.get(f"{API}/business/gaps?limit=50").get_json()["total"] == body["total"]
    # "Nối": a link whose note names the gap closes it.
    linkable = next((item for item in body["items"] if item.get("candidates")), None)
    if linkable is None:
        pytest.skip("demo has no gap with a candidate")
    target = linkable["candidates"][0]
    reply = client.post(f"{API}/business/links", json={"source": linkable["source"]["node_id"], "target": target["node_id"],
                                                      "edge_type": "CALLS", "note": f"Nối từ chỗ hở · [gap {linkable['id']}]"}, headers=WHO)
    if reply.status_code != 200:
        pytest.skip(f"demo candidate cannot take a CALLS link: {reply.get_json()}")
    assert linkable["id"] not in {item["id"] for item in client.get(f"{API}/business/gaps?limit=50").get_json()["items"]}
    assert client.post(f"{API}/business/gaps/dismiss", json={"gap": ""}).status_code == 400


def test_search_shows_the_address_and_why_it_matched(client, pack):
    nodes = client.get(f"{API}/business/search?q=ORDER_HEADER").get_json()["nodes"]
    assert nodes and nodes[0]["label"] == "ORDER_HEADER"
    assert " › table › " in nodes[0]["address"] and nodes[0]["address"].endswith("ORDER_HEADER") and nodes[0]["reason"]
    by_address = client.get(f"{API}/business/search", query_string={"q": nodes[0]["address"]}).get_json()["nodes"]
    assert by_address[0]["id"] == nodes[0]["id"] and by_address[0]["reason"] == "đúng id / địa chỉ"
