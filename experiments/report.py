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
                  threshold='<...>', method='<...>') -> str:
    """Return a draft in result-template order; reject gates with no records."""
    arms = {}
    for row in store.query(gate=gate):
        interval = row['interval']
        uncertainty = ('interval: none recorded' if interval is None else
                       f'95% CI {interval[0]}-{interval[1]}')
        line = (f"- {row['metric']}: {row['value']} ({uncertainty}), n={row['n']}; "
                f"commit: {row['commit']}; modelVersion: {row['modelVersion']}; "
                f"inventoryVersion: {row['inventoryVersion']}; timestamp: {row['timestamp']}")
        arms.setdefault(row['arm'], []).append(line)
    if not arms:
        raise ValueError(f'No records for gate {gate}')
    numbers = '\n\n'.join(f"### {arm}\n" + '\n'.join(lines)
                            for arm, lines in arms.items())
    return (f'# {gate} — {question}\n\n'
            f'## Hypothesis\n{hypothesis}\n\n'
            f'## Threshold\n{threshold}\n\n'
            f'## Method\n{method}\n\n'
            f'## Numbers\n{numbers}\n\n'
            '## Verdict\n<passed | failed | inconclusive — and who decided>\n\n'
            '## Fallback taken\n'
            '<none, or the fallback from docs/architecture.md section 6 and its follow-up row>\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--store', required=True, type=Path)
    parser.add_argument('--gate', required=True)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args(argv)
    store = ResultStore(args.store)
    try:
        report = render_report(store, args.gate, '<gate question>')
    finally:
        store.close()
    args.out.write_text(report, encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
