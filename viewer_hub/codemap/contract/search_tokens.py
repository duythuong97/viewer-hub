"""Search tokens shared by the retriever and the MCP tools (no index building here).

Copied from code-map ``extractor/code_tree_exporter/search_index.py`` (fold, tokens,
compact): the reader must split words exactly like the extract that wrote the
``search_*`` tables in codemap.sqlite.
"""
from __future__ import annotations

import re
import unicodedata

_STOPWORDS = frozenset(
    "a an and are as at be by do does for from how in is it of on or the this to what when where which who why with "
    "ai bi cac cho co cua da den duoc gi hay khi khong la ma mot nao nay nhu nhung o ra roi sao se thi tren trong tu va vao voi".split()
)
_CJK = re.compile(r"[぀-ヿ㐀-鿿豈-﫿ｦ-ﾟ]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_SPLIT = re.compile(r"[\W_]+")


def fold(text: str) -> str:
    """Lower-case and strip diacritics: ``Hủy đơn`` -> ``huy don``."""
    text = str(text or "").replace("đ", "d").replace("Đ", "D")
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.category(ch).startswith("M")).lower()


def tokens(text: str) -> list[str]:
    """Search tokens: camelCase/snake_case split, folded, CJK as character bigrams."""
    result: list[str] = []
    for word in _SPLIT.split(fold(_CAMEL.sub(" ", str(text or "")))):
        if not word:
            continue
        position = 0
        for match in _CJK.finditer(word):
            _plain(word[position:match.start()], result)
            run = match.group()
            result.extend([run] if len(run) == 1 else [run[i:i + 2] for i in range(len(run) - 1)])
            position = match.end()
        _plain(word[position:], result)
    return result


def _plain(word: str, result: list[str]) -> None:
    if len(word) >= 2 and word not in _STOPWORDS:
        result.append(word)


def compact(text: str) -> str:
    return "".join(ch for ch in fold(text) if ch.isalnum())
