"""Node names people and AI write → nodes (business/resolve.py), and links found again after a re-extract."""
from __future__ import annotations

import sqlite3

import pytest

from viewer_hub.codemap.business import links
from viewer_hub.codemap.business.common import KNOWLEDGE_SCHEMA
from viewer_hub.codemap.business.graph import GraphIndex, apply_links
from viewer_hub.codemap.business.resolve import NameIndex, full_name

SAVE = "Api.csproj|global::Shop.Data.OrderRepository|M:Shop.Data.OrderRepository.Save(Shop.Order)"
NODES = [
    # node_id, type, technical, qualified, repository, database
    ("m:save:1", "METHOD", "Save", SAVE, "order-api", ""),
    ("m:save:2", "METHOD", "Save", SAVE.replace("(Shop.Order)", "(Shop.Order,System.Boolean)"), "order-api", ""),
    ("m:load", "METHOD", "Load", "Api.csproj|global::Shop.Data.OrderRepository|M:Shop.Data.OrderRepository.Load", "order-api", ""),
    ("m:create", "METHOD", "CreateOrder", "Api.csproj|global::Shop.Api.OrderController|M:Shop.Api.OrderController.CreateOrder",
     "order-api", ""),
    ("m:batch", "METHOD", "Load", "Batch.csproj|global::Shop.Batch.OrderJob|M:Shop.Batch.OrderJob.Load", "batch", ""),
    ("p:create", "PROCEDURE", "CREATE_ORDER", "DB1.PKG_ORDER.CREATE_ORDER(NUMBER)", "", "DB1"),
    ("t:order", "TABLE", "T_ORDER", "DB1.APP.T_ORDER", "", "DB1"),
    ("c:app", "ANGULAR_COMPONENT", "AppComponent", "order-web-src.AppComponent", "order-web", ""),
    ("u:order", "UNRESOLVED_REFERENCE", "T_ORDER", "T_ORDER", "", "DB1"),
]


def _graph(nodes=NODES) -> sqlite3.Connection:
    db = sqlite3.connect(":memory:", uri=True)  # uri: a knowledge db can be attached read-only (file:…?mode=ro)
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE graph_nodes(node_id,node_type,technical_name,qualified_name,default_display_name,"
               "properties_json,system_key,database_key,repository_key)")
    db.execute("CREATE TABLE graph_edges(edge_id,source_node_id,target_node_id,edge_type,graph_layer)")
    db.executemany("INSERT INTO graph_nodes VALUES(?,?,?,?,?,'{}','',?,?)",
                   [(node_id, kind, name, qualified, name, database, repository)
                    for node_id, kind, name, qualified, repository, database in nodes])
    return db


@pytest.fixture()
def lookup() -> NameIndex:
    return NameIndex(GraphIndex(_graph()), [("p:create", "ja:注文登録; en:Create order")])


def test_full_name_drops_project_file_and_source(lookup):
    assert full_name(lookup.index.nodes["m:save:1"]) == ("Shop.Data.OrderRepository.Save", "(Shop.Order)")
    assert full_name(lookup.index.nodes["p:create"]) == ("PKG_ORDER.CREATE_ORDER", "(NUMBER)")
    assert lookup.address["t:order"] == "DB1 › table › APP.T_ORDER"
    assert lookup.address["c:app"] == "order-web › angular_component › AppComponent"
    # Overloads keep their parameter list; a name with one node does not.
    assert lookup.address["m:save:2"] == "order-api › method › Shop.Data.OrderRepository.Save(Shop.Order,System.Boolean)"
    assert lookup.address["m:load"] == "order-api › method › Shop.Data.OrderRepository.Load"


