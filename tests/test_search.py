from __future__ import annotations

import json
import sqlite3

from viewer_hub.fsearch import highlight
from viewer_hub.fsearch.store import build_match, parse_terms, search


def p(**kw):
    base = {"query": "", "operator": "OR", "rows": 10, "start": 0, "page": 1, "sort_val": "score desc",
            "repository": [], "file_type": [], "language": "", "date_from": "", "date_to": "", "hl_enabled": True}
    base.update(kw)
    return base


def test_export_maps_fields(search_db):
    db = sqlite3.connect(search_db)
    row = db.execute("SELECT image_orc_text, extra, content FROM docs WHERE id='c'").fetchone()
    assert row[0] == "スキャンされたログイン仕様"  # image_ocr_text → image_orc_text
    assert json.loads(row[1]) == {"custom_s": "x"}
    assert db.execute("SELECT value FROM meta WHERE key='docCount'").fetchone()[0] == "3"


def test_match_expression():
    terms = parse_terms('jwt "generate token" -hash')
    assert build_match(p(operator="AND"), terms) == '(("jwt" OR "jwt"*) AND "generate token") NOT "hash"'
    assert build_match(p(exact_terms=True), parse_terms("jwt")) == '"jwt"'
    assert build_match(p(proximity="3"), parse_terms("a b")) == 'NEAR("a" "b", 3)'
    assert build_match(p(phrase_mode=True), parse_terms("a b")) == '"a b"'


def test_word_search_with_highlight(search_db):
    result = search(search_db, p(query="token"))
    assert result["engine"] == "fts_word" and result["num_found"] == 1
    hl = result["highlighting"]["a"]
    assert "<mark>token</mark>" in hl["source_code_content"][0]


def test_vietnamese_without_diacritics(search_db):
    result = search(search_db, p(query="dang nhap"))
    assert [d["id"] for d in result["docs"]] == ["b"]
    assert "<mark>đăng</mark>" in result["highlighting"]["b"]["content"][0]


def test_japanese_trigram_and_short_fallback(search_db):
    assert search(search_db, p(query="ログイン"))["engine"] == "fts_tri"
    assert {d["id"] for d in search(search_db, p(query="ログイン"))["docs"]} == {"c"}
    short = search(search_db, p(query="仕様"))
    assert short["engine"] == "like" and short["num_found"] == 1


def test_facets_keep_other_values_when_selected(search_db):
    result = search(search_db, p(query="*", repository=["docs"]))
    # "*" alone is not a term: all docs, filtered by repository
    assert result["num_found"] == 2
    assert dict(result["facets"]["repository"]) == {"docs": 2, "backend": 1}


def test_group_by(search_db):
    result = search(search_db, p(query="ログイン OR token OR đăng", group_by="repository"))
    assert result["grouped"] and {g["key"] for g in result["groups"]} <= {"docs", "backend"}


def test_unsupported_options_are_reported(search_db):
    result = search(search_db, p(query="jwt", fuzzy="2", extra_fq="x:y"))
    assert len(result["notices"]) == 2


def test_bad_query_is_an_error_not_a_crash(search_db):
    assert search(search_db, p(query='"'))["error"] is None  # quotes are escaped


def test_highlight_is_escaped():
    out = highlight.snippets("<script>alert(1)</script> token", ["token"])
    assert "<script>" not in out[0] and "<mark>token</mark>" in out[0]


def test_search_page(client, search_db):
    assert '<div id="app">' in client.get("/ocr-search/search?q=token").data.decode()
    docs = client.get("/ocr-search/api/search?q=token").get_json()["search"]["docs"]
    assert docs and any("<mark>token</mark>" in snip for doc in docs for snip in doc["snippets"])
    assert client.get("/ocr-search/api/open-file?path=x").status_code == 403  # off by default


def test_code_snippets_keep_lines():
    code = "import os\n\ndef a():\n    x = 1\n    return token_value(x)\n\n\ndef b():\n    pass\n"
    out = highlight.code_snippets(code, ["token"], context=1)
    assert out == ["    x = 1\n    return <mark>token</mark>_value(x)\n"] or "\n    return <mark>token</mark>" in out[0]
    assert "\n" in out[0] and "    return" in out[0]  # indentation and line breaks preserved


