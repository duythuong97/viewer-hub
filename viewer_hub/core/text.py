"""Text from bytes in whatever encoding a Japanese / Windows / legacy tool saved it: UTF-8 (with or without BOM),
UTF-16, CP932 (Shift_JIS), EUC-JP, or what the file declares (<?xml encoding=…?>, <meta charset>, coding: …).

Used by the Hub (code map sources, CSV / dictionary input) and by addons through viewer_hub.addons.sdk.decode_text.
Standard library only: the addon SDK ships this file.
"""
from __future__ import annotations

import codecs
import re
import sys

_HASH_COMMENT_ENCODING_DECLARATION = re.compile(
    rb"(?im)^[ \t\f]*#.*?(?:coding|encoding)[ \t]*[:=][ \t]*['\"]?([a-z0-9._-]+)"
)
_COMMENT_ENCODING_DECLARATION = re.compile(
    rb"(?im)^[ \t]*(?://|/\*|\*|--)[ \t]*(?:coding|encoding)[ \t]*[:=][ \t]*['\"]?([a-z0-9._-]+)"
)
_XML_ENCODING_DECLARATION = re.compile(
    rb"(?is)^\s*(?:\xef\xbb\xbf)?<\?xml\b[^>]*\bencoding\s*=\s*['\"]\s*([a-z0-9._-]+)\s*['\"]"
)
_HTML_CHARSET_DECLARATION = re.compile(
    rb"(?is)<meta\b[^>]*\bcharset\s*=\s*['\"]?\s*([a-z0-9._-]+)"
)

SUPPORTED_ENCODINGS = frozenset({
    "utf-8", "utf-8-sig", "utf-16-le", "utf-16-be", "shift_jis", "cp932", "euc_jp"
})
_BOMS = (
    (codecs.BOM_UTF8, "utf-8-sig", "UTF-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le", "UTF-16-LE"),
    (codecs.BOM_UTF16_BE, "utf-16-be", "UTF-16-BE"),
)


class SourceDecodingError(ValueError):
    def __init__(self, issue_type: str, path: str, message: str, properties: dict[str, object]) -> None:
        super().__init__(message)
        self.issue_type = issue_type
        self.path = path
        self.properties = properties


# Names Oracle, Java and Windows tools write that Python's codec registry does not know.
_ENCODING_ALIASES = {
    "ja16sjis": "cp932", "ja16sjistilde": "cp932", "sjis-win": "cp932", "sjis_win": "cp932", "x-sjis": "cp932",
    "windows-31j": "cp932", "ms932": "cp932", "ms_kanji": "cp932", "ja16euc": "euc_jp", "ja16euctilde": "euc_jp",
    "al32utf8": "utf-8", "utf8mb4": "utf-8",
}


def canonical_encoding(value: str) -> str:
    if value.strip().lower() == "auto":
        return "auto"
    value = _ENCODING_ALIASES.get(value.strip().lower(), value)
    name = codecs.lookup(value).name
    aliases = {"utf-8": "utf-8", "utf-8-sig": "utf-8-sig", "utf-16-le": "utf-16-le", "utf-16-be": "utf-16-be", "shift-jis": "shift_jis", "cp932": "cp932", "euc-jp": "euc_jp"}
    canonical = aliases.get(name, name)
    if canonical not in SUPPORTED_ENCODINGS:
        raise ValueError(f"Unsupported source encoding: {value}")
    return canonical


def _bom(raw: bytes) -> tuple[str, str]:
    for marker, codec, name in _BOMS:
        if raw.startswith(marker):
            return codec, name
    return "", ""

def _declared_in_file(raw: bytes, relative_path: str) -> str:
    header = raw[:4096]
    match = _XML_ENCODING_DECLARATION.search(header)
    if match is None:
        match = _HTML_CHARSET_DECLARATION.search(header)
    if match is None:
        # Source encodings are conventionally declared in a comment header;
        # limit scanning to the first two lines to avoid matching identifiers.
        header_lines = b"\n".join(header.splitlines()[:2])
        match = _COMMENT_ENCODING_DECLARATION.search(header_lines)
    if match is None:
        match = _HASH_COMMENT_ENCODING_DECLARATION.search(header_lines)
    if not match:
        return ""
    try:
        value = match.group(1).decode("ascii")
        return canonical_encoding(value)
    except (LookupError, ValueError):
        # An encoding name we do not know (a tool-specific spelling) is no reason to drop the file:
        # detect the encoding from the bytes instead.
        return ""

def _detect_encoding(raw: bytes, relative_path: str) -> str:
    if not raw:
        return "utf-8"
    try:
        raw.decode("utf-8", errors="strict")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    if _looks_utf16(raw, little_endian=True):
        return "utf-16-le"
    if _looks_utf16(raw, little_endian=False):
        return "utf-16-be"
    matches = []
    for encoding in ("cp932", "euc_jp"):
        try:
            matches.append((encoding, raw.decode(encoding, errors="strict")))
        except UnicodeDecodeError:
            pass
    if len(matches) == 1 or len(matches) == 2 and matches[0][1] == matches[1][1]:
        return matches[0][0]
    if len(matches) > 1:
        # Half-width katakana is ordinary in CP932 sources (ｺｰﾄﾞ) but needs an SS2 prefix in EUC-JP, so it only
        # counts against EUC-JP; private-use characters count against both. CP932 wins ties: Windows-era sources.
        ranked = sorted(matches, key=lambda item: (_mojibake_score(item[1], item[0]), item[0] != "cp932"))
        if _mojibake_score(ranked[0][1], ranked[0][0]) < _mojibake_score(ranked[1][1], ranked[1][0]) or ranked[0][0] == "cp932":
            return ranked[0][0]
        raise SourceDecodingError(
            "ENCODING_CONFLICT", relative_path, "Legacy Japanese encoding is ambiguous",
            {"candidate_encodings": [encoding for encoding, _ in matches]},
        )
    raise SourceDecodingError(
        "ENCODING_ERROR", relative_path, "Cannot detect source encoding",
        {"hex_context": raw[:16].hex()},
    )

