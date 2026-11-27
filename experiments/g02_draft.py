"""G-02.5 agent half: run g02 on a blind session's choices and write a DRAFT result document.

``draft(session_path, choices_path, *, seed, out_path, n_resamples=None,
text_model=None, judge_is_expert=False, preregistration_root=DEFAULT_ROOT)`` runs
``experiments.gates.g02.run`` only through ``experiments.runner.run_gate`` (confirmed ``g02``
preregistration required) and writes ``<out>.json`` (``runner.serialize``) and a DRAFT
``<out>.md``: Basis line, the three comparison rows with intervals and n, self-consistency,
completeness counts, the A_vs_C ``verdict_hint`` (a hint, never a status) and
"Verdict: owed to the expert (G-02.5 [H])". The person choosing is called "judge" unless
``judge_is_expert``. No section or reason text is written (non-empty reason count only).

Output-path safety (refusal under experiments/results/, all-or-nothing pair write) is
g01_draft's ``output_paths`` / ``write_pair``; the path is checked before anything runs.
Production caller: the CLI (G-02.5 real run, after BJ-03). Choices are streamed; memory is
O(session items).

CLI: ``python -m experiments.g02_draft --session S --choices C --seed N [--n-resamples K]
[--text-model ID] [--judge-is-expert] [--preregistration-root DIR] --out PATH_STEM``.
"""
from __future__ import annotations

import argparse
import json
import sys

from experiments import runner
from experiments.g01_draft import DraftError, output_paths, write_pair
from experiments.gates import g02
from experiments.preregistration import DEFAULT_ROOT, PreregistrationError

_ROWS = (("A_vs_C", "C preferred over A (headline)"), ("A_vs_B", "B preferred over A"),
         ("C_vs_original", "C preferred over the original"))


def _iv(iv):
    return 'n/a' if iv is None else f'[{iv[0]}, {iv[1]}]'


def render(run, *, text_model=None, judge_is_expert=False) -> str:
    res, man = run['result'], run['manifest']
    judge = 'expert' if judge_is_expert else 'judge'
    comps, cons, c = res['comparisons'], res['consistency'], res['completeness']
    population = sum(r['n'] for r in comps.values())
    texts = (f'texts LLM-built by {text_model}' if text_model else
             'texts LLM-built (generating model not stated in the session or arguments)')
    lines = ['# G-02 result — DRAFT', '',
             '**DRAFT** prepared by an agent (G-02.5 [A→H] agent half). Not a result; '
             'no gate status.', '']
    if not c['complete']:
        lines += [f"**INCOMPLETE run**: {c['unanswered']} of {c['session_items']} session "
                  'items have no choice.', '']
    lines += [f"Basis: population = {population} blind pairs judged (first presentations; "
              f"{c['session_items']} session items); metric = win rate of the reported arm, "
              f"ties at half credit, seeded percentile bootstrap 95 % interval; reference = "
              f"the {judge}'s blind choices; {texts}.",
              f"- Seed {man['seed']}; resamples {res['n_resamples']}; thresholds "
              f"{res['thresholds_source']}: {json.dumps(res['thresholds'], sort_keys=True)}.",
              '', '## Preference rates', '',
              '| comparison | reported arm | win rate | 95 % interval | n | wins/losses/ties '
              '| verdict_hint (hint only) |', '| --- | --- | --- | --- | --- | --- | --- |']
    for name, _ in _ROWS:
        r = comps[name]
        rate = 'n/a' if r['win_rate'] is None else str(r['win_rate'])
        lines.append(f"| {name} | {r['arm']} | {rate} | {_iv(r['interval'])} | {r['n']} | "
                     f"{r['wins']}/{r['losses']}/{r['ties']} | {r.get('verdict_hint', '—')} |")
    lines += ['', '`verdict_hint` compares the A_vs_C rate to the threshold mechanically; it is '
              'a hint, not a verdict.', '', f'## {judge.capitalize()} self-consistency', '',
              f"- repeated pairs n {cons['n']}; agreement rate "
              f"{'n/a' if cons['rate'] is None else cons['rate']}; 95 % interval "
              f"{_iv(cons['interval'])}.", '', '## Completeness', '',
              f"- session items: {c['session_items']}; unanswered: {c['unanswered']}; "
              f"unknown item: {c['unknown_item']}; duplicate: {c['duplicate']}; "
              f"contradicting: {c['contradicting']}; malformed: {c['malformed']}; "
              f"torn: {c['torn']}.",
              f"- non-empty reasons: {res['reasons_nonempty']} (texts not reproduced).",
              '', '## Verdict', '', 'Verdict: owed to the expert (G-02.5 [H])', '']
    return '\n'.join(lines)


def draft(session_path, choices_path, *, seed, out_path, n_resamples=None, text_model=None,
          judge_is_expert=False, preregistration_root=DEFAULT_ROOT) -> dict:
    json_path, md_path = output_paths(out_path)
    with open(session_path, encoding='utf-8') as fh:
        session = json.load(fh)
    if not isinstance(session, list) or not all(isinstance(d, dict) for d in session):
        raise DraftError('session file must be a JSON list of objects')
    with open(choices_path, encoding='utf-8') as choices:
        cfg = {'session': session, 'choices': choices}
        if n_resamples is not None:
            cfg['n_resamples'] = n_resamples
        if text_model:
            cfg['model_versions'] = {'texts': text_model}
        try:
            run = runner.run_gate(g02.run, seed=seed, config=cfg,
                                  preregistration_root=preregistration_root)
        except PreregistrationError as e:
            raise DraftError(f'g02 preregistration not confirmed: {e}') from e
        except g02.G02ContradictionError as e:
            raise DraftError(f'{e}; counts {json.dumps(e.completeness, sort_keys=True)}') from e
    md = render(run, text_model=text_model, judge_is_expert=judge_is_expert)
    try:
        json_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise DraftError(f'cannot write draft ({out_path}): {e.strerror or e}') from e
    write_pair([(json_path, runner.serialize(run) + '\n'), (md_path, md)])
    return run


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for k in ('--session', '--choices', '--out'):
        ap.add_argument(k, required=True)
    ap.add_argument('--seed', type=int, required=True)
    ap.add_argument('--n-resamples', type=int)
    ap.add_argument('--text-model')
    ap.add_argument('--judge-is-expert', action='store_true')
    ap.add_argument('--preregistration-root', default=DEFAULT_ROOT)
    a = ap.parse_args(argv)
    try:
        output_paths(a.out)
        draft(a.session, a.choices, seed=a.seed, out_path=a.out, n_resamples=a.n_resamples,
              text_model=a.text_model, judge_is_expert=a.judge_is_expert,
              preregistration_root=a.preregistration_root)
    except (DraftError, OSError, ValueError, KeyError) as e:
        print(f'error: {e}', file=sys.stderr)
        return 2
    print(f'draft written: {a.out}.json, {a.out}.md (verdict owed to the expert)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
