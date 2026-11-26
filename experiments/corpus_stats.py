"""CO-09: corpus statistics over a Markdown corpus (stdlib plus CK-02 segmentation).

Streams documents one at a time through experiments.corpus.iter_documents and
keeps only per-document counts, per-heading document/level usage and integer
section-length lists; document text is never retained. Sections are split on
ATX headings (``#``..``######``); text before the first heading is a section
with heading ``null`` (a preamble counts only when it has non-whitespace text).
Sentence counts come from service.segment.segment_sentences over the prose paragraphs
annotation_sample.section_paragraphs yields (fenced/indented code, setext heading text and
front matter excluded), so per-document counts equal document_sentences. Heading text is
normalised (stripped, closing ``#`` sequence removed, case-folded); the report
contains heading strings only, no body excerpts.

``--metadata`` joins CO-06 JSONL records to documents by doc_id = path stem and
adds per-genre document counts plus matched/unmatched counts. A metadata record
matches every document with that stem; duplicate stems are not detected.
Lines inside fenced code blocks (CommonMark: 3+ backticks or tildes with up to
three leading spaces; closed by the same character at least as long; an unclosed
fence runs to end of document) are section body text, never headings. Unwired by design: MV-02 and CO-05 will read the report.

CLI: python -m experiments.corpus_stats report CORPUS_DIR OUT.json
     [--metadata META.jsonl] [--force]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from pathlib import Path
from typing import Iterator

from experiments.annotation_sample import section_paragraphs
from experiments.corpus import iter_documents
from experiments.corpus_metadata import iter_records, word_count
from service.segment import segment_sentences

# ATX heading: up to three leading spaces, one to six #s, then whitespace or EOL.
_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*$")
# Optional closing sequence (CommonMark): #s preceded by whitespace or forming the whole
# content, e.g. "## Title ##" and "### ###"; "# foo#" keeps "foo#".
_CLOSING = re.compile(r"(?:^|[ \t]+)#+$")

# Fence line: up to three leading spaces, 3+ backticks or tildes, then the rest.
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
_PREAMBLE = object()


def _heading_text(raw: str | None) -> str:
    """Normalised heading text: closing #s and surrounding space removed, case-folded."""
    if raw is None:
        return ""
    return _CLOSING.sub("", raw.strip()).strip().casefold()


def _iter_sections(text: str) -> Iterator[tuple[object, str]]:
    """Yield (heading, body) pairs; heading is (level, normalised text) or _PREAMBLE."""
    heading: object = _PREAMBLE
    body: list[str] = []
    fence: str | None = None  # opening marker while inside a fenced code block
    for line in text.splitlines():
        fmatch = _FENCE.match(line)
        if fence is not None:
            if (
                fmatch is not None
                and fmatch.group(1)[0] == fence[0]
                and len(fmatch.group(1)) >= len(fence)
                and not fmatch.group(2).strip()
            ):
                fence = None
            body.append(line)
            continue
        if fmatch is not None and not (
            fmatch.group(1)[0] == "`" and "`" in fmatch.group(2)
        ):
            fence = fmatch.group(1)
            body.append(line)
            continue
        match = _ATX.match(line)
        if match is None:
            body.append(line)
            continue
        if heading is not _PREAMBLE:
            yield heading, "\n".join(body)
        else:
            preamble = "\n".join(body)
            if preamble.strip():
                yield _PREAMBLE, preamble
        heading = (len(match.group(1)), _heading_text(match.group(2)))
        body = []
    if heading is not _PREAMBLE:
        yield heading, "\n".join(body)
    else:
        preamble = "\n".join(body)
        if preamble.strip():
            yield _PREAMBLE, preamble


def _length_stats(values: list[int]) -> dict:
    """Min/median/max/total over integer section lengths; zeroes when empty."""
    if not values:
        return {"min": 0, "median": 0.0, "max": 0, "total": 0}
    return {
        "min": min(values),
        "median": float(statistics.median(values)),
        "max": max(values),
        "total": sum(values),
    }


