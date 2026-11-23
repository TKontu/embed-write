"""Signal gate check (SF-04, invariant I6: signals default off until their gate passes).

Every registered signal kind gets exactly one flag, default ``enabled=False``,
bound to the kind's gates. A flag may be enabled only when all of its gates
have passed.

Pass marker: a gate ``G-XX`` has passed only if ``experiments/results/G-XX.md``
exists and the first non-blank line of its ``## Verdict`` section starts with
the word ``passed`` (case-insensitive), as laid out in
``experiments/results/TEMPLATE.md``. A missing file, a missing Verdict section,
or any other verdict means not passed.

CLI: ``python3 -m analysis.signal_gates [--results DIR]`` checks the default
flag state of all registered kinds; exits 0 clean, 1 violations, 2 bad input.
Editor/runtime wiring is absent by design until the live layers land.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from analysis.signals import SignalKind, registered_kinds

DEFAULT_RESULTS_DIR = Path(__file__).resolve().parent.parent / "experiments" / "results"
_GATE_RE = re.compile(r"^G-\d{2,}$")


@dataclass(frozen=True)
class SignalFlag:
    kind: str
    gates: tuple[str, ...]
    enabled: bool = False


def default_flags(kinds: Iterable[SignalKind] | None = None) -> dict[str, SignalFlag]:
    """One flag per registered kind, all off, bound to the kind's gates."""
    kinds = registered_kinds() if kinds is None else tuple(kinds)
    return {k.name: SignalFlag(k.name, tuple(k.gate), False) for k in kinds}


def check(
    flags: dict[str, SignalFlag],
    passed_gates: Iterable[str],
    kinds: Iterable[SignalKind] | None = None,
) -> list[str]:
    """Return violation messages; empty list means clean."""
    kinds = registered_kinds() if kinds is None else tuple(kinds)
    passed = set(passed_gates)
    by_name = {k.name: k for k in kinds}
    violations: list[str] = []
    for name, kind in by_name.items():
        flag = flags.get(name)
        if flag is None:
            violations.append(f"registered kind {name!r} has no flag")
            continue
        if flag.enabled:
            missing = [g for g in kind.gate if g not in passed]
            if missing:
                violations.append(
                    f"flag {name!r} enabled but gate(s) {missing} have not passed"
                )
    for name in flags:
        if name not in by_name:
            violations.append(f"flag {name!r} is for an unregistered kind")
    return violations


def gate_passed(path: Path) -> bool:
    """True iff ``path`` exists and its Verdict section starts with ``passed``."""
    if not path.is_file():
        return False
    in_verdict = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            if in_verdict:
                return False
            in_verdict = stripped[3:].strip().lower() == "verdict"
            continue
        if in_verdict and stripped:
            return re.match(r"passed\b", stripped, re.IGNORECASE) is not None
    return False


def passed_gates(gates: Iterable[str], results_dir: Path = DEFAULT_RESULTS_DIR) -> set[str]:
    out = set()
    for g in gates:
        if not _GATE_RE.match(g):
            raise ValueError(f"malformed gate id {g!r}")
        if gate_passed(Path(results_dir) / f"{g}.md"):
            out.add(g)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m analysis.signal_gates")
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS_DIR)
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return 0 if e.code == 0 else 2
    if not args.results.is_dir():
        print(f"error: results dir {args.results} not found", file=sys.stderr)
        return 2
    kinds = registered_kinds()
    if not kinds:
        print("error: no registered signal kinds", file=sys.stderr)
        return 2
    all_gates = sorted({g for k in kinds for g in k.gate})
    try:
        passed = passed_gates(all_gates, args.results)
    except (ValueError, OSError, UnicodeDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    violations = check(default_flags(kinds), passed, kinds)
    for v in violations:
        print(f"violation: {v}")
    print(
        f"signal gates: {len(kinds)} kinds, {len(all_gates)} gates, "
        f"{len(passed)} passed, {len(violations)} violation(s)"
    )
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
