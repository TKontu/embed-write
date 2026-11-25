"""Import paths for source items (todo-09 SR-03).

Three local file formats, each read into ``tuple[SourceItem, ...]`` through SR-02's
``validate_source_items`` (so duplicate ids are rejected), plus writers for round-tripping:

* Tables: CSV/TSV with a header row. Required columns ``id, type, content``; optional ``units``
  (";"-separated), ``locator``, ``recorded_at``, ``source``. Columns starting with "_" are
  ignored, any other unknown column is rejected. Empty optional cells mean "absent"; an empty
  ``source`` cell falls back to the ``source`` argument (default: the file name). Errors name
  "row N" (header = row 0, data rows from 1) and the column. Spreadsheets (.xlsx/.ods) are not
  parsed (stdlib only): export them to CSV first.
* Structured notes: UTF-8 text, blocks separated by a line ``---``. A block is ``key: value``
  lines (id, type, units, locator, recorded_at, source), a blank line, then free-text content
  kept verbatim minus trailing whitespace. Errors name "block N" and a line number.
* Image captions: CSV with columns ``image, caption`` and optional ``id, locator, recorded_at``.
  Items are ``photo_note``; provenance.source is the image path as written; the id defaults to
  ``slug_id(image)``.

``recorded_by`` is never in the file; the caller supplies it. Readers stream rows/blocks and hold
only the output tuple and the id set (plus one notes block). Stdlib only, local only (I9).

Unwired by design until AD-05 / source store (the future source-item store and the support
matcher, AD-02/AD-05, are the production callers).
"""

from __future__ import annotations

import csv
import os
import re
import unicodedata

from service.source_items import SourceItem, SourceItemError, to_dict, validate_source_items

_TABLE_REQUIRED = ("id", "type", "content")
_TABLE_COLUMNS = ("id", "type", "content", "units", "locator", "recorded_at", "source")
_CAPTION_REQUIRED = ("image", "caption")
_CAPTION_COLUMNS = ("image", "caption", "id", "locator", "recorded_at")
_NOTE_KEYS = ("id", "type", "units", "locator", "recorded_at", "source")
_DELIMITERS = {".csv": ",", ".tsv": "\t"}
_SPREADSHEETS = (".xlsx", ".xls", ".xlsm", ".ods")
_INDEX_PREFIX = re.compile(r"\[\d+\]\.")


def _validate(pairs):
    """Run (where, obj) pairs through validate_source_items, re-prefixing errors with ``where``.

    validate_source_items consumes the generator lazily, so when it raises, ``state[0]`` is the
    location of the object being validated.
    """
    state = [""]

    def objs():
        for where, obj in pairs:
            state[0] = where
            yield obj

    try:
        return validate_source_items(objs())
    except SourceItemError as exc:
        msg = str(exc)
        if not _INDEX_PREFIX.match(msg):
            raise  # raised by the reader itself, already located
        raise SourceItemError(f"{state[0]}{_INDEX_PREFIX.sub('', msg, count=1)}") from exc


def _item_obj(id_, type_, content, units, source, locator, recorded_by, recorded_at):
    prov = {"source": source, "recorded_by": recorded_by}
    if locator:
        prov["locator"] = locator
    if recorded_at:
        prov["recorded_at"] = recorded_at
    return {"id": id_, "type": type_, "content": content, "units": units, "provenance": prov}


def _split_units(cell):
    return [u.strip() for u in cell.split(";") if u.strip()] if cell else []


def _delimiter(path, delimiter):
    ext = os.path.splitext(str(path))[1].lower()
    if ext in _SPREADSHEETS:
        raise SourceItemError(
            f"<file> {path}: {ext} spreadsheets are not supported; export the sheet to CSV "
            "(or TSV) and import that")
    if delimiter is not None:
        return delimiter
    if ext not in _DELIMITERS:
        raise SourceItemError(f"<file> {path}: cannot infer delimiter from {ext or 'no extension'!r}; "
                              "use .csv/.tsv or pass delimiter=")
    return _DELIMITERS[ext]


