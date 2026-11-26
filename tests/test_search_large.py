"""F-Search on large documents: bounded memory and answers, whatever the size of a document."""
from __future__ import annotations

import json
import tracemalloc
import unicodedata

import pytest

from viewer_hub.fsearch import highlight, mcp, store
from viewer_hub.fsearch.export_solr import write

MB = 1024 * 1024


def p(**kw):
    base = {"query": "", "operator": "OR", "rows": 10, "start": 0, "page": 1, "sort_val": "title asc",
            "repository": [], "file_type": [], "language": "", "date_from": "", "date_to": "", "hl_enabled": True}
    base.update(kw)
    return base


@pytest.fixture(scope="module")
def large_db(tmp_path_factory):
    minified = "var token=1;" * 250_000  # one line of 3 MB
    text = "báo cáo token đăng nhập. " * 120_000  # 3 M characters, Vietnamese
    late = "không có gì ở đây. " * 150_000 + "cuối tài liệu có needle"
    docs = [{"id": f"d{i}", "title": f"doc {i:02d}", "content": late if i >= 10 else text,
             "source_code_content": minified if i < 5 else None, "repository": f"r{i % 4}", "file_type": "js"}
            for i in range(12)]
    target = tmp_path_factory.mktemp("large") / "search.sqlite"
    write(target, ((len(docs), d) for d in docs), "test")
    highlight.matcher(["token"])  # the character table is built once per process: not part of a search's cost
    return target


def measure(call):
    tracemalloc.start()
    try:
        out = call()
        return out, tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


@pytest.mark.parametrize("options", [{}, {"group_by": "repository"}, {"hl_enabled": False}])
def test_search_memory_and_answer_stay_small(large_db, options):
    result, peak = measure(lambda: store.search(large_db, p(query="token", **options)))
    assert result["error"] is None and result["num_found"]
    assert peak < 20 * MB, f"peak {peak / MB:.0f} MB"
    assert len(json.dumps(result)) < MB / 2
    for fields in result["highlighting"].values():
        for snippet in fields.get("content", []) + fields.get("source_code_content", []):
            assert len(snippet) < 4000 and 0 < snippet.count("<mark>") <= highlight.MAX_MARKS


def test_group_items_and_page_limit(large_db, tmp_path):
    (docs, hl), peak = measure(lambda: store.get_group_items(large_db, p(query="token", group_by="repository"), "r0", 15, 0))
    assert docs and hl and peak < 20 * MB
    many = [{"id": f"m{i}", "title": f"t{i}", "content": "token", "repository": f"r{i % 40}"} for i in range(400)]
    target = tmp_path / "many.sqlite"
    write(target, ((len(many), d) for d in many), "test")
    result = store.search(target, p(query="token", group_by="repository", rows=40))
    assert len(result["groups"]) == 40
    assert sum(len(g["docs"]) for g in result["groups"]) <= store.GROUP_PAGE_DOCS


def test_match_at_the_end_of_a_large_document_is_marked(large_db):
    result = store.search(large_db, p(query="needle"))
    assert result["num_found"] == 2
    for doc in result["docs"]:
        assert "<mark>needle</mark>" in result["highlighting"][doc["id"]]["content"][0]


def test_mcp_on_large_documents(large_db):
    def call(name, **arguments):
        out = mcp.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                          "params": {"name": name, "arguments": arguments}}, lambda: large_db)
        assert not out["result"]["isError"], out
        return out["result"]["content"][0]["text"]

    text, peak = measure(lambda: call("search_documents", query="token", limit=10))
    assert "«token»" in text and len(text) < 8000 and peak < 20 * MB
    text, peak = measure(lambda: call("read_document", id="d11", query="needle"))
    assert "«needle»" in text and peak < 20 * MB
    full = "không có gì ở đây. " * 150_000 + "cuối tài liệu có needle"
    text, peak = measure(lambda: call("read_document", id="d11", offset=len(full) - 23, max_chars=200))
    assert f"of {len(full)}:" in text and "cuối tài liệu có needle\n[end]" in text and peak < 20 * MB


def test_too_slow_snippets_are_skipped_with_a_notice(large_db, monkeypatch):
    monkeypatch.setattr(store, "HIGHLIGHT_BUDGET", -1.0)
    result = store.search(large_db, p(query="token"))
    assert result["docs"] and store.TOO_SLOW in result["notices"] and result["docs"][0]["preview"]


def test_out_of_memory_is_a_message(large_db, monkeypatch):
    def fail(*_args):
        raise MemoryError

    monkeypatch.setattr(store, "_fetch", fail)
    assert store.search(large_db, p(query="token"))["error"] == store.NO_MEMORY


@pytest.mark.parametrize("text,term,found", [
    ("Đăng Nhập hệ thống", "dang nhap", "Đăng Nhập"),
    (unicodedata.normalize("NFD", "Đăng Nhập hệ thống"), "dang nhap", unicodedata.normalize("NFD", "Đăng Nhập")),
    ("dang nhap", "đăng nhập", "dang nhap"),
    ("ﾛｸﾞｲﾝ画面", "ログイン", None),
    ("ＴＯＫＥＮ", "token", "ＴＯＫＥＮ"),
    ("한국어 문서", "한국", "한국"),
    ("Straße", "straße", "Straße"),
])
def test_matching_ignores_case_and_diacritics(text, term, found):
    match = highlight.matcher([term]).search(text)
    assert match, (text, term)
    if found:
        assert match.group().rstrip() == found


@pytest.mark.parametrize("size", [1, 7, 100, 65536])
def test_chunk_borders_do_not_change_snippets(size):
    text = "a\n" * 40 + "x " * 3000 + "\ndef đăng_nhập():\n    return token\n" + "y " * 6000 + "token end"
    chunks = [text[i:i + size] for i in range(0, len(text), size)]
    for cut in (highlight.snippets, highlight.code_snippets):
        assert cut(iter(chunks), ["token"]) == cut(text, ["token"])
        assert len(cut(text, ["token"])) == 2


def test_long_code_line_is_cut_around_the_match():
    line = "a" * 100_000 + " token " + "b" * 100_000
    out = highlight.code_snippets("first\n" + line + "\nlast", ["token"])
    assert len(out) == 1 and "<mark>token</mark>" in out[0] and len(out[0]) < 400 + highlight.MAX_LINE
    assert out[0].startswith("…") and out[0].endswith("…") and "\n" not in out[0]
    short = "first\n" + "a" * 1000 + " token " + "b" * 1000 + "\nlast"
    out = highlight.code_snippets(short, ["token"])
    assert out[0].startswith("first\n…") and out[0].endswith("…\nlast")
