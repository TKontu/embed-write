"""Palette validation: minimum pairwise colour difference (todo-05 LG-03).

Checks every pair of move colours in normal vision and three simulated
colour-vision deficiencies (Machado et al. 2009, severity 1.0) using CIEDE2000.
Pure stdlib. O(n^2) over palette size; n is the number of moves in a genre.

No palette is chosen here (LG-01 is [H]). genre_palette() wires the validator
to a genre file's legend; its production caller is the --genre CLI mode (CI
wiring is a residual).

CLI (build-failing hook):
    python3 -m service.palette (PALETTE.json | --genre GENRE.json) [--min-delta-e X]
exits 1 if any pair is below threshold, 0 otherwise; 2 on an invalid input.
"""

import argparse
import itertools
import json
import math
import re
import sys
from dataclasses import dataclass
from typing import Mapping

from service.genre import OTHER, GenreFileError, load_genre

MIN_DELTA_E = 20.0
"""Provisional default CIEDE2000 threshold; the expert may revise it under G-09."""

VISIONS = ('normal', 'protan', 'deutan', 'tritan')

# Machado, Oliveira & Fernandes 2009, severity 1.0, applied to linear RGB.
_MACHADO = {
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

_HEX = re.compile(r'#[0-9a-fA-F]{6}')
_WHITE = (0.95047, 1.0, 1.08883)  # D65


@dataclass(frozen=True)
class Violation:
    vision: str
    move_a: str
    move_b: str
    delta_e: float


def parse_hex(text):
    """'#rrggbb' -> (r, g, b) ints 0..255; ValueError if malformed."""
    if not isinstance(text, str) or not _HEX.fullmatch(text):
        raise ValueError(f'malformed colour {text!r}; expected #rrggbb')
    return tuple(int(text[i:i + 2], 16) for i in (1, 3, 5))


def _to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _to_srgb(c):
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def _linear_to_lab(lin):
    r, g, b = lin
    xyz = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b,
           0.2126729 * r + 0.7151522 * g + 0.0721750 * b,
           0.0193339 * r + 0.1191920 * g + 0.9503041 * b)

    def f(t):
        return t ** (1 / 3) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29

    fx, fy, fz = (f(v / w) for v, w in zip(xyz, _WHITE))
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def srgb_to_lab(rgb):
    """sRGB (r, g, b) ints 0..255 -> CIE L*a*b* (D65)."""
    return _linear_to_lab(tuple(_to_linear(c / 255) for c in rgb))


def _simulate_linear(lin, kind):
    try:
        m = _MACHADO[kind]
    except KeyError:
        raise ValueError(f'unknown deficiency {kind!r}') from None
    return tuple(min(1.0, max(0.0, sum(row[i] * lin[i] for i in range(3))))
                 for row in m)


def simulate(rgb, kind):
    """Simulate (r, g, b) ints 0..255 under kind; returns sRGB floats in [0, 1]."""
    lin = tuple(_to_linear(c / 255) for c in rgb)
    return tuple(_to_srgb(c) for c in _simulate_linear(lin, kind))


def delta_e_2000(lab1, lab2):
    """CIEDE2000 colour difference (kL = kC = kH = 1)."""
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
    t = (1 - 0.17 * math.cos(math.radians(hbp - 30))
         + 0.24 * math.cos(math.radians(2 * hbp))
         + 0.32 * math.cos(math.radians(3 * hbp + 6))
         - 0.20 * math.cos(math.radians(4 * hbp - 63)))
    dtheta = 30 * math.exp(-(((hbp - 275) / 25) ** 2))
    rc = 2 * math.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7))
    sl = 1 + 0.015 * (Lbp - 50) ** 2 / math.sqrt(20 + (Lbp - 50) ** 2)
    sc = 1 + 0.045 * Cbp
    sh = 1 + 0.015 * Cbp * t
    rt = -math.sin(math.radians(2 * dtheta)) * rc
    return math.sqrt((dLp / sl) ** 2 + (dCp / sc) ** 2 + (dHp / sh) ** 2
                     + rt * (dCp / sc) * (dHp / sh))


def validate(palette: Mapping[str, str], min_delta_e=MIN_DELTA_E):
    """Return a tuple of Violation for every pair below min_delta_e.

    Ordered by vision (normal, protan, deutan, tritan), then sorted move
    names. An empty tuple means the palette passes.
    """
    moves = sorted(palette)
    lin = {m: tuple(_to_linear(c / 255) for c in parse_hex(palette[m]))
           for m in moves}
    out = []
    for vision in VISIONS:
        if vision == 'normal':
            labs = {m: _linear_to_lab(lin[m]) for m in moves}
        else:
            labs = {m: _linear_to_lab(_simulate_linear(lin[m], vision))
                    for m in moves}
        for a, b in itertools.combinations(moves, 2):
            d = delta_e_2000(labs[a], labs[b])
            if d < min_delta_e:
                out.append(Violation(vision, a, b, d))
    return tuple(out)


def genre_palette(genre_obj):
    """Validated genre object -> {move: hex} in moves order, plus 'other'.

    Colours come from legend.colors ("_" comment keys skipped) and
    legend.other; the legend is stored, never computed (I3).
    """
    colors = genre_obj['legend']['colors']
    out = {m['id']: colors[m['id']] for m in genre_obj['moves']
           if not m['id'].startswith('_')}
    out[OTHER] = genre_obj['legend']['other']
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python3 -m service.palette')
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('palette', nargs='?', help='JSON object {move: "#rrggbb"}')
    mode.add_argument('--genre', metavar='PATH',
                      help='genre file; validates legend.colors plus legend.other')
    parser.add_argument('--min-delta-e', type=float, default=MIN_DELTA_E)
    args = parser.parse_args(argv)
    if args.genre is not None:
        try:
            data = genre_palette(load_genre(args.genre))
        except GenreFileError as exc:
            print(exc, file=sys.stderr)
            return 2
    else:
        with open(args.palette, encoding='utf-8') as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            print('palette must be a JSON object', file=sys.stderr)
            return 2
    violations = validate(data, args.min_delta_e)
    for v in violations:
        print(f'{v.vision}: {v.move_a} vs {v.move_b} delta_e={v.delta_e:.2f}'
              f' < {args.min_delta_e}')
    return 1 if violations else 0


if __name__ == '__main__':
    sys.exit(main())
