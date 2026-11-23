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
