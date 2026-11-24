"""Generation run records (GE-06).

A record holds every input needed to regenerate each candidate: prompt text, ordered exemplar
ids, model identifier/version and per-candidate sampling parameters (including seed), plus the
candidates produced. ``run_id`` is sha256 over canonical JSON of all inputs; it is the string
EL-01's ``editlog.schema`` ``generation_run_id`` references.

Unwired by design: GE-03/GE-04 will produce these records and EL-02 will reference ``run_id``.
Pure Python, no LLM or network calls; one record in memory at a time.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, fields
from typing import Callable, Sequence

_RECORD_KEYS = ("run_id", "prompt", "exemplar_ids", "model", "sampling", "candidates")
_PARAM_KEYS = ("seed", "temperature", "top_p", "max_tokens")


@dataclass(frozen=True)
class SamplingParams:
    seed: int
    temperature: float
    top_p: float
    max_tokens: int

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in _PARAM_KEYS}


@dataclass(frozen=True)
class GenerationRunRecord:
    run_id: str
    prompt: str
    exemplar_ids: tuple
    model: str
    sampling: tuple
    candidates: tuple

    @classmethod
    def build(cls, prompt: str, exemplar_ids: Sequence[str], model: str,
              sampling: Sequence[SamplingParams], candidates: Sequence[str]) -> "GenerationRunRecord":
        rec = cls("", prompt, tuple(exemplar_ids), model, tuple(sampling), tuple(candidates))
        rec = cls(compute_run_id(rec), *(getattr(rec, f.name) for f in fields(cls)[1:]))
        validate_record(rec)
        return rec


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def _inputs(rec: GenerationRunRecord) -> dict:
    return {
        "prompt": rec.prompt,
        "exemplar_ids": list(rec.exemplar_ids),
        "model": rec.model,
        "sampling": [s.to_dict() for s in rec.sampling],
    }


def compute_run_id(rec: GenerationRunRecord) -> str:
    return hashlib.sha256(_canonical(_inputs(rec)).encode("utf-8")).hexdigest()


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v) -> bool:
    return (_is_int(v) or isinstance(v, float)) and math.isfinite(v)


def validate_record(rec: GenerationRunRecord) -> None:
    """Raise ValueError if the record is incomplete or inconsistent."""
    if not isinstance(rec.prompt, str) or not rec.prompt:
        raise ValueError("prompt must be a non-empty string")
    if not isinstance(rec.model, str) or not rec.model:
        raise ValueError("model must be a non-empty string")
    if not all(isinstance(e, str) and e for e in rec.exemplar_ids):
        raise ValueError("exemplar_ids must be non-empty strings")
    if not rec.sampling:
        raise ValueError("at least one candidate sampling entry required")
    for s in rec.sampling:
        if not isinstance(s, SamplingParams):
            raise ValueError("sampling entries must be SamplingParams")
        if not (_is_int(s.seed) and _is_int(s.max_tokens) and s.max_tokens > 0):
            raise ValueError("seed and max_tokens must be ints, max_tokens > 0")
        if not (_is_num(s.temperature) and _is_num(s.top_p)):
            raise ValueError("temperature and top_p must be finite numbers")
    if not all(isinstance(c, str) for c in rec.candidates):
        raise ValueError("candidates must be strings")
    if len(rec.candidates) != len(rec.sampling):
        raise ValueError("candidates count must match sampling entries")
    if rec.run_id != compute_run_id(rec):
        raise ValueError("run_id does not match record inputs")


def to_json(rec: GenerationRunRecord) -> str:
    validate_record(rec)
    d = _inputs(rec)
    d["run_id"] = rec.run_id
    d["candidates"] = list(rec.candidates)
    return _canonical(d)


def from_json(text: str) -> GenerationRunRecord:
    d = json.loads(text)
    if not isinstance(d, dict) or set(d) != set(_RECORD_KEYS):
        raise ValueError(f"record must have exactly keys {_RECORD_KEYS}")
    try:
        sampling = tuple(SamplingParams(**{k: s[k] for k in _PARAM_KEYS}) for s in d["sampling"])
    except (KeyError, TypeError) as exc:
        raise ValueError(f"bad sampling entry: {exc}") from exc
    rec = GenerationRunRecord(d["run_id"], d["prompt"], tuple(d["exemplar_ids"]), d["model"],
                              sampling, tuple(d["candidates"]))
    validate_record(rec)
    return rec


GenerateFn = Callable[[str, tuple, str, SamplingParams], str]


def replay(rec: GenerationRunRecord, generate_fn: GenerateFn) -> bool:
    """True iff a deterministic generator reproduces every recorded candidate from the record."""
    return all(
        generate_fn(rec.prompt, rec.exemplar_ids, rec.model, s) == c
        for s, c in zip(rec.sampling, rec.candidates, strict=True)
    )
