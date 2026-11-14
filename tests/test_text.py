"""core/text.py: text from bytes as Japanese / Windows tools save it (also the addon SDK's decode_text and fold)."""
from __future__ import annotations

import pytest

from viewer_hub.core.text import decode_text, fold, looks_binary

SAMPLE = "受注を登録する ｶﾀｶﾅ ①髙～"


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig", "cp932", "utf-16"])
def test_decodes_what_tools_write(encoding):
    text, used = decode_text(SAMPLE.encode(encoding))
    assert text == SAMPLE and used != "utf-8?"


def test_euc_jp_and_declarations():
    assert decode_text("日本語のテキストです。カタカナ".encode("euc_jp")) == ("日本語のテキストです。カタカナ", "euc_jp")
    xml = b'<?xml version="1.0" encoding="Shift_JIS"?><a>' + "漢字".encode("cp932") + b"</a>"
    assert decode_text(xml)[0].endswith("<a>漢字</a>")
    latin = b'<?xml version="1.0" encoding="ISO-8859-1"?><a>\xe9</a>'
    assert decode_text(latin)[0].endswith("<a>é</a>")
    assert decode_text("café".encode("cp1252")) == ("café", "cp1252")


def test_never_raises_and_binary():
    assert decode_text(b"\x81\x00\xff\xfe\x80")[1]  # some text, whatever it is
    assert looks_binary(bytes(range(256)) * 4) and not looks_binary("テキスト".encode("utf-16"))
    assert not looks_binary("ok".encode())


def test_fold_matches_across_widths():
    assert fold("ｶﾀｶﾅ") == fold("カタカナ") and fold("ＡＢＣ") == fold("abc") and "ｼﾞｭﾁｭｳ" != fold("ｼﾞｭﾁｭｳ")