def _rows(path, delimiter, required, allowed):
    """Yield (row number, {column: cell}) for data rows; header checked as row 0."""
    try:
        fh = open(path, encoding="utf-8", newline="")
    except OSError as exc:
        raise SourceItemError(f"<file> {path}: {exc}") from exc
    with fh:
        reader = csv.reader(fh, delimiter=delimiter)
        header = next(reader, None)
        if header is None:
            raise SourceItemError("row 0: missing header row")
        for col in header:
            if not col.startswith("_") and col not in allowed:
                raise SourceItemError(f"row 0: column {col!r}: unknown column")
        if len(set(header)) != len(header):
            raise SourceItemError("row 0: duplicate column name")
        for col in required:
            if col not in header:
                raise SourceItemError(f"row 0: column {col!r}: required column missing")
        for n, cells in enumerate(reader, 1):
            if not cells:
                continue
            if len(cells) != len(header):
                raise SourceItemError(
                    f"row {n}: has {len(cells)} cells, header has {len(header)}")
            yield n, dict(zip(header, cells))


def import_table(path, *, source=None, recorded_by, delimiter=None) -> tuple[SourceItem, ...]:
    """Import a CSV/TSV table of source items (see module docstring)."""
    delim = _delimiter(path, delimiter)
    default_source = source if source is not None else os.path.basename(str(path))

    def pairs():
        for n, row in _rows(path, delim, _TABLE_REQUIRED, _TABLE_COLUMNS):
            yield f"row {n}: ", _item_obj(
                row["id"], row["type"], row["content"], _split_units(row.get("units")),
                row.get("source") or default_source, row.get("locator"), recorded_by,
                row.get("recorded_at"))

    return _validate(pairs())


def _check_units_cell(item):
    for u in item.units:
        if ";" in u:
            raise SourceItemError(f"{item.id}: unit {u!r} contains ';'")


def export_table(items, path) -> None:
    """Write items in the import_table format; delimiter from the .csv/.tsv extension."""
    delim = _delimiter(path, None)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter=delim, lineterminator="\n")
        writer.writerow(_TABLE_COLUMNS)
        for item in items:
            _check_units_cell(item)
            p = item.provenance
            writer.writerow([item.id, item.type, item.content, ";".join(item.units),
                             p.locator or "", p.recorded_at or "", p.source])


def _blocks(path):
    """Yield (block number, start line, {key: (value, line)}, content) per non-empty block."""
    try:
        fh = open(path, encoding="utf-8")
    except OSError as exc:
        raise SourceItemError(f"<file> {path}: {exc}") from exc
    with fh:
        block, start, header, body, in_body = 1, 1, {}, [], False

        def finish():
            return (block, start, header, "\n".join(body).rstrip())

        for n, raw in enumerate(fh, 1):
            line = raw.rstrip("\r\n")
            if line == "---":
                if header or body:
                    yield finish()
                    block += 1
                start, header, body, in_body = n + 1, {}, [], False
                continue
            if in_body:
                body.append(line)
            elif not line.strip():
                if header:
                    in_body = True
                else:
                    start = n + 1  # leading blank lines before the header
            else:
                key, sep, value = line.partition(":")
                key = key.strip()
                where = f"block {block}, line {n}: "
                if not sep:
                    raise SourceItemError(f"{where}expected 'key: value' header line")
                if key not in _NOTE_KEYS:
                    raise SourceItemError(f"{where}{key}: unknown key")
                if key in header:
                    raise SourceItemError(f"{where}{key}: duplicate key")
                header[key] = (value.strip(), n)
        if header or body:
            yield finish()


