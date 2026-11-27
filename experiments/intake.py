"""CO-12: corpus intake, one command from a folder of reports to an annotation-ready set.

Chains the existing steps in-process through their public functions (no subprocess, no
duplicated logic):

1. ``ingest``: CO-04 ``experiments.ingest.convert_dir`` SRC -> OUT/converted (+ ingest_report.json)
2. ``conversion_quality``: CO-05 ``build_report``/``write_report`` -> OUT/conversion_quality.json
3. ``corpus_stats``: CO-09 ``build_report``/``write_report`` over OUT/converted -> OUT/corpus_stats.json
4. ``metadata``: CO-06 ``validate_file`` (only with --metadata; else skipped)
5. ``sections``: CO-14 ``section_inference.infer_sections`` for documents with no ATX headings
   (D-015) -> OUT/sections.json (private; line numbers and methods, marked inferred). The report
   holds documents by status, sections by method and the embedder model_id only. When
   EMBED_WRITE_MODEL_DIR names a model dir (same rule as ``discovery``) the OnnxEmbedder drives
   the ``topic_shift_embedding`` fallback; otherwise no embedder (lexical ``topic_shift``; never
   the HashEmbedder, whose vectors are not semantic).
6. ``annotation_sample``: AN-02 ``split_documents`` + ``build_manifest`` -> OUT/manifest.json.
   Inferred sections from OUT/sections.json become provisional ``inferred`` strata; if the
   sections step did not succeed, sampling proceeds without them and says so in ``reason``.
7. ``prelabel``: G-01.4 ``iter_prelabel`` over the manifest items (only with --model-url; else
   skipped) -> OUT/prelabels.jsonl
8. ``discovery``: MV-02 ``move_discovery.make_embedder`` + ``build_report``/``write_report`` over
   OUT/converted (only with --discover; else skipped) -> OUT/move_discovery.json. The embedder is
   the development HashEmbedder unless EMBED_WRITE_MODEL_DIR names a local ONNX model directory,
   then the real BGE-M3 OnnxEmbedder. The discovery report holds corpus sentences and stays under
   OUT (private); intake_report.json records only its path, status and counts (clusters per
   section type, sentences sampled/seen, whether the embedder is development-only).

It writes OUT/intake_report.json: per step ``status`` (ok/failed/skipped), ``reason``, ``output``
and counts only, then ``next_steps`` (exact expert command lines built from the actual paths).
A failed step makes its dependents ``skipped`` with reason ``blocked by <step>``.

Privacy (acceptance-critical): the report and everything printed hold file names, codes and
counts only. Exception messages from sub-steps can quote corpus text, so a failure is reduced to
its exception type name; per-document conversion errors and flag details stay in the sub-step
files under OUT (private, like the corpus) and only their counts/codes reach the report.

Determinism: no timestamps, sorted keys, paths exactly as given on the command line; a re-run
with the same arguments and --force rewrites a byte-identical report (prelabels.jsonl is removed
first so the run relabels instead of resuming).

Scale: documents are streamed one at a time by every sub-step; this module holds ids, paths and
counts only. The ingest step holds one entry per source file (paths + status), and AN-02 holds
O(test sentences) id tuples (its own documented bound). Not tested above the demo size.

A document that fails to convert is counted under ``documents.failed`` and the step stays ``ok``
while at least one document converted (per-file isolation, CO-04); it is ``failed`` when none did.

Production caller: the expert/operator CLI.

CLI: python -m experiments.intake run SRC OUT --genre GENRE.json [--metadata META.jsonl]
     [--split-seed N] [--test-fraction F] [--n N] [--seed N]
     [--model-url URL --model-name NAME] [--discover [--discover-k N]
     [--discover-sample N]] [--force]

--force first removes the files a previous intake run wrote into OUT (``OWNED`` names and
OUT/converted only; every other file survives), so a rerun leaves no stale output. An owned
name that is a directory, or --metadata pointing at an owned file or into OUT/converted, is
refused with exit 2 before anything is removed (metadata is never deleted unread).
Exit 0 when every step is ok or skipped, 1 when any step failed, 2 on usage errors.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sys
from collections import Counter
from pathlib import Path

from experiments import annotate, annotation_sample, conversion_quality, corpus_metadata
from experiments import corpus_stats, ingest, move_discovery, prelabel, section_inference
from experiments.corpus import iter_documents
from experiments.splits import split_documents
from service.genre import load_genre

REPORT_NAME = "intake_report.json"
CONVERTED = "converted"
STEPS = ("ingest", "conversion_quality", "corpus_stats", "metadata", "sections",
         "annotation_sample", "prelabel", "discovery")
DEPENDS = {"conversion_quality": "ingest", "corpus_stats": "ingest",
           "annotation_sample": "ingest", "prelabel": "annotation_sample",
           "discovery": "corpus_stats", "sections": "corpus_stats"}
NO_METADATA = "metadata owed by the expert (CO-06)"
NO_MODEL = "no local model endpoint given"
NO_DISCOVER = "not requested"
DISCOVERY_NAME = "move_discovery.json"
SECTIONS_NAME = "sections.json"
MODEL_DIR_ENV = "EMBED_WRITE_MODEL_DIR"
# CO-14 (c): expert section corrections saved by the demo (private, gitignored edit-log/).
SECTION_CORRECTIONS_ENV = "SECTION_CORRECTIONS_DIR"
DEFAULT_SECTION_CORRECTIONS = Path(__file__).resolve().parent.parent / "edit-log" / "section-corrections"
# Files intake itself writes into OUT (besides CONVERTED); a run removes these first so a
# --force rerun leaves no stale output. Never other files (annotations.jsonl is the expert's).
OWNED = ("conversion_quality.json", "corpus_stats.json", "manifest.json", "prelabels.jsonl",
         DISCOVERY_NAME, SECTIONS_NAME, REPORT_NAME)


def _code(exc: BaseException) -> str:
    """Reduce an exception to its type name: messages may quote corpus text."""
    return type(exc).__name__


def _step(status: str, reason: str | None = None, output: str | None = None,
          counts: dict | None = None) -> dict:
    return {"status": status, "reason": reason, "output": output, "counts": counts or {}}


def _ingest(src: Path, converted: Path) -> tuple[dict, list[str]]:
    report = ingest.convert_dir(src, converted)
    (converted / ingest.REPORT_NAME).write_text(json.dumps(report, indent=2) + "\n",
                                                encoding="utf-8")
    outputs = sorted(e["output"] for e in report["files"] if e["status"] == "ok")
    counts = {"documents": dict(report["summary"])}
    status = "ok" if outputs else "failed"
    reason = None if outputs else "no document converted"
    return _step(status, reason, str(converted / ingest.REPORT_NAME), counts), outputs


def _quality(converted: Path, out: Path) -> dict:
    report = json.loads((converted / ingest.REPORT_NAME).read_text(encoding="utf-8"))
    result = conversion_quality.build_report(report)
    path = out / "conversion_quality.json"
    conversion_quality.write_report(result, path, force=True)
    s = result["summary"]
    return _step("ok", None, str(path), {"documents_checked": s["documents_checked"],
                                         "documents_flagged": s["documents_flagged"],
                                         "flags": dict(s["flags"])})


def _stats(converted: Path, out: Path) -> dict:
    report = corpus_stats.build_report(converted)
    path = out / "corpus_stats.json"
    corpus_stats.write_report(report, path, force=True)
    sentences = sum(d["sentences"] for d in report["per_document"].values())
    return _step("ok", None, str(path), {"documents": report["documents"],
                                         "sections": report["sections"]["count"],
                                         "sentences": sentences})


def _metadata(meta: str) -> dict:
    errors = corpus_metadata.validate_file(meta)
    records = 0
    if not errors:
        records = sum(1 for _ in corpus_metadata.iter_records(meta))
    counts = {"errors": len(errors), "records": records}
    if errors:
        return _step("failed", "invalid metadata", meta, counts)
    return _step("ok", None, meta, counts)


def _sample(converted: Path, out: Path, genre, args, sections_ok: bool = False) -> dict:
    ids = sorted(q.relative_to(converted).as_posix() for q in converted.rglob("*.md")
                 if q.is_file())
    split = split_documents(ids, args.test_fraction, args.split_seed)
    docs = ((d.path.relative_to(converted).as_posix(), d.text)
            for d in iter_documents(converted))
    sections = out / SECTIONS_NAME
    inferred = (annotation_sample.load_inferred(sections)
                if sections_ok and sections.exists() else None)  # O(documents x sections)
    manifest = annotation_sample.build_manifest(
        ((d, t) for d, t in docs if d in split.test_ids), split, genre, n=args.n,
        seed=args.seed, inferred=inferred)
    path = out / "manifest.json"
    annotation_sample.write_manifest(path, manifest)
    reason = None if inferred is not None else "sampled without inferred sections"
    return _step("ok", reason, str(path), {
        "test_documents": len(split.test_ids), "strata": len(manifest["candidates_per_stratum"]),
        "n_requested": manifest["n_requested"], "n_drawn": manifest["n_drawn"],
        "repeat": len(manifest["repeat"]), "unknown_sentences": manifest["unknown_sentences"],
        "inferred_sentences": manifest.get("inferred_sentences", 0)})


def _prelabel(converted: Path, out: Path, genre, model) -> dict:
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    items = annotate.resolve_items(manifest, annotate.load_documents(converted, manifest), genre,
                                   only=annotate.pass_ids(manifest, "first"))
    path = out / "prelabels.jsonl"
    path.unlink(missing_ok=True)
    status: Counter = Counter()
    labels: Counter = Counter()
    for rec in prelabel.iter_prelabel(items, genre, model, out_path=path):
        status["invalid_reply" if rec["invalid_reply"] else "labelled"] += 1
        labels[rec["label"]] += 1
    return _step("ok", None, str(path), {"records": sum(status.values()),
                                         "by_status": dict(sorted(status.items())),
                                         "labels": dict(sorted(labels.items()))})


def _discover(converted: Path, out: Path, genre, k: int | None = None,
              sample: int | None = None) -> dict:
    model_dir = os.environ.get(MODEL_DIR_ENV) or None
    embedder = move_discovery.make_embedder("onnx" if model_dir else "hash", model_dir)
    params = {}
    if k is not None:
        params["k"] = k
    if sample is not None:
        params["max_per_type"] = sample
    report = move_discovery.build_report(converted, genre, embedder=embedder, **params)
    path = out / DISCOVERY_NAME
    move_discovery.write_report(report, path, force=True)
    return _step("ok", None, str(path), {
        "clusters_per_section_type": {t: len(c) for t, c in sorted(report["clusters"].items())},
        "sentences_sampled": report["sentences"]["sampled"],
        "sentences_seen": report["sentences"]["seen"],
        "development_only_embedder": report["embedder"]["development_only"], **params})


def _section_correction(corrections: Path, name: str, line_count: int) -> list[dict] | None:
    """The expert's saved section boundaries for document ``name`` (DIR/<name>.json), or None.

    Written by the demo (editor/demo/server.js); line numbers and levels only, method "expert".
    A malformed file raises ValueError (the step fails by type name; no text is reported),
    including non-object JSON and a start_line outside ``range(line_count)`` or repeated.
    """
    path = corrections.joinpath(*name.split("/")).with_name(name.split("/")[-1] + ".json")
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("not a section correction")
    secs = data.get("sections")
    if data.get("schema") != 1 or data.get("document") != name or not isinstance(secs, list):
        raise ValueError("not a section correction")
    out = []
    for s in secs:
        if (not isinstance(s, dict) or type(s.get("start_line")) is not int
                or not 0 <= s["start_line"] < line_count
                or type(s.get("level")) is not int or s.get("method") != "expert"
                or s.get("inferred") is not False):
            raise ValueError("bad section correction entry")
        if any(o["start_line"] == s["start_line"] for o in out):
            raise ValueError("duplicate section correction entry")
        out.append({"start_line": s["start_line"], "level": s["level"], "method": "expert",
                    "inferred": False})
    return sorted(out, key=lambda s: s["start_line"])


def _sections(converted: Path, out: Path) -> dict:
    """CO-14 (D-015): infer provisional sections for documents with no ATX headings.

    Headings are used as written when ``corpus_stats._iter_sections`` finds a non-preamble one.
    Sections (line numbers, methods) go to private OUT/sections.json; counts only reach the report.
    With EMBED_WRITE_MODEL_DIR set, the real OnnxEmbedder drives the semantic fallback and
    ``counts.embedder`` records its model_id; otherwise it is None (lexical fallback).
    A heading-less document with an expert correction (SECTION_CORRECTIONS_DIR, default
    edit-log/section-corrections) uses it instead of the inference; ``counts.corrected`` counts them.
    """
    corrections = Path(os.environ.get(SECTION_CORRECTIONS_ENV) or DEFAULT_SECTION_CORRECTIONS)
    corrected = 0
    model_dir = os.environ.get(MODEL_DIR_ENV) or None
    embedder = move_discovery.make_embedder("onnx", model_dir) if model_dir else None
    documents: dict[str, dict] = {}
    by_status: Counter = Counter()
    by_method: Counter = Counter()
    for doc in iter_documents(converted):  # one document at a time
        name = doc.path.relative_to(converted).as_posix()
        expert = None
        if any(h is not corpus_stats._PREAMBLE for h, _ in corpus_stats._iter_sections(doc.text)):
            status, secs = "has_headings", []
        else:
            expert = _section_correction(corrections, name, len(doc.text.splitlines()))
            secs = (expert if expert is not None
                    else section_inference.infer_sections(doc.text, embedder=embedder))
            status = "inferred" if secs else "none_found"
        by_status[status] += 1
        by_method.update(s["method"] for s in secs)
        documents[name] = {"status": status, "sections": secs}
        if status != "has_headings" and expert is not None:
            documents[name]["corrected"] = True
            corrected += 1
    path = out / SECTIONS_NAME
    path.write_text(json.dumps({"schema": 1, "documents": documents}, indent=2, sort_keys=True)
                    + "\n", encoding="utf-8")
    return _step("ok", None, str(path), {"documents": dict(sorted(by_status.items())),
                                         "sections": dict(sorted(by_method.items())),
                                         "corrected": corrected,
                                         "embedder": embedder.model_id if embedder else None})


def _editor_path(path: str) -> str:
    """The converted file as seen from editor/ (npm runs the demo there)."""
    return path if Path(path).is_absolute() else str(Path("..") / path)


def _next_steps(steps: dict, out: Path, converted: Path, genre_path: str,
                outputs: list[str]) -> list[str]:
    q = shlex.quote
    lines = []
    if steps["annotation_sample"]["status"] == "ok":
        cmd = (f"python -m experiments.annotate --manifest {q(str(out / 'manifest.json'))} "
               f"--corpus {q(str(converted))} --genre {q(genre_path)} "
               f"--store {q(str(out / 'annotations.jsonl'))} --annotator EXPERT")
        if steps["prelabel"]["status"] == "ok":
            cmd += f" --prelabels {q(str(out / 'prelabels.jsonl'))}"
        lines.append(cmd)
    inferred = _inferred_documents(steps, out)
    sections = q(_editor_path(str(out / SECTIONS_NAME)))
    for path in outputs:
        cmd = f"cd editor && npm run demo -- --report {q(_editor_path(path))}"
        if _converted_key(path, converted) in inferred:  # CO-14: show them as provisional
            cmd += f" --sections {sections}"
        lines.append(cmd)
    return lines


def _inferred_documents(steps: dict, out: Path) -> set[str]:
    """Documents the sections step wrote inferred sections for (empty unless it succeeded)."""
    if steps["sections"]["status"] != "ok":
        return set()
    data = json.loads((out / SECTIONS_NAME).read_text(encoding="utf-8"))
    return {name for name, d in data["documents"].items()
            if d["status"] == "inferred" and d["sections"]}


def _converted_key(path: str, converted: Path) -> str | None:
    """``path``'s sections.json key (relative to CONVERTED), or None outside it."""
    try:
        return Path(path).resolve().relative_to(converted.resolve()).as_posix()
    except ValueError:
        return None


