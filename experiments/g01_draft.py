"""G-01.6 agent half: run g01 on stored labels and write a DRAFT result document.

``draft(store, genre, manifest, prelabel_path, *, annotator=None, model_id=None,
include_non_blind=False, seed, out_path, n_resamples=None, preregistration_root=DEFAULT_ROOT)``
builds the config with ``g01_inputs.build_config``, runs it only through
``experiments.runner.run_gate(g01.run, ...)`` (which requires a confirmed ``g01``
preregistration) and writes ``<out_path>.json`` (run result + manifest, ``runner.serialize``)
and ``<out_path>.md`` (a DRAFT document: population counts, reference = expert labels, LLM labels
LLM-built, κ rows with intervals, ``other`` share, per-move P/R/F1, missing / degenerate /
non-blind counts, ``verdict_hint`` labelled as a hint and the placeholder
"Verdict: owed to the expert (G-01.6 [H])"). It never emits a gate status.

An output path (the stem or either written file, symlinks resolved) inside
``experiments/results/`` is refused (``DraftError``; CLI exit 2)
before anything runs or is written: that directory holds only the expert's actual results.

Public symbols: unwired by design until the real G-01.6 run (needs AN-03 labels and a G-01.4 local-model run).
Memory: bounded by build_config's streaming (maps O(manifest sample size)).

CLI: ``python -m experiments.g01_draft --store S --genre G --manifest M --prelabel P
[--annotator A] [--model-id ID] [--include-non-blind] --seed N [--n-resamples K]
[--preregistration-root DIR] --out PATH_STEM``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from experiments import annotate, g01_inputs, runner
from experiments.gates import g01
from experiments.preregistration import DEFAULT_ROOT, PreregistrationError
from service.annotation_store import AnnotationStore
from service.genre import load_genre

RESULTS_DIR = Path(__file__).resolve().parent / 'results'


class DraftError(ValueError):
    """The draft cannot be produced (refused output path, missing preregistration)."""


def _inside_results(p):
    return p == RESULTS_DIR or RESULTS_DIR in p.parents


def _paths(out_path):
    base = Path(out_path).expanduser().resolve()
    json_path, md_path = base.with_name(base.name + '.json'), base.with_name(base.name + '.md')
    # Check the resolved base and each resolved final path: a leaf symlink (even dangling)
    # named <stem>.json / <stem>.md would otherwise redirect the write into results/.
    for p in (base, json_path.resolve(), md_path.resolve()):
        if _inside_results(p):
            raise DraftError(f'refusing output inside experiments/results/ ({p}): '
                             'that directory holds only actual expert-judged results')
    return json_path, md_path


def _fmt(v):
    return 'n/a' if v is None else str(v)


def render(run, cfg) -> str:
    res, man = run['result'], run['manifest']
    m = {r['metric']: r for r in res['metrics']}
    pairing = res['pairing']
    n_rep = len(cfg.get('expert_repeat', {}))
    lines = [
        '# G-01 result — DRAFT', '',
        '**DRAFT** prepared by an agent (G-01.6 [A→H] agent half). Not a result; no gate status.',
        '',
        f"- Population: {len(cfg['expert'])} expert first-pass labels, {n_rep} expert repeat "
        f"labels, {len(cfg['llm'])} LLM labels; {pairing['expert_llm']['paired']} expert-LLM "
        'pairs.',
        '- Reference: the expert labels (first pass; repeat pass for self-agreement).',
        '- LLM labels are LLM-built (model pre-labels, not expert judgment).',
        f"- Seed {man['seed']}; resamples {res['n_resamples']}; thresholds "
        f"{res['thresholds_source']}: {json.dumps(res['thresholds'], sort_keys=True)}.",
        '', '## Agreement', '',
        '| metric | value | 95 % interval | n | method | verdict_hint (hint only) |',
        '| --- | --- | --- | --- | --- | --- |']
    for name in ('kappa_expert_llm', 'kappa_expert_self', 'other_share_expert',
                 'other_share_llm'):
        r = m[name]
        iv = r['interval']
        lines.append(f"| {name} | {_fmt(r['value'])} | "
                     f"{'n/a' if iv is None else f'[{iv[0]}, {iv[1]}]'} | {r['n']} | "
                     f"{r['method']} | {r['verdict_hint']} |")
    lines += ['', '`verdict_hint` compares a value to a threshold mechanically; it is a hint, '
              'not a verdict.', '', '## Per-move precision / recall / F1 (expert reference)', '',
              '| move | precision | recall | f1 |', '| --- | --- | --- | --- |']
    for lab, v in res['confusion']['per_move'].items():
        lines.append(f"| {lab} | {v['precision']} | {v['recall']} | {v['f1']} |")
    el, es = pairing['expert_llm'], pairing['expert_self']
    lines += ['', '## Missing, degenerate and non-blind counts', '',
              f"- expert-LLM: only expert {el['only_expert']}, only LLM {el['only_llm']}.",
              ('- expert-self: no repeat pass.' if es is None else
               f"- expert-self: paired {es['paired']}, only expert {es['only_expert']}, "
               f"only repeat {es['only_repeat']}.")]
    for name in ('kappa_expert_llm', 'kappa_expert_self'):
        r = m[name]
        lines.append(f"- {name}: degenerate resamples {r['degenerate_resamples']}"
                     + (f"; degenerate sample ({r['degenerate_reason']})"
                        if r.get('degenerate') else ''))
    for p, c in cfg.get('non_blind', {}).items():
        lines.append(f"- non-blind {p}: excluded {c['excluded']}, included {c['included']}.")
    if 'expert_repeat_omitted' in cfg:
        lines.append(f"- expert_repeat omitted: {cfg['expert_repeat_omitted']}.")
    lines += ['', '## Verdict', '', 'Verdict: owed to the expert (G-01.6 [H])', '']
    return '\n'.join(lines)


def draft(store, genre, manifest, prelabel_path, *, annotator=None, model_id=None,
          include_non_blind=False, seed, out_path, n_resamples=None,
          preregistration_root=DEFAULT_ROOT) -> dict:
    json_path, md_path = _paths(out_path)
    cfg = g01_inputs.build_config(store, genre, manifest, prelabel_path, annotator=annotator,
                                  model_id=model_id, include_non_blind=include_non_blind)
    run_cfg = dict(cfg)
    if model_id is not None:
        run_cfg['model_versions'] = {'llm': model_id}
    if n_resamples is not None:
        run_cfg['n_resamples'] = n_resamples
    try:
        run = runner.run_gate(g01.run, seed=seed, config=run_cfg,
                              preregistration_root=preregistration_root)
    except PreregistrationError as e:
        raise DraftError(f'g01 preregistration not confirmed: {e}') from e
    md = render(run, cfg)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(runner.serialize(run) + '\n', encoding='utf-8')
    md_path.write_text(md, encoding='utf-8')
    return run


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for k in ('--store', '--genre', '--manifest', '--prelabel', '--out'):
        ap.add_argument(k, required=True)
    ap.add_argument('--annotator')
    ap.add_argument('--model-id')
    ap.add_argument('--include-non-blind', action='store_true')
    ap.add_argument('--seed', type=int, required=True)
    ap.add_argument('--n-resamples', type=int)
    ap.add_argument('--preregistration-root', default=DEFAULT_ROOT)
    a = ap.parse_args(argv)
    try:
        _paths(a.out)
        genre = load_genre(a.genre)
        with open(a.manifest, encoding='utf-8') as fh:
            manifest = json.load(fh)
        draft(AnnotationStore(a.store), genre, manifest, a.prelabel, annotator=a.annotator,
              model_id=a.model_id, include_non_blind=a.include_non_blind, seed=a.seed,
              out_path=a.out, n_resamples=a.n_resamples,
              preregistration_root=a.preregistration_root)
    except (DraftError, annotate.AnnotateError, g01_inputs.G01InputsError) as e:
        print(f'error: {e}', file=sys.stderr)
        return 2
    print(f'draft written: {a.out}.json, {a.out}.md (verdict owed to the expert)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