def import_notes(path, *, recorded_by) -> tuple[SourceItem, ...]:
    """Import a structured-notes text file (see module docstring)."""
    default_source = os.path.basename(str(path))
    lines = {}

    def pairs():
        for block, start, header, content in _blocks(path):
            get = lambda k: header.get(k, (None, None))[0]  # noqa: E731
            lines.clear()
            lines.update({k: ln for k, (_, ln) in header.items()})
            lines["<start>"] = start
            lines["<block>"] = block
            obj = _item_obj(get("id"), get("type"), content, _split_units(get("units")),
                            get("source") or default_source, get("locator"), recorded_by,
                            get("recorded_at"))
            for key in ("id", "type"):
                if key not in header:
                    del obj[key]
            yield f"block {block}, line {start}: ", obj

    try:
        return _validate(pairs())
    except SourceItemError as exc:
        # point at the header line of the offending key when there is one
        m = re.match(r"block (\d+), line (\d+): (?:provenance\.)?([a-z_]+)", str(exc))
        if m and m.group(3) in lines and lines.get("<block>") == int(m.group(1)):
            msg = str(exc).replace(f"line {m.group(2)}:", f"line {lines[m.group(3)]}:", 1)
            raise SourceItemError(msg) from exc
        raise


def _note_value(item, key, value):
    if value != value.strip() or "\n" in value or "\r" in value:
        raise SourceItemError(f"{item.id}: {key} {value!r} cannot be written as a notes header")
    return value


def export_notes(items, path) -> None:
    """Write items in the import_notes format.

    Raises SourceItemError for content that would not read back identically (trailing
    whitespace, a line ``---``) or header values with surrounding whitespace or newlines.
    """
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for i, item in enumerate(items):
            content = item.content
            if content != content.rstrip() or "---" in content.replace("\r", "").split("\n"):
                raise SourceItemError(
                    f"{item.id}: content with trailing whitespace or a '---' line "
                    "cannot be written as a note")
            _check_units_cell(item)
            d = to_dict(item)
            prov = d["provenance"]
            fields = [("id", d["id"]), ("type", d["type"])]
            if item.units:
                fields.append(("units", "; ".join(item.units)))
            for key in ("locator", "recorded_at", "source"):
                if key in prov:
                    fields.append((key, prov[key]))
            if i:
                fh.write("---\n")
            for key, value in fields:
                fh.write(f"{key}: {_note_value(item, key, value)}\n")
            fh.write("\n" + content + "\n")


def slug_id(image) -> str:
    """Default caption id: the image file stem, ASCII-folded, lowercased, runs of characters
    outside [a-z0-9.] replaced by "-", leading/trailing "-" and "." stripped."""
    stem = os.path.splitext(os.path.basename(image.replace("\\", "/")))[0]
    ascii_ = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9.]+", "-", ascii_.lower()).strip("-.")
    if not slug:
        raise SourceItemError(f"id: cannot derive an id from image {image!r}; give an id column")
    return slug


def import_captions(path, *, recorded_by) -> tuple[SourceItem, ...]:
    """Import an image-caption CSV as photo_note items (see module docstring)."""

    def pairs():
        for n, row in _rows(path, ",", _CAPTION_REQUIRED, _CAPTION_COLUMNS):
            where = f"row {n}: "
            image = row["image"]
            if not image.strip():
                raise SourceItemError(f"{where}image: must be a non-empty string")
            try:
                item_id = row.get("id") or slug_id(image)
            except SourceItemError as exc:
                raise SourceItemError(f"{where}{exc}") from None
            yield where, _item_obj(item_id, "photo_note", row["caption"], [], image,
                                   row.get("locator"), recorded_by, row.get("recorded_at"))

    return _validate(pairs())


def export_captions(items, path) -> None:
    """Write photo_note items in the import_captions format (id always written)."""
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(_CAPTION_COLUMNS)
        for item in items:
            if item.type != "photo_note" or item.units:
                raise SourceItemError(
                    f"{item.id}: only photo_note items without units can be written as captions")
            p = item.provenance
            writer.writerow([p.source, item.content, item.id, p.locator or "",
                             p.recorded_at or ""])
