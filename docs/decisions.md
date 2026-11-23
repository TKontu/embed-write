# Decisions

Append-only record of operator rulings and architecture decisions.

## D-001 — Executor lanes run on Codex (2026-11-23, operator)

- **Ruling:** supervised rounds run executor lanes on Codex whenever possible. Planning,
  independent review and merge decisions stay in Claude. A lane falls back to Claude only when
  Codex cannot run, with the reason recorded in that round's HANDOFF.md.
- **Launch:** `codex exec --approve-for-me -C <lane worktree> "<task>"` in the lane's Herdr tab.
- **Why this form:** this host does not allow unprivileged user namespaces, so Codex's
  `-s workspace-write` sandbox (bwrap) fails every shell command with
  `bwrap: No permissions to create a new namespace`. `--approve-for-me` routes each approval to
  Codex's automatic reviewer, which can approve running outside the sandbox; it is the mode the
  iknosreview loop uses. `--full-auto` no longer exists in codex 0.166. Verified 2026-11-23 with a
  probe that writes a file: `-s workspace-write` failed, `--approve-for-me` succeeded.
- **Carried in:** the round prompt in `scripts/round_supervisor.py`.

## D-002 — Standing merge delegation to the planner (2026-11-23, operator)

- **Ruling:** the loop must not wait on the operator for routine merges. The round planner merges
  any PR whose current head passed independent review (`/review-round`), passed the configured
  gate, and is mergeable, following `/merge-round`.
- **Still the operator's:** PRs that change `docs/decisions.md`, `docs/architecture.md` or
  `.agent/config.toml`; PRs that decide an `[H]` item or the `[H]` half of an `[A→H]` item; and
  PRs that mark a gate `passed`. Executors never merge their own work.
- **Why:** with `merge_authority` reserved to the operator, every round parked its approved PRs,
  main stopped moving, and the supervisor halted with "main unchanged across 3 rounds"
  (2026-11-23, PRs #6 to #9 waiting).
- **Carried in:** `[policy] merge_authority` in `.agent/config.toml`.
- **Amendment (2026-11-23, operator):** `.claude/settings.json` denies raw `gh pr merge`, so the
  planner's merges were refused. Planners merge only through `scripts/merge_guard.py`, which is
  allowed. It checks the reviewed head, mergeability, the base branch and the operator-owned paths
  above, then merges with `--match-head-commit` and confirms the merge.
