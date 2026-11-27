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
The comparison uses the resolved ``RESULTS_DIR``; a symlink loop in the output path is also
``DraftError`` (exit 2), in any path component; other OS errors resolving or writing the output path are
``DraftError`` naming the OS error and failing path. The pair is written via same-directory
temps and ``os.replace``: if either write fails, neither new file is left (prior files restored).
Not handled: TOCTOU races and hard links.

Public symbols: unwired by design until the real G-01.6 run (needs AN-03 labels and a G-01.4 local-model run).
Memory: bounded by build_config's streaming (maps O(manifest sample size)).

CLI: ``python -m experiments.g01_draft --store S --genre G --manifest M --prelabel P
[--annotator A] [--model-id ID] [--include-non-blind] --seed N [--n-resamples K]
[--preregistration-root DIR] --out PATH_STEM``.
"""
from __future__ import annotations

import argparse
import contextlib
import errno
import json
import os
import stat
import sys
import tempfile
from pathlib import Path

from experiments import annotate, g01_inputs, runner
from experiments.gates import g01
from experiments.preregistration import DEFAULT_ROOT, PreregistrationError
from service.annotation_store import AnnotationStore
from service.genre import load_genre

RESULTS_DIR = Path(__file__).resolve().parent / 'results'


class DraftError(ValueError):
    """The draft cannot be produced (refused output path, missing preregistration)."""


def _resolve(p):
    # A symlink loop raises RuntimeError (Python < 3.13) or OSError; on 3.13+ non-strict
    # resolve() returns the looping link unresolved, so a symlink left after resolving is a loop.
    try:
        r = Path(p).resolve()
    except (RuntimeError, OSError) as e:
        raise DraftError(f'refusing output path: symlink loop or unresolvable ({p}): {e}') from e
    # A symlink in ANY component (not just the leaf) of the resolved path means resolve() left
    # a loop in place. Walk from the root: each prefix's parents are then real directories,
    # so lstat reaches the component itself. A missing component is fine (created later);
    # ELOOP is a loop; any other OSError (EACCES, ENAMETOOLONG, ...) is reported as itself.
    for q in (*reversed(r.parents), r):
        try:
            looped = stat.S_ISLNK(os.lstat(q).st_mode)
        except FileNotFoundError:
            looped = False
        except OSError as e:
            if e.errno != errno.ELOOP:
                raise DraftError(f'refusing output path ({p}): {e.strerror or e}') from e
            looped = True
        if looped:
            raise DraftError(f'refusing output path: symlink loop ({p})')
    return r


def _inside_results(p):
    # Resolve RESULTS_DIR too: a symlinked experiments/results must not escape the check.
    results = _resolve(RESULTS_DIR)
    return p == results or results in p.parents


def _paths(out_path):
    raw = os.fspath(out_path)
    seps = (os.sep,) + ((os.altsep,) if os.altsep else ())
    if '\x00' in (raw if isinstance(raw, str) else raw.decode('latin-1')):
        raise DraftError(f'refusing --out {raw!r}: contains a NUL byte')
    try:
        is_dir = Path(raw).expanduser().is_dir()
    except OSError as e:  # is_dir re-raises EACCES/ENAMETOOLONG on Python < 3.14
        raise DraftError(f'refusing output path ({raw}): {e.strerror}') from e
    if raw.endswith(seps) or is_dir:
        raise DraftError(f'refusing --out {raw!r}: --out is a path stem, not a directory '
                         '(files are written as STEM.json and STEM.md)')
    base = _resolve(Path(out_path).expanduser())
    json_path, md_path = base.with_name(base.name + '.json'), base.with_name(base.name + '.md')
    # Check the resolved base and each resolved final path: a leaf symlink (even dangling)
    # named <stem>.json / <stem>.md would otherwise redirect the write into results/.
    for p in (base, _resolve(json_path), _resolve(md_path)):
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
    try:
        json_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise DraftError(f'cannot write draft ({e.filename or out_path}): '
                         f'{e.strerror or e}') from e
    _write_pair([(json_path, runner.serialize(run) + '\n'), (md_path, md)])
    return run


def _write_pair(items):
    # Write every file to a temp beside its target (same filesystem), then os.replace each.
    # On any failure (any exception): remove the temps, put back targets already replaced
    # (restoring a prior file from its backup, or removing the new one), and name the failing
    # target path plus any backup that could not be restored. A new file keeps a prior regular
    # file's permission bits, otherwise the umask mode. Any prior entry (incl. a dangling symlink
    # or FIFO) of a non-last target is backed up.
    tmps, placed, stranded = {}, [], []  # placed: (target, backup or None)
    target = items[0][0]
    umask = os.umask(0)
    os.umask(umask)

    def restore(backup, t):
        try:
            os.replace(backup, t)
        except OSError:
            stranded.append(backup)

    def rollback():
        for t, backup in reversed(placed):
            if backup is not None:
                restore(backup, t)
            else:
                with contextlib.suppress(OSError):
                    os.unlink(t)
        for tmp in tmps.values():
            with contextlib.suppress(OSError):
                os.unlink(tmp)

    try:
        for target, text in items:
            fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f'.{target.name}.', suffix='.tmp')
            os.close(fd)
            tmps[target] = Path(tmp)
            mode = 0o666 & ~umask  # mkstemp is 0600; keep write_text's umask mode
            with contextlib.suppress(OSError):
                st = os.lstat(target)
                if stat.S_ISREG(st.st_mode):
                    mode = stat.S_IMODE(st.st_mode) & 0o777
            Path(tmp).write_text(text, encoding='utf-8')
            os.chmod(tmp, mode)
        for target, _ in items:
            backup = None
            if target is not items[-1][0] and os.path.lexists(target):
                fd, bak = tempfile.mkstemp(dir=target.parent, prefix=f'.{target.name}.',
                                           suffix='.bak')
                os.close(fd)
                try:
                    os.replace(target, bak)
                except BaseException:
                    with contextlib.suppress(OSError):
                        os.unlink(bak)
                    raise
                backup = Path(bak)
            try:
                os.replace(tmps[target], target)
            except BaseException:
                if backup is not None:
                    restore(backup, target)
                raise
            del tmps[target]
            placed.append((target, backup))
    except OSError as e:
        rollback()
        msg = f'cannot write draft ({target}): {e.strerror or e}'
        if stranded:
            msg += '; prior content left in ' + ', '.join(map(str, stranded))
        raise DraftError(msg) from e
    except BaseException:
        rollback()
        raise
    for _, backup in placed:
        if backup is not None:
            with contextlib.suppress(OSError):
                os.unlink(backup)


def _refuse_nul(name: str, raw: str) -> None:
    if '\x00' in raw:
        flag = '--' + name.replace('_', '-')
        raise DraftError(f'refusing {flag} {raw!r}: contains a NUL byte')


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for k in ('--store', '--genre', '--manifest', '--prelabel', '--out'):
        ap.add_argument(k, required=True)
    ap.add_argument('--annotator')
    ap.add_argument('--model-id')
    ap.add_argument('--include-non-blind', action='store_true')
    ap.add_argument('--seed', type=int, required=True)
    ap.add_argument('--n-resamples', type=int)
    ap.add_argument('--preregistration-root', default=str(DEFAULT_ROOT))
    a = ap.parse_args(argv)
    try:
        for name in ('store', 'genre', 'manifest', 'prelabel', 'preregistration_root'):
            _refuse_nul(name, getattr(a, name))
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
    except ValueError as e:
        if 'share no sentence ids' not in str(e):
            raise
        print(f'error: {e}\nhint: labels annotated with pre-labels shown are non-blind and are '
              'excluded unless --include-non-blind is given', file=sys.stderr)
        return 2
    print(f'draft written: {a.out}.json, {a.out}.md (verdict owed to the expert)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