@pytest.mark.parametrize("query, node_id, level", [
    ("m:load", "m:load", 1),
    ("order-api › method › Shop.Data.OrderRepository.Load", "m:load", 1),
    ("method: Shop.Data.OrderRepository.Load", "m:load", 2),
    ("OrderRepository.Load", "m:load", 2),  # Class.method, the short name documents use
    ("Data.OrderRepository.Load", "m:load", 3),
    ("procedure: PKG_ORDER.CREATE_ORDER", "p:create", 2),
    ("CREATE_ORDER", "p:create", 2),
    ("table: T_ORDER", "t:order", 2),  # the placeholder of the same name is never meant without its type
    ("注文登録", "p:create", 4),
    ("OrderControler.CreatOrder", "m:create", 5),
    ({"table": "APP.T_ORDER"}, "t:order", 2),
    ("order-web › angular_component › AppComponent", "c:app", 1),
    ("order-web › angular_component › AppComponnt", "c:app", 5),  # a type without a short key, misspelled
])
def test_levels(lookup, query, node_id, level):
    result = lookup.resolve(query)
    assert (result.status, result.node_id, result.level) == ("match", node_id, level), result.message()


def test_shared_names_give_candidates_or_the_near_one(lookup):
    result = lookup.resolve("Load")
    assert result.status == "ambiguous" and {c.node_id for c in result.candidates} == {"m:load", "m:batch"}
    assert "batch › method › Shop.Batch.OrderJob.Load" in result.message()
    near = lookup.resolve("Load", near=["m:batch"])
    assert (near.status, near.node_id) == ("match", "m:batch") and "cùng luồng" in near.reason
    assert lookup.resolve("batch › method › Load").node_id == "m:batch"  # the system in the address decides
    assert lookup.resolve("Save").status == "ambiguous"
    assert lookup.resolve("unresolved: T_ORDER").node_id == "u:order"
    assert lookup.resolve("NO_SUCH_THING").status == "none"
    assert lookup.resolve("Data.OrderRepository.Load", max_level=2).status == "none"


def _knowledge(db: sqlite3.Connection) -> None:
    db.execute("ATTACH DATABASE ':memory:' AS kn")
    db.executescript(KNOWLEDGE_SCHEMA)


def test_link_is_found_again_after_the_node_id_changes():
    db = _graph()
    _knowledge(db)
    before = GraphIndex(db)
    link = links.create_link(db, before, {"source": "m:create", "target": "m:load", "edge_type": "CALLS"}, "An")
    assert link["target"]["address"] == "order-api › method › Shop.Data.OrderRepository.Load"
    lost = links.create_link(db, before, {"source": "m:create", "target": "m:batch", "edge_type": "CALLS"}, "An")

    # Re-extract: the repository moved to another file (new id); the batch job was renamed to OrderJob.Lode.
    moved = [(("m:load:new",) + row[1:]) if row[0] == "m:load" else row for row in NODES if row[0] != "m:batch"]
    moved.append(("m:batch:new", "METHOD", "Lode", "Batch.csproj|global::Shop.Batch.OrderJob|M:Shop.Batch.OrderJob.Lode",
                  "batch", ""))
    db2 = _graph(moved)
    db2.execute("ATTACH DATABASE ':memory:' AS kn")
    db2.executescript(KNOWLEDGE_SCHEMA)
    for table in ("biz_links", "biz_link_moves"):
        rows = db.execute(f"SELECT * FROM kn.{table}").fetchall()
        if rows:
            db2.executemany(f"INSERT INTO kn.{table} VALUES({','.join('?' * len(rows[0]))})", [tuple(row) for row in rows])
    after = GraphIndex(db2)
    apply_links(db2, after)

    rows = {row["link_id"]: row for row in links.list_links(db2, after)}
    found = rows[link["link_id"]]
    assert found["target"]["node_id"] == "m:load:new" and not found["target"]["missing"]
    assert found["target"]["moved"]["old_ref"] == "order-api › method › Shop.Data.OrderRepository.Load"
    assert ("m:load:new", "CALLS", f"link:{link['link_id']}") in after.edges_from("m:create")

    # A close spelling is only offered: the person picks it.
    gone = rows[lost["link_id"]]
    assert gone["target"]["missing"] and [c["node_id"] for c in gone["target"]["candidates"]] == ["m:batch:new"]
    picked = links.update_link(db2, after, lost["link_id"], {"target": "m:batch:new"}, "An")
    assert picked["target"]["node_id"] == "m:batch:new" and "moved" not in picked["target"]

    confirmed = links.update_link(db2, after, link["link_id"], {"confirm": True}, "An")
    assert "moved" not in confirmed["target"]
    with pytest.raises(Exception):
        links.update_link(db2, after, link["link_id"], {"status": "proposed"}, "An")


