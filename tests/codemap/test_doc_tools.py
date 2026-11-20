"""MCP tools for a documentation-aware agent: gaps, name resolution, links / notes / answers with citations."""
from __future__ import annotations

import json
import re
import shutil
import sqlite3

import pytest

from tests.codemap.test_codemap import DEMO, FILES, needs_demo
from viewer_hub.codemap import knowledge
from viewer_hub.codemap.mcp.server import CallContext, McpServer
from viewer_hub.codemap.storage import open_knowledge, open_web
from viewer_hub.codemap.workspace import Workspace

pytestmark = needs_demo
CITE = [{"doc": "注文登録画面設計書.xlsx", "section": "3.2 イベント定義", "quote": "保存ボタン押下で注文を登録する"}]
ARCHIVE = "OrderRepository.ArchiveLegacy"
SUMMARY = "ORDER_DAILY_SUMMARY"


@pytest.fixture()
def workspace(tmp_path):
    output = tmp_path / "codemap"
    output.mkdir()
    for name in FILES:
        if (DEMO / name).is_file():
            shutil.copy2(DEMO / name, output / name)
    return Workspace(output=output, knowledge=tmp_path / "knowledge.sqlite")


def call(workspace, tool, arguments, user="copilot-studio"):
    server = McpServer(workspace)
    reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}},
                          CallContext(user=user, allow_write=True))
    result = reply["result"]
    return result["content"][0]["text"], result["isError"]


def rows(workspace, sql, params=()):
    with sqlite3.connect(workspace.knowledge) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute(sql, params)]


def link(**overrides):
    return {"source": ARCHIVE, "target": SUMMARY, "edge_type": "INSERTS", "reason": "Theo thiết kế, lưu trữ ghi tổng hợp ngày.",
            "citations": CITE, "confidence": 0.7, "gap_id": "issue:demo", **overrides}


# --------------------------------------------------------------------------- reads

def test_resolve_exact_ambiguous_none(workspace):
    text, error = call(workspace, "codemap_resolve", {"names": ["ORDER_HEADER", "CreateOrder", "nothing_like_this_xyz"]})
    assert not error
    assert "`ORDER_HEADER` → exact" in text and "table:DB1:ORDER_HEADER" in text
    assert "`CreateOrder` → ambiguous" in text
    assert "`nothing_like_this_xyz` → none" in text
    narrowed, _ = call(workspace, "codemap_resolve", {"names": ["CreateOrder"], "type": "PROCEDURE"})
    assert "→ exact: PROCEDURE CREATE_ORDER" in narrowed
    too_many, error = call(workspace, "codemap_resolve", {"names": [f"n{i}" for i in range(21)]})
    assert error and "at most 20" in too_many


def test_gaps_lists_flows_and_links(workspace):
    text, error = call(workspace, "codemap_knowledge_gaps", {"kind": "all", "limit": 50})
    assert not error
    assert "[flow:" in text and "no documentation yet" in text
    assert "DYNAMIC_SQL" in text and "candidate:" in text
    # Missing input (a table outside the catalog) is the admin's job, not a document's.
    assert "TABLE_NOT_IMPORTED" not in text and "ORDER_ARCHIVE_TMP" not in text
    assert "question" not in text.lower()  # no questions for a person: the Hub runs on one person's machine
    only_links, _ = call(workspace, "codemap_knowledge_gaps", {"kind": "link"})
    assert "## Flow documentation" not in only_links
    bad, error = call(workspace, "codemap_knowledge_gaps", {"kind": "question"})
    assert error


def test_gap_closed_by_a_link_is_gone(workspace):
    text, _ = call(workspace, "codemap_knowledge_gaps", {"kind": "link", "limit": 50})
    gap_id = next(line.split("]")[0][3:] for line in text.splitlines() if line.startswith("- [issue:") and "DYNAMIC_SQL" in line)
    reply, error = call(workspace, "codemap_propose_link", {"links": [link(gap_id=gap_id)]})
    assert not error and "created" in reply
    assert gap_id not in call(workspace, "codemap_knowledge_gaps", {"kind": "link", "limit": 50})[0]


