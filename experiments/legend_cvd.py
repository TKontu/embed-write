"""G-09.1 colour-blind simulation check on a genre's stored legend (stdlib only).

``python -m experiments.legend_cvd check GENRE_JSON [--min-delta-e X] [--json OUT]`` reads
``genre.legend.colors`` ({move_id: "#rrggbb"}) plus ``genre.legend.other`` (shape as in
editor/src/legend.js readLegend) and, for normal vision and protan, deutan and tritan simulation,
reports the minimum pairwise CIEDE2000 difference among all legend colours and the pairs below
the threshold. Exit 0 when all four simulations pass, 1 when any fails, 2 on bad input.

Method: sRGB -> linear RGB; Machado, Oliveira & Fernandes (2009) full-severity (1.0) matrices
for protanopia, deuteranopia and tritanopia applied in linear RGB, clipped to [0, 1]; linear RGB
-> XYZ (D65) -> CIELAB -> CIEDE2000 (Sharma, Wu & Dalal 2005).

The default ``--min-delta-e 10.0`` is a PROPOSED threshold that the expert confirms (the G-09
preregistration is [H]); the report always prints the threshold used. This tool only checks
colours (invariant I3: the legend is fixed per genre, never computed); it never picks them.
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import re
import sys
from pathlib import Path

DEFAULT_MIN_DELTA_E = 10.0  # PROPOSED; expert confirms (G-09 preregistration is [H])

MACHADO = {
    'protan': ((0.152286, 1.052583, -0.204868),
               (0.114503, 0.786281, 0.099216),
               (-0.003882, -0.048116, 1.051998)),
    'deutan': ((0.367322, 0.860646, -0.227968),
               (0.280085, 0.672501, 0.047413),
               (-0.011820, 0.042940, 0.968881)),
    'tritan': ((1.255528, -0.076749, -0.178779),
               (-0.078411, 0.930809, 0.147602),
               (0.004733, 0.691367, 0.303900)),
}
SIMULATIONS = ('normal', 'protan', 'deutan', 'tritan')
_HEX = re.compile(r'^#[0-9a-fA-F]{6}$')
_XYZ = ((0.4124564, 0.3575761, 0.1804375),
        (0.2126729, 0.7151522, 0.0721750),
        (0.0193339, 0.1191920, 0.9503041))
_WHITE = (0.95047, 1.0, 1.08883)


class LegendError(ValueError):
    """Bad input: the message names the offending field."""


def _mul(m, v):
    return tuple(sum(m[i][j] * v[j] for j in range(3)) for i in range(3))


def hex_to_linear(hexcolor: str) -> tuple[float, float, float]:
    out = []
    for i in (1, 3, 5):
        c = int(hexcolor[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return tuple(out)


def simulate(linear, sim: str):
    if sim == 'normal':
        return tuple(linear)
    return tuple(min(1.0, max(0.0, c)) for c in _mul(MACHADO[sim], linear))


def linear_to_lab(linear):
    xyz = _mul(_XYZ, linear)

    def f(t):
        return t ** (1 / 3) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29
    fx, fy, fz = (f(xyz[i] / _WHITE[i]) for i in range(3))
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def ciede2000(lab1, lab2) -> float:
    """CIEDE2000 colour difference (kL = kC = kH = 1), per Sharma, Wu & Dalal 2005."""
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2
    cbar = (math.hypot(a1, b1) + math.hypot(a2, b2)) / 2
    g = 0.5 * (1 - math.sqrt(cbar ** 7 / (cbar ** 7 + 25 ** 7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if c1p else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if c2p else 0.0
    dLp = L2 - L1
    dCp = c2p - c1p
    if c1p * c2p == 0:
        dhp = 0.0
    else:
        dhp = h2p - h1p
        if dhp > 180:
            dhp -= 360
        elif dhp < -180:
            dhp += 360
    dHp = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dhp / 2))
    Lbp = (L1 + L2) / 2
    Cbp = (c1p + c2p) / 2
    if c1p * c2p == 0:
        hbp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbp = (h1p + h2p) / 2
    elif h1p + h2p < 360:
        hbp = (h1p + h2p + 360) / 2
    else:
        hbp = (h1p + h2p - 360) / 2
    t = (1 - 0.17 * math.cos(math.radians(hbp - 30)) + 0.24 * math.cos(math.radians(2 * hbp))
         + 0.32 * math.cos(math.radians(3 * hbp + 6)) - 0.20 * math.cos(math.radians(4 * hbp - 63)))
    dtheta = 30 * math.exp(-(((hbp - 275) / 25) ** 2))
    rc = 2 * math.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7))
    sl = 1 + 0.015 * (Lbp - 50) ** 2 / math.sqrt(20 + (Lbp - 50) ** 2)
    sc = 1 + 0.045 * Cbp
    sh = 1 + 0.015 * Cbp * t
    rt = -math.sin(math.radians(2 * dtheta)) * rc
    return math.sqrt((dLp / sl) ** 2 + (dCp / sc) ** 2 + (dHp / sh) ** 2
                     + rt * (dCp / sc) * (dHp / sh))


def _hex(value, where: str) -> str:
    if not isinstance(value, str) or not _HEX.match(value):
        raise LegendError(f'{where}: must be a "#rrggbb" hex colour, got {value!r}')
    return value.lower()


def read_legend(genre) -> dict[str, str]:
    """Return {name: hex} for every move colour plus ``other`` (mirrors editor readLegend)."""
    if not isinstance(genre, dict):
        raise LegendError('genre: must be an object')
    legend = genre.get('legend')
    if not isinstance(legend, dict):
        raise LegendError('legend: must be an object')
    colors = legend.get('colors')
    if not isinstance(colors, dict):
        raise LegendError('legend.colors: must be an object')
    if 'other' not in legend:
        raise LegendError('legend.other: required field missing')
    moves = genre.get('moves')
    known = None
    if isinstance(moves, list):
        known = {m.get('id') for m in moves if isinstance(m, dict)}
    out = {}
    for key, value in colors.items():
        if key.startswith('_'):
            continue  # comment key, ignored as in service/genre.py
        if key == 'other':
            raise LegendError('legend.colors.other: "other" is reserved for the neutral class')
        if known is not None and key not in known:
            raise LegendError(f'legend.colors.{key}: legend entry for unknown move')
        out[key] = _hex(value, f'legend.colors.{key}')
    if known is not None:
        for mid in sorted(k for k in known if isinstance(k, str)):
            if mid not in out:
                raise LegendError(f'legend.colors.{mid}: move missing from legend')
    out['other'] = _hex(legend['other'], 'legend.other')
    if len(out) < 2:
        raise LegendError('legend: fewer than 2 colours to compare')
    return out


def check(colors: dict[str, str], min_delta_e: float = DEFAULT_MIN_DELTA_E) -> dict:
    linear = {k: hex_to_linear(v) for k, v in colors.items()}
    sims = {}
    for sim in SIMULATIONS:
        labs = {k: linear_to_lab(simulate(v, sim)) for k, v in linear.items()}
        pairs = [(a, b, ciede2000(labs[a], labs[b])) for a, b in itertools.combinations(colors, 2)]
        lo = min(pairs, key=lambda p: p[2])
        below = [{'a': a, 'b': b, 'delta_e': round(d, 4)} for a, b, d in pairs if d < min_delta_e]
        sims[sim] = {'min_delta_e': round(lo[2], 4), 'min_pair': [lo[0], lo[1]],
                     'below': sorted(below, key=lambda p: p['delta_e']), 'pass': not below}
    return {'threshold': min_delta_e, 'threshold_status': 'proposed', 'colors': colors,
            'simulations': sims, 'pass': all(s['pass'] for s in sims.values())}


def format_report(report: dict) -> str:
    lines = [f"threshold: CIEDE2000 >= {report['threshold']} (proposed; expert confirms)"]
    for sim, s in report['simulations'].items():
        a, b = s['min_pair']
        lines.append(f"{sim:7s} min {s['min_delta_e']:.2f} ({a}/{b}) {'PASS' if s['pass'] else 'FAIL'}")
        for p in s['below']:
            lines.append(f"        below: {p['a']}/{p['b']} {p['delta_e']:.2f}")
    lines.append('overall: ' + ('PASS' if report['pass'] else 'FAIL'))
    return '\n'.join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='python -m experiments.legend_cvd', description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    c = sub.add_parser('check', help='check legend colours under normal, protan, deutan, tritan vision')
    c.add_argument('genre_json', type=Path)
    c.add_argument('--min-delta-e', type=float, default=DEFAULT_MIN_DELTA_E,
                   help='minimum pairwise CIEDE2000 (default 10.0: a PROPOSED threshold the expert '
                        'confirms; G-09 preregistration is [H])')
    c.add_argument('--json', type=Path, help='also write the report as JSON to this path')
    args = ap.parse_args(argv)
    try:
        genre = json.loads(args.genre_json.read_text(encoding='utf-8'))
        colors = read_legend(genre)
    except (OSError, json.JSONDecodeError, LegendError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2
    report = check(colors, args.min_delta_e)
    print(format_report(report))
    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return 0 if report['pass'] else 1


if __name__ == '__main__':
    sys.exit(main())
