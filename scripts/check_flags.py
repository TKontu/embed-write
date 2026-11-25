#!/usr/bin/env python3
"""Fail when an enabled flag's gate has not passed (X-02, invariant I6).

Usage: python3 scripts/check_flags.py [--flags PATH] [--registry PATH] [--root DIR]
Exit 0 ok, 1 violation, 2 schema error. Run by nightly CI and tests/test_check_flags.py.
"""

import argparse
import sys
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from experiments.gates.flags import DEFAULT_PATH as FLAGS_PATH  # noqa: E402
from experiments.gates.flags import FlagError, check, load_flags  # noqa: E402
from experiments.gates.registry import DEFAULT_PATH as REGISTRY_PATH  # noqa: E402
from experiments.gates.registry import REPO_ROOT, RegistryError, load_registry  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--flags", type=Path, default=FLAGS_PATH)
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH)
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="resolves result_doc paths")
    args = parser.parse_args(argv)
    try:
        gates = load_registry(args.registry, root=args.root)
        flags = load_flags(args.flags, gates)
    except (FlagError, RegistryError, tomllib.TOMLDecodeError, OSError) as exc:
        print(f"check_flags: schema error: {exc}", file=sys.stderr)
        return 2
    violations = check(flags, gates)
    for message in violations:
        print(f"check_flags: {message}", file=sys.stderr)
    if violations:
        return 1
    print(f"check_flags: ok ({len(flags)} flags, {sum(f.enabled for f in flags)} enabled)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
