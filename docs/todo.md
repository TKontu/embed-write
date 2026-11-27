# TODO — Master Tracker

**Project:** Semantic Text Workbench
**Design:** `architecture.md` (revision 2, 2026-11-22)
**Status:** pre-implementation, Phase 0 not started

---

## Goal

1. **Stage 1:** help experts write reports in their genre's patterns.
2. **Stage 2:** write those reports automatically, with the expert reviewing.

The system learns a genre's patterns from a corpus of good reports, shows the expert how a draft fits them, steers LLM output toward them, and logs every expert correction as training data.

---

## Two tracks

| Track | Content | Who | Limited by |
|---|---|---|---|
| **E — engineering** | Document model, editor, embedding service, pattern-model code, overlays, harness | Agents | Mechanical acceptance checks |
| **R — research** | Corpus selection, move inventory, annotation, blind judgments, gate verdicts | The expert | Expert attention |

Task markers in every todo file: `[A]` agent-executable with a mechanical check · `[H]` needs the expert's judgment · `[A→H]` agent prepares, human decides.

Track E can start today. Track R decides whether the project continues.

---

## Subsystem documents

| Doc | Subsystem | Tasks | `[A]` | `[H]` | `[A→H]` | Done |
|---|---|---|---|---|---|---|
| `todo-01-experiments.md` | Gates G-01 to G-11 | 58 | 30 | 16 | 12 | 0 |
| `todo-02-embedding.md` | Embedding service, cache | 28 | 28 | 0 | 0 | 20 |
| `todo-03-document-model.md` | Markdown round-trip, node identity | 24 | 24 | 0 | 0 | 20 |
| `todo-04-analysis.md` | Pattern model, two-layer analysis | 47 | 45 | 0 | 2 | 18 |
| `todo-05-visualization.md` | Overlays, legend, inspector | 35 | 30 | 5 | 0 | 0 |
| `todo-06-editor.md` | Editor, app shell | 39 | 38 | 1 | 0 | 9 |
| `todo-07-proposals.md` | Proposals, verification, edit log, automatic drafting | 46 | 43 | 3 | 0 | 8 |
| `todo-08-evaluation.md` | Evaluation harness | 29 | 26 | 2 | 1 | 1 |
| `todo-09-corpus.md` | Reference corpus, annotation, source items | 35 | 22 | 11 | 2 | 4 |
| **Total** | | **336** | **281** | **38** | **17** | **60** |

The 38 `[H]` tasks are the critical path.

---

## Phase progress

| Phase | Track R | Track E | Exit criterion | Status |
|---|---|---|---|---|
| **0** | Corpus, move inventory, annotation, **G-01**, **G-02** | Harness, ingestion, annotation tool, document model, embedding service, editor start | Both fatal gates pass, or stop | ☐ |
| **1** | G-03, G-05, G-06 | Classifier, sequence model, exemplar index, register profile | Pattern model reproduces expert labels on held-out reports | ☐ |
| **2** | G-09 | Editor complete, overlays, legend, inspector | Expert reads a report's structure from the overlay | ☐ |
| **3** | G-04 | Two-layer live analysis, distillation | Live overlay stable and trusted | ☐ |
| **4** | G-07, G-08 | Proposals, verification panel, edit log | **Stage 1 in daily use** | ☐ |
| **5** | Blind review of drafts | Source grounding, automatic drafting, review flow | Drafts accepted with bounded corrections | ☐ |
| **6** | G-10 | Fine-tuning from the edit log | Fine-tuned model adopted or dropped | ☐ |
| **7** | — | Hardening, packaging | — | ☐ |

---

## Gate status

Thresholds are proposals until confirmed; see `todo-01-experiments.md`.

| Gate | Question | Blocks | Status |
|---|---|---|---|
| **G-01** | Can the genre's moves be recovered reliably? | **everything in Track R, the pattern model** | ☐ |
| **G-02** | Do exemplars + critic steer LLM output to the genre? | **proposals, automatic drafting** | ☐ |
| G-03 | Embedding model and chunking strategy | model default | ☐ |
| G-04 | Is the fast layer close enough to the slow layer? | live provisional results | ☐ |
| G-05 | Sequence fit | missing and misplaced move flags | ☐ |
| G-06 | Register fit | off-register flags | ☐ |
| G-07 | Support mapping | unsupported-claim flags | ☐ |
| G-08 | Meaning-preservation check | proposal filtering | ☐ |
| G-09 | Overlay legibility | text tinting | ☐ |
| G-10 | Fine-tuning vs exemplars + critic | fine-tuned model | ☐ |
| G-11 | Topic overlay (optional) | topic overlay | ☐ |

