#!/usr/bin/env python3
"""Flag score-combining code in the verification-axis modules (VF-10).

Verification is a panel of separate checks, never one score. This bounded,
per-file AST check reports:

1. Any function/class name, argument, variable (Name), attribute or string
   dict key whose name matches, case-insensitively,
   (aggregate|overall|combined|composite|total)_?score, score_?(sum|total|mean|avg)
   or weighted_(sum|score).
2. A call whose callee's final name is sum, mean, fmean or average (covers
   sum(), statistics.mean/fmean, numpy mean/average and their bare imports)
   when its arguments contain two or more distinct names (Name ids or
   attribute names) ending in `score` or `_result`.

Not detected: combining via operators (a_score + b_score), via other
functions or loops, through aliases or renamed imports, names built at run
time, or any dataflow (a combined value held under a neutral name). A single
axis name such as `support_score` is not flagged. Run nightly by .github/workflows/nightly.yml.
"""

import argparse
import ast
import re
from pathlib import Path


DEFAULT_TARGETS = ('service/support_check.py', 'service/length_delta.py',
                   'service/number_check.py', 'service/verify_panel.py')
NAME_RE = re.compile(r'(aggregate|overall|combined|composite|total)_?score'
                     r'|score_?(sum|total|mean|avg)|weighted_(sum|score)', re.I)
COMBINERS = {'sum', 'mean', 'fmean', 'average'}


def _name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _names(node):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        yield node.name
    elif isinstance(node, ast.arg):
        yield node.arg
    elif isinstance(node, (ast.Name, ast.Attribute)):
        yield _name(node)
    elif isinstance(node, ast.Dict):
        for key in node.keys:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                yield key.value


def findings(source, filename):
    """Yield sorted, unique (line, message) findings for one source file."""
    found = set()
    for node in ast.walk(ast.parse(source, filename=filename)):
        for name in _names(node):
            if name and NAME_RE.search(name):
                found.add((node.lineno, f'aggregate-score name: {name}'))
        if isinstance(node, ast.Call) and _name(node.func) in COMBINERS:
            axes = {_name(sub) for arg in [*node.args, *(k.value for k in node.keywords)]
                    for sub in ast.walk(arg)}
            axes = sorted(n for n in axes if n and (n.endswith('score') or n.endswith('_result')))
            if len(axes) >= 2:
                found.add((node.lineno,
                           f'{_name(node.func)}() combines axes: {", ".join(axes)}'))
    return sorted(found)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('paths', nargs='*', type=Path,
                        default=[Path(p) for p in DEFAULT_TARGETS])
    args = parser.parse_args()
    failed = False
    for path in args.paths:
        files = sorted(path.rglob('*.py')) if path.is_dir() else [path]
        for file in files:
            try:
                for line, message in findings(file.read_text(encoding='utf-8'), str(file)):
                    print(f'{file}:{line}: {message}')
                    failed = True
            except (OSError, UnicodeError, SyntaxError) as error:
                print(f'{file}:{getattr(error, "lineno", 1)}: {error}')
                failed = True
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
