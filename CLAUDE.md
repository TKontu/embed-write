# Claude entrypoint

Before any action, read and follow [`AGENTS.md`](AGENTS.md). It is the canonical agent contract.
Do not duplicate its rules here.

## Project Commands

Every command in `.claude/commands/` resolves its tooling from this table. No product stack exists
yet, so most keys are `n/a`; commands skip those steps and say so. Update when code lands.

<!-- claude:commands -->
| Key       | Command |
| --------- | ------- |
| install   | n/a |
| test      | uv run --no-project --with pytest python -m pytest -q tests |
| test-one  | uv run --no-project --with pytest python -m pytest -q {arg} |
| lint      | n/a |
| lint-fix  | n/a |
| format    | n/a |
| typecheck | n/a |
| run       | n/a |
| build     | n/a |
<!-- /claude:commands -->

## Commands and skills

- Round workflow: `/bootstrap`, `/takeoff`, `/plan-round`, `/execute-task`, `/review-round`,
  `/merge-round`, `/reconcile`, `/handoff`, plus `/status` and `/pr-verdict`.
- Everyday: `/test`, `/lint-fix`, `/review`, `/secrets-check`, `/commit-push-pr`.
- Skills: `debug`, `tdd`, `verify`, `loop-manager`. Subagents: `review-lens`, `ci-watcher`,
  `quick-fixer`.
- Unattended loop: `python3 scripts/round_supervisor.py up` from a Herdr pane
  (`docs/agents/round_supervisor.md`).
