# Architecture — Semantic Text Workbench

**Status:** design, pre-implementation · revision 2 (2026-11-22)
**Companion docs:** `todo.md` (master tracker), `todo-*.md` (per subsystem)

---

## 0. What changed in revision 2

Revision 1 was built around topic colorization of a single document. Revision 2 is built around a **pattern model of a report genre**, learned from good reports, with the editor as the place where it is applied and where expert corrections are collected.

| Area | Revision 1 | Revision 2 |
|---|---|---|
| Goal | Visualize topical structure, propose edits | Stage 1: help experts write reports in the genre's patterns. Stage 2: write them automatically, expert reviews |
| Core model | Embedding geometry of one document | Pattern model learned from a reference corpus |
| Color encodes | Position in a continuous topic space | Which move a passage performs (fixed legend) |
| Analysis | Embeddings only | Two layers: embeddings first, LLM in parallel |
| Fatal gate | "Do colors reveal anything?" | "Can moves be recovered?" and "Can output be steered to the genre?" |
| Execution | Sized for a small team | Two tracks: agent-executable engineering, human-gated research |
| Dropped | — | Word-level attribution, continuous colour projection as the centrepiece |
| Added | — | Reference corpus, move classifier, edit log, source grounding, generation pipeline |

---

## 1. Goal

**Stage 1 — assisted writing.** An expert writes a report in a WYSIWYG Markdown editor. Overlays show which move each passage performs, which expected moves are missing or out of order, which passages are off-register and which conclusions lack support. Rewrites are proposed on request.

**Stage 2 — automatic writing.** Given source material (measurements, findings, observations), the system drafts the report in the genre's patterns. The expert reviews it in the same editor, with the same overlays pointing at the weak spots.

Stage 1 is a goal in itself and also the data source for stage 2: every expert correction of a machine draft is a training pair.

---

## 2. Core concepts

| Term | Meaning |
|---|---|
| **Genre** | One report type with its own reference corpus and pattern model |
| **Move** | A functional step in a report: e.g. scope, observation, evidence, interpretation, conclusion, recommendation. The inventory is defined per genre |
| **Pattern model** | Move inventory + expected move sequence per section + exemplars per move + the genre's register profile |
| **Fast layer** | Embeddings plus a small classifier. Milliseconds, runs on every edit |
| **Slow layer** | An LLM reviewing a section. Seconds, runs in parallel, confirms or corrects the fast layer |
| **Source item** | A piece of input material (a measurement, a finding, a photo note) that report text can be traced to |
| **Edit log** | Stored pairs of machine text before and expert text after |

---

## 3. Design invariants

| # | Invariant | Enforced by |
|---|---|---|
| I1 | Markdown is the only source of truth for the document. The editor never shows raw syntax; shortcuts inject it | Round-trip test suite |
| I2 | No embedding comparison across granularity levels | Level-tagged vector types + lint rule |
| I3 | The colour legend is fixed per genre. A move's colour never changes | Legend stored with the pattern model, not computed |
| I4 | Every signal carries confidence, a method reference and its layer (provisional or confirmed) | Required fields on the `Signal` type |
| I5 | No edit is applied without a user action on a visible diff. Automatic drafts are never marked final without expert review | No auto-apply code path; draft status field |
| I6 | A capability whose gate has not passed stays behind a flag | CI check against the gate registry |
| I7 | Every expert change to machine-generated text is logged, locally | Edit-log hook on accept, reject and manual edit |
| I8 | Pattern fit is never presented as correctness | Naming rules + method text on every signal |
| I9 | Reports and corpus stay on the machine by default. Remote models are opt-in per session | Network guard in the analysis service |

---

## 4. System overview

