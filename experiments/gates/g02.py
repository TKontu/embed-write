"""G-02 gate: blind preference rates for the steering arms (G-02.5 agent half).

Config:
  session      the blind session (``blind_session.save_session`` output: list of item dicts)
  choices      iterable of choice lines (``blind_session.record_session_choice`` output),
               read one line at a time; a str line may lack its trailing newline only if it is
               the last (a torn final line)
  thresholds   optional {"c_over_a"}; absent means the proposed 0.70 (G-02.1 is [H]),
               reported as "proposed"; explicit None means no threshold, hint "n/a"
  n_resamples  bootstrap resamples for the 95 % intervals (default 10000)

Per comparison (``A_vs_C`` reports C, ``A_vs_B`` reports B, ``C_vs_original`` reports C): the
reported arm's win rate with ties at half credit, n, wins/losses/ties and a seeded percentile
bootstrap interval, over first presentations only (``repeat_of`` null). Repeats feed only the
self-consistency figure (experiments.consistency). n 0 gives win_rate/interval None with
"interval_reason": "no_choices".

Completeness counts: unanswered session items, choices for unknown item ids, duplicate
choices for an already answered item (blind_ui treats an item with any recorded choice as done,
so the first recorded choice counts and later ones are ignored and counted), malformed lines,
a torn final line, and contradicting choices (comparison, repeat_of, pair_id, choice or winner not
matching the session item); ``complete`` is false for a session with no items. A session breaking the shared contract (unknown comparison, wrong
arm pair, duplicate item id) raises G02SessionError. Any contradiction raises G02ContradictionError (no numbers).

Only ``A_vs_C`` carries a ``verdict_hint`` (meets / misses / n/a); no gate status is emitted.
Reason texts and section texts never enter the output (count of non-empty reasons only).

Run only through experiments.runner.run_gate (requires a confirmed "g02" preregistration).
Production caller: experiments.g02_draft (G-02.5 real run after BJ-03); otherwise unwired by
design. Memory: O(session items); choices are streamed.
"""
from __future__ import annotations

import json
import random
from typing import Any, Mapping

from experiments.blind_session import consistency_pairs
from experiments.consistency import consistency_report
from experiments.metrics.preference import bootstrap_interval, win_rate

gate_id = "g02"

REPORTED_ARM = {"A_vs_C": "C", "A_vs_B": "B", "C_vs_original": "C"}
PROPOSED_THRESHOLDS = {"c_over_a": 0.7}
EXPECTED_ARMS = {"A_vs_C": {"A", "C"}, "A_vs_B": {"A", "B"},
                 "C_vs_original": {"C", "original"}}
_KEYS = ("item_id", "comparison", "winner", "pair_id")


class G02ContradictionError(ValueError):
    """A choice contradicts its session item; carries the completeness counts."""

    def __init__(self, message: str, completeness: dict):
        super().__init__(message)
        self.completeness = completeness


class G02SessionError(ValueError):
    """The session violates the shared contract; message carries ids/counts only."""


def _session_index(items) -> dict:
    index = {}
    for d in items:
        iid = d["item_id"]
        if iid in index:
            raise G02SessionError(f"duplicate session item id {iid!r}")
        want = EXPECTED_ARMS.get(d.get("comparison"))
        if want is None:
            raise G02SessionError(f"session item {iid!r} has an unknown comparison")
        if {d.get("left_arm"), d.get("right_arm")} != want or d["left_arm"] == d["right_arm"]:
            raise G02SessionError(
                f"session item {iid!r} arms do not match its comparison {d['comparison']}")
        index[iid] = d
    return index


def _r(v):
    return None if v is None else round(v, 6)


def _parse(line):
    if isinstance(line, (bytes, bytearray)):
        line = line.decode("utf-8")
    record = json.loads(line)
    if not isinstance(record, dict) or any(not isinstance(record.get(k), str) for k in _KEYS):
        raise ValueError("bad record")
    return record


