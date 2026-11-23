# Semantic Text Workbench agent contract

Canonical guide for every development agent. Vendor files (`CLAUDE.md`) point here and must not
duplicate it.

## Authority and context

- `docs/architecture.md` is the authoritative target. `docs/todo.md` is the sole plan/status
  registry; the subsystem file it links (`docs/todo-NN-*.md`) holds the task detail and its check.
  A handoff, prompt or summary never substitutes for those sources.
- Progressive disclosure: read the assigned row and its subsystem section, then the architecture
  sections the assignment names. Read the whole architecture only for a cross-cutting change or an
  unresolved conflict.
- Observed state first: probe the repository, PRs and running lanes before acting. Handoffs and
  memory are dated records, not facts.
- Task markers: `[A]` agent-executable with a mechanical check; `[H]` needs the expert's judgment;
  `[A→H]` the agent prepares, the expert decides. Never decide an `[H]` item or act as a judge in a
  gate. Product code for a gated capability stays behind its flag until the gate reads `passed`.

## Development loop

The Reconcile-loop protocol runs this project (`SPEC.md`, `.agent/commands/`, `.agent/config.toml`).

The planner owns selection, dependencies, assignment, shared resources and reconciliation. Executors
own only assigned code/records and work in isolated checkouts at the pinned base. Preserve unrelated
work; never force-push. Return target/scope conflicts to planning; make routine authorized choices.

For behavior changes show the intended failing test, implement the smallest fix and run targeted
checks. Run the configured gate once before the PR. A skipped check is not a pass. Review relevant
callers, data boundaries and scale.

- **Procedures:** use the `tdd`, `debug` and `verify` skills; run `/lint-fix` once the stack has a
  linter. Run the packet's premise checks before any code.
- **Done means seen:** a behaviour row is done only with `seen: <run id or artifact path>`. Merged
  but never exercised (flag off, gate not run) stays partial and names the run that will show it.
  A gate is `passed` only with its `experiments/results/G-XX.md` from an actual run.
- **Connections:** a new public symbol names its production caller, or is "unwired by design"
  with the row that wires it.
- **Scale:** loops over the corpus or its embeddings bound memory (stream, never hold the corpus),
  batch sizes and transaction size (LMDB/SQLite commits), or record the untested bound as a
  residual.
- **Private data is absent from fresh checkouts:** the corpus, annotations, models and `.env` are
  gitignored. A packet names where each comes from; a check skipped for lack of them is reported
  as skipped. Green CI does not mean the local-model path was exercised.
- **Who judged what:** say "expert" only for the expert's own judgment; anything a model produced
  is "LLM-built". Quote a figure only with its basis: population, metric, reference and who built
  it.
- **Flags have a lifecycle:** each flag names the gate that removes it; a shortcut is recorded as
  debt with its follow-up row.

Before publication inspect the diff for defects, secrets and private material. Corpus documents,
expert annotations and the edit log are private: they stay gitignored and are never quoted in PRs,
commits or handoffs. PRs record assignment identity, head, actual verification and residuals. The
designated reviewer checks the current head and merge authority; executors do not self-merge.

After integration, verify combined state, reconcile observed outcomes into `docs/todo.md` and the
subsystem file, and write a bounded `HANDOFF.md` (`templates/handoff.md`). Start the next round with
fresh context only after reconciliation closes the previous one. No conversation is project memory.

Architecture changes need a recorded decision in `docs/decisions.md`; never smuggle a design change
through implementation.

## Unattended rounds

`scripts/round_supervisor.py` runs one fresh Claude session per round inside Herdr; see
`.agent/supervisor.md`. A supervised orchestrator ends its round with
`python3 scripts/round_supervisor.py complete --outcome continue`, which refuses until
`HANDOFF.md` is fresh and valid. `/loop-manager` starts a session that watches the loop.
