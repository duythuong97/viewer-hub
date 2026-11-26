"""Highlight snippets (<mark>) the way the old Solr hl output looked.

Matching ignores case and Vietnamese diacritics like the fts_word tokenizer, and the marks are placed on the original
text. Output is HTML-escaped.

Documents can be huge (tens of MB, sometimes one single line), so nothing here needs the whole text: every function
takes a string or an iterable of chunks (store.field_chunks), keeps a small window of it, stops as soon as it has its
snippets, and caps what one snippet can hold.
"""
from __future__ import annotations

import html
import re
import unicodedata
from functools import lru_cache
from typing import Callable, Iterable, Iterator

_WS = re.compile(r"\s+")
_CJK = re.compile(r"[぀-ヿ㐀-鿿豈-﫿ｦ-ﾟ]")

OVERLAP = 512        # characters kept between two chunks so a match cut in half is still found
MAX_SNIPPET = 2000   # characters of text one snippet shows
MAX_LINE = 300       # characters shown of one code line; a longer line is cut around its match
MAX_MARKS = 50       # marks in one snippet
CODE_BACK = 4000     # characters before a match looked at for the lines above it
CODE_AHEAD = 8000    # characters after a match looked at for the lines below it

Text = str | Iterable[str]


def has_cjk(text: str) -> bool:
    return bool(_CJK.search(text or ""))


def _fold_char(ch: str) -> str:
    base = "".join(c for c in unicodedata.normalize("NFKD", ch) if not unicodedata.combining(c))
    return {"đ": "d", "Đ": "d"}.get(ch, base).casefold()


def fold(text: str) -> str:
    return "".join(_fold_char(c) for c in text or "")


@lru_cache(maxsize=1)
def _classes() -> tuple[dict[str, str], str]:
    """For every folded character: all characters (BMP) that fold to it; and the combining marks that may follow."""
    variants: dict[str, list[str]] = {}
    marks = []
    for code in range(0x20, 0x10000):
        if 0xD800 <= code < 0xE000:  # surrogates
            continue
        ch = chr(code)
        folded = _fold_char(ch)
        if not folded:  # accents, Japanese voicing marks (also the half-width ones)
            marks.append(ch)
        elif len(folded) == 1:
            variants.setdefault(folded, []).append(ch)
    return {key: "".join(chars) for key, chars in variants.items()}, "".join(marks)


@lru_cache(maxsize=256)
def _term_pattern(term: str) -> str:
    variants, marks = _classes()
    follow = f"[{re.escape(marks)}]*"
    folded = []
    for ch in fold(term):
        chars = "".join(sorted(set(variants.get(ch, "")) | {ch}))
        folded.append(f"[{re.escape(chars)}]{follow}")
    pattern = "".join(folded)
    # A character that folds to several (Korean syllables, ligatures, ß) is not covered by the classes above:
    # also accept the term as it was typed.
    if any(len(_fold_char(c)) > 1 for c in term):
        pattern = f"(?i:{re.escape(term)})|{pattern}"
    return pattern


def matcher(terms: list[str]) -> re.Pattern | None:
    """One pattern finding any of the terms, longest first (so "generate" wins over "gen")."""
    useful = sorted({t for t in terms if fold(t)}, key=len, reverse=True)
    return re.compile("|".join(_term_pattern(t) for t in useful)) if useful else None


def _scan(text: Text, pattern: re.Pattern, back: int, ahead: int,
          cut: Callable[[str, re.Match, int], tuple[str, int]], count: int) -> list[str]:
    """Walk the chunks and call ``cut(window, match, floor)`` for up to ``count`` matches. The window holds at least
    ``back`` characters before the match and ``ahead`` after its start (when the text has them); ``floor`` is where
    the previous snippet ended. ``cut`` returns the snippet and the position to search on from."""
    chunks: Iterator[str] = iter([text] if isinstance(text, str) else text)
    window, pos, floor, ended = "", 0, 0, False
    out: list[str] = []
    while len(out) < count:
        match = pattern.search(window, pos)
        if match is not None and (ended or match.start() + ahead <= len(window)):
            snippet, resume = cut(window, match, floor)
            out.append(snippet)
            pos = floor = max(resume, match.end())
            continue
        if ended:
            break
        # Nothing complete in the window: drop what is behind, read one more chunk.
        pos = match.start() if match is not None else max(pos, len(window) - OVERLAP)
        drop = max(0, pos - back - 1)  # one more: tells whether a line starts there
        window, pos, floor = window[drop:], pos - drop, max(0, floor - drop)
        chunk = next(chunks, None)
        if chunk is None:
            ended = True
        else:
            window += chunk
    return out


