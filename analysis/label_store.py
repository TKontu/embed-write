"""DS-01 candidate label store: every slow-layer verdict kept as a candidate training label.

Append-only JSON Lines (UTF-8, one object per line). Records match the
analysis.label_precedence.resolve_labels candidate contract with source "slow_layer".

Unwired by design: LY-02 (analysis/slow_path.py) writes verdicts here and PT-01 reads them.
Residual: single writer only; no file locking and no rotation.
"""

import json
import math


def _require_str(name, value):
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty str")


class CandidateLabelStore:
    def __init__(self, path):
        self.path = path

    def append(self, node_id, label, model_version, timestamp):
        """Validate, then append one full line and flush. Nothing is written on ValueError."""
        _require_str("node_id", node_id)
        _require_str("label", label)
        _require_str("model_version", model_version)
        if (isinstance(timestamp, bool) or not isinstance(timestamp, (int, float))
                or not math.isfinite(timestamp)):
            raise ValueError("timestamp must be a finite int or float")
        record = {
            "node_id": node_id,
            "label": label,
            "source": "slow_layer",
            "model_version": model_version,
            "timestamp": timestamp,
        }
        line = json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n"
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line)
            fh.flush()

    def iter_candidates(self):
        """Yield stored records in file order, streaming line by line."""
        try:
            fh = open(self.path, encoding="utf-8")
        except FileNotFoundError:
            return
        with fh:
            for lineno, line in enumerate(fh, start=1):
                try:
                    if not line.endswith("\n"):
                        raise ValueError("truncated (no newline)")
                    record = json.loads(line)
                    if not isinstance(record, dict):
                        raise ValueError("not a JSON object")
                except ValueError as exc:
                    raise ValueError(f"{self.path}: line {lineno}: malformed record: {exc}") from None
                yield record
