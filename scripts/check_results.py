#!/usr/bin/env python3
"""Lint the result template and every gate result report (X-03).

Lints experiments/results/TEMPLATE.md with --template, the result_doc of each registry gate
whose status is passed or failed (when the file exists), and any experiments/results/G-*.md.
Usage: python3 scripts/check_results.py [--registry PATH] [--root DIR]
Exit 0 ok, 1 lint problems, 2 registry schema error. Run by nightly CI and
tests/test_check_results.py.
"""

import argparse
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.gates.registry import DEFAULT_PATH as REGISTRY_PATH  # noqa: E402
from experiments.gates.registry import REPO_ROOT, RegistryError, load_registry  # noqa: E402
from scripts.lint_result import lint  # noqa: E402


def targets(gates, root):
    docs = {root / g.result_doc for g in gates if g.status in {"passed", "failed"}}
    docs = {p for p in docs if p.is_file()}
    docs.update((root / "experiments" / "results").glob("G-*.md"))
    return sorted(docs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="resolves result_doc paths")
    args = parser.parse_args(argv)
    try:
        gates = load_registry(args.registry, root=args.root)
    except (RegistryError, tomllib.TOMLDecodeError, OSError) as exc:
        print(f"check_results: schema error: {exc}", file=sys.stderr)
        return 2
    checks = [(args.root / "experiments" / "results" / "TEMPLATE.md", True)]
    checks += [(path, False) for path in targets(gates, args.root)]
    failed = False
    for path, template in checks:
        try:
            problems = lint(path.read_text(encoding="utf-8"), template)
        except OSError as exc:
            problems = [f"cannot read: {exc.strerror}"]
        for problem in problems:
            print(f"check_results: {path}: {problem}")
        failed = failed or bool(problems)
        if not problems:
            print(f"check_results: ok {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