```
┌────────────────────────────────────────────────────────────────┐
│  OFFLINE (per genre)                                           │
│  Reference corpus ─► move inventory ─► LLM labels ─► Pattern   │
│  of good reports      (expert)          + expert     model     │
│                                          validation            │
└───────────────────────────────┬────────────────────────────────┘
                                │ pattern model, exemplars, legend
┌───────────────────────────────▼────────────────────────────────┐
│  CLIENT                                                        │
│  Editor (Milkdown / ProseMirror) ◄── overlays (decorations)    │
│        │ transactions                    ▲ signals             │
│  Document model: markdown ⇄ doc · node IDs · hashes · dirty set│
└────────┬───────────────────────────────────────────────────────┘
         │ dirty nodes
┌────────▼───────────────────────────────────────────────────────┐
│  ANALYSIS SERVICE (local)                                      │
│                                                                │
│  FAST LAYER (every edit)        SLOW LAYER (in parallel)       │
│  embed ─► classifier head       LLM section review             │
│  move · sequence · register     confirms / corrects / explains │
│  · support candidates           · entailment checks            │
│        │   provisional                 │   confirmed           │
│        └──────────────┬────────────────┘                       │
│                       ▼                                        │
│              signals ─► client          labels ─► distillation │
│                                                                │
│  GENERATION                                                    │
│  exemplar retrieval ─► LLM candidates ─► critic ─► panel/diff  │
└────────┬───────────────────────────────────────────────────────┘
         │ accept / reject / manual edit
┌────────▼───────────────────────────────────────────────────────┐
│  EDIT LOG (local) ─► training pairs ─► fine-tuning (stage 2)   │
└────────────────────────────────────────────────────────────────┘
```

---

## 5. Subsystems

### 5.1 Reference corpus and source grounding

The corpus is the most important input: reports of one genre that a competent person has judged good. Everything the system knows about "good" comes from this selection.

- **Ingestion** converts reports to Markdown with the same document model the editor uses.
- **Move inventory** is seeded by the expert, refined with clustering and LLM suggestions, and finalized by the expert. Target: ten moves or fewer.
- **Labels** come from an LLM labeling every corpus sentence, validated against an expert-annotated sample.
- **Source items** are stored as first-class objects. Text spans link to the items they rest on.

→ `todo-09-corpus.md`

### 5.2 Document model

Unchanged in substance from revision 1: Markdown ⇄ ProseMirror with idempotent round-trip, persistent node IDs in a sidecar file, hierarchy derived from Markdown structure (section → block → sentence), content hashes and dirty sets. New: the sidecar also binds a document to a genre and stores span-to-source links.

→ `todo-03-document-model.md`

### 5.3 Embedding service

Local service with a content-hash cache. Sentences are the main unit. The model and chunking strategy are chosen by gate G-03, now measured on the tasks that matter here: move classification and exemplar retrieval. Per-level whitening is one arm of that gate and ships only if it wins.

→ `todo-02-embedding.md`

### 5.4 Pattern model

Four parts, each learned from the corpus:

1. **Move classifier.** A small supervised model on sentence embeddings. This is where the evidence is on our side: raw cosine similarity is a weak quality signal, but supervised models on embeddings work well.
2. **Sequence model.** Expected order of moves per section. Starts simple (transition statistics) so its judgments are explainable.
3. **Exemplar index.** Corpus passages indexed by genre, section and move, for retrieval during generation.
4. **Register profile.** What the genre sounds like, measured with style embeddings against the corpus and against default LLM output.

→ `todo-04-analysis.md`

### 5.5 Two-layer analysis

| | Fast layer | Slow layer |
|---|---|---|
| Method | Embeddings + classifier head | LLM with section context |
| Latency | Milliseconds | Seconds |
| Trigger | Every edit, changed sentence only | In parallel, edited section + uncertain sentences |
| Output status | Provisional | Confirmed |
| Cached by | Content hash | Content hash + context hash |

Rules:

- **Division of labour.** The fast layer owns stable properties (move label, similarity). The slow layer owns judgments and explanations. The slow layer mostly adds flags to a stable picture.
- **Triage.** Only uncertain sentences and edited sections go to the slow layer.
- **Staleness.** A slow result for text that has since changed is discarded.
- **Distillation.** Slow-layer labels retrain the classifier head, so the first approximation converges on the final answer.
- **Visibility policy** is set by the measured disagreement rate (gate G-04): low disagreement shows provisional results immediately; high disagreement hides them until confirmed.

→ `todo-04-analysis.md`

### 5.6 Signals

| Signal | Fast layer | Slow layer | Gate |
|---|---|---|---|
| **Move** | Classifier on the sentence embedding | LLM label with section context | G-01, G-04 |
| **Sequence fit** | Sequence model over move labels | LLM review of section structure | G-05 |
| **Register fit** | Style distance to the genre profile | LLM names the off-register feature | G-06 |
| **Support** | Retrieve candidate evidence for a conclusion | Entailment check | G-07 |
| **Redundancy** | Within-level similarity, across sections | LLM separates repetition from intentional recap | G-04 |
| **Topic** (optional overlay) | Within-level clusters | — | G-11 |

None of these is a quality score. Each is named for what it measures.