# --------------------------------------------------------------------------- links

def test_ambiguous_reference_writes_nothing(workspace):
    text, error = call(workspace, "codemap_propose_link", {"links": [link(), link(source="CreateOrder", target="ORDER_HEADER")]})
    assert not error
    assert text.startswith("Nothing was written") and "`CreateOrder` → ambiguous" in text and "id `" in text
    assert rows(workspace, "SELECT * FROM biz_links") == []


def test_link_without_citations_is_rejected(workspace):
    for citations in (None, [], [{"doc": "spec.xlsx"}], [{"doc": "a", "section": "b", "quote": "x" * 201}],
                      [{"doc": "a", "section": "b", "url": "javascript:alert(1)"}]):
        text, error = call(workspace, "codemap_propose_link", {"links": [link(citations=citations)]})
        assert error, citations
    assert rows(workspace, "SELECT * FROM biz_links") == []


def test_resend_updates_and_a_persons_link_is_untouched(workspace):
    first, error = call(workspace, "codemap_propose_link", {"links": [link()]})
    assert not error and "created lnk-" in first and "in use" in first and "review" not in first
    [stored] = rows(workspace, "SELECT * FROM biz_links")
    assert stored["status"] == "approved" and stored["origin"] == "ai" and stored["created_by"] == "copilot-studio"
    assert json.loads(stored["citations_json"]) == CITE and "[gap issue:demo]" in stored["note"]

    again, _ = call(workspace, "codemap_propose_link", {"links": [link(reason="Lý do mới", gap_id="")]})
    [updated] = rows(workspace, "SELECT * FROM biz_links")
    assert f"updated {stored['link_id']}" in again and updated["note"].startswith("Lý do mới")
    assert "[ngoài điểm gãy]" in updated["note"] and "not tied to a gap" in again

    with sqlite3.connect(workspace.knowledge) as db:
        db.execute("UPDATE biz_links SET origin='user', created_by='An'")  # as if a person had added it
    third, _ = call(workspace, "codemap_propose_link", {"links": [link(reason="AI ghi đè")]})
    [kept] = rows(workspace, "SELECT * FROM biz_links")
    assert "rejected" in third and kept["note"] == updated["note"] and kept["origin"] == "user"


def test_ai_link_is_walked_at_once(workspace):
    call(workspace, "codemap_propose_link", {"links": [link()]})
    text, error = call(workspace, "codemap_impact", {"target": SUMMARY})
    assert not error and "ArchiveLegacy" in text


def test_link_checks_edge_type_and_extract(workspace):
    text, error = call(workspace, "codemap_propose_link", {"links": [link(edge_type="DROPS")]})
    assert error
    text, error = call(workspace, "codemap_propose_link", {"links": [link(target="OrderRepository.CancelOrder")]})
    assert not error and "rejected" in text  # INSERTS only goes to data
    assert rows(workspace, "SELECT * FROM biz_links") == []


# --------------------------------------------------------------------------- notes, answers, rules

def test_note_on_a_node(workspace):
    text, error = call(workspace, "codemap_propose_note", {"node": "ORDER_HEADER", "text": "Bảng đầu đơn hàng.", "citations": CITE})
    assert not error and "Created note" in text
    again, _ = call(workspace, "codemap_propose_note", {"node": "table:DB1:ORDER_HEADER", "text": "Bảng đầu đơn hàng."})
    assert "Updated note" in again
    [note] = rows(workspace, "SELECT * FROM graph_knowledge")
    assert note["status"] == "approved" and note["target_id"] == "table:DB1:ORDER_HEADER" and note["created_by"] == "copilot-studio"
    ambiguous, _ = call(workspace, "codemap_propose_note", {"node": "CreateOrder", "text": "x"})
    assert ambiguous.startswith("Nothing was written")
    assert len(rows(workspace, "SELECT * FROM graph_knowledge")) == 1
    with sqlite3.connect(workspace.knowledge) as db:  # a person's note with the same text is left alone
        db.execute("INSERT INTO graph_knowledge(target_id,body,status) VALUES('table:DB1:ORDER_LINE','Dòng đơn.','approved')")
    kept, _ = call(workspace, "codemap_propose_note", {"node": "table:DB1:ORDER_LINE", "text": "Dòng đơn.", "citations": CITE})
    assert "nothing changed" in kept
    assert rows(workspace, "SELECT created_by, citations_json FROM graph_knowledge WHERE target_id='table:DB1:ORDER_LINE'") == [
        {"created_by": "", "citations_json": "[]"}]


