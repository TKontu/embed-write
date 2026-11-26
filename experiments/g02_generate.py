"""G-02.3 generation runner: the same section three ways, off neutral notes.

Input sections are the G-02.2 shape ``{section_id, report_id, section_type, notes}``: facts only,
never the original phrasing. Each section is generated three times:

  A  plain instruction: the notes and the section type, no exemplars.
  B  the same prompt plus retrieved exemplars from other reports.
  C  arms B's prompt sampled ``n_candidates`` times, the critic's top-scoring candidate kept.

``model(prompt) -> str`` and ``critic(candidate, context) -> float`` are injected. The critic's
context is arm C's exemplar prompt without the candidate marker, so the arms stay comparable.
``model_critic(model)`` is the default critic for the CLI; it asks a local model for a 0-10 score
and returns 0.0 when the reply holds no number.

Exemplars: the pool is any iterable of ``{section_id, report_id, section_type, text}``.
``lexical_retriever`` scores word overlap (same section type breaks ties) and is injectable. Hard
rule: an exemplar is never drawn from the target section's own ``report_id`` or from the target
section itself. ``iter_generate`` re-applies that filter to whatever the retriever returns, so a
buggy or custom retriever cannot leak the held-out report into its own prompt. Prompts carry
exemplar text only, never an exemplar's report or section id.

Output: one JSONL record per ``(section_id, arm)``, appended and flushed as produced:
  {section_id, report_id, section_type, arm, text, model, prompt_hash, prompt_version,
   exemplar_section_ids, exemplar_report_ids}
Arm C also records ``n_candidates``, ``chosen_candidate`` and ``critic_scores``.
``prompt_hash`` is the hash of the prompt that produced ``text`` (for C, the chosen variant's). ``arm`` is the
identifier G-02.4 blind pairing consumes: ``experiments.blind_pair.make_pair`` takes the text and
the arm and hides both from the judge. Feed ``summarize(...)['complete']`` to decide whether the
30 x 3 set is ready for judging.

Resumable: ``(section_id, arm)`` pairs already in ``out_path`` under the same model id and
``PROMPT_VERSION`` are skipped, so a rerun after a change of prompts regenerates them.
Memory: the exemplar pool, the done keys and the seen section ids; sections stream one at a time.
A ``section_id`` repeated in the input raises ``ValueError`` before anything is written for the
repeat (the CLI exits 2).

Sampling: ``temperature`` (CLI ``--temperature``) is passed as ``model(prompt, temperature=t)``
for arm C candidates only, so the k drafts can differ. With ``temperature=None`` and
``n_candidates > 1`` arm C uses ``DEFAULT_C_TEMPERATURE`` (``local_model`` would otherwise send 0
and the drafts would differ only by prompt suffix); an explicit 0 is honoured. Arms A and B, and
arm C with one candidate and no temperature, call ``model(prompt)`` unchanged. Arm C records carry
``temperature`` when one was used; ``summarize`` reports ``c_deterministic`` when any counted arm C
record has ``n_candidates > 1`` with temperature 0 or missing (``complete`` is unaffected).

``summarize(..., model=, prompt_version=)`` counts only the records of that run, so stale-version
records in a reused ``out_path`` neither duplicate nor complete the current run; the CLI passes both.

Production caller: the CLI run for G-02.3 on the G-02.2 notes. ``local_model`` (experiments.prelabel)
posts to a loopback OpenAI-compatible endpoint gated by service.network_guard (I9); no model ships.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from functools import partial
from typing import Callable, Iterable, Iterator, Sequence, TypedDict

from experiments.prelabel import local_model

ARMS = ('A', 'B', 'C')
PROMPT_VERSION = 'g02.3-v1'
DEFAULT_C_TEMPERATURE = 0.7  # arm C sampling when n_candidates > 1 and none is given


class NotesRecord(TypedDict):
    """One section to generate (G-02.2 shape)."""
    section_id: str
    report_id: str
    section_type: str
    notes: str


class Exemplar(TypedDict):
    """One pool section, never from the target's report."""
    section_id: str
    report_id: str
    section_type: str
    text: str