### 5.7 Frontend overlays

Colour is the expert's main channel.

- **Hue = move.** A fixed legend of a handful of colours per genre.
- **Second channel = fit.** Underline or saturation marks off-register, unsupported or out-of-place passages.
- **Provisional vs confirmed.** Fast-layer results render lighter or outlined; confirmed results render solid.
- **Granularity toggle.** Section: margin ribbon showing the move sequence, with markers for missing or misplaced moves. Paragraph and sentence: tint by move.
- **Inspector.** Hovering any mark explains what it means, how confident the system is and which layer produced it.
- **Off** is a first-class state.

→ `todo-05-visualization.md`

### 5.8 Editor

WYSIWYG Markdown on **Milkdown** (MIT, built on ProseMirror), with overlays as ProseMirror decorations. Formatting shortcuts inject Markdown; the author's stylistic conventions are preserved on save. No analysis feature can block typing.

→ `todo-06-editor.md`

### 5.9 Proposals and verification

**Generate.** For a selected passage: retrieve exemplars of the same move from the corpus, give them to the LLM with the passage and its section context, produce several candidates.

**Verify.** A panel of separate checks, never one score:

| Axis | Method |
|---|---|
| Move preserved | Classifier + slow-layer confirmation |
| Meaning preserved | Bidirectional entailment |
| Support preserved | Numbers, units and source links unchanged or still entailed |
| Register fit | Distance to the genre profile, before and after |
| Grammar | Grammar-correction model |
| Length delta | Reported, not judged |

A candidate that changes meaning is filtered (and countable, and viewable on request). Everything else is shown with its panel. The expert decides.

An LLM is not used as the final judge of a candidate's quality: position, verbosity and self-preference biases are well documented.

→ `todo-07-proposals.md`

### 5.10 Edit log

Every accept, reject and manual correction of machine text is stored locally as a pair with context: genre, section, move, the candidate, the final text, and the panel values. This is the dataset for fine-tuning and for measuring the remaining gap between LLM default style and the genre.

→ `todo-07-proposals.md`

### 5.11 Automatic drafting (stage 2)

```
source items ─► plan (move sequence from the pattern model)
             ─► per move: retrieve exemplars + relevant source items
             ─► generate candidates
             ─► critic: move · register · support against sources · numbers
             ─► assemble draft
             ─► expert review in the editor, overlays on weak spots
             ─► corrections ─► edit log
```

A generated sentence that cannot be traced to a source item is flagged, never silently kept. Fine-tuning on the edit log starts once enough pairs exist (gate G-10).

→ `todo-07-proposals.md`

### 5.12 Evaluation

Two tiers. **Own corpus:** expert-annotated moves, support links and blind preference judgments; this is what the gates run on. **Public benchmarks:** used only to check that components work at all.

→ `todo-08-evaluation.md`

---

## 6. Gates

Thresholds are proposals. Confirm or change each one before its run; after that it is fixed.

| ID | Question | Proposed threshold | If it fails |
|---|---|---|---|
| **G-01** | Can the genre's moves be recovered reliably? | Expert vs LLM κ ≥ 0.6; expert self-agreement κ ≥ 0.7 | Merge moves and retry once; then stop and rethink the premise |
| **G-02** | Do exemplars + critic steer LLM output toward the genre? | Expert prefers steered over baseline in ≥ 70 % of blind pairs | Fine-tuning becomes the only route; stage 1 continues as data collection |
| G-03 | Which embedding model and chunking strategy? | Beats baseline on move classification and exemplar retrieval | Use the best general-purpose model |
| G-04 | Is the fast layer close enough to the slow layer? | Disagreement ≤ 10 %: show provisional. Above 30 %: hide until confirmed | Slow layer only for that signal |
| G-05 | Does the sequence model find missing and misplaced moves? | Precision ≥ 0.7 at recall ≥ 0.5 on perturbed reports; ≤ 1 false flag per good report | Sequence fit from the slow layer only |
| G-06 | Does register fit separate genre text from default LLM text? | AUC ≥ 0.8 on content-controlled pairs | Register from the slow layer only |
| G-07 | Does support mapping find the evidence for a conclusion? | Recall@5 ≥ 0.8; unsupported-conclusion precision ≥ 0.6 | Manual linking only |
| G-08 | Does meaning-preservation checking agree with the expert? | Agreement ≥ 0.6; silent filter at ≥ 0.95 precision | Show every candidate, filter nothing |
| G-09 | Is the overlay legible and learnable? | Legend recall ≥ 90 % after one session; no significant reading penalty; colour-blind safe | Margin-only rendering |
| G-10 | Does fine-tuning on the edit log beat exemplars + critic? | Expert prefers it in blind pairs; no verbatim corpus leakage | Stay with exemplars + critic |
| G-11 | (Optional) Does a topic overlay add anything? | ≥ 3 findings the expert did not already know | Leave the overlay out |

