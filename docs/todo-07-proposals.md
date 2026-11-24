# TODO — Proposals, Verification, Edit Log & Automatic Drafting

**Phase:** 4 (proposals, edit log), 5 (automatic drafting), 6 (fine-tuning)
**Track:** E for implementation, R for the gates and reviews
**Gated by:** G-02 (steering works), G-07, G-08, G-10
**Depends on:** pattern model, exemplar index, editor

Markers: `[A]` agent-executable with a mechanical check · `[H]` needs the expert's judgment · `[A→H]` agent prepares, human decides.

Stage 1 proposes rewrites and logs what the expert does with them. Stage 2 drafts whole reports from source material. Both use the same generate-and-check loop; the edit log is what connects them.

**Hard rules:** no edit is applied without a user action on a visible diff, and no automatic draft is marked final without expert review (invariant I5). There is no combined quality score.

---

## Generation

- [ ] **GE-01** `[A]` Context assembly: the passage, its section, its move, and the neighbouring passages
- [ ] **GE-02** `[A]` Exemplar conditioning: retrieve passages performing the same move in the same section type and pass them as examples — check: exemplars never come from the current document
- [ ] **GE-03** `[A]` Several candidates per request with varied sampling; near-duplicates removed — check: pairwise similarity below a cutoff
- [ ] **GE-04** `[A]` Local LLM through an OpenAI-compatible endpoint; remote models only with explicit per-session opt-in (invariant I9)
- [ ] **GE-05** `[A]` Streaming and cancellation
- [ ] **GE-06** `[A]` Generation run records: prompt, exemplars used, model version, candidates — check: every candidate is reproducible from its record

---

## Critic and verification panel

Each axis is a separate, separately validated check. They are shown side by side and never combined.

