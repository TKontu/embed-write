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
  - partial (R59/A3, PR #159, merge 1b4430b): generation/context.py Passage/Section/GenerationContext and build_context(section, passage_id, k, max_chars) - immutable section-local window of up to k neighbours each side, character budget over the whole rendered prompt drops neighbours farthest-first (following first on ties), core never truncated (raises), render_prompt() deterministic string for LLMClient.complete. seen: tests/test_context_assembly.py 8 tests OK (gate 940 OK) at head 6ac44f2662172b6bbfe05754825bb0b35a8f756f, incl. fake-transport pass through llm_client. Unwired by design until GE-03/GE-04 proposal flow; stays partial until that flow exercises it. Residuals: caller supplies the section (no corpus retrieval/exemplars, GE-02); no live local model; very large sections not load-tested.
- [ ] **GE-02** `[A]` Exemplar conditioning: retrieve passages performing the same move in the same section type and pass them as examples — check: exemplars never come from the current document
  - partial (R60/A1, PR #161, merge f05ab89): generation/exemplars.py Exemplar, select_exemplars (exact section_type+move, current document excluded, stream order, lazy stop at limit, invalid limit raises) and render_prompt (unchanged GE-01 prompt + deterministic JSON exemplars, ordered ids for GenerationRunRecord). seen: tests/test_exemplars.py 9 tests OK (gate 958 OK) at head 7d79bb49ad1afdfa0444e9b8543fd287774e87a0. Unwired by design until GE-03/GE-04. Residuals: caller supplies the candidate stream and labels (no store retrieval or similarity ranking); text sizes uncapped; no live local model.
- [ ] **GE-03** `[A]` Several candidates per request with varied sampling; near-duplicates removed — check: pairwise similarity below a cutoff
  - partial (R57/A2, PR #152, merge 25df765): generation/candidates.py vary_sampling(base, n) (seeds base..base+n-1, temperatures in [0.2, 1.0]) and remove_near_duplicates(candidates, vectors, cutoff) (order-preserving greedy, kept pairs below cutoff, cross-level raises); unwired by design until GE-04. seen: tests/test_candidates.py 12 tests OK (combined gate 910 OK) at head 5913d718a12055744070be038a0166e2e862555e. Residuals: production cutoff not chosen (caller supplies); no request-size cap, large-request performance untested; synthetic LLM-built vectors only.
  - partial (R63/A2, PR #165, merge de5a99c): generation/propose.py propose(context, exemplars, *, client, base_sampling, n, embed, cutoff, current_document_id, section_type, exemplar_limit) -> frozen Proposal(record, kept candidates, aligned panels, dropped_count): render_prompt (GE-01/02) -> vary_sampling -> one sequential complete() per setting -> GenerationRunRecord of all raw candidates (GE-06) -> one embed call -> remove_near_duplicates -> build_panel per kept (VF-07); returns data only (I5); LLMClient gained read-only `model`. This is the proposal flow GE-01/02/04/06 and VF-07 waited on at library level; each stays partial until UX-01 wires it and a live local model runs it. seen: tests/test_propose.py 10 tests OK (gate 978 OK, rerun by planner) at head 45a54cf7d7cb477b78c48bfab1ccf61359996466. Unwired by design until UX-01. Residuals: no request-size cap beyond vary_sampling's n check; synthetic fake client/embedder only; production cutoff and embedder not chosen.
- [ ] **GE-04** `[A]` Local LLM through an OpenAI-compatible endpoint; remote models only with explicit per-session opt-in (invariant I9)
  - partial (R58/A1, PR #154, merge 0afd7c4): generation/llm_client.py stdlib OpenAI-compatible chat client; loopback-only by default (localhost pinned to 127.0.0.1, literal loopback IPs), remote only with per-instance allow_remote; proxies ignored, redirects refused, 4 MiB bounded read, malformed responses raise without echoing the body. seen: tests/test_llm_client.py 8 tests OK (gate 918 OK) at head b21f0173ea3537a30c829a2373f18264d5fa55de, incl. vary_sampling -> GenerationRunRecord -> replay with a fake transport. Unwired by design until GE-01/the proposal flow. Residuals: no live local model exercised; per-session opt-in is per client instance until a session owner exists; Unix sockets unsupported.
- [ ] **GE-05** `[A]` Streaming and cancellation
  - partial (R62/A1, PR #163, merge 411e8de): LLMClient.stream(prompt, sampling, *, cancel=None) yields OpenAI-compatible SSE delta.content chunks incrementally through the same URL/transport/loopback policy; [DONE] ends it, cancel or generator.close() closes the response (pre-set cancel sends no request); malformed events, missing [DONE], >1 MiB line or >4 MiB total raise ValueError without echoing the body. seen: tests/test_llm_streaming.py 10 tests OK (gate 968 OK) at head 604a015e69467430a416fffc60467fc775fc1c1d. Unwired by design until GE-03/GE-04 proposal flow. Residuals: byte-at-a-time reads (live throughput unmeasured); cancellation cannot interrupt an in-flight socket read; single-line data events only; no live local model.
- [ ] **GE-06** `[A]` Generation run records: prompt, exemplars used, model version, candidates — check: every candidate is reproducible from its record
  - partial (R49/A1, PR #116): `generation/run_record.py` GenerationRunRecord (prompt, ordered exemplar ids, model, per-candidate SamplingParams with seed, candidates), validate_record, canonical to_json/from_json, run_id = sha256 of inputs, replay(record, generate_fn) checked with a deterministic fake; unwired until GE-03/GE-04 produce records and EL-02 references run_id; real-model reproducibility not yet seen

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
  - partial (R47/A1, PR #114): `service/length_delta.py` reports word counts (regex `\w+(?:[-'’]\w+)*`), stripped character counts, signed deltas and candidate/original ratios (None for an empty original); no threshold or verdict; unwired until VF-07
- [ ] **VF-07** `[A]` Panel: each axis with value, confidence and method link
  - partial (R56/A2, PR #149, merge 47b8f02; seen: tests/test_verify_panel.py 12 tests OK, gate 875 OK at head 7d622645be9e7098329234344937b98600c11c5b): `service/verify_panel.py` — `build_panel(original, candidate)` returns one entry per §5.9 axis in table order (frozen `AxisEntry`: axis, status, value, confidence, method_link, implementation, note); Support preserved (`support_diff`; value `{preserved, missing, added}`, confidence `deterministic-literal`, residual "still entailed" path pending VF-02/G-08) and Length delta (`length_delta` fields, confidence `deterministic`) implemented; Move/Meaning/Register/Grammar present as `not_available` with null value and confidence, never omitted or guessed; panel-level `methods` links `docs/methods/llm-not-final-judge.md` (VF-11); no field, function or rank combines the axes (VF-10 lint target); unwired by design until UX-01/VF-08 consume `build_panel`
- [ ] **VF-08** `[A]` Filter: only candidates failing meaning preservation at the G-08 threshold are hidden; a counter shows how many, and they can be viewed
- [ ] **VF-09** `[A]` Critic rerank for generation: candidates ordered by move and register fit, subject to the filters. The ordering is a default, not a verdict
- [ ] **VF-10** `[A]` No aggregate score anywhere — check: lint for score-combining code in this module
  - partial (R49/A2, PR #117): `scripts/lint_no_aggregate.py` flags aggregate-score names (function, argument, variable, attribute, dict key) and sum/mean/fmean/average calls over two or more distinct `*score`/`*_result` names in service/support_check.py, length_delta.py, number_check.py by default; no operator/dataflow detection; run nightly in .github/workflows/nightly.yml (R50/A1); seen only once a nightly run shows it (residual)
  - partial (R74/A1, PR #187, merge 83f8374): default targets now also follow every `implementation="….py"` literal in service/verify_panel.py (ast-parsed, `panel_implementations`/`default_targets`); effective list unchanged today; gate 1108 OK at head 1713fbc2739d32d941aca92e71be06bc92db0669; still seen only once a nightly run shows it
- [ ] **VF-11** `[A]` Method text stating why an LLM is not the final judge of candidate quality (position, verbosity and self-preference bias)
  - partial (R49/A3, PR #119): docs/methods/llm-not-final-judge.md; linked from service/verify_panel.py (R56/A2)

---

## Interaction

- [ ] **UX-01** `[A]` Diff-first: word-level diff visible before any accept
  - partial (R64/A1, PR #167, merge 3ae2ec2): `service/word_diff.py` word_diff(original, candidate) -> frozen DiffOp(kind, original_text, candidate_text) rows (equal/delete/insert/replace) over word-plus-trailing-whitespace tokens, difflib.SequenceMatcher(autojunk=False); both sides reconstruct exactly; proposal_diffs maps it over Proposal.candidates. Library half only; ran by OpenCode (D-008). seen: tests/test_word_diff.py 20 tests OK (gate 998 OK, rerun by planner) at head 36e566ff4f4b891ccadf05554eea3cac67714130. Unwired by design until the UX-01 UI (needs the TS stack, todo-06). Residuals: no length cap (quadratic worst case); whitespace-only changes attach to the neighbouring word.
  - partial (R116/A1, PR #300, merge 23deed6): UI half: `editor/src/diff.js` renderDiff(ops, doc) renders word_diff DiffOp rows as text/<del>/<ins> with data-kind, text only (no HTML parsing), unknown kind throws; re-exported from editor/src/index.js; no JS diff algorithm. seen: editor/test/diff.test.js, npm test 25/25 and gate 1424 OK at head c5e3d23736fbbbf0259c9f99b07b00324d299ae4 (rerun by planner). Stays partial: unwired by design until UX-02 shows it next to a proposal.
- [ ] **UX-02** `[A]` Accept, reject, or edit then accept; reject is one keystroke
  - partial (R117/A1, PR #302, merge 6237073): editor half: `editor/src/proposal.js` showProposal(ed, proposal, {doc, onAction}) panel with renderDiff before any action (I5), editable candidate, Accept/Reject buttons, Escape rejects, Ctrl/Cmd+Enter accepts, one action only, accept via acceptProposal (one undo step); onAction reports accept/edit/reject for EL-* (log not written here). seen: editor/test/proposal.test.js, npm test 33/33 and gate 1424 OK at head 3cad041555b2a67a85f929af1612fae9c7d5d82d (rerun by planner). Stays partial: unwired by design until the app shell / UX-03 opens panels and EL-* logs onAction.
- [ ] **UX-03** `[A]` Proposals on request only; no unprompted ghost text
  - partial (R118/A1, PR #304, merge e9e40b3): editor half: `editor/src/request.js` proposalRequestKeymap({onRequest}) binds Mod-Shift-p to call onRequest({from,to,text}) for a non-empty selection only; never edits the doc or renders anything; createEditor installs it only when onRequest is given; re-exported from editor/src/index.js. seen: editor/test/request.test.js, npm test 38/38 and gate 1424 OK at head c8fb411700a8804e199c16c200f6b5ae2171a9e7 (rerun by planner). Stays partial: unwired by design until the app shell connects onRequest to the service propose call and showProposal.
- [x] **UX-04** `[A]` Undo restores the original exactly — check: document hash equal after accept and undo
  - done (R115/A1, PR #296): `editor/src/index.js` acceptProposal + undo (ProseMirror history, one step per accept). Unwired by design until UX-02. Residual: block ids change after undo (idPlugin reassigns; hash unaffected). seen: editor/test/undo.test.js, npm test 18/18 and gate OK at head 0f510196c5dd0e7a5ac5a3e57433bf5d3860a4aa
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
- [x] **EL-07a** `[A]` Export control for the expert: whole edit log to JSON Lines (`python3 -m editlog.export DB_PATH OUT_PATH [--force]`; atomic, 0600, no overwrite without --force) — check: tests/test_editlog_export.py
  - done (R46/A1, PR #112): `editlog/export.py` export_jsonl streams iter_entries into a 0600 temp file, published atomically (os.link no-clobber, os.replace with --force); CLI `python3 -m editlog.export`. Residual: no-clobber publish needs hard-link support on the destination filesystem. seen: tests/test_editlog_export.py, gate 692 tests OK at head b30a9b949aae9cc8f4018c217cc471001d9ea748
- [x] **EL-07b** `[A]` Delete control for the expert — permanent whole-log delete after offering the EL-07a export (D-004); no per-entry delete, no tombstones
  - done (R51/A1, PR #127): `editlog/delete.py` delete_log + CLI `python3 -m editlog.delete` per D-004. seen: tests/test_editlog_delete.py, gate 759 tests OK at head 2f23aaa6a22dc80db84034868e0f79a6177e9b60. Residual: unlink is not secure erasure of backups or storage blocks; writers must be closed first.

---

## Automatic drafting *(stage 2)*

- [ ] **AD-01** `[A]` Planner: move sequence per section from the pattern model for the chosen genre
- [ ] **AD-02** `[A]` Source selection: which source items feed each move
  - partial (R73/A1, PR #185): library `service/source_selection.py` `select_sources(requests, items, score, *, k=5, min_score=0.0)` -> `SelectionReport` (per-move top-k `MoveSelection` sorted by score, ties by input order; `unused_ids`; `empty_moves`), single pass over items, plus offline `lexical_score` (token overlap). seen: tests/test_source_selection.py, gate OK at head 65e604219737d1fd48cfc430b41204fdc4fb8060 (executor 1106 tests; reviewer rerun OK). Unwired by design until AD-03; moves caller-supplied until AD-01. Residuals: O(moves x items) score calls untested at corpus scale; lexical scorer only until G-03.
- [ ] **AD-03** `[A]` Per-move generation with exemplars and the selected source items
- [ ] **AD-04** `[A]` Grounding check: every generated sentence with a factual claim links to a source item; unlinked sentences are flagged, never silently kept — check: test with a deliberately unsupported sentence
  - partial (R72/A1, PR #183): library `service/grounding_check.py` `check_grounding(sentences, items, is_claim=None)` -> `GroundingReport` of `SentenceGrounding` rows (every sentence kept in order; a claim with no existing linked item is flagged `unlinked` or `unknown-source`; unknown ids always reported) plus `sentences_from_text`. seen: tests/test_grounding_check.py (deliberately unsupported sentence flagged), gate OK at head 0fbf724aff2d21e376d482fdcecdcf5508339982 (executor 1099 tests; reviewer rerun OK). Unwired by design until AD-03 (producer) and AD-08 (consumer). Residuals: link check only (no semantic support, VF-02/G-08); every sentence is a claim by default (no claim classifier).
- [ ] **AD-05** `[A]` Number check: every number and unit in the draft matches a source item — check: unit tests
  - partial (R48/A1, PR #115): `service/number_check.py` maps each draft `num:` token (via `extract_support`) to the ids of source items containing it and lists unmatched tokens; presence semantics, URL digits ignored, literal value+unit match; reporting only; unwired until AD-04/AD-06
  - partial (R68/A1, PR #175): `check_quantities(draft, items)` matches each SR-04 draft quantity occurrence against quantities in SR-02 `SourceItem.content` (same unit, unitless item quantity inherits a single `item.units` entry; value by isclose, range/tolerance by equal low/high); streams items; reporting only. seen: tests/test_number_check.py, gate 1072 tests OK at head c363214465bf17619faa5fd2837cda42bac23a53. Unwired by design until AD-06. Residuals: linear in draft x item quantities; no unit conversion or paraphrased numbers; a value never matches a degenerate range.
- [ ] **AD-06** `[A]` Assembly into a Markdown document with provenance `machine` on every block
  - partial (R69/A1, PR #177): library half `service/draft_assembly.py` `assemble_draft(sections, items=None)` -> `AssembledDraft` (Markdown `## heading` + paragraphs, `DraftBlock` rows with provenance `machine`, status always `draft`, optional per-block `check_quantities`); rejects empty headings/text, empty sections and `#`-started lines in block text. seen: tests/test_draft_assembly.py, gate OK at head 87fdc3a8ab7759f377cf6566da4c8c4bbe60ff54 (executor 1078 tests; reviewer rerun OK). Unwired by design until AD-03 (producer) and AD-08 (consumer). Residuals: quantity check costs blocks x item quantities (items bounded by AD-02); any `#`-started block line is rejected, including non-heading `#tag`.
- [ ] **AD-07** `[A]` Draft status: `draft` until the expert marks it reviewed (invariant I5) — check: no code path sets `reviewed` without a user action
  - partial (R71/A1, PR #181): library `service/draft_status.py` `mark_reviewed(draft, ReviewAction)` -> new `AssembledDraft` with status `reviewed`; raises TypeError for a non-`ReviewAction`, ValueError for empty user_id, unconfirmed action or a non-`draft` input. Static guard in tests/test_draft_status.py allows a `reviewed` status assignment only in that module. seen: tests/test_draft_status.py, gate OK at head a30a50e958a9eef0bb956c78be3930b842505f7e (executor 1091 tests; reviewer rerun OK). Unwired by design until AD-08. Residuals: the guard is regex-based, so indirect assignment (setattr, kwargs dicts) is not detected.
- [ ] **AD-08** `[A]` Review flow: the editor opens the draft with overlays on and the open-issues list sorted by severity
- [ ] **AD-09** `[H]` Blind review of drafts against reference reports for the same source material
- [ ] **AD-10** `[A]` Correction metrics per draft: share of sentences edited, by move
  - partial (R70/A1, PR #179): library `service/correction_metrics.py` `correction_metrics(blocks, final_texts)` -> `DraftCorrection` with per-move `MoveCorrection` (first-appearance order); a machine sentence counts edited when its whitespace-normalized form is absent (multiset) from the block's final text; deleted block counts all edited; length mismatch raises ValueError. seen: tests/test_correction_metrics.py, gate OK at head c5eaf742bcae9be4cb04bff74d12a23df3efa058 (executor 1084 tests; reviewer rerun OK). Unwired by design until AD-08. Residuals: a line break inside a sentence is a sentence boundary, so a pure re-wrap counts as an edit; no block alignment.

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
