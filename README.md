# Semantic Text Workbench

A WYSIWYG Markdown editor that learns the **patterns of a report genre** from good examples, shows an expert how a draft fits those patterns, and proposes edits in the genre's own style. The longer-term aim is to draft such reports automatically, with the expert reviewing.

Markdown is the storage format. It is never shown raw: formatting shortcuts (`Ctrl+I`, `Ctrl+B`, `Ctrl+K`, `#`) apply styling in the editor and inject the corresponding Markdown into the file.

---

## Premise

Good reports in one genre follow recurring patterns: a fixed format, an expected sequence of functional steps (**moves**) such as observation, evidence, interpretation and conclusion, and a particular register. A general-purpose LLM writes in its own default style instead.

Those patterns can be learned from a corpus of good reports and used in three ways:

1. **Show** the expert how a draft fits the pattern.
2. **Steer** LLM output toward the genre.
3. **Collect** the expert's corrections as training data for automatic writing.

---

## Two stages

| Stage | What the system does | What the expert does |
|---|---|---|
| **1. Assisted writing** | Overlays and on-request rewrite proposals | Writes; accepts, rejects or corrects proposals |
| **2. Automatic writing** | Drafts the report from source material | Reviews and corrects the draft |

---

## Core features

### Pattern overlays

Colour is the main channel. Each move has a fixed colour per genre, so the legend is learned once.

| Level | What is shown |
|---|---|
| Section | Margin ribbon with the sequence of moves; markers for missing or misplaced moves |
| Paragraph, sentence | Tint by move |
| Second channel | Underline or saturation for off-register, unsupported or out-of-place passages |

### Two-layer analysis

- **Fast layer:** embeddings plus a small classifier. Runs on every edit, gives a first approximation in milliseconds.
- **Slow layer:** an LLM reviews the section in parallel and confirms or corrects.

First-approximation results render as provisional, confirmed results as solid. The slow layer's verdicts retrain the fast layer, so the two converge over time.

### Edit proposals

On request, the system retrieves passages performing the same move in good reports, generates rewrites conditioned on them, and shows each candidate as a diff with a panel of separate checks: move preserved, meaning preserved, support preserved, register fit, grammar. There is no combined score and no auto-apply.

### Edit log

Every correction of machine text is stored locally as a before-and-after pair. This is the training data for stage 2.

---

## What the tool does not claim

- **Pattern fit is not correctness.** A report can follow the format and be wrong. Support for conclusions is checked separately.
- **No quality score.** Each signal is named for what it measures and shows its confidence.

---

## Documents

| File | Content |
|---|---|
| [`architecture.md`](docs/architecture.md) | Design, invariants, gates, stack, phasing |
| [`todo.md`](docs/todo.md) | Master tracker |
| [`todo-01-experiments.md`](docs/todo-01-experiments.md) | Gates G-01 to G-11 |
| [`todo-02-embedding.md`](docs/todo-02-embedding.md) | Embedding service and cache |
| [`todo-03-document-model.md`](docs/todo-03-document-model.md) | Markdown round-trip, node identity |
| [`todo-04-analysis.md`](docs/todo-04-analysis.md) | Pattern model and two-layer analysis |
| [`todo-05-visualization.md`](docs/todo-05-visualization.md) | Overlays and legend |
| [`todo-06-editor.md`](docs/todo-06-editor.md) | Editor and app shell |
| [`todo-07-proposals.md`](docs/todo-07-proposals.md) | Proposals, verification, edit log, automatic drafting |
| [`todo-08-evaluation.md`](docs/todo-08-evaluation.md) | Evaluation harness |
| [`todo-09-corpus.md`](docs/todo-09-corpus.md) | Reference corpus, annotation, source items |

---

## Development order

1. **Fatal gates first, without an editor.** G-01: can the genre's moves be recovered reliably from the corpus? G-02: do exemplars plus a critic move LLM output toward the genre, judged blind by the expert?
2. **In parallel:** the engineering with no research risk (document model, editor, embedding service).
3. **Then:** pattern model, overlays, two-layer analysis, proposals, automatic drafting, fine-tuning.
