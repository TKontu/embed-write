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
| `todo-02-embedding.md` | Embedding service, cache | 28 | 28 | 0 | 0 | 12 |
| `todo-03-document-model.md` | Markdown round-trip, node identity | 24 | 24 | 0 | 0 | 0 |
| `todo-04-analysis.md` | Pattern model, two-layer analysis | 47 | 45 | 0 | 2 | 8 |
| `todo-05-visualization.md` | Overlays, legend, inspector | 35 | 30 | 5 | 0 | 0 |
| `todo-06-editor.md` | Editor, app shell | 34 | 33 | 1 | 0 | 0 |
| `todo-07-proposals.md` | Proposals, verification, edit log, automatic drafting | 45 | 42 | 3 | 0 | 0 |
| `todo-08-evaluation.md` | Evaluation harness | 29 | 26 | 2 | 1 | 1 |
| `todo-09-corpus.md` | Reference corpus, annotation, source items | 32 | 19 | 11 | 2 | 0 |
| **Total** | | **332** | **277** | **38** | **17** | **21** |

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
