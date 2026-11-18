"""Highlight snippets (<mark>) the way the old Solr hl output looked.

Matching folds case and Vietnamese diacritics like the fts_word tokenizer,
and the marks are placed on the original text. Output is HTML-escaped.
"""
from __future__ import annotations

import html
import re
import unicodedata

_WS = re.compile(r"\s+")
_CJK = re.compile(r"[぀-ヿ㐀-鿿豈-﫿ｦ-ﾟ]")


def has_cjk(text: str) -> bool:
    return bool(_CJK.search(text or ""))


_FOLDED: dict[str, str] = {}
MAX_SCAN = 1_000_000  # characters of one field looked at for matches; the rest of a huge document is not highlighted


def _fold_char(ch: str) -> str:
    folded = _FOLDED.get(ch)
    if folded is None:
        base = "".join(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c))
        folded = _FOLDED[ch] = {"đ": "d", "Đ": "d"}.get(ch, base).casefold()
    return folded


def _fold(text: str) -> tuple[str, list[int] | None]:
    """Folded text and, for each folded char, the index of the original char (None: the same index, plain ASCII)."""
    if text.isascii():
        return text.lower(), None
    out, index = [], []
    for i, ch in enumerate(text):
        folded = _fold_char(ch)
        out.append(folded)
        index.extend([i] * len(folded))
    return "".join(out), index


def fold(text: str) -> str:
    return _fold(text)[0]


def _spans(text: str, terms: list[str]) -> list[tuple[int, int]]:
    folded, index = _fold(text[:MAX_SCAN])
    at = (lambda pos: pos) if index is None else index.__getitem__
    spans = []
    for term in terms:
        needle = fold(term)
        if not needle:
            continue
        start = 0
        while (pos := folded.find(needle, start)) >= 0:
            spans.append((at(pos), at(pos + len(needle) - 1) + 1))
            start = pos + len(needle)
    spans.sort()
    merged: list[tuple[int, int]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
        else:
            merged.append((a, b))
    return merged


def _render(text: str, spans: list[tuple[int, int]], pre: str, post: str) -> str:
    out, last = [], 0
    for a, b in spans:
        out.append(html.escape(text[last:a]))
        out.append(pre + html.escape(text[a:b]) + post)
        last = b
    out.append(html.escape(text[last:]))
    return "".join(out)


def snippets(text: str | None, terms: list[str], *, count: int = 3, size: int = 150,
             pre: str = "<mark>", post: str = "</mark>") -> list[str]:
    if not text or not terms:
        return []
    spans = _spans(text, terms)
    if not spans:
        return []
    out, used_until = [], -1
    for a, b in spans:
        if a < used_until:
            continue
        start = max(0, a - size // 3)
        end = min(len(text), start + size)
        # Do not cut a word in half at the fragment edges.
        while start > 0 and not text[start - 1].isspace() and a - start < size // 2:
            start -= 1
        fragment = [(x - start, y - start) for x, y in spans if x >= start and y <= end]
        out.append(_WS.sub(" ", _render(text[start:end], fragment, pre, post)).strip())
        used_until = end
        if len(out) == count:
            break
    return out


def code_snippets(text: str | None, terms: list[str], *, count: int = 2, context: int = 2,
                  max_lines: int = 12, pre: str = "<mark>", post: str = "</mark>") -> list[str]:
    """Code keeps its lines: whole lines around each match (``context`` lines before/after),
    line breaks and indentation preserved, so the block can be read and scrolled like code."""
    if not text or not terms:
        return []
    spans = _spans(text, terms)
    if not spans:
        return []
    starts = [0]
    newline = text.find("\n")
    while newline >= 0:
        starts.append(newline + 1)
        newline = text.find("\n", newline + 1)

    def line_of(pos: int) -> int:
        low, high = 0, len(starts) - 1
        while low < high:
            mid = (low + high + 1) // 2
            if starts[mid] <= pos:
                low = mid
            else:
                high = mid - 1
        return low

    out, used_until = [], -1
    for a, _b in spans:
        line = line_of(a)
        if line <= used_until:
            continue
        first = max(0, line - context, used_until + 1)
        last = min(len(starts) - 1, line + context, first + max_lines - 1)
        start = starts[first]
        end = starts[last + 1] - 1 if last + 1 < len(starts) else len(text)
        fragment = [(x - start, y - start) for x, y in spans if x >= start and y <= end]
        body = _render(text[start:end], fragment, pre, post).rstrip("\n")
        out.append(body)
        used_until = last
        if len(out) == count:
            break
    return out


def whole(text: str | None, terms: list[str], pre: str = "<mark>", post: str = "</mark>") -> str | None:
    """Short fields (title): the full value with marks, or None when nothing matches."""
    if not text:
        return None
    spans = _spans(text, terms)
    return _render(text, spans, pre, post) if spans else None
