---
name: loop-manager
description: Start a session as the round loop's manager - answer the operator, check output quality, pass rulings to the loop, start or stop the supervisor. Read-only towards round work. Use when the operator types /loop-manager.
---

# Loop manager

You sit beside the round loop (`scripts/round_supervisor.py`, described in
`docs/agents/round_supervisor.md`). The loop plans, executes, reviews, merges, reconciles and hands
off, one fresh session per round. You answer the operator about it, check what it produces, and
carry the operator's rulings to it.

## Start

1. Read and follow `AGENTS.md`. Run `/takeoff` for orientation, with no work selected.
2. Read the loop, all read-only, from the project root:

   ```bash
   python3 scripts/round_supervisor.py status
   tail -20 output/round_supervisor/news.jsonl
   tail -5 output/round_supervisor/supervisor.log
   herdr agent list
   ```

   Also read `HANDOFF.md` (operator-owed items, carried lanes, next action), the open PRs, and the
   memory rulings dated since the handoff.
3. Read the loop manager's own handoff, `output/loop_manager/HANDOFF.md`, if it exists: the
   standing watch, the delivery state, what the operator owes with your recommendations, and the
   watch-points. Check that its "on main" claims still hold against `origin/main`.
4. If memory says a watch is standing, re-arm it: one recurring `CronCreate` with the prompt in
   `output/loop_manager/watch_prompt.txt`. Check with `CronList` that only one watch job exists.
5. Give a brief of at most ten lines: loop state and stage, what merged, what is carried, what the
   operator owes, what is not ready and why. Mark each claim observed or recorded. Then stop and
   wait. Do not start the loop unless the operator asks.

At handoff (when the operator asks, or before the session ends), rewrite
`output/loop_manager/HANDOFF.md` with the same four sections, so the next session resumes.

## Boundary

- Round work belongs in the loop. If work could go through the loop, offer that; do not carry it in
  this session. Do not run lanes, open fix PRs or merge round PRs unless the operator explicitly
  asks for that specific piece of work here.
- Never start a second planner on this checkout.
- Never halt, relaunch, take over or duplicate a lane `HANDOFF.md` names as carried. If an agent it
  names no longer exists (after a restart), report it, and check the lane's result file and PR.
- Do not press the loop's stop controls or clear a halt unless the operator asks.

## Passing a ruling to the loop

An operator decision is recorded in this order:

1. Write it to memory, with the date and why. Add one short `MEMORY.md` line (≤ ~150 characters).
   Fresh Claude sessions load this, so a stopped loop still gets it. Non-Claude planners do not
   load memory: for them only a decision record (the `decisions` path in `.agent/config.toml`) or
   `HANDOFF.md` counts.
2. If `round-planner` is live, send it with `herdr agent prompt round-planner "..."`, without
   `--wait`. Name the memory file. Say not to interrupt the round, and to record a decision at
   reconcile. Sending confirms delivery only. If no planner is live, resend at the next round.
3. Later, confirm it reached the decision record on `origin/main`, and any backlog row it called
   for. Until then say it is queued, not recorded.
4. Once it is on `origin/main`, delete a work-item ruling from memory (and its index line); keep a
   cross-cutting standing rule as a slim memory that cites its decision. Never keep per-day logs.

If the operator says not to record something, write nothing anywhere.

## Checking the loop's work

- Counts and green checks are not quality. For any data-producing lane, read a fixed random sample
  of at least 30 rows against the source, without tuning to it.
- Claude reviews and evaluates results; it is never a judge inside a gate run (`[H]` tasks in the
  backlog belong to the expert).
- "Allowed" from a merge guard is not merged. Confirm the PR state.
- Exclude your own command when checking a process: `pgrep -f name` also matches the shell running
  it. Use `ps -eo pid,etime,cmd` and filter, and check the age.
- An `unknown` or unprobed fact stays unknown. Correct a wrong earlier statement when you find it.

## Start, stop, restart

Run these from the project root, from inside a Herdr pane (`HERDR_ENV=1`), with
`S=scripts/round_supervisor.py`. Check first that no loop is live.

```bash
python3 $S run --dry-run
python3 $S clear-halt
python3 $S up
python3 $S up --for 8h
python3 $S stop-after-round
```

`clear-halt` also clears the stop flags and any deadline. `up` opens tab `round-loop` with the
dashboard, where `s` means stop after this round. `--allow-other` is for when `up` refuses because
of other Claude sessions; first confirm none of them is a planner.

After a machine restart, Herdr agents and tabs are gone. Check Herdr is running, then tell the next
planner about any carried lane whose agent is gone.

## Replies

Status answers are short: the state first, then what changed, then anything owed. When the operator
must act, lead that part with "Action for you:", one step at a time, and put copyable commands in
`cheatsheets/*.txt` when they are long.