def run(rng: random.Random, config: Mapping[str, Any]) -> dict:
    session = _session_index(config["session"])
    n_resamples = int(config.get("n_resamples", 10000))
    if "thresholds" in config and config["thresholds"] is None:
        thresholds, source = None, "none"
    elif "thresholds" in config:
        thresholds = {**PROPOSED_THRESHOLDS, **dict(config["thresholds"])}
        source = config.get("thresholds_source", "config")  # g02_draft.draft: "preregistration"
    else:
        thresholds, source = dict(PROPOSED_THRESHOLDS), "proposed"

    counts = dict(unknown_item=0, duplicate=0, malformed=0, torn=0, contradicting=0)
    tallies = {name: [] for name in REPORTED_ARM}
    answered, repeat_records, reasons = set(), [], 0
    pending = None
    for line in config["choices"]:
        if pending is not None:
            counts["malformed"] += 1
        text = line.decode("utf-8") if isinstance(line, (bytes, bytearray)) else line
        if not text.strip():
            pending = None
            continue
        try:
            record = _parse(text)
        except ValueError:
            pending = text  # malformed; decided as torn if it is the last, unterminated line
            continue
        pending = None
        it = session.get(record["item_id"])
        if it is None:
            counts["unknown_item"] += 1
            continue
        side = record.get("choice")
        expected = ("tie" if side == "tie" else it["left_arm"] if side == "left"
                    else it["right_arm"] if side == "right" else None)
        if (record["comparison"] != it["comparison"] or record.get("repeat_of") != it["repeat_of"]
                or record["pair_id"] != it["pair_id"] or expected is None
                or record["winner"] != expected):
            counts["contradicting"] += 1
            continue
        if record["item_id"] in answered:
            counts["duplicate"] += 1
            continue
        answered.add(record["item_id"])
        if isinstance(record.get("reason"), str) and record["reason"].strip():
            reasons += 1
        slim = dict(item_id=record["item_id"], pair_id=record["pair_id"],
                    winner=record["winner"], repeat_of=it["repeat_of"])
        repeat_records.append(slim)
        if it["repeat_of"] is None and it["comparison"] in tallies:
            arm = REPORTED_ARM[it["comparison"]]
            tallies[it["comparison"]].append(
                "tie" if record["winner"] == "tie" else "a" if record["winner"] == arm else "b")
    if pending is not None:
        counts["torn" if not pending.endswith("\n") else "malformed"] += 1
    counts["unanswered"] = sum(1 for i in session if i not in answered)
    counts["session_items"] = len(session)
    counts["complete"] = bool(session) and counts["unanswered"] == 0
    if counts["contradicting"]:
        raise G02ContradictionError(
            f"{counts['contradicting']} choice(s) contradict their session item "
            "(comparison, repeat_of, pair_id or winner); no numbers computed", counts)

    th = thresholds or {}
    comparisons = {}
    for name, arm in REPORTED_ARM.items():
        choices = tallies[name]
        seed = rng.randrange(2 ** 32)
        row = dict(arm=arm, n=len(choices), wins=choices.count("a"),
                   losses=choices.count("b"), ties=choices.count("tie"),
                   method="win_rate_ties_half_percentile_bootstrap")
        if choices:
            row["win_rate"] = _r(win_rate(choices)["win_rate"])
            lo, hi = bootstrap_interval(choices, n_resamples=n_resamples, seed=seed)
            row["interval"] = [_r(lo), _r(hi)]
        else:
            row.update(win_rate=None, interval=None, interval_reason="no_choices")
        if name == "A_vs_C":
            t = th.get("c_over_a")
            row["verdict_hint"] = ("n/a" if t is None or row["win_rate"] is None
                                   else "meets" if row["win_rate"] >= t else "misses")
        comparisons[name] = row

    pairs = list(consistency_pairs(repeat_records))
    seed = rng.randrange(2 ** 32)
    if pairs:
        rep = consistency_report(pairs, n_resamples=n_resamples, seed=seed)
        consistency = dict(n=rep["n"], agreements=rep["agreements"], rate=_r(rep["rate"]),
                           interval=[_r(v) for v in rep["interval"]])
    else:
        consistency = dict(n=0, agreements=0, rate=None, interval=None,
                           interval_reason="no_repeated_pairs")
    return {"comparisons": comparisons, "consistency": consistency, "completeness": counts,
            "reasons_nonempty": reasons, "n_resamples": n_resamples,
            "thresholds": thresholds, "thresholds_source": source}
