#!/usr/bin/env python3
"""Lint gate result reports (experiments/results/G-XX.md) for required sections.

Usage: python3 scripts/lint_result.py [--template] FILE...

Outside --template mode the Numbers section must also state an interval as
"95% CI [lo, hi]" and one basis line (AGENTS.md "Who judged what"):

    Basis: population: <...>; metric: <...>; reference: <...>; built by: <expert | LLM>

Called by scripts/check_results.py (nightly CI) and tests/test_report.py.
"""

import argparse
import re
import sys
from pathlib import Path

REQUIRED = ("Hypothesis", "Threshold", "Method", "Numbers", "Verdict", "Fallback taken")
HEADING = re.compile(r"^##\s+(.+?)\s*#*\s*$")
PLACEHOLDER = re.compile(r"<[^<>\n]+>")
COMMENT = re.compile(r"<!--.*?-->", re.S)
SAMPLE_SIZE = re.compile(r"\bn\s*=\s*\d")
_NUM = r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"
INTERVAL = re.compile(rf"95% CI \[\s*{_NUM}\s*,\s*{_NUM}\s*\]")
BASIS_LINE = re.compile(r"^\s*(?:[-*]\s*)?basis:(.*)$", re.I | re.M)
BASIS_FIELDS = ("population", "metric", "reference", "built by")


def basis_problems(body):
    lines = BASIS_LINE.findall(body)
    if not lines:
        return ["Numbers section must state a basis line: Basis: population: ...; "
                "metric: ...; reference: ...; built by: ..."]
    fields = {}
    for part in lines[0].split(";"):
        key, sep, value = part.partition(":")
        if sep:
            fields[key.strip().lower()] = value.strip()
    return [f"basis line missing or empty field: {name}"
            for name in BASIS_FIELDS if not fields.get(name)]


def sections(text):
    found, current = {}, None
    for line in COMMENT.sub("", text).splitlines():
        match = HEADING.match(line)
        if match:
            current = match.group(1).strip().lower()
            found.setdefault(current, [])
        elif current is not None:
            found[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in found.items()}


def lint(text, template=False):
    problems, found = [], sections(text)
    for name in REQUIRED:
        body = found.get(name.lower())
        if body is None:
            problems.append(f"missing section: {name}")
        elif not body:
            problems.append(f"empty section: {name}")
        elif not template:
            if PLACEHOLDER.search(body):
                problems.append(f"placeholder left in section: {name}")
            elif name == "Numbers":
                if not SAMPLE_SIZE.search(body):
                    problems.append("Numbers section must state a sample size as n=<count>")
                if not INTERVAL.search(body):
                    problems.append("Numbers section must state an interval as 95% CI [lo, hi]")
                problems.extend(basis_problems(body))
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--template", action="store_true",
                        help="allow <...> placeholders (for TEMPLATE.md itself)")
    parser.add_argument("files", nargs="+", type=Path)
    args = parser.parse_args(argv)
    failed = False
    for path in args.files:
        try:
            problems = lint(path.read_text(encoding="utf-8"), args.template)
        except OSError as exc:
            problems = [f"cannot read: {exc.strerror}"]
        for problem in problems:
            print(f"{path}: {problem}")
        failed = failed or bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
