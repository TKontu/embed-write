"""Compare all stored arms without choosing a winner or deciding a gate.

CLI for the G-01 result document author; unwired by design to EV-03 until
G-01 runs. The author supplies population, reference and attribution context.
Query rows are streamed; memory is O(distinct metric/arm pairs + output size).
Gate sizes are expected to be small; the number of pairs is not bounded here.
"""
import argparse
from datetime import datetime, timezone
from html import escape

from experiments.store import ResultStore


def compare_arms(store, gate, metric=None):
    """Return sorted metric -> sorted arm rows, including superseded counts.

    Timestamps must be ISO 8601; dates and naive times are treated as UTC.
    Equal timestamps select the last inserted row (ResultStore query order).
    A missing gate or metric selection raises ValueError.
    """
    groups = {}
    for row in store.query(gate=gate, metric=metric):
        timestamp = datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00'))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        arms = groups.setdefault(row['metric'], {})
        previous = arms.get(row['arm'])
        superseded = 0 if previous is None else previous[1]['superseded'] + 1
        if previous is None or timestamp >= previous[0]:
            selected = {key: row[key] for key in ('arm', 'value', 'n', 'interval')}
            selected['superseded'] = superseded
            arms[row['arm']] = (timestamp, selected)
        else:
            previous[1]['superseded'] = superseded
    if not groups:
        raise ValueError(f'No records for gate {gate}, metric {metric}')
    return {name: [arms[arm][1] for arm in sorted(arms)]
            for name, arms in sorted(groups.items())}


def _cell(value):
    return (escape(str(value), quote=False).replace('|', '&#124;')
            .replace('\r\n', '\n').replace('\r', '\n').replace('\n', '<br>'))


def render_comparison(store, gate, metric=None):
    """Return a Markdown table and per-arm notes for superseded measurements."""
    lines = ['| metric | arm | value | n | interval |',
             '| --- | --- | --- | --- | --- |']
    notes = []
    hidden = 0
    for name, rows in compare_arms(store, gate, metric).items():
        for row in rows:
            interval = row['interval']
            bounds = '—' if interval is None else f'[{interval[0]}, {interval[1]}]'
            cells = (name, row['arm'], row['value'], row['n'], bounds)
            lines.append('| ' + ' | '.join(_cell(value) for value in cells) + ' |')
            if row['superseded']:
                notes.append(f"- {_cell(name)} / {_cell(row['arm'])}: "
                             f"{row['superseded']} superseded rows")
                hidden += row['superseded']
    if notes:
        lines.extend(['', *notes, '',
                      f'{hidden} earlier rows not shown (counts per arm above); '
                      'they remain in the store and in the full report.'])
    return '\n'.join(lines) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('store')
    parser.add_argument('gate')
    parser.add_argument('--metric')
    args = parser.parse_args(argv)
    store = ResultStore(args.store)
    try:
        print(render_comparison(store, args.gate, args.metric), end='')
    finally:
        store.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