---

## Critical path

**Planning order (D-009, operator 2026-11-25, record in PR #246):** until G-01 and G-02 have actual result files, lanes come only from, in this order:

1. **G-01/G-02 enablers:** corpus ingestion (CO-04, CO-06, CO-08, CO-10), move-inventory draft (MV-02), annotation tool and sampling (AN-01, AN-02), LLM pre-labels for the expert to confirm or overturn (G-01.4), the κ harness (G-01.5), the G-02 notes/generation/blind-pair runner (G-02.2, G-02.3, X-04), preregistration drafts with proposed thresholds for the expert (G-01.1, G-02.1 are `[H]`; agents prepare only).
2. **Thin demo:** a Tauri shell (AP-01) with the Milkdown editor (ED-01) that opens one real report, round-trips it, and shows provisional move overlays with a legend.
3. **Anything that cuts the expert's effort per judgment.**

Later-phase rows (proposals, generation, fine-tuning, distillation, extra signals) wait unless they are a direct dependency of 1-3. The tracks below remain the long-run shape.

**Strategic re-rank (R195, 2026-11-26, D-014 strategic round):**

- **Observed:** two real texts appeared under `input/` (locally excluded from git) on 2026-11-26. No genre, corpus or confidentiality decision is recorded for them (CO-01 to CO-03 are `[H]`). Until the operator rules, agents run local tools over `input/` and read counts and statuses only; no agent, lane or PR reads or quotes the text (I9: agent models are remote).
- **Drift corrected:** R192 to R194 built pattern-model rows PT-01 to PT-04 on synthetic data. They are not dependencies of items 1-3, and "do not start the pattern model before G-01 returns" still stands. PT-05 and later PT rows wait.
- **Biggest reducible risk:** nothing on the G-01 path had ever touched real text or a real model. Order within item 1 is now: (a) whatever lets real input reach the expert in one step (CO-12 intake, MV-02 with the real embedder, a genre file for the real genre once the expert seeds MV-01); (b) real-run readiness of pre-labels and G-02 generation against a local LLM endpoint (none exists on this host: owed to the operator); (c) residuals of rows the real run exposes.
- **Takeoff duty:** each takeoff lists `input/` (names, sizes, dates only) and compares it with this section.
- **Sections (D-015, operator 2026-11-27, PR #520):** sections come from the best available headings; where a document has none, intake infers them, marks them as inferred with the method and shows them as provisional (CO-14). This settles the earlier design question about heading-less real texts; the expert's section types (MV-01/MV-03) stay the expert's call.
- **R210 diagnosing round (D-012, 2026-11-27):** R209 ran no lanes. Causes found: executor-limit (Codex probe still refuses until 2026-11-30 08:24 UTC), plus two the wait hid: operator PRs #520 (D-015) and #521 (gitignore `/input/`) were open and unmerged, and main's gate was red because `lane_cleanup` held the finished in-repo worktree `worktrees/r207-a1` as `foreign` (tool-broken). Acted: merged #520 (e22a547) and #521 (2df8c8a) after independent review; R210/A1 (PR #522, merge 66050f3, reviewed head 0690a65, Fable review D-014 APPROVE; Claude lane) makes `<root>/worktrees/<name>` a lane path under the usual hold rules. seen: `lane_cleanup --go` on main removed worktrees/r207-a1 and closed its tab; gate 1767 OK (skipped=4) at 86b8b03. Residuals: in-repo `busy`/`unpushed`/`open-pr` holds untested (shared code path); an empty `worktrees/` directory stays. R210/A3 delivered CO-14's first slice (todo-09). Claude lanes for product rows in D-009 order are the working harness until Codex returns (D-008).
- **R215 (2026-11-27):** two Claude lanes (Codex usage-limited until 2026-11-30 08:24 UTC): CO-14 correction hardening in intake (PR #538) and tested demo correction logic (PR #537), both merged after independent review; gate 1803 OK (skipped=4) and npm 333 pass on main e11b53c. Next: the expert corrects the 7 inferred boundaries in the demo.
- **R218 (2026-11-27):** one Claude lane (Codex usage-limited): g01_draft reports unwritable or unresolvable output paths as exit 2 naming the OS error, no traceback (PR #544, Fable review D-014), merged; gate OK (skipped=4) on main 5a63c0c. Residual: a failed .md write can leave a lone new .json; detail in todo-09 under the g01_draft rows.
- **R220 (2026-11-27):** one Claude lane (Codex re-probed: usage-limited until 2026-11-30 08:24 UTC): g01_draft redraft keeps the prior file's permission bits (also read-only priors), backs up non-regular priors, names a stranded .bak and cleans temps on any exception (PR #548, Fable review D-014 found a read-only-prior regression, fixed before merge), merged; gate OK (skipped=4) on main f4de799. Residuals in todo-09.
- **R225 (2026-11-27):** one Claude lane (Codex re-probed: usage-limited until 2026-11-30 08:24 UTC): g01_draft refuses a NUL byte in any input path argument as exit 2 before reading inputs (PR #558, merge 584c493, reviewed head eae6aa3, Fable review D-014 APPROVE), merged; gate OK (skipped=4) on main. Detail in todo-09.
- **R224 (2026-11-27):** one Claude lane (Codex re-probed: usage-limited until 2026-11-30 08:24 UTC): g01_draft refuses a NUL byte in `--out` as exit 2 before any write (PR #556, merge 05d777b, reviewed head e636b1b, Fable review D-014 APPROVE), merged; gate OK (skipped=4) on main. Detail in todo-09.
- **R223 (2026-11-27):** one Claude lane (Codex re-probed: usage-limited until 2026-11-30 08:24 UTC): g01_draft refuses an `--out` ending in a separator or naming a directory (exit 2, stem rule) before any write (PR #554, merge c1e240f, reviewed head 2654fb8; Fable review D-014 found is_dir OS errors escaping as tracebacks, planner fixed before merge), merged; gate 1834 OK (skipped=4) on main. Detail in todo-09.
- **R222 (2026-11-27):** one Claude lane (Codex re-probed: usage-limited until 2026-11-30 08:24 UTC): CO-13 `genre_scaffold check` flags only scaffold markers, not any value containing "TODO" (PR #552, merge 3d9dc92, independent review APPROVE), merged; gate OK (skipped=4) on main. Detail in todo-09.
- **R221 (2026-11-27):** one Claude lane (Codex re-probed: usage-limited until 2026-11-30 08:24 UTC): `lane_cleanup` now reports orphan lane directories (unregistered `<root>-rN-xN` siblings and `<root>/worktrees/<name>`) as `orphan <path>: unregistered directory, not removed`, never touching them (PR #550, merge ba74a58, reviewed head 7f6b02e; Fable review D-014 found containers such as `-results` misreported, planner fixed before merge). seen: `lane_cleanup --go` on main ba74a58 reported r140-a1 and r215-a2 as orphans and released r221-a1; gate 1828 OK (skipped=4). Residuals: non-round sibling names (`<root>-wt-*`) and orphans inside `-lanes`/`-worktrees` containers are not scanned; a remove killed at 600s shows as orphan only on the next run; docstrings say "lane path" broadly; test swaps module ROOT via globals(). Orphan recovery stays with the operator.
- **R219 (2026-11-27):** one Claude lane (Codex usage-limited until 2026-11-30 08:24 UTC, re-probed): g01_draft writes its .json/.md pair all-or-nothing and names the failing path (PR #546, Fable review D-014), merged; gate OK (skipped=4) on main 81ff266. Residuals: file mode reset, double-fault .bak, non-OSError temp leak; detail in todo-09.
- **R217 (2026-11-27):** one Claude lane (Codex usage-limited): g01_draft refuses symlink loops in non-leaf output components on any Python (PR #542, Fable review D-014), merged; gate 1807 OK (skipped=4) on main 34f3bcc. Closes the R214 residual; detail in todo-09 under the g01_draft rows.
- **R214 (2026-11-27):** two Claude lanes: CO-14 (c) expert section correction replacing the inference, demo line numbering as splitlines() (PR #535), and g01_draft exits 2 on a symlink loop and resolves RESULTS_DIR (PR #534, Fable review D-014), both merged after independent review; gate 1802 OK (skipped=4) and npm 329 pass on main 3711bb5. Residual (#534 review): on Python 3.13+ a loop in a non-leaf output component is not caught by `_resolve` and tracebacks at mkdir (nothing written; venv is 3.12). Next: the expert corrects the 7 inferred boundaries in the demo.
- **R213 (2026-11-27):** two Claude lanes: CO-14 demo shows inferred sections as provisional badges (PR #532) and g01_draft refuses leaf symlinks into experiments/results (PR #531, Fable review), both merged after independent review; gate OK (skipped=4) on main b3931b8. Next: the expert opens the demo to judge the 7 inferred boundaries.
- **R212 (2026-11-27):** two Claude lanes: CO-14 semantic topic shift with the real embedder (PR #529) and hermetic g01 draft tests (PR #528, cause: cross-checkout import), both merged after independent review. Finding: with bge-m3 the real heading-less text now gets 7 provisional `topic_shift_embedding` sections (counts only; expert has not judged them).
- **R211 (2026-11-27):** two Claude lanes on CO-14 (todo-09): topic_shift inference (PR #526) and inferred sections as sampling strata (PR #525), both merged after independent review; gate 1783 OK (skipped=4) on main bb7028d. Finding: on the real heading-less text no method yet infers sections, so sampling there stays one `unknown` stratum.
- **Loop tooling:** #480 residuals F1 to F5 were fixed in R197 (PR #494, merge 783ee76; Fable review D-014). A failed strong-model start now falls back to the default model on both diagnosing and strategic rounds; trials never touch strategic.json; a non-finite or future `at` counts as absent; `[supervisor] strong_model` is configurable. F6: no code assumes contiguous decision numbers (D-013 gap is docs only). Residuals: the fallback retries in the same pane after a failure of unknown kind (Herdr behaviour unverified); a non-string strong_model is ignored without a log; main() wiring untested; not yet run live (takes effect at the next supervisor restart). R198 (PR #496, merge 5bc32d4, Fable review D-014): an invalid or empty `strong_model` now warns on stderr and uses the default; a test drives main() to the strategic start command. Residuals: the warning repeats on every subcommand; a non-table `[supervisor]` still crashes (pre-existing); diagnose path through main() untested. R199/A2 (PR #500, merge 824ee3c, reviewed head 22780dd, Fable review D-014; Claude lane, Codex usage-limited): a non-table `[supervisor]` warns once and uses defaults; config warnings print once per process. seen: gate 1732 OK (skipped=7) at head; reviewer exercised status/--help with `supervisor = "x"`. Residuals: permission_mode not type-checked. R200/A1 (PR #503, merge adf354c, reviewed head fed68ab, Fable review D-014; Claude lane, Codex usage-limited): a non-table `[supervisor]` no longer crashes lane_cleanup.lane_prefix and a non-table `[project]` uses defaults with one warning in round_supervisor; supervisor tests clear `_WARNED` in setUp. seen: gate 1738 OK at merged main; reviewer imported round_supervisor with malformed configs (BRANCH main, no traceback). Residuals: merge_guard.py:42 same crash shape on non-table `[project]` (operator-only file, D-010); lane_prefix does not catch TOMLDecodeError on an invalid config.toml; BRANCH import-time path tested only through project_section(). R201/A1 (PR #505, merge 3b8c4fe, reviewed head 396ed69, Fable review D-014 APPROVE; Claude lane, Codex usage-limited): lane_prefix treats an invalid config.toml (TOMLDecodeError) like a missing one; a non-string or empty `[supervisor] permission_mode` warns once and uses "auto". seen: gate 1740 OK at merged main; reviewer ran lane_prefix on invalid TOML and imported round_supervisor with bad permission_mode values. Residuals: a whitespace-only permission_mode passes unwarned; invalid UTF-8 in config.toml (UnicodeDecodeError) still tracebacks in lane_prefix and round_supervisor; permission-mode test calls permission_args() directly, not the start command. Intake re-run R201 (planner, counts only, private input/): exit 0, 2 documents ok, 179 sentences, 1 flagged no_headings, 98 drawn of 300 requested in 1 stratum (R195 reported 180 sentences and 40 drawn; difference unexplained). R203/A1 (PR #509, merge 83d2dc9, reviewed head 9b195ad, Fable review D-014 APPROVE; Claude lane, Codex usage-limited): a whitespace-only `permission_mode` warns once and uses "auto"; invalid UTF-8 in config.toml is treated as missing in lane_prefix and round_supervisor.project_config. seen: gate 1744 OK (skipped=7) at head; reviewer exercised both by hand. Residuals: a padded valid mode (" auto ") passes unstripped; warning text still says "non-empty"; merge_guard.py same unguarded load (operator-only, D-010). R204/A1 (PR #511, merge 5ba8248, reviewed head e42ece1, Fable review D-014 APPROVE; Claude lane, Codex usage-limited): a padded permission_mode is stripped (" auto " -> "auto"); the warning says "non-blank". seen: gate 1744 OK (skipped=4) at merged main; reviewer probed padded, tab/newline and invalid values by hand. Residuals: test pads only to the default "auto"; mode values not validated against known modes; import-time PERMISSION_ARGS path untested. R216/A1 (PR #540, merge a9b8ec7, reviewed head 1fd068f, Fable review D-014 APPROVE; Claude lane, Codex usage-limited): lane_cleanup's `git worktree remove` gets a 600s timeout (other commands keep 120s) and a timeout is reported as `remove timed out after 600s`. seen: gate 1805 OK (skipped=4) at merged main; reviewer probed the real _run timeout. Residuals: a remove killed at 600s can still leave git unregistered with the directory on disk (R215 symptom, no recovery); timeout detected by output prefix; Run type loosened to Callable[...].

```
Track R (expert)                          Track E (agents, start now)
────────────────                          ───────────────────────────
choose genre, select corpus  (todo-09)    harness, gate registry      (todo-01, 08)
        ↓                                 document model              (todo-03)
move inventory + legend      (todo-09)    corpus ingestion, annot. tool (todo-09)
        ↓                                 embedding service, cache    (todo-02)
annotate ~300 sentences                   editor, app shell           (todo-06)
        ↓
G-01 ── fails twice ──► STOP
  │ passes
  ↓
G-02 ── fails ──► stage 2 needs fine-tuning; stage 1 continues
  │ passes
  ↓
pattern model (todo-04) ─► overlays (todo-05) ─► two-layer live analysis
  ↓
proposals + edit log (todo-07)   ◄── Stage 1 complete
  ↓
automatic drafting ─► fine-tuning (todo-07)   ◄── Stage 2
```

If G-01 fails, the Track E work on the document model and editor is still a usable Markdown editor, and nothing else is lost.

---

## Invariants

| # | Invariant | Enforcement |
|---|---|---|
| I1 | Markdown is the only source of truth | Round-trip test suite |
| I2 | No embedding comparison across granularity levels | Level-tagged types + lint |
| I3 | The colour legend is fixed per genre | Stored in the genre file, never computed |
| I4 | Every signal carries confidence, method and layer | Required type fields |
| I5 | No edit applied and no draft finalized without a user action | No such code path |
| I6 | Ungated capabilities stay behind flags | CI gate check |
| I7 | Every expert change to machine text is logged, locally | Edit-log hook + test |
| I8 | Pattern fit is never presented as correctness | Naming lint + method text |
| I9 | Reports and corpus stay local by default | Network guard |

---

## What changed from revision 1

| Was | Is now |
|---|---|
| Topic colorization of one document as the centrepiece | Pattern model of a genre, learned from a corpus |
| Continuous colour projection | Fixed legend, one colour per move |
| Embeddings as the only analysis | Fast embedding layer + slow LLM layer, with distillation |
| Fatal gate E-01 on topic colours | Fatal gates G-01 (moves) and G-02 (steering) |
| Hand-annotated corpus before any test | LLM labels at scale, expert annotation as validation |
| Word-level attribution | Dropped |
| Edit proposals only | Proposals, edit log, automatic drafting, fine-tuning |
| One undifferentiated task list | Every task marked agent-executable or human-gated |

---

## Immediate next actions

**Expert (Track R):**

1. `todo-09` CO-01 to CO-03: choose the genre, select the reference reports, decide confidentiality handling.
2. `todo-09` MV-01: write the seed list of moves.
3. `todo-01` G-01.1 and G-02.1: confirm or change the proposed thresholds.

**Agents (Track E), in parallel:**

1. `todo-01` X-00 to X-04 and `todo-08` EV-01 to EV-05: harness and gate registry.
2. `todo-03` DM-01 to DM-06: Markdown round-trip.
3. `todo-09` CO-04, AN-01: ingestion and annotation tool, so they are ready when the corpus is.
4. `todo-02` SV-01 to SV-05, `todo-06` ED-01 to ED-05: service and editor foundations.

**Do not start the pattern model (`todo-04`) before G-01 returns.**
