"""Source text decoding, copied from code-map extractor/code_tree_exporter/decoding.py (used by /api/snippet)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from viewer_hub.core.text import (  # noqa: F401  (re-exported: callers import them from here)
    SUPPORTED_ENCODINGS, SourceDecodingError, _bom, _declared_in_file, _detect_encoding, _looks_utf16,
    _mojibake_score, canonical_encoding,
)


@dataclass(frozen=True)
class DecodedSource:
    path: Path
    relative_path: str
    raw_bytes: bytes
    text: str
    declared_encoding: str
    actual_encoding: str
    raw_sha256: str
    text_sha256: str
    newline_style: str
    bom: str


def decode_source(path: Path, relative_path: str, declared_encoding: str) -> DecodedSource:
    raw = path.read_bytes()
    declared = canonical_encoding(declared_encoding)
    bom_codec, bom_name = _bom(raw)
    file_declaration = _declared_in_file(raw, relative_path)
    if bom_codec and declared != "auto" and not _compatible_bom(declared, bom_codec):
        raise SourceDecodingError(
            "ENCODING_CONFLICT",
            relative_path,
            f"BOM {bom_name} conflicts with configured encoding {declared}",
            {"configured_encoding": declared, "bom": bom_name},
        )
    if bom_codec and file_declaration and not _compatible_bom(file_declaration, bom_codec):
        raise SourceDecodingError(
            "ENCODING_CONFLICT",
            relative_path,
            f"BOM {bom_name} conflicts with file declaration {file_declaration}",
            {"declared_encoding": file_declaration, "bom": bom_name},
        )
    actual = bom_codec or (declared if declared != "auto" else file_declaration) or _detect_encoding(raw, relative_path)
    # Shift_JIS files from Windows tools use CP932 extensions (①, 髙, ～); CP932 is a superset, so read them as it.
    if actual == "shift_jis":
        actual = "cp932"
    try:
        text = raw.decode(actual, errors="strict")
    except UnicodeDecodeError as exc:
        start = max(0, exc.start - 8)
        end = min(len(raw), exc.end + 8)
        raise SourceDecodingError(
            "ENCODING_ERROR",
            relative_path,
            f"Cannot decode source as {actual} at byte {exc.start}",
            {"encoding": actual, "byte_offset": exc.start, "hex_context": raw[start:end].hex()},
        ) from exc
    if bom_codec and text.startswith("\ufeff"):
        text = text[1:]
    return DecodedSource(
        path=path,
        relative_path=relative_path,
        raw_bytes=raw,
        text=text,
        declared_encoding=declared,
        actual_encoding=actual,
        raw_sha256=hashlib.sha256(raw).hexdigest(),
        text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        newline_style=_newline_style(text),
        bom=bom_name,
    )


def _compatible_bom(declared: str, bom_codec: str) -> bool:
    return declared == bom_codec or (bom_codec == "utf-8-sig" and declared in {"utf-8", "utf-8-sig"})


def _newline_style(text: str) -> str:
    crlf = text.count("\r\n")
    remainder = text.replace("\r\n", "")
    lf = remainder.count("\n")
    cr = remainder.count("\r")
    kinds = sum(value > 0 for value in (crlf, lf, cr))
    if kinds > 1:
        return "mixed"
    if crlf:
        return "CRLF"
    if lf:
        return "LF"
    if cr:
        return "CR"
    return "none"


def read_text_auto(path: Path) -> str:
    """Text of an input file (CSV, dictionary) saved as UTF-8 with or without
    BOM, CP932/Shift_JIS, EUC-JP or UTF-16 - Excel on Japanese Windows saves
    CSV as CP932 by default."""
    return decode_source(path, path.name, "auto").text
