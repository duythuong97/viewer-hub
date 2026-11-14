"""CSV datasets on disk.

workspace/csv/<id>/
  source.csv     the uploaded file, untouched          (source data)
  dataset.json   detected format + the user's column settings (source data)
  data.sqlite    rows + FTS index, rebuilt from source.csv  (derived data)
"""
from __future__ import annotations

import codecs
import csv
import hashlib
import io
import re
import shutil
import sqlite3
import time
import unicodedata
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from viewer_hub.core.atomic import read_json, write_json

SCHEMA = 1
OPERATORS = ("IN", "==")
SAMPLE_BYTES = 256 * 1024
TYPE_SAMPLE_ROWS = 1000
MAX_COLUMNS = 500
csv.field_size_limit(16 * 1024 * 1024)

_NUMBER = re.compile(r"^[+-]?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?$")
_DATE = re.compile(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}([ T]\d{1,2}:\d{2}(:\d{2})?)?$")


class CsvError(ValueError):
    pass


# ── Detection ──────────────────────────────────────────────────────────────────────

def detect_encoding(sample: bytes) -> str:
    if sample.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    for bom, name in ((codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16")):
        if sample.startswith(bom):
            return name
    try:
        # A cut multi-byte character at the end of the sample is not an error.
        codecs.getincrementaldecoder("utf-8")().decode(sample, final=False)
        return "utf-8"
    except UnicodeDecodeError:
        pass
    import chardet

    guess = (chardet.detect(sample) or {}).get("encoding") or "cp1252"
    guess = guess.lower()
    # chardet reports SHIFT_JIS for files Excel writes as cp932 (a superset).
    return {"shift_jis": "cp932", "windows-1252": "cp1252", "ascii": "utf-8"}.get(guess, guess)


def detect_dialect(text: str) -> str:
    try:
        return csv.Sniffer().sniff(text[:64 * 1024], delimiters=",;\t|").delimiter
    except csv.Error:
        first = text.splitlines()[0] if text else ""
        return max(",;\t|", key=first.count) if first else ","


def _infer_type(values: list[str]) -> str:
    filled = [v.strip() for v in values if v and v.strip()]
    if not filled:
        return "text"
    if all(_NUMBER.match(v) for v in filled):
        return "number"
    if all(_DATE.match(v) for v in filled):
        return "date"
    return "text"


def _unique_headers(raw: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for index, name in enumerate(raw):
        name = (name or "").strip().lstrip("﻿") or f"Cột {index + 1}"
        count = seen.get(name, 0)
        seen[name] = count + 1
        out.append(name if count == 0 else f"{name} ({count + 1})")
    return out


def slugify(text: str) -> str:
    value = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value[:48] or "dataset"


# ── Dataset ────────────────────────────────────────────────────────────────────────

@dataclass
class Dataset:
    folder: Path
    meta: dict
    readonly: bool = False  # shipped in a data pack: never written, never deleted

    @property
    def id(self) -> str:
        return self.meta["id"]

    @property
    def title(self) -> str:
        return self.meta.get("title") or self.id

    @property
    def columns(self) -> list[dict]:
        return self.meta["columns"]

    @property
    def visible(self) -> list[dict]:
        return [c for c in self.columns if c.get("visible", True)]

    @property
    def description(self) -> str:
        """What the file is, for people (dataset page) and AI (MCP csv_list)."""
        return (self.meta.get("description") or "").strip()

    @property
    def mcp(self) -> bool:
        """Readable by AI agents through MCP. Off for uploads unless the user turns it on (a CSV may hold data
        nobody meant for an agent); on for data pack files unless the admin's config says ``"mcp": false``."""
        return bool(self.meta.get("mcp", self.readonly))

    @property
    def default_filters(self) -> list[dict]:
        """The filter rows the page opens with (old csv-viewer ``filterCol``): the visible columns marked "Lọc",
        else the first visible column. Datasets made before this marked every column, which means the first."""
        marked = [c for c in self.visible if c.get("filter")]
        if not marked or (len(marked) == len(self.visible) > 1):
            marked = self.visible[:1]
        return [{"column": c["key"], "operator": c.get("op", "IN")} for c in marked]

    def apply_viewer_config(self, entry: dict) -> None:
        """Take ``visibleCols`` / ``filterCol`` from an old csv-viewer config.json entry (columns by header name)."""
        by_name = {c["name"]: c for c in self.columns}
        visible = [name for name in entry.get("visibleCols") or [] if name in by_name]
        if visible:
            for column in self.columns:
                column["visible"] = column["name"] in visible
        filters = {}
        for item in entry.get("filterCol") or []:
            if isinstance(item, dict) and len(item) == 1:
                name, operator = next(iter(item.items()))
                if name in by_name and operator in {"IN", "=="}:
                    filters[name] = operator
        if filters:
            for column in self.columns:
                column["filter"] = column["name"] in filters
                column["op"] = filters.get(column["name"], column.get("op", "IN"))
                column["visible"] = column["visible"] or column["filter"]  # a filter column is always shown
        if isinstance(entry.get("description"), str):
            self.meta["description"] = entry["description"].strip()[:2000]
        if isinstance(entry.get("mcp"), bool):
            self.meta["mcp"] = entry["mcp"]
        notes = entry.get("columnDescriptions")
        if isinstance(notes, dict):
            for column in self.columns:
                note = notes.get(column["name"])
                if isinstance(note, str) and note.strip():
                    column["description"] = note.strip()[:500]

    @property
    def source(self) -> Path:
        return self.folder / "source.csv"

    @property
    def db_path(self) -> Path:
        return self.folder / "data.sqlite"

    def save(self) -> None:
        if self.readonly:
            raise PermissionError("Dataset thuộc data pack, chỉ đọc")
        self.meta["updatedAt"] = _now()
        write_json(self.folder / "dataset.json", self.meta)

    # Reading ---------------------------------------------------------------------
    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(f"{self.db_path.as_uri()}?mode=ro", uri=True, check_same_thread=False)
        db.create_function("casefold", 1, lambda v: v.casefold() if isinstance(v, str) else v, deterministic=True)
        return db

    def _text_where(self, text: str) -> tuple[str, list]:
        if len(text) >= 3:
            return "rowid IN (SELECT rowid FROM fts WHERE fts MATCH ?)", ['"' + text.replace('"', '""') + '"']
        like = [f"casefold({c['key']}) LIKE ? ESCAPE '\\'" for c in self.visible]
        return "(" + " OR ".join(like) + ")", [f"%{_escape_like(text.casefold())}%"] * len(like)

    def search(self, *, text: str = "", rules: list[dict] | None = None, sort: str | None = None,
               desc: bool = False, offset: int = 0, limit: int = 50) -> dict:
        """Rows matching ``text`` and every rule (AND), as the old csv-viewer: ``IN`` contains, ``==`` equals
        after trimming, both ignoring case. Rules may use any visible column."""
        keys = {c["key"]: c for c in self.columns}
        where, params = [], []
        text = (text or "").strip()
        if text:
            clause, values = self._text_where(text)
            where.append(clause)
            params.extend(values)
        for rule in rules or []:
            column = keys.get(rule.get("column"))
            value = str(rule.get("value", "")).strip()
            if not column or not column.get("visible", True) or not value:
                continue
            if rule.get("operator", column.get("op", "IN")) == "==":
                where.append(f"casefold(trim({column['key']})) = ?")
                params.append(value.casefold())
            else:
                where.append(f"casefold({column['key']}) LIKE ? ESCAPE '\\'")
                params.append(f"%{_escape_like(value.casefold())}%")
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        order = "rowid"
        if sort in keys:
            expr = f"CAST(replace({sort}, ',', '') AS REAL)" if keys[sort]["type"] == "number" else sort
            order = f"{expr} {'DESC' if desc else 'ASC'}, rowid"
        visible = [c["key"] for c in self.visible]
        with closing(self.connect()) as db:
            total = db.execute(f"SELECT COUNT(*) FROM rows {clause}", params).fetchone()[0]
            rows = db.execute(
                f"SELECT {', '.join(visible) or 'rowid'} FROM rows {clause} ORDER BY {order} LIMIT ? OFFSET ?",
                [*params, limit, offset],
            ).fetchall()
        return {"total": total, "rows": [list(r) for r in rows], "columns": self.visible}

    def iter_rows(self, *, text: str = "", rules: list[dict] | None = None) -> Iterator[list]:
        page, size = 0, 1000
        while True:
            result = self.search(text=text, rules=rules, offset=page * size, limit=size)
            yield from result["rows"]
            if len(result["rows"]) < size:
                return
            page += 1


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


class CsvStore:
    def __init__(self, root: Path, tmp: Path, packs: list[tuple[str, str, Path]] | None = None):
        self.root = root
        self.tmp = tmp
        self.packs = packs or []  # (pack_id, pack title, <pack>/csv) of active data packs

    @staticmethod
    def _pack_dataset(pack_id: str, title: str, folder: Path) -> Dataset | None:
        meta = read_json(folder / "dataset.json")
        if not meta or not (folder / "data.sqlite").is_file():
            return None
        meta = {**meta, "id": f"{pack_id}--{meta.get('id') or folder.name}", "pack": {"id": pack_id, "title": title}}
        return Dataset(folder, meta, readonly=True)

    def list(self) -> list[Dataset]:
        out = []
        if self.root.is_dir():
            for folder in sorted(self.root.iterdir()):
                meta = read_json(folder / "dataset.json")
                if meta:
                    out.append(Dataset(folder, meta))
        out.sort(key=lambda d: d.meta.get("updatedAt", ""), reverse=True)
        for pack_id, title, root in self.packs:
            for folder in sorted(p for p in root.iterdir() if p.is_dir()):
                dataset = self._pack_dataset(pack_id, title, folder)
                if dataset:
                    out.append(dataset)
        return out

    def get(self, dataset_id: str) -> Dataset | None:
        if not re.fullmatch(r"[a-z0-9-]{1,130}", dataset_id or ""):
            return None
        if "--" in dataset_id:  # <pack_id>--<dataset id>: from a data pack
            pack_id, local = dataset_id.split("--", 1)
            for pid, title, root in self.packs:
                if pid == pack_id and re.fullmatch(r"[a-z0-9-]{1,64}", local) and (root / local).is_dir():
                    return self._pack_dataset(pid, title, root / local)
            return None
        folder = self.root / dataset_id
        meta = read_json(folder / "dataset.json")
        return Dataset(folder, meta) if meta else None

    def _new_id(self, title: str) -> str:
        base = slugify(title).replace("--", "-")  # "--" is reserved for pack items
        candidate, n = base, 2
        while (self.root / candidate).exists():
            candidate, n = f"{base}-{n}", n + 1
        return candidate

    def create(self, upload: Path, filename: str, title: str | None = None, *, description: str = "",
               mcp: bool = False) -> Dataset:
        """``upload`` is a file in tmp/; it is moved into the dataset folder."""
        title = (title or Path(filename).stem).strip() or "dataset"
        dataset_id = self._new_id(title)
        work = self.tmp / f"csv-{dataset_id}-{int(time.time() * 1000)}"
        work.mkdir(parents=True)
        try:
            source = work / "source.csv"
            shutil.move(str(upload), source)
            meta = analyse(source, filename)
            meta.update({"schema": SCHEMA, "id": dataset_id, "title": title, "createdAt": _now(), "updatedAt": _now(),
                         "description": (description or "").strip()[:2000], "mcp": bool(mcp)})
            meta["rows"] = build_index(source, meta, work / "data.sqlite")
            write_json(work / "dataset.json", meta)
            self.root.mkdir(parents=True, exist_ok=True)
            work.rename(self.root / dataset_id)  # the dataset appears complete or not at all
        except Exception:
            shutil.rmtree(work, ignore_errors=True)
            raise
        return Dataset(self.root / dataset_id, meta)

    def rebuild(self, dataset: Dataset) -> int:
        target = dataset.db_path
        temp = dataset.folder / "data.sqlite.new"
        temp.unlink(missing_ok=True)
        rows = build_index(dataset.source, dataset.meta, temp)
        temp.replace(target)
        dataset.meta["rows"] = rows
        dataset.save()
        return rows

    def delete(self, dataset: Dataset) -> None:
        if dataset.readonly:
            raise PermissionError("Dataset thuộc data pack, chỉ đọc")
        trash = self.tmp / f"deleted-{dataset.id}-{int(time.time())}"
        dataset.folder.rename(trash)
        shutil.rmtree(trash, ignore_errors=True)


def _open_text(path: Path, encoding: str) -> io.TextIOWrapper:
    return open(path, encoding=encoding, errors="replace", newline="")


def analyse(source: Path, filename: str) -> dict:
    with open(source, "rb") as handle:
        sample = handle.read(SAMPLE_BYTES)
    if not sample.strip():
        raise CsvError("File rỗng.")
    if b"\x00" in sample and not sample.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        raise CsvError("File không phải CSV dạng văn bản.")
    encoding = detect_encoding(sample)
    text = sample.decode(encoding if encoding != "utf-16" else "utf-16", errors="replace")
    delimiter = detect_dialect(text)
    with _open_text(source, encoding) as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        try:
            header = next(reader)
        except StopIteration:
            raise CsvError("Không đọc được dòng tiêu đề.") from None
        if len(header) > MAX_COLUMNS:
            raise CsvError(f"Quá nhiều cột ({len(header)} > {MAX_COLUMNS}).")
        sample_rows = [row for _, row in zip(range(TYPE_SAMPLE_ROWS), reader)]
    names = _unique_headers(header)
    columns = []
    for index, name in enumerate(names):
        values = [row[index] if index < len(row) else "" for row in sample_rows]
        columns.append({"key": f"c{index}", "name": name, "label": None, "type": _infer_type(values),
                        "visible": True, "filter": index == 0, "op": "IN"})
    digest = hashlib.sha256()
    with open(source, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return {
        "source": {"filename": Path(filename).name, "encoding": encoding, "delimiter": delimiter,
                   "size": source.stat().st_size, "sha256": digest.hexdigest()},
        "columns": columns,
    }


def build_index(source: Path, meta: dict, target: Path) -> int:
    """Rows + FTS5 (trigram: substring search in any language, incl. Japanese)."""
    keys = [c["key"] for c in meta["columns"]]
    target.unlink(missing_ok=True)
    db = sqlite3.connect(target)
    try:
        db.execute("PRAGMA journal_mode=OFF")
        db.execute("PRAGMA synchronous=OFF")
        db.execute(f"CREATE TABLE rows ({', '.join(f'{k} TEXT' for k in keys)})")
        insert = f"INSERT INTO rows VALUES ({', '.join('?' for _ in keys)})"
        count = 0
        with _open_text(source, meta["source"]["encoding"]) as handle:
            reader = csv.reader(handle, delimiter=meta["source"]["delimiter"])
            next(reader, None)
            batch = []
            for row in reader:
                if not any(cell.strip() for cell in row):
                    continue
                row = (row + [""] * len(keys))[: len(keys)]
                batch.append(row)
                if len(batch) == 5000:
                    db.executemany(insert, batch)
                    count += len(batch)
                    batch.clear()
            if batch:
                db.executemany(insert, batch)
                count += len(batch)
        db.execute(
            f"CREATE VIRTUAL TABLE fts USING fts5({', '.join(keys)}, content='rows', content_rowid='rowid', tokenize='trigram')"
        )
        db.execute("INSERT INTO fts(fts) VALUES ('rebuild')")
        db.commit()
    finally:
        db.close()
    return count


def export_csv(dataset: Dataset, rows: Iterable[list]) -> Iterator[str]:
    """CSV text with formula injection neutralised (cells starting with = + - @ are prefixed with ')."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    def flush() -> str:
        value = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate()
        return value

    writer.writerow([c.get("label") or c["name"] for c in dataset.visible])
    yield "﻿" + flush()
    for row in rows:
        writer.writerow(["'" + v if isinstance(v, str) and v[:1] in "=+-@\t\r" else v for v in row])
        yield flush()