def test_rule_needs_evidence_or_citations(workspace):
    neither, error = call(workspace, "codemap_propose_rule", {"title": "Đơn đã giao không huỷ được", "nodes": ["ORDER_HEADER"]})
    assert error and "citations" in neither
    cited, error = call(workspace, "codemap_propose_rule", {"title": "Đơn đã giao không huỷ được", "nodes": ["ORDER_HEADER"],
                                                            "citations": CITE, "domain": "ORD"})
    assert not error and "RULE-ORD-001" in cited and "source doc" in cited
    ambiguous, _ = call(workspace, "codemap_propose_rule", {"title": "x", "nodes": ["CreateOrder"], "citations": CITE})
    assert ambiguous.startswith("Nothing was written")
    [rule] = rows(workspace, "SELECT * FROM biz_rules")
    assert rule["status"] == "approved" and json.loads(rule["citations_json"]) == CITE  # no approval: in use at once


def test_flow_doc_keeps_citations_per_step_and_rule(workspace):
    gaps, _ = call(workspace, "codemap_knowledge_gaps", {"kind": "flow_doc", "limit": 50})
    flow_id = next(line.split("[flow:")[1].split("]")[0] for line in gaps.splitlines() if line.startswith("- [flow:"))
    doc_text, _ = call(workspace, "codemap_get_flow_doc", {"flow": flow_id})
    import yaml

    flow = yaml.safe_load(doc_text.split("```yaml")[1].split("```")[0])["flow"]
    step = flow["steps"][0]
    step.update({"name": "Lưu đơn", "text": "Nhân viên bấm lưu.", "citations": CITE,
                 "rules": [{"title": "Đơn mới ở trạng thái chờ", "citations": CITE, "status": "ok"}]})
    reply, error = call(workspace, "codemap_propose_flow_doc", {"flow_id": flow_id, "document": {"flow": flow}})
    assert not error and "Rules without evidence" not in reply
    [stored] = rows(workspace, "SELECT doc_json FROM biz_flows")
    saved = json.loads(stored["doc_json"])["steps"][0]
    assert saved["citations"] == CITE and saved["rules"][0]["citations"] == CITE and saved["rules"][0]["status"] == "ok"


# --------------------------------------------------------------------------- schema upgrade

OLD_ROWS = """
INSERT INTO kn.biz_rules(rule_id,domain,title,status,source) VALUES('RULE-ORD-001','ORD','Quy tắc cũ','approved','sme');
INSERT INTO kn.biz_questions(question_id,text,status) VALUES('Q-0001','Câu hỏi cũ','open');
INSERT INTO kn.biz_links(link_id,source_id,target_id,edge_type,note,status) VALUES('lnk-old','a','b','CALLS','cũ','approved');
INSERT INTO kn.graph_knowledge(target_id,body,status) VALUES('table:DB1:ORDER_HEADER','Ghi chú cũ','approved');
"""


