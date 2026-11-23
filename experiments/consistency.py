"""Expert self-consistency (BJ-04); unwired by design until G-02 (BJ-03).

Consumes (pair_id, first_winner, repeat_winner) tuples from
blind_session.consistency_pairs, holding only one agree flag per repeated pair.
A low rate is reported with a caution; no threshold is loosened here — the
expert decides how dependent thresholds change.
"""
import argparse
import json
import sys

from experiments.blind_session import consistency_pairs
from experiments.metrics.preference import bootstrap_interval

METRIC = 'self_consistency'
CAUTION = ('CAUTION: self-consistency is below the low threshold; thresholds that depend '
           'on expert agreement must be loosened, and the expert decides how. '
           'Nothing has been loosened automatically.')
DEGENERATE_NOTE = ('NOTE: the percentile bootstrap interval collapsed to a point (rate 0 or 1); '
                   'it carries no width information for this n.')


def consistency_report(pairs, *, n_resamples=10000, confidence=0.95, seed=0):
    """Return {n, agreements, rate, interval[, degenerate_interval]}; interval is a seeded percentile
    bootstrap over pairs. Memory O(number of repeated pairs)."""
    # Agree -> 'a', disagree -> 'b': the win rate of 'a' is the agreement rate.
    flags = ['a' if first == repeat else 'b' for _, first, repeat in pairs]
    if not flags:
        raise ValueError('no repeated pairs: consistency is undefined for n == 0')
    n = len(flags)
    agreements = flags.count('a')
    rate = agreements / n
    lo, hi = bootstrap_interval(flags, n_resamples=n_resamples,
                                confidence=confidence, seed=seed)
    # Guard against float rounding at the extremes so lo <= rate <= hi holds.
    interval = (min(lo, rate), max(hi, rate))
    report = dict(n=n, agreements=agreements, rate=rate, interval=interval)
    if interval[0] == interval[1]:
        report['degenerate_interval'] = True
    return report


def to_store_record(report, *, gate, arm, timestamp, commit, modelVersion, inventoryVersion):
    """Return a ResultStore record for a consistency report."""
    return dict(gate=gate, arm=arm, metric=METRIC, value=report['rate'], n=report['n'],
                interval=tuple(report['interval']), timestamp=timestamp, commit=commit,
                modelVersion=modelVersion, inventoryVersion=inventoryVersion)


def main(argv=None, out=None):
    out = out or sys.stdout
    parser = argparse.ArgumentParser(prog='python3 -m experiments.consistency')
    parser.add_argument('choices', help='session choices JSONL (BJ-02)')
    parser.add_argument('--low-threshold', type=float, default=0.8)
    parser.add_argument('--n-resamples', type=int, default=10000)
    parser.add_argument('--confidence', type=float, default=0.95)
    parser.add_argument('--seed', type=int, default=0)
    args = parser.parse_args(argv)
    try:
        with open(args.choices, encoding='utf-8') as lines:
            report = consistency_report(consistency_pairs(lines), n_resamples=args.n_resamples,
                                        confidence=args.confidence, seed=args.seed)
    except ValueError as exc:
        parser.exit(2, f'{parser.prog}: error: {exc}\n')
    print(json.dumps(dict(report, interval=list(report['interval']))), file=out)
    if report.get('degenerate_interval'):
        print(DEGENERATE_NOTE, file=out)
    if report['rate'] < args.low_threshold:
        print(CAUTION, file=out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
