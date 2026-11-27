"""G-02.4 session builder: G-02.3 generations plus originals -> a saved blind session.

Inputs:
  --generations  the G-02.3 JSONL (``experiments.g02_generate``): one record per
                 ``(section_id, arm)`` with ``text``, ``model`` and ``prompt_version``.
  --originals    the held-out section texts ``{section_id, report_id, section_type, text}``
                 (``python -m experiments.g02_notes ... --sections-out``).

Three comparisons, one pair per ``(comparison, section_id)`` with pair_id
``<comparison>:<section_id>``: ``A_vs_C`` (arms A, C), ``A_vs_B`` (A, B) and
``C_vs_original`` (C, ``original``). ``blind_session.build_session`` interleaves them and adds
``ceil(repeat_fraction * pairs)`` repeats; ``blind_session.save_session`` writes the file that
``python -m experiments.blind_ui SESSION CHOICES`` serves. Recorded choices carry ``comparison``.

Run selection: ``--model-id`` / ``--prompt-version`` pick one run; the default is the single one
present, and several without a selector is exit 2. Strict by default: a section missing an arm or
its original, an empty text, a duplicate ``(section, arm)`` or original, or ``summarize`` not
complete is exit 2 naming counts and section ids only, with nothing written.
``--allow-incomplete`` builds pairs only for sections holding every text a comparison needs and
prints how many were dropped; duplicates and same-report exemplars still refuse (the run itself
is unsound).

Safety: an existing session file is replaced only with ``--force``, and never when the
``--choices`` file exists and is non-empty (its judgments would be orphaned). The file is written
to a temporary name, mode 0600, and renamed into place.

PRIVATE: the session file holds corpus section text and generated text, plus arm mappings and
keys. Keep it, the originals file and CHOICES in private storage; never commit or quote them.
Stdout carries counts, paths, the ``blind_ui`` command and the ``g02_draft`` command to run after
judging (seed = ``--seed`` or 0, ``--text-model`` = the selected run's model), never text.

Production caller: this CLI, run by the expert/operator for G-02.4 (``python -m
experiments.g02_session``). Consumers: ``experiments.blind_ui`` and the G-02 preference draft.
Memory: records are read streaming; only the selected run's texts are held (about 30 sections).
No judgment happens here; the judgments are the expert's (G-02.4 / BJ-03, [H]).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shlex
import sys
import tempfile

from experiments import blind_session
from experiments.g02_generate import read_jsonl, summarize

COMPARISONS = {'A_vs_C': ('A', 'C'), 'A_vs_B': ('A', 'B'), 'C_vs_original': ('C', 'original')}
ORIGINAL = 'original'


class SessionInputError(ValueError):
    """Input unfit for a session; the message names counts and ids only."""


def _ids(items, limit=20):
    items = sorted(items)
    more = f' (+{len(items) - limit} more)' if len(items) > limit else ''
    return ', '.join(items[:limit]) + more


def _select_run(path, model, prompt_version):
    runs = set()
    for r in read_jsonl(path):
        if model is not None and r.get('model') != model:
            continue
        if prompt_version is not None and r.get('prompt_version') != prompt_version:
            continue
        runs.add((r.get('model'), r.get('prompt_version')))
    if not runs:
        raise SessionInputError('no generation records match the selected model/prompt version')
    models = sorted({m for m, _ in runs}, key=str)
    versions = sorted({v for _, v in runs}, key=str)
    if len(models) > 1:
        raise SessionInputError(f'{len(models)} models present ({_ids(map(str, models))}); '
                                'pass --model-id')
    if len(versions) > 1:
        raise SessionInputError(f'{len(versions)} prompt versions present '
                                f'({_ids(map(str, versions))}); pass --prompt-version')
    return models[0], versions[0]


def build_comparisons(generations_path, originals_path, *, model=None, prompt_version=None,
                      allow_incomplete=False):
    """Return (comparisons, info) for blind_session.build_session; raise SessionInputError."""
    model, prompt_version = _select_run(generations_path, model, prompt_version)
    texts, light, order = {}, [], {}
    empty = set()
    for r in read_jsonl(generations_path):
        if r.get('model') != model or r.get('prompt_version') != prompt_version:
            continue
        light.append({k: v for k, v in r.items() if k != 'text'})
        order.setdefault(r['section_id'], True)
        text = r.get('text')
        if not isinstance(text, str) or not text.strip():
            empty.add(r['section_id'])
            continue
        texts.setdefault((r['section_id'], r['arm']), text)
    summary = summarize(light, expected_sections=None, model=model, prompt_version=prompt_version)
    sections = list(order)
    wanted = set(sections)
    originals, dup_orig = {}, set()
    for r in read_jsonl(originals_path):
        s = r.get('section_id')
        if s not in wanted:
            continue
        if s in originals:
            dup_orig.add(s)
        text = r.get('text')
        if not isinstance(text, str) or not text.strip():
            empty.add(s)
            originals.setdefault(s, None)
            continue
        if originals.get(s) is None:
            originals[s] = text
    missing_orig = sorted(wanted - set(originals))
    for s, text in originals.items():
        if text is not None:
            texts[(s, ORIGINAL)] = text

    duplicates = sorted({s for s, _ in summary['duplicates']} | dup_orig)
    leaked = summary['same_report_exemplars']
    if duplicates:
        raise SessionInputError(f'{len(duplicates)} sections with duplicate records: '
                                f'{_ids(duplicates)}')
    if leaked:
        raise SessionInputError(f'{len(leaked)} sections with same-report exemplars: '
                                f'{_ids(leaked)}')
    missing = sorted({s for s, _ in summary['missing']})
    problems = []
    if missing:
        problems.append(f'{len(missing)} sections missing an arm ({len(summary["missing"])} '
                        f'records): {_ids(missing)}')
    if missing_orig:
        problems.append(f'{len(missing_orig)} sections missing an original: {_ids(missing_orig)}')
    if empty:
        problems.append(f'{len(empty)} sections with an empty text: {_ids(empty)}')
    if (problems or not summary['complete']) and not allow_incomplete:
        raise SessionInputError('; '.join(problems) or 'generation summary is not complete')

    comparisons, dropped = {}, 0
    for name, (x, y) in COMPARISONS.items():
        pairs = []
        for s in sections:
            if (s, x) in texts and (s, y) in texts:
                pairs.append((f'{name}:{s}', texts[(s, x)], x, texts[(s, y)], y))
            else:
                dropped += 1
        comparisons[name] = pairs
    total = sum(map(len, comparisons.values()))
    if total == 0:
        raise SessionInputError('no section has the texts any comparison needs')
    info = {'model': model, 'prompt_version': prompt_version, 'sections': len(sections),
            'pairs': total, 'dropped_pairs': dropped,
            'per_comparison': {n: len(p) for n, p in comparisons.items()}}
    return comparisons, info


def _write_session(path, session):
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix='.session-', suffix='.tmp', dir=directory)
    os.close(fd)
    try:
        os.chmod(tmp, 0o600)
        blind_session.save_session(tmp, session)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='python -m experiments.g02_session',
                                 description=__doc__.splitlines()[0])
    ap.add_argument('--generations', required=True, help='G-02.3 generation JSONL')
    ap.add_argument('--originals', required=True, help='original sections JSONL (private)')
    ap.add_argument('--out', required=True, help='session JSON to write (private)')
    ap.add_argument('--choices', required=True, help='CHOICES JSONL blind_ui will append to')
    ap.add_argument('--model-id')
    ap.add_argument('--prompt-version')
    ap.add_argument('--seed', type=int)
    ap.add_argument('--repeat-fraction', type=float, default=0.1)
    ap.add_argument('--min-gap', type=int, default=3)
    ap.add_argument('--allow-incomplete', action='store_true')
    ap.add_argument('--force', action='store_true', help='replace an existing session file')
    a = ap.parse_args(argv)

    def refuse(message):
        print(f'g02_session: {message}; nothing written', file=sys.stderr)
        return 2

    if os.path.exists(a.choices) and os.path.getsize(a.choices) > 0:
        return refuse(f'{a.choices} already holds choices; a new session would orphan them')
    if os.path.exists(a.out) and not a.force:
        return refuse(f'{a.out} exists; pass --force to replace it')
    try:
        comparisons, info = build_comparisons(
            a.generations, a.originals, model=a.model_id, prompt_version=a.prompt_version,
            allow_incomplete=a.allow_incomplete)
        session = blind_session.build_session(comparisons, repeat_fraction=a.repeat_fraction,
                                              min_gap=a.min_gap, rng=random.Random(a.seed))
    except (SessionInputError, ValueError, OSError) as error:
        return refuse(str(error))
    _write_session(a.out, session)
    repeats = sum(item.repeat_of is not None for item in session)
    print(f'model: {info["model"]}  prompt_version: {info["prompt_version"]}')
    print(f'sections: {info["sections"]}  pairs: {info["pairs"]}  repeats: {repeats}  '
          f'items: {len(session)}  dropped pairs: {info["dropped_pairs"]}')
    print('per comparison: ' + ', '.join(f'{n}={k}' for n, k in info['per_comparison'].items()))
    print(f'session (private): {a.out}')
    print(f'serve: python -m experiments.blind_ui {shlex.quote(a.out)} {shlex.quote(a.choices)}')
    print('after judging: ' + shlex.join([
        'python', '-m', 'experiments.g02_draft', '--session', a.out, '--choices', a.choices,
        '--seed', str(0 if a.seed is None else a.seed), '--text-model', str(info['model']),
        '--out', os.path.join(os.path.dirname(a.out), 'g02_draft')]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
