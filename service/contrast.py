"""LG-04 contrast floor: tinted text stays above a contrast ratio per theme.

Pure stdlib. A move's tint is composited over each theme's background at a
given alpha; the theme's text colour must keep at least MIN_CONTRAST against
the result (WCAG 2.x relative luminance and contrast ratio).

Unwired by design: the production caller is the overlay theme build
(RE-04/LG-05), which will supply real themes, palette and alpha. No colours
are chosen here.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Mapping

from service.palette import _to_linear, parse_hex

# Provisional: WCAG AA body text. The expert may revise under G-09.
MIN_CONTRAST = 4.5


@dataclass(frozen=True)
class Shortfall:
    theme: str
    move: str
    ratio: float


def relative_luminance(rgb):
    """WCAG 2.x relative luminance of (r, g, b) ints 0..255."""
    r, g, b = (_to_linear(c / 255.0) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg, bg):
    """WCAG contrast ratio of two rgb tuples, in [1, 21]; symmetric."""
    a, b = relative_luminance(fg), relative_luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def blend(tint_rgb, bg_rgb, alpha):
    """Composite tint over bg in sRGB space at alpha in [0, 1]; rounded ints."""
    if not isinstance(alpha, (int, float)) or isinstance(alpha, bool) \
            or not 0.0 <= alpha <= 1.0:
        raise ValueError(f'alpha {alpha!r} outside [0, 1]')
    return tuple(int(round(alpha * t + (1.0 - alpha) * b))
                 for t, b in zip(tint_rgb, bg_rgb))


def check(themes: Mapping[str, Mapping[str, str]], palette: Mapping[str, str],
          alpha: float, min_ratio=MIN_CONTRAST):
    """Shortfalls (sorted by theme, then move) below min_ratio; empty = pass."""
    blend((0, 0, 0), (0, 0, 0), alpha)  # validate alpha even if palette is empty
    out = []
    for theme in sorted(themes):
        spec = themes[theme]
        text, bg = parse_hex(spec['text']), parse_hex(spec['background'])
        for move in sorted(palette):
            ratio = contrast_ratio(text, blend(parse_hex(palette[move]), bg, alpha))
            if ratio < min_ratio:
                out.append(Shortfall(theme, move, ratio))
    return tuple(out)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='python3 -m service.contrast')
    parser.add_argument('spec', help='JSON {"alpha", "themes", "palette"}')
    parser.add_argument('--min-ratio', type=float, default=MIN_CONTRAST)
    args = parser.parse_args(argv)
    try:
        with open(args.spec, encoding='utf-8') as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError('spec must be a JSON object')
        themes, palette = data['themes'], data['palette']
        if not isinstance(themes, dict) or not isinstance(palette, dict) \
                or not all(isinstance(t, dict) for t in themes.values()):
            raise ValueError('themes and palette must be JSON objects')
        shortfalls = check(themes, palette, data['alpha'], args.min_ratio)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'malformed spec: {exc}', file=sys.stderr)
        return 2
    for s in shortfalls:
        print(f'{s.theme}: {s.move} ratio={s.ratio:.2f} < {args.min_ratio}')
    return 1 if shortfalls else 0


if __name__ == '__main__':
    sys.exit(main())
