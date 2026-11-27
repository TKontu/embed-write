"""CO-04 / D-016: MinerU native ``/file_parse`` adapter for PDF ingestion (stdlib only).

Modelled on iknosreview's ``src/iknos/core/mineru_native.py`` (read-only reference). One PDF is
posted as multipart ``POST {PARSER_BASE_URL}/file_parse`` with ``backend=pipeline``,
``lang_list=en``, ``return_content_list=true`` and ``return_images=true``; the response is held for
that file only and its ``content_list`` (reading-order typed blocks) is mapped to Markdown:

- ``text`` with ``text_level`` N >= 1 -> ATX heading (``#`` * N, capped at 6), feeding D-015;
- ``text`` / ``aside_text`` / ``page_footnote`` / ``list`` -> paragraph (list items one per line);
- ``equation`` -> ``$$`` block with the LaTeX kept verbatim;
- ``table`` -> Markdown pipe table (``table_body`` HTML parsed with html.parser), caption line
  before it and footnote line after it;
- ``image`` / ``chart`` -> one figure caption line (``Figure: <caption>``, or ``[image]``/``[chart]``);
- ``page_number`` / ``footer`` / ``header`` -> dropped and counted per type;
- unknown types with text -> paragraph, so nothing is silently lost.

Figure crops are not kept: no local blob path is configured in this repository, so the
``images`` map returned under ``return_images`` is discarded with the response.

Settings come from the environment: ``PARSER_BASE_URL`` (empty/unset means no service, pypdf only)
and ``PARSER_TIMEOUT_S`` (default 300). Network errors are left to the caller
(``experiments.ingest.convert_pdf``), which retries a timeout/connection error once and then falls
back to pypdf for that file.
"""
from __future__ import annotations

import json
import os
import urllib.request
import uuid
from collections import Counter
from html.parser import HTMLParser
from typing import Any, Callable

DEFAULT_TIMEOUT_S = 300.0
CHROME_TYPES = frozenset({"page_number", "footer", "header"})
FIELDS = (("backend", "pipeline"), ("lang_list", "en"),
          ("return_content_list", "true"), ("return_images", "true"))


def settings() -> tuple[str, float]:
    """(base_url, timeout_s) from the environment; base_url "" means no service."""
    url = os.environ.get("PARSER_BASE_URL", "").strip()
    try:
        timeout = float(os.environ.get("PARSER_TIMEOUT_S", "") or DEFAULT_TIMEOUT_S)
    except ValueError:
        timeout = DEFAULT_TIMEOUT_S
    return url, timeout


def _multipart(data: bytes, filename: str) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts = []
    for name, value in FIELDS:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
                     f"{value}\r\n".encode())
    safe = filename.replace('"', "_").replace("\r", "_").replace("\n", "_")
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="files"; '
                 f'filename="{safe}"\r\nContent-Type: application/pdf\r\n\r\n'.encode())
    parts.append(data + b"\r\n" + f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def post_file_parse(data: bytes, filename: str, base_url: str, timeout: float) -> dict:
    body, ctype = _multipart(data, filename)
    req = urllib.request.Request(base_url.rstrip("/") + "/file_parse", data=body, method="POST",
                                 headers={"Content-Type": ctype, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def content_list_of(raw: dict) -> list:
    results = raw.get("results") if isinstance(raw, dict) else None
    if not isinstance(results, dict) or not results:
        raise ValueError("mineru: response has no results")
    record = results[next(iter(results))]
    cl = record.get("content_list") if isinstance(record, dict) else None
    if isinstance(cl, str):
        cl = json.loads(cl)
    if not isinstance(cl, list):
        raise ValueError("mineru: content_list missing or not a list")
    return cl


class _TableHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th"):
            self._cell = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            if self._row is not None:
                self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None


def table_rows(table_body: str) -> list[list[str]]:
    p = _TableHTML()
    p.feed(table_body or "")
    p.close()
    return [r for r in p.rows if r]


def _captions(values: Any) -> str:
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, list):
        return ""
    return " ".join(v.strip() for v in values if isinstance(v, str) and v.strip())


def _level(value: Any) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return min(n, 6) if n >= 1 else None


def _identity(s: str) -> str:
    return s


def content_list_to_markdown(blocks: list, escape: Callable[[str], str] = _identity,
                             table: Callable[[list[list[str]]], str] | None = None
                             ) -> tuple[str, dict[str, int]]:
    """Map content_list blocks to (markdown, dropped chrome counts by type)."""
    out: list[str] = []
    dropped: Counter[str] = Counter()
    for b in blocks:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t in CHROME_TYPES:
            dropped[str(t)] += 1
            continue
        text = (b.get("text") or "").strip() if isinstance(b.get("text"), str) else ""
        if t == "text" and text and (lvl := _level(b.get("text_level"))):
            out.append("#" * lvl + " " + escape(" ".join(text.split())))
        elif t == "list":
            items = [str(i).strip() for i in (b.get("list_items") or []) if str(i).strip()]
            if items:
                out.append("\n".join(escape(i) for i in items))
            elif text:
                out.append(escape(text))
        elif t == "equation":
            if text:
                latex = text.strip("$").strip() if text.startswith("$$") else text
                out.append("$$\n" + latex + "\n$$")
        elif t == "table":
            cap = _captions(b.get("table_caption"))
            if cap:
                out.append(escape(cap))
            rows = [[escape(c) for c in r] for r in table_rows(b.get("table_body") or "")]
            if rows and table is not None:
                out.append(table(rows))
            foot = _captions(b.get("table_footnote"))
            if foot:
                out.append(escape(foot))
        elif t in ("image", "chart"):
            cap = _captions(b.get(f"{t}_caption"))
            out.append("Figure: " + escape(cap) if cap else f"\\[{t}\\]")
            foot = _captions(b.get(f"{t}_footnote"))
            if foot:
                out.append(escape(foot))
        elif text:
            out.append(escape(text))
    md = "\n\n".join(s for s in out if s.strip())
    return (md + "\n" if md else ""), dict(sorted(dropped.items()))


def parse_pdf(data: bytes, filename: str, base_url: str, timeout: float,
              escape: Callable[[str], str] = _identity,
              table: Callable[[list[list[str]]], str] | None = None) -> tuple[str, dict[str, int]]:
    """POST one PDF to MinerU and map the response; network errors propagate."""
    raw = post_file_parse(data, filename, base_url, timeout)
    return content_list_to_markdown(content_list_of(raw), escape, table)