def test_search_page_renders_code_block(client, search_db):
    # A code hit is shown as a code block (kind "code", Results.jsx), keeping its lines.
    docs = client.get("/ocr-search/api/search?q=token").get_json()["search"]["docs"]
    code = [doc for doc in docs if doc["kind"] == "code"]
    assert code and any("<mark>token</mark>" in snip for snip in code[0]["snippets"])


def test_partial_word_finds_words_it_starts(search_db):
    # "authenti" is no word of its own; "authentication.py" starts with it.
    result = search(search_db, p(query="authenti"))
    assert result["engine"] == "fts_word" and result["num_found"] >= 1
    assert search(search_db, p(query='"authenti"'))["num_found"] == 0  # quoted: whole word only
    assert search(search_db, p(query="authenti", exact_terms=True))["num_found"] == 0


def test_inside_a_word_falls_back_to_substring(search_db):
    result = search(search_db, p(query="enticat"))
    assert result["engine"] == "fts_tri" and result["num_found"] >= 1
    assert any("giữa từ" in notice for notice in result["notices"])
    assert search(search_db, p(query="zz"))["num_found"] == 0  # too short for the trigram index: no fallback


def test_search_group_items_api(client, search_db):
    res = client.get("/ocr-search/api/search/groups/my-repo/items?q=token&limit=10&offset=0")
    assert res.status_code == 200
    data = res.get_json()
    assert "items" in data
    assert data["group_key"] == "my-repo"


def _many_db(tmp_path, n=40):
    from viewer_hub.fsearch.export_solr import write

    docs = [{"id": f"d{i}", "title": f"file{i:02d}.py", "content": "token " * (1 + i % 5), "file_type": "py",
             "repository": ("alpha" if i % 2 else "beta") if i % 10 else ("" if i % 20 else None),
             "last_modified": f"2026-01-{1 + i % 28:02d}T00:00:00Z"} for i in range(n)]
    target = tmp_path / "many.sqlite"
    write(target, ((n, d) for d in docs), "test")
    return target


def test_group_counts_every_match_and_empty_values_share_one_group(tmp_path):
    from viewer_hub.fsearch.store import NO_GROUP, get_group_items

    db = _many_db(tmp_path)
    result = search(db, p(query="token", group_by="repository", sort_val="title asc"))
    groups = {g["key"]: g for g in result["groups"]}
    assert {k: g["count"] for k, g in groups.items()} == {"alpha": 20, "beta": 16, NO_GROUP: 4}
    assert [d["title"] for d in groups["alpha"]["docs"]][:3] == ["file01.py", "file03.py", "file05.py"]
    assert len(groups["alpha"]["docs"]) == 10
    # "Xem thêm" continues in the same order, also for the group of NULL / "" values.
    more, _hl = get_group_items(db, p(query="token", group_by="repository", sort_val="title asc"), "alpha", 15, 10)
    assert [d["title"] for d in more][:2] == ["file21.py", "file23.py"] and len(more) == 10
    empty, _hl = get_group_items(db, p(query="token", group_by="repository"), NO_GROUP, 15, 0)
    assert len(empty) == 4


def test_sort_filters_and_paging_use_indexes(tmp_path):
    db = _many_db(tmp_path)
    newest = search(db, p(query="", sort_val="last_modified desc", rows=3))
    assert newest["num_found"] == 40 and [d["last_modified"][:10] for d in newest["docs"]][0] == "2026-01-28"
    dated = search(db, p(query="token", date_from="2026-01-01", date_to="2026-01-02", repository=["alpha"]))
    assert {d["id"] for d in dated["docs"]} == {"d1", "d29"}
    assert dict(dated["facets"]["repository"])["beta"] >= 1  # facet ignores its own filter
    page2 = search(db, p(query="token", rows=5, start=5, sort_val="title desc"))
    assert [d["title"] for d in page2["docs"]][0] == "file34.py"
    facets_only = search(db, p(query="", rows=0, hl_enabled=False))
    assert facets_only["docs"] == [] and dict(facets_only["facets"]["file_type"]) == {"py": 40}