def _owned_by_intake(path: Path, out: Path) -> bool:
    """True when ``path`` is a file a run deletes before reading inputs (OWNED or CONVERTED)."""
    p, o = path.resolve(), out.resolve()
    return p in {(o / n) for n in OWNED} or (o / CONVERTED) in p.parents


def run(args, model=None) -> tuple[int, dict]:
    """Run the chain; ``model`` overrides --model-url (tests inject a fake)."""
    src, out = Path(args.src), Path(args.out)
    converted = out / CONVERTED
    genre = load_genre(args.genre)
    if converted.exists():  # only reached with --force or an empty OUT
        shutil.rmtree(converted)
    for name in OWNED:  # stale outputs of an earlier run this run may not rewrite
        (out / name).unlink(missing_ok=True)
    steps: dict[str, dict] = {}
    outputs: list[str] = []

    def attempt(name, fn, *a):
        dep = DEPENDS.get(name)
        if dep and steps[dep]["status"] != "ok":
            steps[name] = _step("skipped", f"blocked by {dep}")
            return
        try:
            steps[name] = fn(*a)
        except Exception as exc:  # noqa: BLE001 - one step's failure is reported, not raised
            steps[name] = _step("failed", _code(exc))

    def do_ingest():
        step, found = _ingest(src, converted)
        outputs.extend(found)
        return step

    attempt("ingest", do_ingest)
    attempt("conversion_quality", _quality, converted, out)
    attempt("corpus_stats", _stats, converted, out)
    if args.metadata:
        attempt("metadata", _metadata, args.metadata)
    else:
        steps["metadata"] = _step("skipped", NO_METADATA)
    attempt("sections", _sections, converted, out)
    attempt("annotation_sample", _sample, converted, out, genre, args,
            steps["sections"]["status"] == "ok")
    if model is not None or args.model_url:
        def do_prelabel():
            m = model or prelabel.local_model(args.model_url, model=args.model_name)
            return _prelabel(converted, out, genre, m)
        attempt("prelabel", do_prelabel)
    else:
        steps["prelabel"] = (_step("skipped", "blocked by annotation_sample")
                             if steps["annotation_sample"]["status"] != "ok"
                             else _step("skipped", NO_MODEL))
    if args.discover:
        attempt("discovery", _discover, converted, out, genre, args.discover_k,
                args.discover_sample)
    else:
        steps["discovery"] = _step("skipped", NO_DISCOVER)
    report = {"schema_version": 1, "source": args.src, "out": args.out,
              "steps": {name: steps[name] for name in STEPS},
              "next_steps": _next_steps(steps, out, converted, args.genre, outputs)}
    (out / REPORT_NAME).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                                   encoding="utf-8")
    code = 1 if any(s["status"] == "failed" for s in steps.values()) else 0
    return code, report


