"""Literal support check (VF-03): numbers, units and source links preserved by a proposal.

``extract_support`` collects support tokens from a passage; ``support_diff`` reports which tokens a
candidate dropped or introduced relative to the original. Pure reporting: no score, no threshold,
no combination with other verification axes (that is VF-10).

Token forms (strings in a ``Counter``):

- ``num:<value>`` or ``num:<value> <unit>`` / ``num:<value>%`` -- a number, with its directly
  following unit kept as one token. Thousands separators are removed (``1,000`` -> ``1000``), a
  leading ``+`` is dropped, the Unicode minus becomes ``-``, and ``5kg`` equals ``5 kg``. A currency
  symbol (``€``, ``$``, ``£``) directly before the number, with at most one space and after any sign,
  is its unit: ``$5``, ``$ 5`` and ``5 $`` all give ``num:5 $``; ``-$3`` gives ``num:-3 $``. A
  currency symbol not adjacent to a number is ignored.
- ``link:<url>`` -- a Markdown link target ``[x](url)`` or a bare http(s) URL.
- ``cite:<key>`` -- a citation key ``[@key]`` (each key of ``[@a; @b]``).

Links are removed before numbers are scanned, so digits inside URLs are not counted twice.

Unwired by design until VF-07 (the verification panel) calls it. Residuals: the "still entailed"
path (a paraphrased number such as "five" vs "5", or a converted unit) is not handled and waits for
VF-02/G-08; the unit vocabulary is the fixed ``UNITS`` list, and ISO currency codes (``USD``,
``EUR``) are not units. Linear in text length; one passage pair.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

UNITS = (
    "°C", "°F", "K",
    "km", "m", "cm", "mm", "µm", "nm", "mi", "ft", "in",
    "kg", "g", "mg", "µg", "t", "lb", "oz",
    "l", "L", "ml", "mL",
    "h", "min", "s", "ms", "µs", "ns",
    "Hz", "kHz", "MHz", "GHz",
    "B", "KB", "kB", "MB", "GB", "TB",
    "W", "kW", "MW", "kWh", "V", "A", "mA", "J", "kJ", "N", "Pa", "kPa", "bar",
    "€", "$", "£",
)

_MD_LINK = re.compile(r"\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_CITE = re.compile(r"\[(@[^\]]+)\]")
_CITE_KEY = re.compile(r"@([\w:.#$%&+?<>~/-]*\w)")
_URL = re.compile(r"https?://[^\s<>()\[\]]*[^\s<>()\[\].,;:!?\"']")
_UNIT_ALT = "|".join(re.escape(u) for u in sorted(UNITS, key=len, reverse=True))
_CURRENCY_ALT = "€|\\$|£"
_NUMBER = re.compile(
    r"(?<![\w.,])([+\-−]?)(?:(" + _CURRENCY_ALT + r")\s?)?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?"
    r"(?:\s?(%)|\s?(" + _UNIT_ALT + r")(?![\w]))?"
)


def extract_support(text: str) -> Counter:
    """Return a Counter of support tokens (see module docstring) found in ``text``."""
    tokens: Counter = Counter()

    def link(url):
        tokens["link:" + url] += 1
        return " "

    def cite(match):
        for key in _CITE_KEY.findall(match.group(1)):
            tokens["cite:" + key] += 1
        return " "

    rest = _MD_LINK.sub(lambda m: link(m.group(1)), text)
    rest = _CITE.sub(cite, rest)
    rest = _URL.sub(lambda m: link(m.group(0)), rest)
    for sign, lead, whole, frac, pct, unit in _NUMBER.findall(rest):
        value = ("-" if sign in ("-", "−") else "") + whole.replace(",", "") + frac
        if lead:
            value += " " + lead
        elif pct:
            value += "%"
        elif unit:
            value += " " + unit
        tokens["num:" + value] += 1
    return tokens


@dataclass(frozen=True)
class SupportDiff:
    """Support tokens lost (``missing``) and introduced (``added``), with multiplicity."""

    missing: Counter
    added: Counter

    @property
    def preserved(self) -> bool:
        return not self.missing and not self.added


def support_diff(original: str, candidate: str) -> SupportDiff:
    """Compare the support tokens of ``original`` and ``candidate``; reporting only."""
    before, after = extract_support(original), extract_support(candidate)
    return SupportDiff(missing=before - after, added=after - before)
