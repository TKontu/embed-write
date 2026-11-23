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
                  threshold='<...>', method='<...>', allow_missing_interval=False,
                  expected_arms=None, allow_missing_arms=False) -> str:
    """Reject empty gates, missing intervals and missing expected arms unless drafting.

    Every stored arm is always rendered (ST-03); expected_arms only adds checks.
    """
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
    arm_sections = ''
    if expected_arms is not None:
        expected = list(dict.fromkeys(expected_arms))
        missing_arms = [arm for arm in expected if arm not in arms]
        unexpected_arms = [arm for arm in arms if arm not in expected]
        if missing_arms and not allow_missing_arms:
            raise ValueError(f"Missing arms for gate {gate}: {', '.join(missing_arms)}")
        for arm in missing_arms:
            arms[arm] = ['- NO RESULTS STORED (ST-03 violation)']
        if missing_arms:
            arm_sections += ('## Missing arms\n'
                             + ''.join(f'- {arm}\n' for arm in missing_arms) + '\n')
        if unexpected_arms:
            arm_sections += ('## Unexpected arms\n'
                             + ''.join(f'- {arm}\n' for arm in unexpected_arms) + '\n')
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
            f'{arm_sections}'
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
    parser.add_argument('--expected-arm', action='append', dest='expected_arms',
                        help='Arm that must have stored rows (repeatable)')
    parser.add_argument('--allow-missing-arms', action='store_true',
                        help='Render a draft with explicit ST-03 violations for missing arms')
    args = parser.parse_args(argv)
    store = ResultStore(args.store)
    try:
        report = render_report(store, args.gate, '<gate question>',
                               allow_missing_interval=args.allow_missing_interval,
                               expected_arms=args.expected_arms,
                               allow_missing_arms=args.allow_missing_arms)
    finally:
        store.close()
    args.out.write_text(report, encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