def _metadata_summary(metadata: str | os.PathLike, stems: dict[str, str]) -> dict:
    """Per-genre document counts and unmatched counts against metadata doc_ids."""
    genres_by_id = {record["doc_id"]: record["genre"] for record in iter_records(metadata)}
    genres: dict[str, int] = {}
    matched = 0
    unmatched_documents = 0
    for relpath in sorted(stems):
        genre = genres_by_id.get(stems[relpath])
        if genre is None:
            unmatched_documents += 1
        else:
            matched += 1
            genres[genre] = genres.get(genre, 0) + 1
    return {
        "genres": {name: genres[name] for name in sorted(genres)},
        "matched_documents": matched,
        "unmatched_documents": unmatched_documents,
        "unmatched_records": len(set(genres_by_id) - set(stems.values())),
    }


def build_report(corpus_dir: str | os.PathLike, metadata: str | os.PathLike | None = None) -> dict:
    """Build the statistics report; documents are streamed and never retained.

    Raises FileNotFoundError when corpus_dir is not a directory and
    MetadataError when the optional metadata file is invalid.
    """
    root = Path(corpus_dir)
    headings: dict[str, dict] = {}
    word_lengths: list[int] = []
    sentence_lengths: list[int] = []
    per_document: dict[str, dict] = {}
    stems: dict[str, str] = {}
    for document in iter_documents(root):
        relpath = document.path.relative_to(root).as_posix()
        stems[relpath] = document.path.stem
        sections = 0
        sentences = 0
        used: set[str] = set()
        for heading, body in _iter_sections(document.text):
            sections += 1
            # Same paragraph parser as the annotation sample, so per-document counts agree.
            sentences_in_section = sum(len(segment_sentences(p))
                                       for p in section_paragraphs(body))
            sentences += sentences_in_section
            word_lengths.append(word_count(body))
            sentence_lengths.append(sentences_in_section)
            if heading is _PREAMBLE:
                continue
            level, text = heading  # type: ignore[misc]
            entry = headings.setdefault(text, {"documents": 0, "levels": set()})
            entry["levels"].add(level)
            if text not in used:
                used.add(text)
                entry["documents"] += 1
        per_document[relpath] = {"sections": sections, "sentences": sentences}
    report = {
        "documents": len(per_document),
        "headings": {
            text: {"documents": entry["documents"], "levels": sorted(entry["levels"])}
            for text, entry in sorted(headings.items())
        },
        "sections": {
            "count": len(word_lengths),
            "words": _length_stats(word_lengths),
            "sentences": _length_stats(sentence_lengths),
        },
        "per_document": {relpath: per_document[relpath] for relpath in sorted(per_document)},
    }
    if metadata is not None:
        report["metadata"] = _metadata_summary(metadata, stems)
    return report


def write_report(report: dict, out: str | os.PathLike, force: bool = False) -> None:
    """Write the report as sorted-key JSON; refuse to overwrite unless force."""
    data = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with open(out, "w" if force else "x", encoding="utf-8") as fh:
        fh.write(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m experiments.corpus_stats")
    sub = parser.add_subparsers(dest="cmd", required=True)
    report = sub.add_parser("report", help="write a JSON statistics report over a Markdown corpus")
    report.add_argument("corpus")
    report.add_argument("out")
    report.add_argument("--metadata", default=None, help="CO-06 JSONL for per-genre counts")
    report.add_argument("--force", action="store_true", help="overwrite an existing OUT")
    args = parser.parse_args(argv)
    if not Path(args.corpus).is_dir():
        print(f"error: corpus directory not found: {args.corpus}", file=sys.stderr)
        return 2
    if Path(args.out).exists() and not args.force:
        print(f"error: {args.out} exists; use --force to overwrite", file=sys.stderr)
        return 1
    try:
        stats = build_report(args.corpus, metadata=args.metadata)
        write_report(stats, args.out, force=args.force)
    except FileExistsError:
        print(f"error: {args.out} exists; use --force to overwrite", file=sys.stderr)
        return 1
    except (OSError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