def test_read_only_knowledge_leaves_links_for_a_writable_open(tmp_path):
    path = tmp_path / "kn.sqlite"
    db = _graph()
    db.execute("ATTACH DATABASE ? AS kn", (str(path),))
    db.executescript(KNOWLEDGE_SCHEMA)
    link = links.create_link(db, GraphIndex(db), {"source": "m:create", "target": "m:load", "edge_type": "CALLS"}, "An")
    db.close()

    nodes = [(("m:load:new",) + row[1:]) if row[0] == "m:load" else row for row in NODES]
    reader = _graph(nodes)
    reader.execute("ATTACH DATABASE ? AS kn", (f"{path.as_uri()}?mode=ro",))
    index = GraphIndex(reader)
    apply_links(reader, index)
    assert reader.execute("SELECT target_id FROM kn.biz_links").fetchone()[0] == "m:load"

    writer = _graph(nodes)
    writer.execute("ATTACH DATABASE ? AS kn", (str(path),))
    apply_links(writer, index)  # same graph index: the failed read-only attempt does not block it
    assert writer.execute("SELECT target_id FROM kn.biz_links WHERE link_id=?", (link["link_id"],)).fetchone()[0] == "m:load:new"


def test_mcp_writes_take_names_and_stop_on_a_shared_one(tmp_path):
    from types import SimpleNamespace

    from viewer_hub.codemap.mcp import write_tools
    from viewer_hub.codemap.storage import SERVING_DATABASE_NAME

    path = tmp_path / SERVING_DATABASE_NAME
    with sqlite3.connect(path) as built:
        built.executescript("".join(f"{line};" for line in _graph().iterdump() if line.startswith(("CREATE", "INSERT"))))
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    workspace = SimpleNamespace(output=tmp_path)
    assert write_tools._node_ids(workspace, db, ["OrderControler.CreatOrder", "table: T_ORDER", "m:load"]) == \
        ["m:create", "t:order", "m:load"]
    answer = write_tools._node_ids(workspace, db, ["Load"])  # sent back to the agent, nothing written
    assert isinstance(answer, str) and answer.startswith("Nothing was written")
    assert "batch › method › Shop.Batch.OrderJob.Load" in answer


def test_address_contract_is_the_code_map_copy():
    """Viewer Hub computes the addresses the extract stores (graph_node_addresses): the two files must not drift."""
    from pathlib import Path

    import pytest

    ours = Path(__file__).resolve().parents[2] / "viewer_hub" / "codemap" / "contract" / "addresses.py"
    theirs = Path(__file__).resolve().parents[3] / "code-map" / "extractor" / "code_tree_exporter" / "contract" / "addresses.py"
    if not theirs.is_file():
        pytest.skip("code-map checkout not next to viewer-hub")
    copied = ours.read_text(encoding="utf-8").split("\n", 2)[2]
    assert copied == theirs.read_text(encoding="utf-8")[3:], "copy code-map contract/addresses.py again"


def test_gap_noise_is_never_offered():
    from viewer_hub.codemap.business.gaps import is_noise

    columns = {"ORDER_ID", "STATUS"}
    for name in ("DBMS_OUTPUT.PUT_LINE", "UTL_FILE.FOPEN", "NVL", "TO_CHAR", "L_RESULT.OBJECTS.EXISTS", "v_count",
                 "P_ORDER_ID", "status", ""):
        assert is_noise(name, columns), name
    for name in ("PKG_ORDER.SAVE_ORDER", "ORDER_ARCHIVE", "LOAD_DAILY", "ORDER_HEADER.ORDER_ID"):
        assert not is_noise(name, columns), name