Model = Callable[[str], str]
Critic = Callable[[str, str], float]
Retriever = Callable[[NotesRecord, Sequence[Exemplar]], Sequence[Exemplar]]

_WORD = re.compile(r'[a-z0-9]+')
_NUMBER = re.compile(r'-?\d+(?:\.\d+)?')


def _tokens(text) -> set:
    return set(_WORD.findall((text or '').lower()))


def lexical_retriever(record: NotesRecord, pool: Iterable[Exemplar], *, k: int = 3) -> list:
    """Top ``k`` exemplars by word overlap with the notes; same section type breaks ties.

    Deterministic: ties fall back to the section id. Exemplars from the record's own report and
    the record itself are excluded here and again by ``iter_generate``.
    """
    note_tokens = _tokens(record.get('notes'))
    ranked = []
    for ex in pool:
        if ex['report_id'] == record['report_id'] or ex['section_id'] == record['section_id']:
            continue
        overlap = len(note_tokens & _tokens(ex.get('text')))
        same_type = ex.get('section_type') == record.get('section_type')
        ranked.append(((-overlap, -same_type, ex['section_id']), ex))
    ranked.sort(key=lambda pair: pair[0])
    return [ex for _, ex in ranked[:max(0, k)]]


def legal_exemplars(record: NotesRecord, exemplars: Iterable[Exemplar]) -> list:
    """The hard rule: drop same-report and self exemplars, and duplicates, keeping order."""
    kept, seen = [], set()
    for ex in exemplars:
        if ex['report_id'] == record['report_id'] or ex['section_id'] == record['section_id']:
            continue
        if ex['section_id'] in seen:
            continue
        seen.add(ex['section_id'])
        kept.append(ex)
    return kept


def build_prompt(record: NotesRecord, arm: str, exemplars: Sequence[Exemplar] = (),
                 candidate: tuple | None = None) -> str:
    """The arm's prompt. ``candidate=(index, total)`` marks one C draft variant."""
    if arm not in ARMS:
        raise ValueError(f"Expected one of {ARMS}, got {arm!r}")
    section_type = record.get('section_type') or 'unknown'
    lines = [f'Write the {section_type} section of a report in this genre from the notes below.',
             'Use only the facts in the notes; do not invent facts.']
    if arm == 'A':
        lines.append('Do not imitate any particular source; write plain, grammatical prose.')
    else:
        lines.append('The EXEMPLARS are sections of the same type from other reports in the '
                     'genre: follow their moves, structure and register, but do not copy their '
                     'wording or reuse their facts.')
    lines += ['', 'NOTES:', record['notes'], '']
    if arm != 'A' and exemplars:
        lines.append('EXEMPLARS:')
        for i, ex in enumerate(exemplars, 1):
            lines += [f'[{i}]', ex['text'], '']
    lines.append(f'SECTION TYPE: {section_type}')
    if candidate is not None:
        index, total = candidate
        lines.append(f'Draft variant {index + 1} of {total}: produce one candidate phrasing of '
                     'the section.')
    lines.append('Reply with the section text only.')
    return '\n'.join(lines)


def critic_context(record: NotesRecord, exemplars: Sequence[Exemplar]) -> str:
    """What the critic judges candidates against: arm C's prompt without a candidate marker."""
    return build_prompt(record, 'C', exemplars)


def model_critic(model: Model, *, max_score: float = 10.0) -> Critic:
    """Critic that asks the local model for one number; unparseable replies score 0.0."""

    def critic(candidate: str, context: str) -> float:
        prompt = '\n'.join([
            'Score how well the CANDIDATE realizes the genre, structure and section type asked '
            f'for in the TASK, using the notes as the fact base. Reply with one number from 0 to '
            f'{max_score:g} only.',
            '', 'TASK:', context, '', 'CANDIDATE:', candidate])
        found = _NUMBER.search(str(model(prompt) or ''))
        return float(found.group(0)) if found else 0.0

    return critic