G-01 and G-02 are fatal gates. Neither needs an editor.

→ `todo-01-experiments.md`

---

## 7. Execution model

Two tracks run in parallel.

- **Track E — engineering.** No research risk, mechanical acceptance checks, suited to agent execution: document model, editor, embedding service, cache, corpus ingestion, annotation tooling, harness.
- **Track R — research.** Gated on expert judgment: corpus selection, move inventory, annotation, blind comparisons, gate verdicts.

Every task in the todo files is marked:

| Marker | Meaning |
|---|---|
| `[A]` | Agent-executable. Has a stated mechanical check |
| `[H]` | Human-gated. Needs the expert's judgment |
| `[A→H]` | Agent prepares, human decides |

The scarce resource is expert attention, so `[H]` tasks define the critical path.

---

## 8. Technology stack

| Layer | Choice | Reason |
|---|---|---|
| Editor | Milkdown (ProseMirror) | Open source, WYSIWYG Markdown, decorations |
| Markdown | remark / mdast | Real AST, round-trip control |
| Sentence splitting | PySBD or spaCy | Regex splitting breaks on abbreviations and decimals |
| Embeddings | BGE-M3, Jina v3 or similar (G-03 decides) | Local, long context |
| Classifier head | Logistic regression or small MLP, exported to ONNX | Fast, retrainable, inspectable |
| Sequence model | Transition statistics first | Explainable flags |
| Register | Style embeddings (LUAR, StyleDistance) + corpus-vs-LLM classifier | Measures the taste gap directly |
| Entailment | Local NLI model | Support and meaning checks |
| LLM | Any local model behind an OpenAI-compatible endpoint | Local by default (I9) |
| Fine-tuning | LoRA adapters | Small data, cheap to retrain |
| Storage | LMDB for vectors, SQLite for labels and edit log | Embedded, no server |
| App shell | Tauri or Electron | Local files and models |

---

## 9. Phasing

| Phase | Track R (human-gated) | Track E (agents) | Exit criterion |
|---|---|---|---|
| **0** | Corpus selection, move inventory, annotation, **G-01**, **G-02** | Harness, corpus ingestion, annotation tool, document model, embedding service | Both fatal gates pass, or stop |
| **1** | G-03, G-05, G-06 | Pattern model: classifier, sequence model, exemplar index, register profile | Pattern model reproduces expert labels on held-out reports |
| **2** | G-09 | Editor, overlays, legend | Expert can read a report's structure from the overlay |
| **3** | G-04 | Two-layer live analysis, distillation loop | Live overlay is stable and trusted |
| **4** | G-07, G-08 | Proposals, verification panel, edit log | Stage 1 complete: assisted writing in daily use |
| **5** | Blind review of drafts | Source grounding, automatic drafting, review flow | Expert accepts drafts with bounded corrections |
| **6** | G-10 | Fine-tuning pipeline from the edit log | Fine-tuned model beats exemplars + critic, or is dropped |
| **7** | — | Hardening, packaging | — |

---

## 10. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| The genre is less regular than assumed | **fatal** | G-01 first |
| Steering does not overcome LLM default style | high | G-02; fine-tuning as fallback |
| Corpus too small or unevenly good | high | Expert selection; split by document; report sample sizes with every result |
| LLM labels are wrong and distillation spreads the error | high | Expert validation sample; classifier never trained on labels the expert has overturned |
| Pattern fit mistaken for correctness | high | I8; support checks as a separate signal |
| Layers disagree visibly and erode trust | medium | Provisional vs confirmed rendering; G-04 visibility policy |
| Output becomes formulaic beyond what the genre requires | medium | Register target is the corpus, not a template; expert review of drafts |
| Confidential reports leave the machine | medium | I9 |

---

## 11. Non-goals

- Collaborative editing, cloud sync, accounts
- A general writing assistant for arbitrary prose
- Word-level attribution
- Any claim that the tool measures writing quality or factual correctness
- Retrieval across a note vault
