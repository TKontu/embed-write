"""Deterministic local quantity matching (SP-04).

Unwired by design until SP-05 emits the signal behind the G-07 flag. This
checks numeric agreement, not entailment or which entity a quantity describes.
Only the explicit unit table is recognized; unknown units remain unitless.
Years use 365 days (not calendar arithmetic); currencies never cross-convert.
Scientific notation, ranges, compound units and locale inference are outside
this small grammar. Commas with three following digits denote thousands;
other decimal commas denote decimals. Spaces group exactly three digits.
"""
from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Quantity:
    value: float
    unit: str | None
    dimension: str | None
    span: tuple[int, int]
    text: str


@dataclass
class ConsistencyReport:
    supported: list[tuple[Quantity, Quantity]]
    unsupported: list[Quantity]

    @property
    def ok(self) -> bool:
        return not self.unsupported


# alias -> canonical unit, dimension, multiplier. Symbols are case-sensitive:
# M means million whereas m means metres.
_UNITS = {
    'mm': ('m', 'length', .001), 'cm': ('m', 'length', .01),
    'm': ('m', 'length', 1), 'km': ('m', 'length', 1000),
    'mg': ('g', 'mass', .001), 'g': ('g', 'mass', 1),
    'kg': ('g', 'mass', 1000), 't': ('g', 'mass', 1e6),
    'tonne': ('g', 'mass', 1e6),
    's': ('s', 'time', 1), 'min': ('s', 'time', 60),
    'h': ('s', 'time', 3600), 'day': ('s', 'time', 86400),
    'days': ('s', 'time', 86400), 'year': ('s', 'time', 31536000),
    'years': ('s', 'time', 31536000),
    '%': ('%', 'percent', 1), 'percent': ('%', 'percent', 1),
    'per cent': ('%', 'percent', 1),
    'pp': ('pp', 'percentage_points', 1),
    'percentage points': ('pp', 'percentage_points', 1),
    'EUR': ('EUR', 'currency:EUR', 1), '€': ('EUR', 'currency:EUR', 1),
    'USD': ('USD', 'currency:USD', 1), '$': ('USD', 'currency:USD', 1),
}
_SCALES = {'thousand': 1e3, 'million': 1e6, 'billion': 1e9,
           'k': 1e3, 'M': 1e6, 'bn': 1e9}
_SPACE = r'[ \t\u00a0]'
_UNIT_PATTERN = '|'.join(re.escape(u).replace(r'\ ', _SPACE + '+')
                         for u in sorted(_UNITS, key=len, reverse=True))
_NUMBER = (
    r'[+-]?(?:'
    r'[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?'
    r'|[0-9]{1,3}(?:[ \u00a0][0-9]{3})+(?:\.[0-9]+)?'
    r'|[0-9]+[.,][0-9]+|\.[0-9]+|[0-9]+)'
)
_QUANTITY = re.compile(
    rf'(?<![\w.,])(?:(?P<prefix_sign>[+-]?)(?P<prefix>EUR|USD|€|\$){_SPACE}*)?'
    rf'(?P<number>{_NUMBER})'
    rf'(?:{_SPACE}*(?P<scale>{"|".join(_SCALES)})(?!\w))?'
    rf'(?(prefix)|(?:{_SPACE}*(?P<unit>{_UNIT_PATTERN})(?!\w))?)'
    r'(?!\w)'
)


def extract_quantities(text: str) -> list[Quantity]:
    """Extract canonical quantities with half-open spans in the original text.

    Raises ValueError for quantities beyond the finite float range. Whitespace
    between tokens is horizontal only, so a unit on the next line is separate.
    """
    quantities = []
    for match in _QUANTITY.finditer(text):
        number = match['number'].replace(' ', '').replace('\u00a0', '')
        if re.fullmatch(r'[+-]?[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?', number):
            number = number.replace(',', '')
        else:
            number = number.replace(',', '.')
        value = float(number) * _SCALES.get(match['scale'], 1)
        if match['prefix_sign'] == '-':
            value = -value
        alias = match['prefix'] or match['unit']
        if alias:
            alias = ' '.join(alias.split())
            unit, dimension, multiplier = _UNITS[alias]
            value *= multiplier
        else:
            unit = dimension = None
        if not math.isfinite(value):
            raise ValueError('quantity exceeds finite float range')
        quantities.append(Quantity(value, unit, dimension, match.span(), match[0]))
    return quantities


def check_consistency(
    claim: str, sources: Iterable[str], rel_tol: float = 0.005, abs_tol: float = 0.0,
) -> ConsistencyReport:
    """Pair each claim quantity with the first matching source quantity.

    Sources are consumed one at a time. Memory is bounded by claim quantities
    plus quantities in the current source, not by the corpus or source iterator.
    Evidence may support multiple occurrences; output preserves claim order.
    """
    if any(not math.isfinite(t) or t < 0 for t in (rel_tol, abs_tol)):
        raise ValueError('tolerances must be finite and non-negative')
    claims = extract_quantities(claim)
    matches: dict[int, Quantity] = {}
    for source in sources:
        if len(matches) == len(claims):
            break
        for evidence in extract_quantities(source):
            for index, quantity in enumerate(claims):
                if index not in matches and quantity.dimension == evidence.dimension:
                    if math.isclose(quantity.value, evidence.value,
                                    rel_tol=rel_tol, abs_tol=abs_tol):
                        matches[index] = evidence
    return ConsistencyReport(
        [(q, matches[i]) for i, q in enumerate(claims) if i in matches],
        [q for i, q in enumerate(claims) if i not in matches],
    )