- [ ] **VF-01** `[A]` **Move preserved:** classifier plus slow-layer confirmation that the candidate performs the intended move
- [ ] **VF-02** `[A]` **Meaning preserved:** bidirectional entailment *(G-08)*
- [ ] **VF-03** `[A]` **Support preserved:** numbers, units and source links unchanged or still entailed — check: unit tests on altered values
  - partial (R35/A1, PR #90): literal check `service/support_check.py` (numbers with units, percentages, link targets, citation keys; multiset diff, reporting only) merged; unwired until VF-07; residuals: "still entailed" path (e.g. "five" vs "5", converted units) waits for VF-02/G-08; fixed unit list; currency only matched after the number
- [ ] **VF-04** `[A]` **Register fit:** distance to the genre profile before and after *(G-06)*
- [ ] **VF-05** `[A]` **Grammar:** grammar-correction model
- [ ] **VF-06** `[A]` **Length delta:** reported, not judged
- [ ] **VF-07** `[A]` Panel: each axis with value, confidence and method link
- [ ] **VF-08** `[A]` Filter: only candidates failing meaning preservation at the G-08 threshold are hidden; a counter shows how many, and they can be viewed
- [ ] **VF-09** `[A]` Critic rerank for generation: candidates ordered by move and register fit, subject to the filters. The ordering is a default, not a verdict
- [ ] **VF-10** `[A]` No aggregate score anywhere — check: lint for score-combining code in this module
- [ ] **VF-11** `[A]` Method text stating why an LLM is not the final judge of candidate quality (position, verbosity and self-preference bias)

---

## Interaction

- [ ] **UX-01** `[A]` Diff-first: word-level diff visible before any accept
- [ ] **UX-02** `[A]` Accept, reject, or edit then accept; reject is one keystroke
- [ ] **UX-03** `[A]` Proposals on request only; no unprompted ghost text
- [ ] **UX-04** `[A]` Undo restores the original exactly — check: document hash equal after accept and undo
- [ ] **UX-05** `[A]` Acceptance statistics shown to the expert, locally
- [ ] **UX-06** `[H]` Review of the proposal flow after a week of real use

---

## Edit log

- [x] **EL-01** `[A]` Schema: genre, section type, move, original text, candidate, final text, action (accept, reject, edit), panel values, generation run ID, timestamp — check: schema validation
  - done (R43/A1, PR #106): `editlog/schema.py` EditLogEntry + validate_entry. Unwired by design until EL-02. seen: tests/test_editlog_schema.py, gate 671 tests OK at head 59d5da846a50f421af04866fcd9c6ddbf77dc7b0
- [ ] **EL-02** `[A]` Capture on accept, reject and any later manual edit of machine text (invariant I7) — check: provenance change without a log entry fails a test
- [x] **EL-03** `[A]` Local SQLite store; nothing leaves the machine
  - done (R43/A1, PR #106): `editlog/store.py` EditLogStore, append-only, one transaction per append, streaming iter_entries, rejects URI/network paths. Unwired by design until EL-02. Residual: tuples in panel_values round-trip as lists. seen: tests/test_editlog_store.py, gate 671 tests OK at head 59d5da846a50f421af04866fcd9c6ddbf77dc7b0
- [x] **EL-04** `[A]` Pair extraction for training: machine text before, expert text after, with context
  - done (R44/A1, PR #108): `editlog/pairs.py` iter_training_pairs streams a frozen TrainingPair per accept/edit entry (candidate → final_text plus context and entry id). Unwired by design; G-10 fine-tuning consumes it. seen: tests/test_editlog_pairs.py, gate 676 tests OK at head e4871a96a9d79f39718f7d42b835c810c0206370
- [x] **EL-05** `[A]` Rejections kept as negatives
  - done (R44/A1, PR #108): `editlog/pairs.py` iter_negatives streams a frozen NegativeRecord per reject entry; rejects never become pairs. Unwired by design; G-10 fine-tuning consumes it. seen: tests/test_editlog_pairs.py, gate 676 tests OK at head e4871a96a9d79f39718f7d42b835c810c0206370
- [x] **EL-06** `[A]` Gap report: which moves and which register features the expert corrects most often
  - done (R45/A1, PR #110): `editlog/gaps.py` gap_report streams iter_entries once into a frozen GapReport: per move and per (section_type, move) accept/edit/reject and `revised` (edit + reject; named so for I8), plus added/removed counts for an injected register-feature callable on edit entries. Unwired by design; the expert-facing view is a later row and no feature extractor exists yet. seen: tests/test_editlog_gaps.py, gate 684 tests OK at head 2b7bf2c489e88e28acc13b17120de7ca7112a978
- [ ] **EL-07a** `[A]` Export control for the expert: whole edit log to JSON Lines (`python3 -m editlog.export DB_PATH OUT_PATH [--force]`; atomic, 0600, no overwrite without --force) — check: tests/test_editlog_export.py
- [ ] **EL-07b** `[A]` Delete control for the expert — blocked on operator ruling EL-07-delete (delete semantics vs. the append-only store)

---

## Automatic drafting *(stage 2)*

- [ ] **AD-01** `[A]` Planner: move sequence per section from the pattern model for the chosen genre
- [ ] **AD-02** `[A]` Source selection: which source items feed each move
- [ ] **AD-03** `[A]` Per-move generation with exemplars and the selected source items
- [ ] **AD-04** `[A]` Grounding check: every generated sentence with a factual claim links to a source item; unlinked sentences are flagged, never silently kept — check: test with a deliberately unsupported sentence
- [ ] **AD-05** `[A]` Number check: every number and unit in the draft matches a source item — check: unit tests
- [ ] **AD-06** `[A]` Assembly into a Markdown document with provenance `machine` on every block
- [ ] **AD-07** `[A]` Draft status: `draft` until the expert marks it reviewed (invariant I5) — check: no code path sets `reviewed` without a user action
- [ ] **AD-08** `[A]` Review flow: the editor opens the draft with overlays on and the open-issues list sorted by severity
- [ ] **AD-09** `[H]` Blind review of drafts against reference reports for the same source material
- [ ] **AD-10** `[A]` Correction metrics per draft: share of sentences edited, by move

---

## Fine-tuning *(stage 2, G-10)*

- [ ] **FT-01** `[A]` Training-set builder from corpus plus edit-log pairs, split by document
- [ ] **FT-02** `[A]` LoRA training job with pinned configuration
- [ ] **FT-03** `[A]` Leakage test: verbatim overlap with training text
- [ ] **FT-04** `[A]` Adapter versioning; rollback to exemplars + critic
- [ ] **FT-05** `[H]` Blind comparison for G-10

---

## Acceptance criteria

- No code path applies an edit or finalizes a draft without a user action
- Every panel axis traces to a method with its limits stated
- No aggregate score exists in code or UI
- Every expert action on machine text is in the edit log
- Every factual sentence in an automatic draft links to a source item or is flagged
