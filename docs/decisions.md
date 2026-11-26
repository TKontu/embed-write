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

## D-003 — R49/A1 resolves as merged; planners never push to a reported lane (2026-11-24, operator)

- **Ruling:** R49/A1 (PR #116) is `merged` at merge commit `beb7be7`. The merged head `8d5050d`
  is a planner docs commit on top of the executor's result head `8c06b6d`; the lane's own work is
  `8c06b6d` and it merged unchanged. Record that, with this decision as the evidence, and close R49.
- **Rule from now on:** once a lane has reported its result head, planners do not push to that
  lane's branch. A review fix becomes a new lane head that is reviewed again, or a separate PR.
- **Why:** the extra commit made `round.py` refuse `merged`, `cancelled` would misstate a merge,
  and the open R49 halted the loop (2026-11-24 02:47).

## D-004 — EL-07b delete is a permanent whole-log delete (2026-11-24, operator)

- **Ruling:** the expert's delete control permanently deletes the whole edit log, after offering
  the EL-07a export. No per-entry delete and no tombstones for now.
- **Why:** the store stays append-only while it exists, and the expert's private data is truly
  erased; a tombstone would leave it on disk.
- **Unblocks:** EL-07b.

## D-005 — Dependencies install into a local, pinned venv (2026-11-24, operator)

- **Ruling:** Python dependencies (PySBD/spaCy, LMDB and later ones) are pinned in
  `requirements.txt` and installed into the checkout's `.venv` with
  `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`. That command becomes the
  `install` key in CLAUDE.md's Project Commands. Packages are fetched once at install; everything
  at run time stays offline and local (invariant I9). A lane worktree runs the same install.
- **Unblocks:** CK-02, CA-01.

## D-006 — CK-06 policy for tables, code, figures and captions (2026-11-24, operator)

- **Ruling:** code blocks are skipped (not embedded). A figure is embedded as its caption only. A
  table is embedded as its caption plus its header row. Text that is only a caption is embedded as
  that caption.
- **Why:** the simplest rule that gives each type one tested path, which is CK-06's check.

## D-007 — App shell is Tauri (2026-11-24, operator)

- **Ruling:** the app shell is Tauri. It resolves "Tauri or Electron" in `docs/architecture.md`.
  The editor stays Milkdown on ProseMirror, in Tauri's system webview, and the local Python
  analysis service runs as a Tauri sidecar.
- **Why:** small binaries and low memory, and a tight permission model for a local-only app with
  private data.
- **Unblocks:** the TS stack (editor, app shell, and the document-model and visualization rows).
  Needs a Rust toolchain and Node for the frontend build; installs follow D-005's pattern.

## D-008 — Lane fallback when Codex is saturated (2026-11-25, operator)

- **Ruling:** Codex stays the first choice for executor lanes (D-001). When Codex is at its usage
  limit, rounds do not wait or halt: they run lanes on Claude and OpenCode, spread across both.
- **OpenCode launch:** `opencode run --auto -m fireworks-ai/accounts/fireworks/models/deepseek-v4p1-flash-1017 "<task>"`,
  inside the lane worktree in its Herdr tab. The model is the one the iknosreview loop approved;
  change it only by a new decision.
- **Lane tabs:** open every lane tab with `herdr tab create --cwd <lane worktree>`, so
  `lane_cleanup.py` can link a tab to its lane. Tabs opened in the main checkout are held as
  `foreign`.
- **Why:** on 2026-11-24 the planner waited out a Codex limit, ran three empty rounds and halted
  ("main unchanged across 3 rounds").
- **Record:** HANDOFF.md names the harness each lane ran on.

## D-009 — Early feedback first: Phase 0 and a thin demo before later phases (2026-11-25, operator)

- **Ruling:** the backlog is prioritised for the earliest real feedback. Until G-01 and G-02 have
  result files from actual runs, lanes take work in this order:
  1. **Gate enablers for G-01 and G-02:** corpus ingestion of the expert's reports, a move-inventory
     draft for the expert to correct, the annotation tool, LLM pre-labels for the expert to confirm
     or overturn, the G-01 κ harness, the G-02 blind-pair runner, and preregistration files with
     proposed thresholds for the expert to confirm.
  2. **Thin vertical demo:** a Tauri shell (D-007) with the Milkdown editor that opens one real
     report, round-trips it, and shows its move labels as a provisional overlay with a legend.
     It is the smallest thing the expert can look at and react to.
  3. **Anything that cuts the expert's effort per judgment:** batching, pre-filled forms, one-key
     confirm/overturn.
  
  Rows from later phases (proposals, generation, fine-tuning, two-layer distillation, extra
  signals) wait unless they are a direct dependency of 1–3.
- **Why:** after 240 merged PRs no gate had run. Every result came from synthetic or LLM-built
  data, and G-01 is the fatal gate (§9, §10 of the architecture). Building later phases first
  risks sunk cost if G-01 or G-02 fails.
- **Re-evaluation trigger:** G-01 κ < 0.6 or G-02 preference < 70 % reopens the target and the
  vision; nothing else does until those results exist.
- **Planner duty:** re-rank `docs/todo.md`'s critical path to this order in the next reconcile,
  and report each round which item of 1–3 it advanced.

## D-011 — Build the thin demo on synthetic data while the corpus is pending (2026-11-26, operator)

- **Ruling:** until the expert's corpus arrives, the loop builds D-009 item 2 (the thin demo) on
  synthetic sample reports that are clearly labelled as synthetic: the Tauri shell (D-007) with the
  Milkdown editor, opening, round-tripping and saving a report, move labels as a provisional
  overlay with a legend, and a one-command launch. When the corpus arrives, swapping in a real
  report must be the only remaining step.
- **Order:** D-009's gate enablers still come first whenever real data exists.
- **Why:** with no corpus, the remaining D-009 enablers need real-data runs, so rounds found no
  plannable work and the supervisor halted repeatedly ("main unchanged across 3 rounds").
- **Not changed:** results on synthetic data are never quoted as evidence for a gate (AGENTS.md).