def _summary(report: dict) -> str:
    lines = []
    for name in STEPS:
        s = report["steps"][name]
        reason = f" ({s['reason']})" if s["reason"] else ""
        counts = f" {json.dumps(s['counts'], sort_keys=True)}" if s["counts"] else ""
        lines.append(f"{name}: {s['status']}{reason}{counts}")
    lines.append(f"report: {Path(report['out']) / REPORT_NAME}")
    return "\n".join(lines)


def main(argv: list[str] | None = None, model=None) -> int:
    parser = argparse.ArgumentParser(prog="python -m experiments.intake")
    sub = parser.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="take SRC reports to an annotation-ready set in OUT")
    r.add_argument("src")
    r.add_argument("out")
    r.add_argument("--genre", required=True)
    r.add_argument("--metadata", default=None)
    r.add_argument("--split-seed", type=int, default=0)
    r.add_argument("--test-fraction", type=float, default=0.5)
    r.add_argument("--n", type=int, default=300)
    r.add_argument("--seed", type=int, default=0)
    r.add_argument("--model-url", default=None)
    r.add_argument("--model-name", default="local")
    r.add_argument("--discover", action="store_true",
                   help="also write MV-02 move discovery to OUT (embedder from "
                        f"{MODEL_DIR_ENV}, else development hash stub)")
    r.add_argument("--discover-k", type=int, default=None,
                   help="MV-02 clusters per section type (default "
                        f"{move_discovery.DEFAULT_K}; recorded in counts when given)")
    r.add_argument("--discover-sample", type=int, default=None,
                   help="MV-02 sentences sampled per section type (default "
                        f"{move_discovery.DEFAULT_MAX_PER_TYPE}; recorded when given)")
    r.add_argument("--force", action="store_true",
                   help="overwrite a non-empty OUT (removes intake's own earlier outputs)")
    args = parser.parse_args(argv)
    src, out = Path(args.src), Path(args.out)
    if not src.is_dir():
        print(f"error: source directory not found: {args.src}", file=sys.stderr)
        return 2
    if out.exists() and any(out.iterdir()) and not args.force:
        print(f"error: {args.out} is not empty; use --force to overwrite", file=sys.stderr)
        return 2
    if not 0 < args.test_fraction < 1 or args.n < 0:
        print("error: --test-fraction must be in (0, 1) and --n >= 0", file=sys.stderr)
        return 2
    if any(v is not None and v < 1 for v in (args.discover_k, args.discover_sample)):
        print("error: --discover-k and --discover-sample must be >= 1", file=sys.stderr)
        return 2
    if args.metadata and not Path(args.metadata).is_file():
        print(f"error: metadata file not found: {args.metadata}", file=sys.stderr)
        return 2
    if args.metadata and _owned_by_intake(Path(args.metadata), out):
        print(f"error: --metadata {args.metadata} is an intake output in OUT that a run "
              "removes first; move it outside OUT", file=sys.stderr)
        return 2
    for name in OWNED:
        if (out / name).is_dir():
            print(f"error: {out / name} is a directory; intake owns that name in OUT "
                  "and will not remove a directory", file=sys.stderr)
            return 2
    if (out / CONVERTED).exists() and not (out / CONVERTED).is_dir():
        print(f"error: {out / CONVERTED} is not a directory", file=sys.stderr)
        return 2
    try:
        load_genre(args.genre)
    except Exception as exc:  # noqa: BLE001
        print(f"error: cannot load genre {args.genre}: {_code(exc)}", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    code, report = run(args, model=model)
    print(_summary(report))
    return code


if __name__ == "__main__":
    sys.exit(main())