def _old_schema() -> str:
    """Today's knowledge schema without the columns added later (storage.ADDED_COLUMNS): a db from an older hub."""
    from viewer_hub.codemap import storage

    graph = storage.GRAPH_KNOWLEDGE_SCHEMA.split("CREATE TEMP VIEW", 1)[0]
    schema = graph + storage.BUSINESS_SCHEMA + "".join(storage.EXTRA_SCHEMAS)
    schema = re.sub(r",\s*(citations_json|answer_json) TEXT NOT NULL DEFAULT '[^']*'", "", schema)
    schema = re.sub(r",\s*created_by TEXT NOT NULL DEFAULT '',\s*edited_by TEXT NOT NULL DEFAULT '',fingerprint TEXT NOT NULL DEFAULT ''(?=\);)",
                    "", schema)
    assert "citations_json" not in schema and "answer_json" not in schema
    return schema


def _columns(path, table):
    with sqlite3.connect(path) as db:
        return {row[1] for row in db.execute(f"PRAGMA table_info({table})")}


def test_old_knowledge_db_is_upgraded_and_keeps_data(workspace):
    with sqlite3.connect(":memory:") as db:
        db.execute("ATTACH DATABASE ? AS kn", (str(workspace.knowledge),))
        db.executescript(_old_schema() + OLD_ROWS)
    assert "created_by" not in _columns(workspace.knowledge, "graph_knowledge")
    # A read-only hub cannot upgrade the file, but still reads it.
    with open_web(workspace.output, workspace.knowledge, readonly=True) as db:
        assert knowledge.get_rule(db, "RULE-ORD-001")["citations"] == []
    assert "citations_json" not in _columns(workspace.knowledge, "biz_rules")

    with open_web(workspace.output, workspace.knowledge) as db:  # a writable hub upgrades the file
        assert knowledge.get_rule(db, "RULE-ORD-001")["title"] == "Quy tắc cũ"
    # Questions and decisions are no longer used, but what an older hub stored is kept.
    assert rows(workspace, "SELECT text FROM biz_questions") == [{"text": "Câu hỏi cũ"}]
    for table in ("biz_rules", "biz_questions", "biz_links", "graph_knowledge", "biz_decisions"):
        assert "citations_json" in _columns(workspace.knowledge, table), table
    assert "answer_json" in _columns(workspace.knowledge, "biz_questions")
    assert rows(workspace, "SELECT title FROM biz_rules") == [{"title": "Quy tắc cũ"}]
    assert rows(workspace, "SELECT note, citations_json FROM biz_links") == [{"note": "cũ", "citations_json": "[]"}]
    assert rows(workspace, "SELECT body, created_by FROM graph_knowledge") == [{"body": "Ghi chú cũ", "created_by": ""}]
    # The upgraded db takes the new writes.
    text, error = call(workspace, "codemap_propose_note", {"node": "table:DB1:ORDER_LINE", "text": "Dòng đơn.", "citations": CITE})
    assert not error, text


def test_write_tools_need_the_token_over_http(client, app, paths, monkeypatch):
    from tests.codemap.test_codemap import _install_pack, _rpc

    _install_pack(app, paths)
    monkeypatch.setenv("CODE_MAP_KNOWLEDGE_TOKEN", "secret-token")
    anonymous = {tool["name"] for tool in _rpc(client, "tools/list").get_json()["result"]["tools"]}
    assert {"codemap_resolve", "codemap_knowledge_gaps"} <= anonymous and "codemap_propose_link" not in anonymous
    allowed = {tool["name"] for tool in _rpc(client, "tools/list", **{"X-Code-Map-Token": "secret-token"}).get_json()["result"]["tools"]}
    assert {"codemap_propose_link", "codemap_propose_note"} <= allowed
    assert not {"codemap_propose_answer", "codemap_propose_question", "codemap_propose_decision"} & allowed


