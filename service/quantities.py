"""Number-and-unit extraction from report text (SR-04).

``extract_quantities(text)`` returns frozen ``Quantity`` records in text order, for matching
generated sentences against source items. Unwired by design until SR-02/AD-05.

Rules:

* Decimals use "." or ",". A comma (or space / no-break space) followed by exactly three digits
  after a 1-3 digit leading group is a thousands separator, so the ambiguous "1,234" is 1234;
  "3,5" and "1,2345" are decimals. Mixed European "1.234,5" is not supported.
* Signs "+", "-" and "−" are accepted where they do not follow a word character.
* Ranges: "5–10 mm", "5-10 mm", "5 to 10 mm", "from 5 to 10 mm"; a unit written once is
  shared. Ranges whose two units differ are emitted as two values.
* Tolerances: "12 ± 0.5 kg", "12 +/- 0.5 kg", "12 kg ± 4 %". A percent tolerance on a non-percent
  base is relative to the value.
* Units are canonicalised via ``UNIT_ALIASES`` plus ``service.support_check.UNITS``. No conversion
  between units or scales (mm and m stay different).
* Bare URLs, Markdown link targets, ISO dates (YYYY-MM-DD) and times of day (HH:MM) are masked
  out. Spelled-out numbers and other date formats are not handled.

Local only (I9); one passage, regex scan linear in text length.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from service.support_check import UNITS

UNIT_ALIASES = {
    "millimetres": "mm", "millimetre": "mm", "millimeters": "mm", "millimeter": "mm",
    "° C": "°C", "degC": "°C", "deg C": "°C",
    "percent": "%", "per cent": "%",
    "kilograms": "kg", "kilogram": "kg",
    "hours": "h", "hour": "h", "hrs": "h", "hr": "h",
}
_CANON = {u: u for u in (*UNITS, "%")}
_CANON.update(UNIT_ALIASES)
_UNIT = "|".join(re.escape(u) for u in sorted(_CANON, key=len, reverse=True))

_NUM = r"(?:\d{1,3}(?:[,   ]\d{3})+(?!\d)|\d+)(?:[.,]\d+)?(?![.,]\d)"
_SIGNED = r"[+\-−]?" + _NUM
_U = r"(?:\s?(?:" + _UNIT + r")(?!\w))"

_PATTERN = re.compile(
    r"(?<![\w.,])(?P<from>from\s+)?(?P<a>" + _SIGNED + r")(?P<ua>" + _U + r")?"
    r"(?:\s*(?P<rsep>–|—|-|\bto\b)\s*(?P<b>" + _SIGNED.replace(r"[+\-−]?", r"[+−]?", 1) + r")"
    r"(?P<ub>" + _U + r")?"
    r"|\s*(?P<tsep>±|\+/-|\+-)\s*(?P<t>" + _NUM + r")(?P<ut>" + _U + r")?)?"
)

_URL = re.compile(r"https?://\S+|www\.\S+")
_MD_TARGET = re.compile(r"\]\(([^)]*)\)")
_DATE_TIME = re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}:\d{2}(?::\d{2})?\b")


@dataclass(frozen=True)
class Quantity:
    value: float
    low: float
    high: float
    unit: str | None
    kind: str
    span: tuple[int, int]
    text: str


def _num(s: str) -> float:
    s = s.replace("−", "-")
    s = re.sub(r"(?<=\d)[,   ](?=\d{3}(?!\d))", "", s)
    return float(s.replace(",", "."))


def _unit(s: str | None) -> str | None:
    return None if s is None else _CANON[s.strip()]


def _mask(text: str) -> str:
    chars = list(text)

    def blank(start: int, end: int) -> None:
        chars[start:end] = " " * (end - start)

    for m in _MD_TARGET.finditer(text):
        blank(*m.span(1))
    for m in _URL.finditer("".join(chars)):
        blank(*m.span())
    for m in _DATE_TIME.finditer("".join(chars)):
        blank(*m.span())
    return "".join(chars)


def extract_quantities(text: str) -> tuple[Quantity, ...]:
    """Return quantities found in ``text`` in text order (see module docstring)."""
    out: list[Quantity] = []
    for m in _PATTERN.finditer(_mask(text)):
        a = _num(m["a"])
        ua, ub = _unit(m["ua"]), _unit(m["ub"])

        def q(value, low, high, unit, kind, start, end):
            out.append(Quantity(value, low, high, unit, kind, (start, end), text[start:end]))

        if m["b"] is not None:
            if ua is not None and ub is not None and ua != ub:
                q(a, a, a, ua, "value", m.start("a"), m.end("ua"))
                b = _num(m["b"])
                q(b, b, b, ub, "value", m.start("b"), m.end("ub"))
                continue
            b = _num(m["b"])
            lo, hi = min(a, b), max(a, b)
            q(lo, lo, hi, ua or ub, "range", m.start(), m.end())
        elif m["t"] is not None:
            t = _num(m["t"])
            ut = _unit(m["ut"])
            if ut == "%" and ua != "%":
                unit = ua
                half = abs(a) * t / 100
            else:
                unit = ua or ut
                half = t
            q(a, a - half, a + half, unit, "tolerance", m.start(), m.end())
        else:
            q(a, a, a, ua, "value", m.start("a"), m.end())
    return tuple(out)