def _prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode('utf-8')).hexdigest()


def _done_pairs(out_path, model_id, prompt_version) -> set:
    done = set()
    if not os.path.exists(out_path):
        return done
    with open(out_path, encoding='utf-8') as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get('model') == model_id and r.get('prompt_version') == prompt_version:
                done.add((r['section_id'], r['arm']))
    return done


def _choose(critic: Critic, candidates: Sequence[str], context: str) -> tuple:
    scores = [float(critic(text, context)) for text in candidates]
    best = max(range(len(scores)), key=lambda i: (scores[i], -i))
    return best, scores


def iter_generate(sections: Iterable[NotesRecord], pool: Iterable[Exemplar], model: Model, *,
                  out_path, critic: Critic, retriever: Retriever | None = None,
                  k_exemplars: int = 3, n_candidates: int = 4,
                  temperature: float | None = None) -> Iterator[dict]:
    """Generate every missing ``(section_id, arm)``; yield each record as it is written."""
    if n_candidates < 1:
        raise ValueError('n_candidates must be at least 1')
    if temperature is None and n_candidates > 1:
        temperature = DEFAULT_C_TEMPERATURE
    pool = list(pool)
    if retriever is None:
        retriever = partial(lexical_retriever, k=k_exemplars)
    model_id = getattr(model, 'model_id', 'unknown')
    done = _done_pairs(out_path, model_id, PROMPT_VERSION)
    seen_ids = set()
    with open(out_path, 'a', encoding='utf-8') as fh:
        for record in sections:
            if record['section_id'] in seen_ids:
                raise ValueError(f"duplicate section_id in input sections: {record['section_id']!r}")
            seen_ids.add(record['section_id'])
            exemplars = legal_exemplars(record, retriever(record, pool))
            base = {k: record.get(k) for k in ('section_id', 'report_id', 'section_type')}
            base.update(model=model_id, prompt_version=PROMPT_VERSION,
                        exemplar_section_ids=[e['section_id'] for e in exemplars],
                        exemplar_report_ids=[e['report_id'] for e in exemplars])
            for arm in ARMS:
                if (record['section_id'], arm) in done:
                    continue
                if arm == 'C':
                    context = critic_context(record, exemplars)
                    prompts = [build_prompt(record, 'C', exemplars, candidate=(i, n_candidates))
                               for i in range(n_candidates)]
                    if temperature is None:
                        candidates = [model(p) for p in prompts]
                    else:
                        candidates = [model(p, temperature=temperature) for p in prompts]
                    best, scores = _choose(critic, candidates, context)
                    text, prompt = candidates[best], prompts[best]
                    extra = {'n_candidates': n_candidates, 'chosen_candidate': best,
                             'critic_scores': scores}
                    if temperature is not None:
                        extra['temperature'] = temperature
                else:
                    prompt = build_prompt(record, arm, exemplars)
                    text = model(prompt)
                    extra = {}
                rec = {**base, 'arm': arm, 'text': text, 'prompt_hash': _prompt_hash(prompt),
                       **extra}
                fh.write(json.dumps(rec, sort_keys=True, ensure_ascii=False) + '\n')
                fh.flush()
                done.add((record['section_id'], arm))
                yield rec


def generate(sections, pool, model, *, out_path, critic: Critic, retriever: Retriever | None = None,
             k_exemplars: int = 3, n_candidates: int = 4,
             temperature: float | None = None) -> list:
    """Generate every missing pair; return the records this call wrote."""
    return list(iter_generate(sections, pool, model, out_path=out_path, critic=critic,
                              retriever=retriever, k_exemplars=k_exemplars,
                              n_candidates=n_candidates, temperature=temperature))


