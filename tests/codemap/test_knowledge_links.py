"""Hand-made links, the AI export's call trace / re-split steps / AI links (in use at once), and sharing knowledge."""
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


def test_share_knowledge_between_two_people(client, pack, paths):
    flow = _flow_with_entry(client)
    rule = client.post(f"{API}/business/rules", json={"title": "Đơn đã giao không được hủy", "domain": "ORD"}, headers=WHO)
    assert rule.status_code == 201
    target = _outside_node(client, flow)
    client.post(f"{API}/business/links", json={"source": flow["entry_node_id"], "target": target, "edge_type": "CALLS"}, headers=WHO)
    client.patch(f"{API}/business/flows/{flow['flow']['id']}/parts/summary", json={"name": "Tạo đơn", "text": "Viết bởi An."}, headers=WHO)

    response = client.get(f"{API}/business/knowledge/export")
    assert response.status_code == 200
    assert "attachment" in response.headers["Content-Disposition"] and ".codemap-knowledge.json" in response.headers["Content-Disposition"]
    shared = response.get_json()
    assert shared["format"] == "viewer-hub/codemap-knowledge" and shared["pack"]["id"] == "demo"
    assert shared["counts"]["biz_rules"] == 1 and shared["counts"]["biz_links"] == 1 and shared["counts"]["biz_flows"] == 1
    assert "mcp_calls" not in shared["tables"]

    # Another person: empty knowledge, then one local edit that is newer than the file.
    knowledge = paths.user / "codemap" / "demo" / "knowledge.sqlite"
    knowledge.unlink()
    client.patch(f"{API}/business/flows/{flow['flow']['id']}/parts/summary", json={"name": "Tạo đơn", "text": "Bình viết sau."},
                 headers={"X-Code-Map-User": "Binh"})

    check = client.post(f"{API}/business/knowledge/import/check", json={"data": shared, "mode": "newer"}).get_json()
    assert check["ok"] and check["tables"]["biz_rules"]["new"] == 1 and check["tables"]["biz_links"]["new"] == 1
    assert check["tables"]["biz_flows"]["changed"] == 1 and check["tables"]["biz_flows"]["keep"] == 1

    bad = client.post(f"{API}/business/knowledge/import/check", json={"data": {"format": "x"}, "mode": "newer"})
    assert bad.status_code == 400

    applied = client.post(f"{API}/business/knowledge/import", json={"data": shared, "mode": "newer"}).get_json()
    assert applied["backup"].startswith("knowledge-")
    assert (knowledge.parent / "backups" / applied["backup"]).is_file()
    assert len(client.get(f"{API}/business/rules").get_json()) == 1
    assert len(client.get(f"{API}/business/links").get_json()["links"]) == 1
    saved = client.get(f"{API}/business/flows/{flow['flow']['id']}").get_json()
    assert "Bình viết sau." in saved["flow"]["summary"]["text"]  # newer local edit kept
    assert target in {node["node_id"] for node in saved["nodes"]}  # imported link is walked

    # Same file again: nothing new.
    again = client.post(f"{API}/business/knowledge/import/check", json={"data": shared, "mode": "newer"}).get_json()
    assert not again["ok"]

    taken = client.post(f"{API}/business/knowledge/import", json={"data": json.dumps(shared), "mode": "theirs"}).get_json()
    assert taken["tables"]["biz_flows"]["take"] == 1
    saved = client.get(f"{API}/business/flows/{flow['flow']['id']}").get_json()
    assert "Viết bởi An." in saved["flow"]["summary"]["text"]
    with sqlite3.connect(knowledge) as db:
        assert json.loads(db.execute("SELECT value FROM knowledge_meta WHERE key='last_import'").fetchone()[0])["mode"] == "theirs"


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
    assert set(status["open"]) == {"rules_needs_review", "questions_open", "decisions_proposed"}

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