def _render(text: str, spans: list[tuple[int, int]], pre: str, post: str) -> str:
    out, last = [], 0
    for a, b in spans:
        out.append(html.escape(text[last:a]))
        out.append(pre + html.escape(text[a:b]) + post)
        last = b
    out.append(html.escape(text[last:]))
    return "".join(out)


def _spans(text: str, pattern: re.Pattern, limit: int = MAX_MARKS) -> list[tuple[int, int]]:
    """Up to ``limit`` marks in a short text; touching matches become one."""
    spans: list[tuple[int, int]] = []
    for match in pattern.finditer(text):
        a, b = match.span()
        if spans and a <= spans[-1][1]:
            spans[-1] = (spans[-1][0], b)
        elif len(spans) == limit:
            break
        else:
            spans.append((a, b))
    return spans


def snippets(text: Text | None, terms: list[str], *, count: int = 3, size: int = 150,
             pre: str = "<mark>", post: str = "</mark>") -> list[str]:
    pattern = matcher(terms) if text and terms else None
    if pattern is None:
        return []
    size = min(size, MAX_SNIPPET)

    def cut(window: str, match: re.Match, floor: int) -> tuple[str, int]:
        a = match.start()
        start = max(floor, a - size // 3)
        # Do not cut a word in half at the fragment edges.
        while start > floor and not window[start - 1].isspace() and a - start < size // 2:
            start -= 1
        end = min(len(window), max(start + size, min(match.end(), a + MAX_SNIPPET)))
        fragment = window[start:end]
        return _WS.sub(" ", _render(fragment, _spans(fragment, pattern), pre, post)).strip(), end

    return _scan(text, pattern, size, size * 2 + OVERLAP, cut, count)


def _clip_line(line: str, pattern: re.Pattern, focus: int | None) -> tuple[str, int, int]:
    """(shown text with … where cut, first and last offset shown) of one code line."""
    if len(line) <= MAX_LINE:
        return line, 0, len(line)
    if focus is None:
        found = pattern.search(line)
        focus = found.start() if found else 0
    start = max(0, min(focus - MAX_LINE // 3, len(line) - MAX_LINE))
    end = start + MAX_LINE
    return ("…" if start else "") + line[start:end] + ("…" if end < len(line) else ""), start, end


def code_snippets(text: Text | None, terms: list[str], *, count: int = 2, context: int = 2,
                  max_lines: int = 12, pre: str = "<mark>", post: str = "</mark>") -> list[str]:
    """Code keeps its lines: the lines around each match (``context`` lines before/after), line breaks and
    indentation preserved, so the block can be read and scrolled like code. Long lines are cut around the match."""
    pattern = matcher(terms) if text and terms else None
    if pattern is None:
        return []

    def cut(window: str, match: re.Match, floor: int) -> tuple[str, int]:
        a = match.start()
        floor = min(floor, a)
        lowest = max(floor, a - CODE_BACK)
        first = a
        for _ in range(context + 1):  # start of the match's line, then of `context` lines above it
            newline = window.rfind("\n", lowest, max(lowest, first - (0 if first == a else 1)))
            if newline < 0:
                first = lowest
                break
            first = newline + 1
        cut_above = first == lowest and lowest > 0 and window[lowest - 1] != "\n"
        lines: list[str] = []
        at, shown, after, resume = first, 0, 0, a
        while len(lines) < max_lines:
            newline = window.find("\n", at, a + CODE_AHEAD)
            end = newline if newline >= 0 else min(len(window), a + CODE_AHEAD)
            line = window[at:end]
            here = at <= a <= end
            body, left, right = _clip_line(line, pattern, a - at if here else None)
            if at == first and cut_above and not body.startswith("…"):
                body = "…" + body
            if shown + len(body) > MAX_SNIPPET and at > a:
                break
            lines.append(body)
            shown += len(body) + 1
            # A line that was cut resumes after its shown part, so a minified file can give a second snippet.
            resume = at + right if right < len(line) else end + 1
            if at > a:
                after += 1
            if newline < 0 or after >= context:
                break
            at = newline + 1
        block = "\n".join(lines).rstrip("\n")
        return _render(block, _spans(block, pattern), pre, post), resume

    return _scan(text, pattern, CODE_BACK, CODE_AHEAD, cut, count)


def whole(text: str | None, terms: list[str], pre: str = "<mark>", post: str = "</mark>") -> str | None:
    """Short fields (title): the full value with marks, or None when nothing matches."""
    pattern = matcher(terms) if text else None
    if pattern is None:
        return None
    spans = _spans(text, pattern)
    return _render(text, spans, pre, post) if spans else None