def test_agent_writes_a_feature_overview(workspace):
    from viewer_hub.codemap.mcp.write_tools import _business

    with _business(workspace) as (_db, _index, tree):
        stack, feature = list(tree["menus"]), None
        while stack and feature is None:
            item = stack.pop()
            if item["kind"] == "feature" and any(child["kind"] == "flow" for child in item.get("children", [])):
                feature = item
            stack.extend(item.get("children", []))
    assert feature
    text, error = call(workspace, "codemap_get_item_doc", {"feature": feature["id"]})
    assert not error and "codemap_propose_item_doc" in text and "flows:" in text
    empty, error = call(workspace, "codemap_propose_item_doc", {"feature": feature["id"]})
    assert error
    written, error = call(workspace, "codemap_propose_item_doc", {"feature": feature["id"], "name": "Tạo đơn hàng",
                                                                  "description": "Nhân viên nhập đơn mới."})
    assert not error and written.startswith("Wrote"), written
    [row] = rows(workspace, "SELECT name, description, status FROM biz_items WHERE item_id=?", (feature["id"],))
    assert row == {"name": "Tạo đơn hàng", "description": "Nhân viên nhập đơn mới.", "status": "ai"}
    with sqlite3.connect(workspace.knowledge) as db:  # a person edits it: the agent can no longer change it
        db.execute("UPDATE biz_items SET status='edited' WHERE item_id=?", (feature["id"],))
    kept, _ = call(workspace, "codemap_propose_item_doc", {"feature": feature["id"], "description": "AI đè."})
    assert kept.startswith("Nothing was written")
    locked, _ = call(workspace, "codemap_get_item_doc", {"feature": feature["id"]})
    assert "LOCKED" in locked


def test_gaps_list_nodes_with_no_note_and_stale_notes(workspace):
    before, _ = call(workspace, "codemap_knowledge_gaps", {"kind": "note", "limit": 50})
    assert "[note:table:DB1:ORDER_HEADER]" in before and "no business note yet" in before
    call(workspace, "codemap_propose_note", {"node": "ORDER_HEADER", "text": "Bảng đầu đơn hàng.", "citations": CITE})
    after, _ = call(workspace, "codemap_knowledge_gaps", {"kind": "note", "limit": 50})
    assert "[note:table:DB1:ORDER_HEADER]" not in after
    with sqlite3.connect(workspace.knowledge) as db:  # the node changed after the note was written
        db.execute("UPDATE graph_knowledge SET fingerprint='old' WHERE target_id='table:DB1:ORDER_HEADER'")
    stale, _ = call(workspace, "codemap_knowledge_gaps", {"kind": "note", "limit": 50})
    assert "[note:table:DB1:ORDER_HEADER]" in stale and "re-check it" in stale


def test_agent_names_a_menu(workspace):
    from viewer_hub.codemap.mcp.write_tools import _business

    with _business(workspace) as (_db, _index, tree):
        menu = next(item for item in tree["menus"] if not item.get("unsorted") and item["id"].startswith("menu:sys:"))
    text, error = call(workspace, "codemap_get_item_doc", {"feature": menu["id"]})
    assert not error and f"## Menu {menu['id']}" in text and "children:" in text
    written, error = call(workspace, "codemap_propose_item_doc", {"feature": menu["id"], "name": "Hệ thống đơn hàng"})
    assert not error and written.startswith("Wrote"), written
    [row] = rows(workspace, "SELECT name, status FROM biz_items WHERE item_id=?", (menu["id"],))
    assert row == {"name": "Hệ thống đơn hàng", "status": "ai"}
    unsorted, error = call(workspace, "codemap_propose_item_doc", {"feature": "menu:unsorted", "name": "x"})
    assert error


def test_gaps_list_overviews_bottom_up(workspace):
    gaps, error = call(workspace, "codemap_knowledge_gaps", {"kind": "item_doc", "limit": 50})
    assert not error and "## Feature and menu overviews (bottom up)" in gaps
    lines = [line for line in gaps.splitlines() if line.startswith("- [item:")]
    kinds = [line.split("item_doc · ")[1].split(" ")[0] for line in lines]
    assert "feature" in kinds and "menu" in kinds and kinds.index("menu") > kinds.index("feature")
    assert all("no overview yet" in line for line in lines)
