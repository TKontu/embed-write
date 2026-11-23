# Round supervisor: one fresh session per round

`scripts/round_supervisor.py` runs the reconcile loop unattended. It is a plain process in its own
Herdr pane; the only LLM is the per-round orchestrator it starts.

## How a round turns over

1. The supervisor opens tab `round-planner`, starts `claude --session-id <new uuid>` as Herdr agent
   `round-planner`, and submits the round prompt (takeoff, then one full cycle).
2. The orchestrator's last action is `round_supervisor.py complete --outcome continue`. That
   command refuses unless `HANDOFF.md` was written this round and validates. Herdr's `idle` is never
   taken as completion, because an orchestrator waiting on CI is idle too.
3. The supervisor sends `/exit`, closes the tab it created, waits `gap_s`, and starts the next round.

A new process replaces `/clear`: the fresh context holds by construction, and stale heartbeats or
background Bash from the previous round die with it instead of waking the next one.

## Live work

Live lanes run in their own `live-<lane>` tabs, independent of the orchestrator. The supervisor
never touches them. The round prompt forbids waiting for one: the round carries it
in `HANDOFF.md`, and the next takeoff finds it there and in `.agent-runs/`. Anything long must be a
Herdr lane, because the orchestrator's own subagents and background Bash end with its session.

## The no-endless-wait bound

| Trigger | Default | Response |
|---|---|---|
| Transcript silent (subagents included) | 45 min | Nudge |
| No change in main, PR heads or round manifests | 3 h | Nudge |
| Approval dialog unanswered | 30 min | Notify, refuse with Esc, tell the agent. Never approves |
| Usage limit on screen | up to 6 h | Wait, no nudge spent |
| 3 nudges with no outward progress | | Recycle: new session, takeoff rebuilds from git |
| Round older than | 12 h | Recycle |
| 2 consecutive recycles, or main unchanged over 3 rounds | | HALT and notify |

Only outward progress refunds nudges. A heartbeat keeps the transcript alive, so transcript activity
alone cannot be allowed to extend a round.

## Operating it

State lives in the gitignored `output/round_supervisor/` (`supervisor.log`, `current.json`,
`complete.json`, `HALT`).

```
S=scripts/round_supervisor.py
python3 $S run --dry-run
python3 $S up --for 8h
python3 $S stop-in 2h
python3 $S status
python3 $S stop-after-round
python3 $S stop
python3 $S clear-halt
```

`up` opens tab `round-loop`: the supervisor on top, the dashboard below. The dashboard shows the
state, time limit, lanes, items owed by the operator and a scrollable news feed (`j`/`k`); `s`
toggles stop-after-round and `q` closes only the view. The orchestrator fills the feed with `note`,
capped at 140 characters. A time limit is graceful: the round in flight completes, then the loop
stops. `stop-after-round` is the normal stop. `stop` halts at the next poll and leaves the orchestrator
running in its tab. A restarted supervisor adopts the open round rather than starting another.
`run` refuses if another Claude session is working in the checkout (`--allow-other` overrides), if
`HALT` exists, or if another supervisor holds the lock. Every orchestrator runs in `auto` permission
mode (operator ruling); `--claude-arg` adds further flags.

`complete` validates `HANDOFF.md` with `check-handoff` (the sections of `templates/handoff.md`).
Set `ROUND_SUPERVISOR_ROOT` to supervise a checkout other than the script's own repository.

## Trial plan

Precondition: live work halted at the operator's defined point, and no planner session working.
Each step passes before the next.

| # | Check | Pass |
|---|---|---|
| T1 | `--dry-run` | Transcript dir found, fingerprint ok, name free |
| T2 | Start and prompt delivery | `agent start` accepts `--session-id`; `<uuid>.jsonl` appears; prompt submits |
| T3 | Auto mode | Session reports `auto`; the round runs without a dialog stalling it |
| T4 | `complete` refused before handoff, accepted after | Sentinel only after a valid handoff |
| T5 | Turnover | `/exit` via `agent prompt` works; tab closes; new uuid; a `live-*` dummy lane is undisturbed |
| T6 | Carry-over | The dummy lane appears in round 2's takeoff, no duplicate |
| T7 | Watchdog | Temporarily shortened thresholds: idle orchestrator is nudged, then recycled, then HALT |
| T8 | Dialog | A forced dialog is refused after the timeout and the round continues |
| T9 | Supervisor restart | Kill and restart: it adopts the round, one orchestrator only |
| T10 | Soak | Two real rounds in sequence, then `stop-after-round` |

Not yet run in this repository; run T1 (`--dry-run`) once Herdr and `origin` are set up.
A stop leaves `HALT`; run `clear-halt` before the next `up`.
