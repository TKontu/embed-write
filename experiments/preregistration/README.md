# Gate pre-registration

Before a gate runs, save its record as `<gate>.json` in this directory. Only the
expert fills `confirmed_by`; confirming a threshold is an [H] act. Agents must
not create confirmations. A confirmed record is fixed (architecture §6):
the tool never overwrites or changes it. If a record is wrong, the expert deletes
it by hand before any run, then confirms again.

Command: the expert writes a record with
`python -m experiments.preregistration confirm GATE --threshold TEXT --metric TEXT --confirmed-by NAME [--root DIR] [--recorded-commit REF]`.
It sets `confirmed_at` to the current UTC time, writes `ROOT/GATE.json` atomically, re-validates it
with `load` and prints `wrote PATH`. It refuses to overwrite an existing record (exit 1) and
rejects a blank name or bad gate id (exit 2). Only the expert runs it.

Record fields:

| Field | Format |
| --- | --- |
| `gate` | Nonempty gate ID matching the filename and requested gate, e.g. `G-01` |
| `threshold` | Nonempty text describing the confirmed threshold |
| `metric` | Nonempty text naming the metric |
| `confirmed_by` | Nonempty expert identity, filled only by the expert |
| `confirmed_at` | ISO 8601 UTC date-time, with `Z` or `+00:00` offset |
| `recorded_commit` | Optional nonempty commit reference text |

`load(gate, root=...)` and `require_confirmed(gate, root=...)` return the validated
record or raise `PreregistrationError` for missing, malformed, mismatched or
unconfirmed records. `root` is the directory containing the JSON files; by default
it is this directory, independent of the working directory. Gate IDs use letters,
digits, underscores and hyphens.

`runner.run_gate(..., preregistration_root=...)` checks the record before invoking
the gate and copies it into the run manifest under `preregistration`. Only the
synthetic `sample` gate is exempt, through the runner's explicit `exempt` tuple.
There is no caller-supplied bypass. Unit tests use synthetic records in temporary
directories; they are not expert confirmations or real gate evidence.

Validation checks the supplied metadata, not the identity of its author. Keep the
confirmed record under version control for review. Production gate modules remain
unwired until the G-01 run (todo-01, X-00); these checks do not mark any gate passed.
