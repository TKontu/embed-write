# Expert run sheet: G-01 and G-02

One page, in order, for every step the expert (and the operator before them) owes for the two
fatal gates. Each step says what it decides or produces, the exact command, what it reads and
writes, and how to tell it worked. Commands are the lines the tools print themselves (intake
`next_steps`, `g02_session` "serve:", the drafts' "draft written:") with paths replaced by
placeholders.

**Placeholders.** `<PRIVATE:...>` is a path on the expert's machine that holds corpus text,
labels or judgments. Keep it out of git, PRs and chat. `<...>` without `PRIVATE` is a plain value
(a URL, a model name, a seed). Run every command from the repository root with the project's
`.venv` active. `tests/test_expert_run_sheet.py` checks that every command below still names a
real module and only flags it accepts.

## Part 0. Blockers: nothing below runs until these are settled

| # | Blocker | Owner | Done when |
| - | ------- | ----- | --------- |
| B1 | Corpus ruling and size (`input-causeries`, `corpus-size`): which reports may be used and whether there are enough | operator | a folder of allowed reports exists at `<PRIVATE:REPORTS_DIR>` |
| B2 | A local LLM on a loopback OpenAI-compatible endpoint (`local-llm`) | operator | `<MODEL_URL>` (e.g. `http://127.0.0.1:PORT/v1`) answers; its name is `<MODEL_NAME>` |
| B3 | MV-01 seed list of moves in the genre file | expert | `genre_scaffold check` exits 0 (step 0.1) |
| B4 | G-01.1 and G-02.1 thresholds confirmed | expert | step 0.2 records exist with `confirmed_by` filled |
| B5 | Optional: real embedder for move discovery and section inference | operator | `EMBED_WRITE_MODEL_DIR` names a local ONNX model directory (else a development stub is used and intake says so) |

### 0.1 Write the genre file (MV-01, expert)

- Produces: the move inventory both gates label and generate against.
- Command (once, then edit the file by hand):
  `python -m service.genre_scaffold new <PRIVATE:GENRE.json> --name <GENRE_NAME> --moves <N>`
- Check: `python -m service.genre_scaffold check <PRIVATE:GENRE.json>`
- Worked: exit 0. Exit 1 lists placeholders still unfilled; exit 2 means the file is invalid.

### 0.2 Confirm the thresholds (G-01.1, G-02.1, expert)

- Decides: the pass line each gate is judged against. Proposed: G-01 expert vs LLM κ ≥ 0.6,
  expert self-agreement κ ≥ 0.7, `other` ≤ 15 %; G-02 see `docs/todo-01-experiments.md` G-02.
- Command: none (no tool writes this; see Gaps). The expert writes
  `experiments/preregistration/g01.json` and `experiments/preregistration/g02.json` by hand with
  the fields in `experiments/preregistration/README.md` (`gate`, `threshold`, `metric`,
  `confirmed_by`, `confirmed_at`). Only the expert fills `confirmed_by`.
- Worked: the draft steps (1.5, 2.6) run instead of exiting 2 with "preregistration not confirmed".

## Part 1. G-01: can moves be labelled reliably?

### 1.1 Intake (operator or expert)

- Produces: converted reports, a sentence sample to annotate, LLM pre-labels, and the next
  command lines.
- Command:
  `python -m experiments.intake run <PRIVATE:REPORTS_DIR> <PRIVATE:OUT> --genre <PRIVATE:GENRE.json> --model-url <MODEL_URL> --model-name <MODEL_NAME>`
- Reads: the reports folder, the genre file, the local LLM. Writes under `<PRIVATE:OUT>`:
  `converted/`, `manifest.json`, `prelabels.jsonl`, `sections.json`, `boilerplate.json`,
  `intake_report.json`.
- Worked: `intake_report.json` shows `annotation_sample` and `prelabel` as `ok` and lists
  `next_steps`. Copy commands from there; they hold the real paths. If `prelabel` is `skipped`,
  `--model-url` was missing and the G-01 draft line is not printed.

### 1.2 Review the boilerplate flags (CO-07, expert, only if intake printed this line)

- Decides: whether flagged templates/disclaimers are boilerplate.
- Command: `python -m experiments.boilerplate review <PRIVATE:OUT>/boilerplate.json`
- Worked: the flags print to the terminal. Nothing is written.

### 1.3 Check inferred section boundaries (CO-14, expert, only if intake printed it)

- Decides: whether provisional sections in reports with no headings are right.
- Command (printed per report): `cd editor && npm run demo -- --report <PRIVATE:REPORT> --sections <PRIVATE:OUT>/sections.json`
- Worked: the editor opens the report with inferred sections marked provisional.

### 1.4 Annotate, first pass then repeat (G-01.2 and G-01.3, expert)

- Produces: the expert's own move labels, blind (no LLM pre-labels shown).
- First pass (about 300 sentences):
  `python -m experiments.annotate --manifest <PRIVATE:OUT>/manifest.json --corpus <PRIVATE:OUT>/converted --genre <PRIVATE:GENRE.json> --store <PRIVATE:OUT>/annotations.jsonl --annotator EXPERT`
- Repeat pass, **at least a week later** (10 % sample, nothing shown from the first pass):
  `python -m experiments.annotate --manifest <PRIVATE:OUT>/manifest.json --corpus <PRIVATE:OUT>/converted --genre <PRIVATE:GENRE.json> --store <PRIVATE:OUT>/annotations.jsonl --annotator EXPERT --pass repeat`
- Reads: manifest, converted reports, genre. Writes: appends to `annotations.jsonl`.
- Worked: the tool reports every item labelled. Do not add `--prelabels`: labels made with
  pre-labels shown are non-blind and G-01 drops them.

### 1.5 G-01 DRAFT result (agent half of G-01.6; run by expert or operator)

- Produces: κ expert vs LLM and expert vs self with intervals, confusion matrix, `other` share.
- Command (intake prints it):
  `python -m experiments.g01_draft --store <PRIVATE:OUT>/annotations.jsonl --genre <PRIVATE:GENRE.json> --manifest <PRIVATE:OUT>/manifest.json --prelabel <PRIVATE:OUT>/prelabels.jsonl --annotator EXPERT --model-id <MODEL_ID> --seed 0 --out <PRIVATE:OUT>/g01-draft`
- Reads: labels, pre-labels, `experiments/preregistration/g01.json`. Writes
  `g01-draft.json` and `g01-draft.md` (refuses anything under `experiments/results/`).
- Worked: prints `draft written: ... (verdict owed to the expert)`. Exit 2 names what is missing
  (unconfirmed preregistration, or no expert/LLM pairs).

### 1.6 G-01 verdict (G-01.6, expert)

- Decides: pass or fail against the confirmed threshold. The draft's `verdict_hint` is a hint,
  not a verdict; the draft says "Verdict: owed to the expert".
- Command: none. The expert reads `g01-draft.md` and records the verdict; only then does
  `experiments/results/G-01.md` get written. If it fails: merge the most-confused moves and rerun
  once (steps 0.1, 1.4, 1.5).

## Part 2. G-02: does retrieval help generation?

Uses the same corpus split as intake: keep `--split-seed` and `--test-fraction` equal to the
intake run (intake defaults: 0 and 0.5).

### 2.1 Neutral notes for ~30 held-out sections (G-02.2, agent; expert checks a sample)

- Produces: facts-only notes per section, a leak review, and the private originals file.
- Command:
  `python -m experiments.g02_notes --corpus <PRIVATE:OUT>/converted --genre <PRIVATE:GENRE.json> --split-seed 0 --test-fraction 0.5 --model-url <MODEL_URL> --model-name <MODEL_NAME> --out <PRIVATE:G02>/notes.jsonl --sections-out <PRIVATE:G02>/originals.jsonl`
- Writes: `notes.jsonl`, `notes.jsonl.review.json`, `originals.jsonl` (corpus text, 0600).
- Worked: prints a `pool:` line (step 2.2), a `next:` line (step 2.3), then
  `{"selected": 30, "written": ..., "records": 30, "flagged": ...}` and exits 0. An incomplete run
  exits 1 and prints neither line.
- Expert: read the sample in `notes.jsonl.review.json` and decide whether notes leak phrasing.

### 2.2 Exemplar pool (agent)

- Produces: `<PRIVATE:G02>/g02_pool.jsonl`, sections of training-split reports only as
  `{section_id, report_id, section_type, text}` (corpus text, 0600, never overwritten).
- Command (the `pool:` line g02_notes prints; same split values as 2.1):
  `python -m experiments.g02_pool --corpus <PRIVATE:OUT>/converted --genre <PRIVATE:GENRE.json> --split-seed 0 --test-fraction 0.5 --min-words 40 --out <PRIVATE:G02>/g02_pool.jsonl`
  Optional `--max-per-type N` caps sections per type.
- Worked: prints `{"written": ..., "reports": ..., "section_types": {...}}` and exits 0. Exit 2
  means the output exists or a held-out report would have entered the pool; nothing is written.

### 2.3 Generate three arms (G-02.3, agent)

- Command (the `next:` line g02_notes prints):
  `python -m experiments.g02_generate --notes <PRIVATE:G02>/notes.jsonl --pool <PRIVATE:G02>/g02_pool.jsonl --out <PRIVATE:G02>/generations.jsonl --originals <PRIVATE:G02>/originals.jsonl --model-url <MODEL_URL> --model-name <MODEL_NAME>`
- Worked: prints a JSON summary with `complete: true` (30 sections × arms A, B, C, no
  same-report exemplars).

### 2.4 Build the blind session (G-02.4 enabler, agent)

- Command:
  `python -m experiments.g02_session --generations <PRIVATE:G02>/generations.jsonl --originals <PRIVATE:G02>/originals.jsonl --out <PRIVATE:G02>/session.json --choices <PRIVATE:G02>/choices.jsonl`
- Worked: prints model, sections, pairs, per-comparison counts and a `serve:` line. Exit 2 says
  what is incomplete and writes nothing.

### 2.5 Blind judgments (G-02.4, expert)

- Decides: for each pair, which text is better (A vs C, A vs B, C vs original), without knowing
  which arm is which.
- Command (the `serve:` line):
  `python -m experiments.blind_ui <PRIVATE:G02>/session.json <PRIVATE:G02>/choices.jsonl`
- Worked: prints `Open http://127.0.0.1:PORT/`; each choice appends to `choices.jsonl`. Stop
  with Ctrl-C and resume later with the same line.

### 2.6 G-02 DRAFT result (agent half of G-02.5)

- Command:
  `python -m experiments.g02_draft --session <PRIVATE:G02>/session.json --choices <PRIVATE:G02>/choices.jsonl --out <PRIVATE:G02>/g02-draft --seed 0 --text-model <MODEL_NAME> --judge-is-expert`
- Reads: session, choices, `experiments/preregistration/g02.json`. Writes `g02-draft.json`
  and `g02-draft.md`. Use `--judge-is-expert` only when the expert made every choice.
- Worked: prints `draft written: ... (verdict owed to the expert)`.

### 2.7 G-02 verdict (G-02.5, expert)

- Decides: pass or fail. The DRAFT's hint uses the proposed 0.70, not the confirmed threshold;
  the draft says "Verdict: owed to the expert (G-02.5 [H])". The expert records the verdict; only
  then does `experiments/results/G-02.md` get written.

## Gaps: steps no tool prints

- No tool writes the preregistration records (0.2); they are hand-written JSON.
- Intake prints no G-02 line: step 2.1 is typed by hand, and nothing checks its `--split-seed` and
  `--test-fraction` match the intake run. From 2.1 on each tool prints the next line
  (`pool:`/`next:`, `next:`, `serve:`, `after judging:`).
- `g01_draft` line from intake has `--seed 0` and `--annotator EXPERT` fixed; the printed
  `g02_draft` line has `--seed 0` and `--text-model` from the generation run.
- The G-02 hint cannot read the confirmed threshold; the repeat-pass week gap is not enforced.
