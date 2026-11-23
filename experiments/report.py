"""Render stored gate measurements without deciding the gate.

CLI entry point; unwired by design until the G-01 run (X-00 runner).
Only formatted report text is retained, grouped by first-seen arm. Query rows
are consumed once; memory is O(report size), as required by the string API.
The owner must supply population/reference/attribution in the method and
complete the verdict and fallback before publishing an actual gate result.
"""
import argparse
from pathlib import Path

from experiments.store import ResultStore


def render_report(store, gate, question, *, hypothesis='<...>',
                  threshold='<...>', method='<...>', allow_missing_interval=False) -> str:
    """Reject empty gates and missing intervals unless explicitly drafting."""
    arms = {}
    missing_intervals = []
    for row in store.query(gate=gate):
        interval = row['interval']
        if interval is None:
            identity = f"gate: {gate}; arm: {row['arm']}; metric: {row['metric']}"
            if not allow_missing_interval:
                raise ValueError(f'Missing interval for {identity}')
            missing_intervals.append(f'- {identity}')
            uncertainty = 'interval: NOT REPORTED (ST-02 violation)'
        else:
            uncertainty = f'95% CI {interval[0]}-{interval[1]}'
        line = (f"- {row['metric']}: {row['value']} ({uncertainty}), n={row['n']}; "
                f"commit: {row['commit']}; modelVersion: {row['modelVersion']}; "
                f"inventoryVersion: {row['inventoryVersion']}; timestamp: {row['timestamp']}")
        arms.setdefault(row['arm'], []).append(line)
    if not arms:
        raise ValueError(f'No records for gate {gate}')
    numbers = '\n\n'.join(f"### {arm}\n" + '\n'.join(lines)
                            for arm, lines in arms.items())
    missing_section = ('## Missing intervals\n' + '\n'.join(missing_intervals) + '\n\n'
                       if missing_intervals else '')
    return (f'# {gate} — {question}\n\n'
            f'## Hypothesis\n{hypothesis}\n\n'
            f'## Threshold\n{threshold}\n\n'
            f'## Method\n{method}\n\n'
            f'## Numbers\n{numbers}\n\n'
            f'{missing_section}'
            '## Verdict\n<passed | failed | inconclusive — and who decided>\n\n'
            '## Fallback taken\n'
            '<none, or the fallback from docs/architecture.md section 6 and its follow-up row>\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--store', required=True, type=Path)
    parser.add_argument('--gate', required=True)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--allow-missing-interval', action='store_true',
                        help='Render a draft with explicit ST-02 violations for missing intervals')
    args = parser.parse_args(argv)
    store = ResultStore(args.store)
    try:
        report = render_report(store, args.gate, '<gate question>',
                               allow_missing_interval=args.allow_missing_interval)
    finally:
        store.close()
    args.out.write_text(report, encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
