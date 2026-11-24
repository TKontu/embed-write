# TODO — Reference Corpus, Annotation & Source Items

**Phase:** 0 (starts first)
**Track:** R for selection and annotation, E for tooling
**Blocks:** G-01, G-02 and the whole pattern model

Markers: `[A]` agent-executable with a mechanical check · `[H]` needs the expert's judgment · `[A→H]` agent prepares, human decides.

The corpus defines what "good" means for a genre. The selection is the single most important input to the project, and it cannot be delegated.

---

## Corpus

- [ ] **CO-01** `[H]` Choose the first genre. One report type only
- [ ] **CO-02** `[H]` Select the reference reports: ones a competent person judges good. Proposed minimum 20 to start; more is better. Record who judged and why
- [ ] **CO-03** `[H]` Decide confidentiality handling: which reports may be used, whether anything must be redacted
- [ ] **CO-04** `[A]` Ingestion: convert PDF, Word or other formats to Markdown through the document model — check: every report parses, round-trips, and has a section tree
- [ ] **CO-05** `[A→H]` Conversion quality: agent lists reports with suspicious output (broken tables, merged columns, lost headings); the expert spot-checks
- [ ] **CO-06** `[A]` Metadata per report: genre, date, author role, language, length — check: schema validation
- [ ] **CO-07** `[A]` Near-duplicate and boilerplate detection (templates, disclaimers, repeated headers) — check: flagged passages listed for review
- [ ] **CO-08** `[A]` Train / dev / test split **by document**, fixed and versioned — check: no report appears in two splits
- [ ] **CO-09** `[A]` Corpus statistics: section headings in use, section lengths, sentence counts — check: report generated
- [ ] **CO-10** `[A]` Network guard: corpus processing fails closed if a remote endpoint is configured without explicit opt-in (invariant I9) — check: test with a remote URL fails

---

## Move inventory

- [ ] **MV-01** `[H]` Seed list of moves from the expert's own understanding of the genre
- [ ] **MV-02** `[A]` Discovery support: cluster sentence embeddings per section type; LLM proposes a name and definition per cluster — check: cluster report with example sentences
- [ ] **MV-03** `[H]` Finalize the inventory: ten moves or fewer, each with a one-sentence definition, two positive examples and one near-miss
- [ ] **MV-04** `[H]` Assign a colour to each move (the legend, invariant I3)
- [x] **MV-05** `[A]` Store inventory, definitions and legend as a versioned genre file — check: schema validation; a change bumps the version and invalidates dependent labels
  - done (R41/A1, PR #102): `service/genre.py` (GenreFileError, validate_genre, load_genre, content_hash, check_version_bump, version_key, labels_valid_for); stdlib-only; synthetic LLM-built fixture. seen: tests/test_genre.py (21 tests), gate 657 tests OK at head db7c7d01828c6b1fc3b41d7f2b4bb402d7e982ed. Unwired by design until LG-02 and AN-01/G-01.4. Residuals: schema provisional until MV-03/MV-04 [H]; `_`-prefixed keys inside legend.colors fail validation as unknown moves (docstring says comments are ignored).
  - follow-up (R42/A1, PR #104): `_`-prefixed comment keys inside legend.colors are now ignored, as the module docstring says; content_hash unchanged. seen: tests/test_genre.py::test_legend_comment_key_ignored, gate 658 tests OK at head 93520a8a27c91d44edf3429598948e9909003021

---

## Annotation

- [ ] **AN-01** `[A]` Annotation tool: one sentence at a time with its section context, keyboard-driven, move or `other` — check: export matches the label schema; session resumable
- [ ] **AN-02** `[A]` Sampling: stratified over reports and section types, from held-out documents — check: sample manifest
- [ ] **AN-03** `[H]` Annotate ~300 sentences with moves (feeds G-01)
- [ ] **AN-04** `[H]` Re-annotate a 10 % sample after a week (self-agreement)
- [ ] **AN-05** `[H]` For ~50 conclusions, mark supporting passages and source items (feeds G-07)
- [ ] **AN-06** `[H]` Label ~200 rewrite pairs as meaning-preserving or not (feeds G-08)
- [ ] **AN-07** `[A]` Annotation store, versioned, tied to the inventory version — check: labels from an old inventory version are never mixed in silently

---

## LLM labeling

Runs corpus-wide only after G-01 passes.

- [ ] **LB-01** `[A]` Labeling prompt built from the inventory file (definitions, examples, near-misses) with section context
- [ ] **LB-02** `[A]` Label every corpus sentence; store label, confidence and model version — check: coverage 100 %, labels within the inventory
- [ ] **LB-03** `[A]` Consistency pass: label twice with different sentence order; record disagreements
- [ ] **LB-04** `[A]` Expert-overturned labels take precedence and are excluded from classifier training in their LLM form — check: unit test
- [ ] **LB-05** `[A]` Relabel automatically when the inventory version changes

---

## Source items

Needed for support mapping (stage 1) and for automatic drafting (stage 2).

- [ ] **SR-01** `[H]` Decide what counts as a source item in this genre: measurements, test results, observations, photos with notes, referenced documents
- [ ] **SR-02** `[A]` Schema: `{id, type, content, units, provenance}` — check: schema validation
- [ ] **SR-03** `[A]` Import paths: tables (CSV, spreadsheet), structured notes, image captions — check: import round-trip on sample files
- [ ] **SR-04** `[A]` Number-and-unit extraction from report text for matching against source items — check: unit tests on decimals, ranges, tolerances and unit variants
- [ ] **SR-05** `[A→H]` For a few corpus reports where the underlying data is available, reconstruct the source items; the expert confirms they are faithful

---

## Acceptance criteria

- One genre with a selected, versioned corpus and a fixed document-level split
- A finalized move inventory with definitions, examples and legend
- Expert annotations stored against an inventory version
- Corpus-wide LLM labels exist only after G-01 has passed
- Nothing in this pipeline can reach a remote endpoint without explicit opt-in
