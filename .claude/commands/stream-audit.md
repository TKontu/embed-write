# Stream Audit

Audit the analysis stream for the details that decide result quality and speed without raising any
error, and check them against real stored items. Read-only.

Argument: `<mode> [options]`

- `metrics <store> [<store> ...]`: counts over stored builds, caches or edit logs. Minutes, no
  agents, no model call.
- `items <store>`: seeded item reads of a fresh build (several readers).
- `full [--all]`: code sweep of changed segments, claim regression, item reads, owner lookup.

Use `/review` for a diff. Use this for what the pipeline does to the text it carries.

If a stage below has no code yet, list it as "not built" and skip it. If no stage is built, say
so and stop.

## Rules (all modes)

- **Read-only.** No commit, no PR, no backlog edit, no flag change. Findings need a disposition
  through the round loop (`/plan-round`); the report says so.
- **Do not disturb running work.** Read `HANDOFF.md` and `python3 scripts/round_supervisor.py
  status` first. No model call and no GPU load unless the operator approves a named trial.
- **Pin the source.** Resolve the default branch's SHA, then
  `git archive <sha> | tar -x -C <scratchpad>/snap`. Readers read only the snapshot, never the
  working checkout or a lane's worktree (a live run may execute from them).
- **Stores are read-only.** Open LMDB with `readonly=True, lock=False` and SQLite with
  `?mode=ro` URIs. Never write a cache, label or edit-log entry.
- **Claude reads are evaluations, never labels.** Label every item-read figure "Read: Claude
  evaluator, not expert". Never use one as a gate's reference, an acceptance check, a training
  label or a pipeline input (AGENTS.md: who judged what).
- **Models.** Sweep, verification and item readers: Opus. Owner lookup: Sonnet. State model and
  effort in the report.
- **Private material stays private.** No corpus text, report titles, names or source-item content
  in the report. Packets and samples hold corpus text: keep them under `output/` (gitignored).
- **Every number carries its basis**: what was counted, on which build, built when, and how it is
  known (Code / Measured / Read / Expert / Recorded).

## Stream segments

Use these as the sweep units (`docs/architecture.md` §4–§5). Each lists the places where an item can
be dropped, cut, altered, merged, scored or defaulted without an error.

1. **Corpus and source items** (§5.1): ingest filters, sentence splitting (abbreviations,
   decimals, lists, tables), source-item linking.
2. **Document model** (§5.2): Markdown ⇄ doc round-trip losses, node identity across edits, content
   hashing, dirty-set misses.
3. **Embedding service** (§5.3): truncation at the model's token limit, level tagging (I2), cache
   keys and stale hits, batching and normalisation.
4. **Pattern model and fast layer** (§5.4–5.5): label inventory, class thresholds and defaults,
   ties, unknown-move handling, sequence-model smoothing.
5. **Triage and slow layer** (§5.5): what is sent to the LLM, context cut-offs, discarded stale
   results, disagreement handling, retries and parse failures that fall back silently.
6. **Signals and overlays** (§5.6–5.7): the confidence, method and layer fields (I4), signals that
   are suppressed, merged or defaulted before display.
7. **Proposals** (§5.9): exemplar retrieval cut-offs, candidate filtering, critic thresholds, checks
   that are skipped or default to pass.
8. **Edit log and distillation** (§5.10, §5.4): accept, reject or manual-edit events that are not
   logged (I7), pairs dropped before training, label sources mixed together.

## Outputs

- Evidence: `output/audit_<YYYYMMDD>/{metrics,packets,reads,sweep,verify,method}/`.
- Report (modes `items`, `full`): `output/audit_<YYYYMMDD>/report.md`, with a first section
  **"Changed since the last audit"**. Durable conclusions go to the backlog through the round loop,
  not into a tracked report.
- Claims register: `output/stream_audit/claims.md` (plain behaviour statements, each with its
  dated verdict).

## Mode `metrics`

1. For each store, count per segment: items in and out, items dropped or defaulted and why,
   truncation rate, cache hit and stale-hit rate, fallbacks taken, slow-layer disagreement rate.
   Write `output/audit_<date>/metrics/<name>.json`.
2. Diff against the newest earlier metrics file for the same genre and corpus under
   `output/audit_*/metrics/`.
3. Reply with the changed values grouped by segment, each with its basis. Say which builds were
   compared and that their configuration may differ. Stop. No report file.

A diff is only meaningful between builds of the same documents. Say so when they are not.

## Mode `items`

1. Run `metrics` steps 1–2 for the stores given.
2. Draw packets with a fixed seed, so the same build gives the same items: about 15 sections
   (sentences with their move labels, layer and confidence), about 30 slow-layer verdicts with
   their inputs, and, when they exist, about 20 proposals with their checks.
3. Start readers in one message, each with at most ~150 KB of packets and a rubric that asks, per
   item: is the split right, does the label fit the text, did any stage visibly lose or alter
   content, does each check's result follow from its input.
4. Spot-check each reader: open one small packet and compare every verdict. If a reader is wrong on
   more than one item in it, discard that reader's output and re-run it.
5. Write the report sections "What the items look like" and "Changed since the last audit".

## Mode `full`

1. Pin and snapshot. Find the last audited SHA in the newest `output/audit_*/report.md`.
2. **Sweep.** Take the segments that own a file changed since that SHA (all of them with `--all`).
   One reader per segment, in one message, each told to list every place where an item is dropped,
   cut, altered, merged, scored or defaulted, or a model is called, quoting `file:line`.
3. **Check quotes by script**: every quoted line must be at its `file:line` in the snapshot. A row
   that fails goes back to its reader.
4. **Claim regression.** Give the register's claims (statements only, not their verdicts) to two
   fresh verifiers and compare with the recorded verdicts. Add the most consequential new sweep
   claims, worded as plain behaviour, and verify them the same way. A verifier never sees the
   sweep's notes.
5. **Items.** Run mode `items` on the newest build of current code. If that build is older than the
   fixes being checked, say so and report only the code result.
6. **Owners.** One Sonnet reader maps each finding to its rows in `docs/todo.md` and the
   subsystem files, and says whether the specific detail is covered or only the area.
7. **Report.** For each finding: problem, mechanism, evidence with basis, owner, and the suggested
   shape of a fix row. Rank by stream position first (upstream feeds everything), then by how often
   the detail binds, then by whether a later stage can recover the loss. A claim counts as Code only
   if a verifier confirmed it; otherwise list it as unverified.
8. Append newly verified claims to the register and date any verdict that changed.
9. Give the operator at most ten lines: what changed, what is new, where the report is.

## What makes a finding

A place where an item is dropped, cut, altered, merged, scored or defaulted, or a model is called,
**and** evidence that it binds: a count from stored data, or items that show it. A detail with a
locator but no evidence of binding goes in an "unmeasured" list with the probe that would settle
it. Wiring, conformance and strategy are out of scope.
