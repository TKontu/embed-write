#!/usr/bin/env python3
"""Check literal level comparisons and imports of known raw similarity APIs.

This deliberately bounded AST check does not infer variable levels, resolve
aliases, or detect arithmetic on .values. Import checking covers the named raw
APIs below, not arbitrary user-defined similarity functions. CI wiring is deferred.
"""

import argparse
import ast
from pathlib import Path


RAW_MODULES = {'scipy.spatial.distance', 'sklearn.metrics.pairwise'}
RAW_NAMES = {'cosine', 'cosine_similarity', 'cosine_distances', 'dot',
             'vdot', 'inner', 'pairwise_distances', 'cdist', 'pdist'}
LEVELS = {'SENTENCE', 'BLOCK', 'SECTION'}


def _name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _level(node):
    if not isinstance(node, ast.Call) or _name(node.func) != 'LevelVector':
        return None
    level = node.args[0] if node.args else next(
        (kw.value for kw in node.keywords if kw.arg == 'level'), None)
    if (isinstance(level, ast.Attribute) and _name(level.value) == 'Level'
            and level.attr in LEVELS):
        return level.attr
    return None


def findings(source, filename):
    """Yield (line, message) findings for one source file."""
    for node in ast.walk(ast.parse(source, filename=filename)):
        if isinstance(node, ast.Call) and _name(node.func) in {'cosine', 'dot'}:
            args = list(node.args[:2])
            for name in ('a', 'b')[len(args):]:
                args.append(next((kw.value for kw in node.keywords if kw.arg == name), None))
            left, right = map(_level, args)
            if left and right and left != right:
                yield node.lineno, f'cross-level comparison: {left} vs {right}'
        if isinstance(node, ast.Import):
            if any(alias.name in RAW_MODULES for alias in node.names):
                yield node.lineno, 'raw-vector similarity import; use service.vectors'
        if isinstance(node, ast.ImportFrom):
            module = node.module or ''
            if module != 'service.vectors' and (
                module in RAW_MODULES
                or any(f'{module}.{alias.name}' in RAW_MODULES for alias in node.names)
                or any(alias.name in RAW_NAMES for alias in node.names)
                or (module in {'numpy', 'scipy', 'sklearn.metrics', 'torch'}
                    and any(alias.name == '*' for alias in node.names))
            ):
                yield node.lineno, 'raw-vector similarity import; use service.vectors'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths', nargs='+', type=Path)
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
