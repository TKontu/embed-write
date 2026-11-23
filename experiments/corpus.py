"""Streaming corpus loader: yields one Markdown document at a time in sorted path order.

Only the path list is held; file contents are read on demand. The directory is given at runtime
(the corpus is private and gitignored). Unwired by design until G-01 runs (row X-00).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass(frozen=True)
class Document:
    path: Path
    text: str


def iter_documents(root: str | os.PathLike, pattern: str = "*.md") -> Iterator[Document]:
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(f"corpus directory not found: {root}")
    paths = sorted(p for p in root.rglob(pattern) if p.is_file())
    for path in paths:
        yield Document(path=path, text=path.read_text(encoding="utf-8"))