def summarize(records: Iterable[dict], *, expected_sections: int | None = 30,
              model: str | None = None, prompt_version: str | None = None) -> dict:
    """30 x 3 completeness: every section has each arm once, no same-report exemplar.

    ``expected_sections=None`` checks arm completeness only. ``complete`` is the G-02.3 check;
    it also requires the target count when one is given. ``model`` / ``prompt_version``, when
    given, restrict the count to that run's records; others are ignored entirely. ``models`` and
    ``prompt_versions`` list the distinct values among counted records; more than one of either
    makes ``complete`` false (a mixed set is not one run).
    """
    per_pair = Counter()
    order = {}
    leaked = set()
    models, versions = set(), set()
    c_deterministic = False
    for r in records:
        if model is not None and r.get('model') != model:
            continue
        if prompt_version is not None and r.get('prompt_version') != prompt_version:
            continue
        per_pair[(r['section_id'], r['arm'])] += 1
        models.add(r.get('model'))
        versions.add(r.get('prompt_version'))
        order.setdefault(r['section_id'], True)
        if (r['arm'] == 'C' and (r.get('n_candidates') or 1) > 1
                and not r.get('temperature')):
            c_deterministic = True
        if r.get('report_id') in (r.get('exemplar_report_ids') or []):
            leaked.add(r['section_id'])
    section_ids = list(order)
    missing = sorted((sid, arm) for sid in section_ids for arm in ARMS
                     if per_pair[(sid, arm)] == 0)
    duplicates = sorted(pair for pair, n in per_pair.items() if n > 1)
    arm_counts = {arm: sum(n for (sid, a), n in per_pair.items() if a == arm) for arm in ARMS}
    models = sorted(models, key=str)
    versions = sorted(versions, key=str)
    complete = (not missing and not duplicates and not leaked
                and len(models) <= 1 and len(versions) <= 1
                and (expected_sections is None or len(section_ids) == expected_sections))
    return {'n_sections': len(section_ids), 'n_records': sum(per_pair.values()),
            'expected_sections': expected_sections, 'arm_counts': arm_counts,
            'missing': missing, 'duplicates': duplicates,
            'same_report_exemplars': sorted(leaked), 'models': models,
            'prompt_versions': versions, 'c_deterministic': c_deterministic,
            'complete': complete}


def read_jsonl(path) -> Iterator[dict]:
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            if line.strip():
                yield json.loads(line)


def main(argv=None, *, model: Model | None = None, critic: Critic | None = None) -> int:
    ap = argparse.ArgumentParser(prog='python -m experiments.g02_generate')
    ap.add_argument('--notes', required=True, help='G-02.2 notes JSONL')
    ap.add_argument('--pool', required=True, help='exemplar pool JSONL')
    ap.add_argument('--out', required=True)
    ap.add_argument('--model-url', help='loopback OpenAI-compatible endpoint (I9)')
    ap.add_argument('--model-name', default='local')
    ap.add_argument('--k-exemplars', type=int, default=3)
    ap.add_argument('--n-candidates', type=int, default=4)
    ap.add_argument('--expected-sections', type=int, default=30)
    ap.add_argument('--temperature', type=float, default=None,
                    help='sampling temperature for arm C candidates (default: '
                         f'{DEFAULT_C_TEMPERATURE} when --n-candidates > 1; 0 is honoured)')
    a = ap.parse_args(argv)
    if model is None:
        if not a.model_url:
            ap.error('--model-url is required unless a model is injected')
        model = local_model(a.model_url, model=a.model_name)
    if critic is None:
        critic = model_critic(model)
    try:
        records = generate(read_jsonl(a.notes), list(read_jsonl(a.pool)), model, out_path=a.out,
                           critic=critic, k_exemplars=a.k_exemplars, n_candidates=a.n_candidates,
                           temperature=a.temperature)
    except ValueError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    summary = summarize(read_jsonl(a.out), expected_sections=a.expected_sections,
                        model=getattr(model, 'model_id', 'unknown'), prompt_version=PROMPT_VERSION)
    summary['written'] = len(records)
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary['complete'] else 1


if __name__ == '__main__':
    sys.exit(main())
