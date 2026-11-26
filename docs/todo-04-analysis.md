# TODO — Pattern Model & Two-Layer Analysis

**Phase:** 1 (pattern model, offline), 3 (live layers)
**Track:** E for implementation, R for the gates
**Gated by:** G-01 (moves exist), G-03 (embedding choice), G-04, G-05, G-06, G-07
**Depends on:** corpus and labels (`todo-09`), embedding service (`todo-02`)

Markers: `[A]` agent-executable with a mechanical check · `[H]` needs the expert's judgment · `[A→H]` agent prepares, human decides.

This is the core of revision 2. The pattern model is built and tested offline on the corpus before any of it is wired into the editor.

---

## Signal framework

- [x] **SF-01** `[A]` `Signal` type: `{nodeId, level, kind, value, confidence, methodRef, layer, computedAt}`; `confidence`, `methodRef` and `layer` are required (invariant I4) — check: type test
- [x] **SF-02** `[A]` Signal registry: each kind declares its gate, display name, definition and known limits
- [x] **SF-03** `[A]` Naming lint: display names may not contain "quality", "score", "correct" or "coherence" (invariant I8) — check: lint test
  - done (R11/A1, PR #40, merge e6b48ee): `analysis/signals.py` (Signal, SignalKind, register_kind, get_kind, registered_kinds, lint_display_name), six 5.6 kinds pre-registered. seen: tests/test_signals.py, 282 tests OK at main 9b57dbb. Unwired by design until SF-04 consumes registered_kinds. Residuals: get_kind raises KeyError; test-registered kinds persist in the module registry.
- [x] **SF-04** `[A]` Signals default off until their gate passes (invariant I6) — check: CI gate check covers every registered kind
  - done (R12/A1): `analysis/signal_gates.py` (default_flags, check, gate_passed, passed_gates, CLI exit 0/1/2), nightly.yml step after Unit tests. Pass marker: `## Verdict` first line starts `passed`. seen: tests/test_signal_gates.py, 292 tests OK; CLI exit 0 over 6 kinds / 6 gates, 0 passed. Residuals: no persisted flag registry (needs decision); editor/runtime wiring absent until live layers land.

---

## Move classifier *(G-01, G-03, G-04)*

- [ ] **PT-01** `[A]` Training set from corpus LLM labels, with expert-overturned labels taking precedence; document-level split
  - partial (R192/A1, PR #478, merge 22418eb; Claude lane, Codex usage-limited): `analysis/training_set.py` build_training_set(candidates, document_of, held_out_fraction=0.2, seed=0) resolves labels via resolve_labels (expert wins), splits whole documents by sha256(seed:document_id), returns rows (node_id, document_id, label, source) and per-split counts (documents, examples, per label); load_document_map streams node->document JSONL (conflicting mapping raises); CLI `python3 -m analysis.training_set --labels --documents [--seed] [--held-out]` prints counts. seen: tests/test_training_set.py 7 OK (LLM-built synthetic labels), gate 1648 OK at head 1ffeb4c (rerun by planner). Stays partial: no run on corpus labels (operator-owned data); unwired until PT-02. Residuals: memory one winner per node plus the node map, 100k bound untested; held-out share drifts with few documents.
- [ ] **PT-02** `[A]` Classifier head on sentence embeddings: logistic regression baseline, small MLP as an alternative — check: macro-F1 on held-out documents reported per move
  - partial (R193/A1, PR #481, merge 31cec98; Claude lane, Codex usage-limited): `analysis/classifier_head.py` pure-stdlib LogisticRegression (softmax, L2, mini-batch GD) and one-hidden-layer MLP, seeded and deterministic; fit/predict_proba/predict, JSON save/load_model; evaluate -> macro_f1, per-label P/R/F1/support/seen_in_train, examples, documents (held-out label unseen in train scores F1 0); missing or mis-sized vector raises ValueError naming the node; CLI `python3 -m analysis.classifier_head --labels --documents --vectors [--model logreg|mlp] [--seed] [--held-out] [--out]` streams vectors for labelled nodes only. seen: tests/test_classifier_head.py 7 OK (LLM-built synthetic separable vectors, macro-F1 >= 0.9 both models), gate 1655 OK at head 0e8112b (rerun by planner). Stays partial: no run on corpus embeddings (operator-owned data). Unwired by design until PT-04/PT-05. Residuals: O(examples x dim) memory, 100k x 768 bound untested and pure-Python training will be slow; macro-F1 also averages train-only labels with zero held-out support (F1 0), which deflates it on small splits.
- [ ] **PT-03** `[A]` Context features: section type and neighbouring sentences' embeddings as optional inputs; keep only if they improve held-out F1
  - partial (R194/A2, PR #485, merge 223f395; Claude lane, Codex usage-limited): `analysis/context_features.py` load_context streams a JSONL context map {node_id, document_id, section_id, section_type, index} twice and resolves in-section prev/next neighbours; augment appends prev/next sentence vectors (zero-padded at section edges or missing vector; I2: sentence vectors only) and a one-hot section type over a train-only vocabulary (unknown -> zeros); ablate trains the PT-02 head with and without context on the same split and gives verdict keep only if held-out macro-F1 delta > margin (default 0); CLI `python3 -m analysis.context_features --labels --documents --vectors --context [--model] [--seed] [--held-out] [--margin] [--[no-]neighbours] [--[no-]section]`. seen: tests/test_context_features.py 6 OK (LLM-built synthetic), gate 1668 OK at head 996d91b (rerun by planner). Stays partial: keep/drop verdict needs a run on corpus embeddings (operator-owned data). Unwired by design until PT-05. Residuals: duplicate node_id in the context map silently overwrites; memory O(examples x 3 dim), 100k bound untested, pure-Python training slow.
- [ ] **PT-04** `[A]` Calibrated confidence (temperature or isotonic) — check: reliability diagram and expected calibration error recorded
  - partial (R194/A1, PR #484, merge fec4998; Claude lane, Codex usage-limited): `analysis/calibration.py` TemperatureScaling (golden-section NLL search on log T) and IsotonicCalibration (PAV on top-class confidence, rest renormalised), make_calibrator/save/load JSON; reliability(probs, labels, bins) and ece(); CLI `python3 -m analysis.calibration --model --labels --documents --vectors [--method temperature|isotonic] [--bins] [--seed] [--held-out] [--out]` halves held-out documents by stable hash (fit on one, report on other; shared_split flag when a half is empty) and prints ece_before/ece_after and reliability bins with counts. seen: tests/test_calibration.py 7 OK (LLM-built synthetic over-confident probabilities), gate 1669 OK at head adb61e0 (rerun by planner). Stays partial: reliability diagram/ECE on corpus model needs an operator-data run. Unwired by design until PT-05/fast layer. Residuals: memory O(held-out x labels), 100k untested; isotonic lookup linear scan per example; unseen held-out labels count as wrong in ECE.
- [ ] **PT-05** `[A]` Export to ONNX; inference under 5 ms per sentence — check: benchmark
- [x] **PT-06** `[A]` Paragraph and section labels by aggregation of sentence labels; never by comparing vectors across levels (invariant I2)
  - done (R25/A1): `analysis/aggregate.py` (SentenceLabel, AggregateLabel, aggregate, aggregate_section); confidence-weighted vote with exact Fractions, name-ascending ties, count fallback for all-zero confidence, LevelVector rejected (I2), section pools sentences. seen: tests/test_aggregate.py, gate 485 tests OK at head 335c3b49ff65414dda1221e5c345b0c9395e1e90 (PR #69). Production caller: unwired by design until PT-02. Residual: 100 000-word bound untested.
- [ ] **PT-07** `[A→H]` Error review: the 50 most confident disagreements with expert labels, for the expert to judge whether the label or the model is wrong

---

## Sequence model *(G-05)*

- [x] **SQ-01** `[A]` Move-transition statistics per section type from the corpus
  - done (R26/A1): `analysis/transitions.py` (LabelledSection, TransitionStats, START/END sentinels); streaming per-section-type counts, probability, distinct-document support, deterministic transitions(). seen: tests/test_transitions.py, gate 497 tests OK at head 81240766c9ed657611fa8c12612efd9fe5324398 (PR #71). Production caller: unwired by design until SQ-03. Residual: 100 000-word / full-corpus bound untested.
- [x] **SQ-02** `[A]` Expected-move set per section type: which moves are near-universal, which optional
  - done (R27/A1): `analysis/expected_moves.py` (MovePresence, ExpectedMoves, EXPECTED/OPTIONAL/RARE roles); one streaming pass over LabelledSection, presence rate per section type with distinct-document support, inclusive thresholds. seen: tests/test_expected_moves.py, gate 508 tests OK at head 6aab73e1536d0cf7ace430dcb7f883fe2ad61304 (PR #73). Production caller: unwired by design until SQ-03. Residual: full-corpus bound untested.
- [x] **SQ-03** `[A]` Detectors: missing expected move, move out of order, move foreign to the section — each returns the evidence (how often the pattern occurs in the corpus)
  - done (R28/A1): `analysis/detectors.py` (Finding, Detectors; MISSING/FOREIGN/OUT_OF_ORDER with corpus evidence). seen: tests/test_detectors.py, gate 520 tests OK at head cb20ee87a5d85a929cca6e7202bb7e9ecc9aeb9d (PR #75). Production caller: unwired by design until SQ-04. Residual: full-corpus bound untested.
- [x] **SQ-04** `[A]` Confidence from corpus support: a pattern seen in 5 reports is not a rule — check: flags below a minimum support count are suppressed
  - done (R29/A1): `analysis/support.py` (support_of, SupportedFindings, filter_supported; min_support default 5, inclusive). seen: tests/test_support.py, gate 541 tests OK at head 1b1ca4731474956c38830434ddedf69fd3278839 (PR #78). Production caller: unwired by design until the sequence-fit overlay (todo-05). Residual: synthetic corpora only.
- [x] **SQ-05** `[A]` Perturbation generator for G-05
  - done (R30/A1): `analysis/perturb.py` (Perturbation, delete_move, swap_moves, insert_move, perturb, log_record; seeded, streaming). seen: tests/test_perturb.py, gate 553 tests OK at head f527cd4f8fbd5217fface6ab5fc86f6d22bd001c (PR #80). Production caller: unwired by design until the G-05 runner (todo-01). Residual: synthetic sections only; swap pairs not uniformly likely.
- [ ] **SQ-06** `[A→H]` Review of the learned patterns per section type: the expert marks any that are corpus accidents

---

## Exemplar index

- [ ] **EX-01** `[A]` Index corpus passages by genre, section type and move
- [ ] **EX-02** `[A]` Retrieval: nearest passages performing the same move in the same section type, excluding the current document — check: retrieval test asserts the exclusion
- [~] **EX-03** `[A]` Diversity in the returned set, so one report does not dominate
  - partial (R162/A2, PR #408, merge 64fd6fa, reviewed head 3ea182f; OpenCode/DeepSeek lane per D-008): generation/exemplars.py `select_exemplars` and `render_prompt` take optional `max_per_document` (positive int or None; bool/0/non-int raise ValueError); single lazy pass in stream order, a candidate whose document already holds the cap is skipped, not deferred; memory O(limit). Default None unchanged. seen: tests/test_exemplars.py 6 new tests (LLM-built synthetic data); planner rerun at 3ea182f and combined main 64fd6fa: Python gate 1594 OK. Unwired by design until propose.py/EX-02 pass it. Residuals: no similarity-aware diversity; not measured on the real corpus (EX-04/G-03).
- [ ] **EX-04** `[A]` Retrieval quality measured as part of G-03

---

## Register profile *(G-06)*

- [ ] **RG-01** `[A]` Genre profile from style embeddings of corpus text, per move
- [ ] **RG-02** `[A]` Baseline-LLM set: default-style rewrites of corpus sentences, content held constant
- [ ] **RG-03** `[A]` Corpus-vs-LLM classifier on sentence embeddings as a second arm
- [x] **RG-04** `[A]` Feature report: what distinguishes the two sets (sentence length, hedging, passive voice, numbers per sentence, connectives), for the slow layer's explanations and for the expert
  - done (R86/A2, PR #225, merge 9fb3dda): `sentence_features(sentence)` and `compare(set_a, set_b) -> FeatureReport` in analysis/register_features.py (stdlib + analysis.numbers); per feature n/mean/median per set, B-minus-A mean diff, Cohen's d (pooled SD, None when undefined); no aggregate score; `sorted_by_effect` is display order only. Ran on Claude (D-008). seen: tests/test_register_features.py (9 tests, synthetic sentences), Python gate 1136 OK planner rerun at head e0947517cceed48b1b4b65878c8230e26d89489c. Not run on corpus or a baseline-LLM set (RG-02 absent). Unwired by design; RG-05 and slow-layer explanations consume it. Residuals: heuristic passive detection (misses get-passives, misfires on adjectival -ed), fixed English lexicons, O(n) floats per feature.
- [ ] **RG-05** `[A]` Register-fit signal per sentence with confidence

---

## Support mapping *(G-07)*

- [x] **SP-01** `[A]` Identify claims that need support: sentences labeled as conclusion or interpretation
  - done (R20/A2): `analysis/claims.py` (LabelledSentence, Claim, DEFAULT_CLAIM_MOVES, select_claims); validated one-pass selection of conclusion/interpretation sentences (configurable moves, inclusive min_confidence, same-level and unique-id checks). seen: tests/test_claims.py, gate 409 tests OK at head a10d6e1237b0864e405ab732d3f9fb14f1ee2631 (PR #59); combined main 422 OK. Production caller: unwired by design until the move classifier and SP-02 consume it. O(sentences) time, O(claims + ids) memory per document. Residuals: trusts upstream move labels and confidence; genre-specific claim moves are a caller choice; synthetic tests only; no private-corpus/model path exercised.
- [x] **SP-02** `[A]` Fast layer: retrieve candidate evidence within the document and from linked source items (same-level retrieval)
  - done (R21/A1): `analysis/retrieval.py` (EvidenceItem, Candidate, retrieve_candidates, to_support_links); one-pass same-level cosine top-k per claim with bounded heaps, self-exclusion, input-order ties, CrossLevelError on mixed levels. seen: tests/test_retrieval.py, gate 435 tests OK at head aa95ea28b1d8774fad1608bb8124c0c5c6155c83 (PR #61); combined main 435 OK at 1cb5219. Production caller: unwired by design until SP-01 claims are embedded via EM-02/SV-02 and SP-03 consumes the candidates. O(claims x evidence x d) time, O(claims x k + evidence ids) memory. Residuals: G-07 Recall@5 not measured; scores are clipped raw cosine, not calibrated; corpus-scale bound untested; synthetic tests only; no private-corpus/model path exercised.
- [ ] **SP-03** `[A]` Slow layer: entailment check between candidates and the claim
- [x] **SP-04** `[A]` Number-and-unit consistency between a claim and its sources — check: unit tests on tolerances and unit variants
  - done (R19/A1): `analysis/numbers.py` (Quantity, ConsistencyReport, extract_quantities, check_consistency); deterministic stdlib extraction, canonical unit conversion and dimension-aware tolerance matching. seen: tests/test_numbers.py, `python3 -m unittest tests.test_numbers` → 19 tests OK at base 4a85d410b27d109a442ffec44cf9fbad6414aaf8 + this change. Production caller: unwired by design until SP-05 emits the signal behind the G-07 flag. Memory holds claim quantities and one source's quantities at a time; matching time O(claim quantities × source quantities). Residuals: explicit case-sensitive unit table only; unknown units remain unitless; no entailment, entity alignment, scientific notation, compound units or locale inference; three-digit comma groups mean thousands; years mean 365 days; EUR/USD do not cross-convert; non-finite quantities raise ValueError. Synthetic tests only; no private-corpus/model path exercised.
- [x] **SP-05** `[A]` Signals: unsupported claim; evidence never used
  - done (R20/A1): `analysis/support_signals.py` (SupportLink, SupportMap, unsupported_claims, unused_evidence, emit_support_signals); validated frozen support map, provisional `support` Signals for claims below the inclusive threshold and evidence no link supports; emits nothing unless the `support` flag is enabled. seen: tests/test_support_signals.py, full gate 410 tests OK at head 7225d0b4c64ccf17a1c15bc4b4714a44102fb51f (PR #57). Production caller: unwired by design until SP-02/SP-03 produce a SupportMap; flag stays off until G-07 passes. O(claims + evidence + links) per document map; no corpus loop. Residuals: supplied scores are not calibrated; synthetic tests only; no private-corpus/model path exercised.

---

## Redundancy *(G-04)*

- [x] **RD-01** `[A]` Within-level similarity across sections; adjacent sentences are excluded
  - done (R28/A2): `analysis/redundancy.py` (Unit, RedundantPair, redundant_pairs; cross-section cosine, adjacent excluded, heap-bounded limit). seen: tests/test_redundancy.py, gate 520 tests OK at head 70729199fc4c39462c8b7978ea0f58d3931b0edf (PR #76). Production caller: unwired by design until RD-02 / G-04. Residual: O(n^2*d) large-document bound untested.
- [ ] **RD-02** `[A]` Slow layer separates repetition from an intentional recap (summary and conclusion sections restate by design)
- [ ] **RD-03** `[A]` Per-document suppression: the expert marks a pair as intentional
  - partial (R185/A2, PR #464, merge 5d92f76; Claude lane, Codex usage-limited): `analysis/redundancy_suppression.py` SuppressionStore(path).mark/suppressed (append-only JSONL per document, unordered pairs, corrupt line raises with line number) and filter_suppressed(pairs, suppressed). seen: tests/test_redundancy_suppression.py 11 tests, gate 1641 OK at head 092504d and on main (rerun by planner). Stays partial: unwired by design until the G-04 redundancy overlay / RD-02 and an expert marking UI. Residual: single writer, no locking, no un-marking.

---

## Two-layer orchestration *(G-04)*

- [ ] **LY-01** `[A]` Fast path: on each dirty set, embed, classify, update sequence and register signals — check: under 100 ms end to end, warm
- [ ] **LY-02** `[A]` Slow path: LLM section review started in parallel for the edited section — check: never blocks the fast path
  - partial (R58/A2, PR #155, merge cc1bc23): analysis/slow_path.py bounded asynchronous section review (ThreadPoolExecutor, busy Future when full) wiring StalenessGuard, SlowLayerCache and LayerReconciler (results published as layer 'confirmed'); defines the LY-06 context hash (sha256 of canonical JSON [section_id, context]). seen: tests/test_slow_path.py 14 tests OK (combined gate 932 OK on main cc1bc23) at head 7a15ad1c0fe352aee74251161c3faf43e89d658a, incl. submit returns before review finishes. Unwired by design until LY-01/LY-03 call it from the editor loop. Residuals: per-section guard/reconciler state unbounded; review fn must emit signals with node_id == section_id (not enforced); running review not cancellable; fake review fn only, no real LLM.
- [ ] **LY-03** `[A]` Triage: only sentences below a confidence cutoff, plus the edited section, go to the slow layer — check: slow-layer call count logged per session
  - partial (R59/A1, PR #157, merge d03094a): analysis/triage.py TriageSession selects sentences below cutoff plus the edited section and submits via SlowPath; per-session call/busy counts logged at INFO. seen: tests/test_triage.py OK (gate 941 OK on main d03094a) at head abde55f072c76a6ee549b629fdc1d526eece04aa; fake review fn only. Unwired by design until LY-01 calls it. Residuals: corpus-scale latency untested; caller must note_edit every changed node.
- [ ] **LY-04** `[A]` Reconciliation: a confirmed result replaces the provisional one; both carry their layer — check: state-machine tests
  - partial (R55/A2, PR #143, merge 4461e7d): analysis/reconcile_layers.py LayerReconciler state machine; unwired by design until LY-01/LY-02 wire the fast and slow paths. seen: tests/test_reconcile_layers.py 11 tests OK (synthetic LLM-built signals; gate 850 tests OK) at head 924ee47c7ea55f8d8c91f6774a82db5e812c06e0; memory O(live keys). Stays partial until LY-01/LY-02 exercise it.
- [ ] **LY-05** `[A]` Staleness: slow results for changed text are discarded — check: test with edits during an in-flight review
  - partial (R57/A1, PR #151, merge 9958cd6): analysis/staleness.py StalenessGuard (start/note_edit/accept, discard_count); unwired by design until LY-02. seen: tests/test_staleness.py 12 tests OK (gate 898 OK) at head 868dc7af9166549c5104ae77e88b4372aa05e406, incl. edit during in-flight review discarded. Stays partial until LY-02 exercises it. Residuals: in-memory, single-threaded; current hashes kept for guard lifetime; synthetic LLM-built tests only.
- [ ] **LY-06** `[A]` Slow-layer cache keyed by content hash plus context hash
  - partial (R56/A1, PR #148, merge 3d15538): analysis/slow_cache.py SlowLayerCache; unwired by design until LY-02. seen: tests/test_slow_cache.py 11 tests OK (gate 874 OK) at head e93829100e1094cb5b8730b33df4561b2c63b7bc. Stays partial until LY-02 exercises it. Residuals: in-memory only, no persistence; context-hash definition owned by LY-02; synthetic LLM-built tests only.
- [ ] **LY-07** `[A]` Visibility policy read from the G-04 result, per signal
- [ ] **LY-08** `[A]` Disagreement monitor: rolling fast-vs-slow disagreement rate in the debug panel

---

## Distillation

- [x] **DS-01** `[A]` Store every slow-layer verdict as a candidate training label, with model version
  - done (R126/A1, PR #321, merge 2a200bc): SlowPath(label_store=, model_version=, clock=) appends one candidate per accepted fresh signal (label = canonical JSON [level, kind, value]); stale and cached results write nothing; append errors surface in the Future. seen: tests/test_slow_path.py SlowPathLabelStoreTests 7 OK, gate OK at head 4817327adbd2cf8165512a2547a4aad42daa8dee (rerun by planner). Unwired by design: LY-01/LY-03 construct SlowPath from the editor loop; PT-01 reads the store. Residual: one label per node per accepted review (resolve_labels keeps latest per node).
  - partial (R125/A1, PR #319, merge 318c1e5): analysis/label_store.py CandidateLabelStore (append-only JSONL, source slow_layer + model_version, streamed iter_candidates, ValueError names line; output feeds resolve_labels). seen: tests/test_label_store.py 8 OK, gate OK at head ff5447b9704d515f996030073cea346586c48736 (rerun by planner). Unwired by design: LY-02 slow path writes it, PT-01 reads it; done when the slow path stores its verdicts. Residual: single writer, no locking, no rotation.
- [x] **DS-02** `[A]` Expert corrections outrank slow-layer labels, which outrank nothing — check: precedence unit test
  - done (R124/A2, PR #317, merge 5e14bd7): analysis/label_precedence.py resolve_labels (expert > slow_layer, latest timestamp then later position within a source, streamed, ValueError names index). seen: tests/test_label_precedence.py 10 OK, gate OK at head 3b45689f25f4ecdc25802680a5099d14874877be (rerun by planner). Unwired by design: DS-01 and PT-01 consume it.
- [ ] **DS-03** `[A]` Scheduled retraining of the classifier head; a new head is adopted only if held-out F1 against expert labels does not drop — check: regression gate in the retraining job
- [ ] **DS-04** `[A]` Drift report after each retraining: disagreement rate before and after

---

## Topic overlay *(optional, G-11)*

- [ ] **TP-01** `[A]` Within-level clustering and keyword labels, as an alternative overlay mode

---

## Acceptance criteria

- The pattern model reproduces expert move labels on held-out reports at the level recorded in G-01 and G-04
- Every sequence flag cites its support in the corpus
- The fast path never waits for the slow path
- No signal ships without a passed gate, a confidence and a layer
- A retrained classifier is never adopted if it is worse against expert labels