def _mojibake_score(text: str, encoding: str = "euc_jp") -> int:
    """Characters a wrong guess produces. EUC-JP read as CP932 turns the very common lead bytes A1-A5
    (symbols, hiragana, katakana rows) into half-width punctuation ｡｢｣､･; real CP932 text rarely has many.
    CP932 half-width katakana read as EUC-JP would need an SS2 prefix, so half-width katakana counts against
    EUC-JP. Private-use characters count against both."""
    if encoding == "cp932":
        def halfwidth(c: str) -> bool:
            return "\uff61" <= c <= "\uff9f"

        def wide(c: str) -> bool:
            return ord(c) >= 0x3000 and not halfwidth(c)

        score = 0
        for index, c in enumerate(text):
            if "\ue000" <= c <= "\uf8ff" or "\uff61" <= c <= "\uff65":
                score += 1
            elif halfwidth(c) and any(wide(n) for n in text[max(index - 1, 0):index] + text[index + 1:index + 2]):
                # Real half-width katakana comes in runs; glued to kanji it is EUC-JP bytes misread.
                score += 1
        return score
    return sum(1 for c in text if "\ue000" <= c <= "\uf8ff" or "\uff61" <= c <= "\uff9f")


def _looks_utf16(raw: bytes, *, little_endian: bool) -> bool:
    pairs = len(raw) // 2
    if pairs < 2:
        return False
    zero_side = raw[1::2] if little_endian else raw[0::2]
    text_side = raw[0::2] if little_endian else raw[1::2]
    return zero_side.count(0) / pairs > 0.3 and text_side.count(0) / pairs < 0.1


def _declared_any(raw: bytes) -> str:
    """Any codec Python knows that the file declares (Hub sources only accept SUPPORTED_ENCODINGS; addons read
    whatever they are given, e.g. a WSDL in ISO-8859-1)."""
    header = raw[:4096]
    match = _XML_ENCODING_DECLARATION.search(header) or _HTML_CHARSET_DECLARATION.search(header)
    if not match:
        return ""
    value = match.group(1).decode("ascii", "ignore").lower()
    try:
        return codecs.lookup(_ENCODING_ALIASES.get(value, value)).name
    except LookupError:
        return ""


def decode_text(raw: bytes, name: str = "") -> tuple[str, str]:
    """(text, encoding) of ``raw``, never raising: BOM, then the file's own declaration (<?xml encoding=…?>,
    <meta charset>, coding: …), then detection: UTF-8, UTF-16, CP932 (Shift_JIS) or EUC-JP (the one without
    mojibake), then CP1252. The BOM is not part of the text. Bytes nothing accepts are read as UTF-8 with U+FFFD for
    the bad bytes (encoding "utf-8?")."""
    codec, _name = _bom(raw)
    actual = codec or _declared_in_file(raw, name) or _declared_any(raw)
    if not actual:
        try:
            actual = _detect_encoding(raw, name)
        except SourceDecodingError as exc:
            candidates = exc.properties.get("candidate_encodings") or []
            actual = candidates[0] if candidates else "cp1252"
    if actual == "shift_jis":
        actual = "cp932"
    try:
        text = raw.decode(actual)
        return (text[1:] if text.startswith("\ufeff") else text), actual
    except (UnicodeDecodeError, LookupError):
        return raw.decode("utf-8", errors="replace"), "utf-8?"


def looks_binary(raw: bytes) -> bool:
    """NUL bytes in the first 8 KB that are not UTF-16 text."""
    head = raw[:8192]
    if b"\x00" not in head:
        return False
    if _bom(head)[0].startswith("utf-16"):
        return False
    return len(head) < 64 or not (_looks_utf16(head, little_endian=True) or _looks_utf16(head, little_endian=False))


def fold(text: str) -> str:
    """For matching what a person types against stored text: NFKC (half-width ｶﾀｶﾅ → カタカナ, full-width ＡＢＣ１ →
    ABC1, ① → 1) then casefold. Compare fold(query) in fold(text)."""
    import unicodedata

    return unicodedata.normalize("NFKC", text).casefold()


def utf8_output(*streams) -> None:
    """Print Vietnamese / Japanese text whatever the console: on Windows a piped or redirected stdout (just, a file,
    CI) is cp1252 / cp932 and cannot hold "ữ" (UnicodeEncodeError), and the release runs Python with -I, so
    PYTHONUTF8 / PYTHONIOENCODING are ignored. The Hub's CLI and every Python addon (addons/host.py) call this first.
    A real console is UTF-8 already and is left alone."""
    for stream in streams or (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "").replace("_", "")
        if encoding != "utf8" and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
