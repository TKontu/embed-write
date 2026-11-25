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
- [ ] **PT-02** `[A]` Classifier head on sentence embeddings: logistic regression baseline, small MLP as an alternative — check: macro-F1 on held-out documents reported per move
- [ ] **PT-03** `[A]` Context features: section type and neighbouring sentences' embeddings as optional inputs; keep only if they improve held-out F1
- [ ] **PT-04** `[A]` Calibrated confidence (temperature or isotonic) — check: reliability diagram and expected calibration error recorded
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
- [ ] **EX-03** `[A]` Diversity in the returned set, so one report does not dominate
- [ ] **EX-04** `[A]` Retrieval quality measured as part of G-03

---

## Register profile *(G-06)*

- [ ] **RG-01** `[A]` Genre profile from style embeddings of corpus text, per move
- [ ] **RG-02** `[A]` Baseline-LLM set: default-style rewrites of corpus sentences, content held constant
- [ ] **RG-03** `[A]` Corpus-vs-LLM classifier on sentence embeddings as a second arm
- [ ] **RG-04** `[A]` Feature report: what distinguishes the two sets (sentence length, hedging, passive voice, numbers per sentence, connectives), for the slow layer's explanations and for the expert
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

---

## Two-layer orchestration *(G-04)*

- [ ] **LY-01** `[A]` Fast path: on each dirty set, embed, classify, update sequence and register signals — check: under 100 ms end to end, warm
- [ ] **LY-02** `[A]` Slow path: LLM section review started in parallel for the edited section — check: never blocks the fast path
- [ ] **LY-03** `[A]` Triage: only sentences below a confidence cutoff, plus the edited section, go to the slow layer — check: slow-layer call count logged per session
- [ ] **LY-04** `[A]` Reconciliation: a confirmed result replaces the provisional one; both carry their layer — check: state-machine tests
  - partial (R55/A2, PR #143, merge 4461e7d): analysis/reconcile_layers.py LayerReconciler state machine; unwired by design until LY-01/LY-02 wire the fast and slow paths. seen: tests/test_reconcile_layers.py 11 tests OK (synthetic LLM-built signals; gate 850 tests OK) at head 924ee47c7ea55f8d8c91f6774a82db5e812c06e0; memory O(live keys). Stays partial until LY-01/LY-02 exercise it.
- [ ] **LY-05** `[A]` Staleness: slow results for changed text are discarded — check: test with edits during an in-flight review
- [ ] **LY-06** `[A]` Slow-layer cache keyed by content hash plus context hash
  - partial (R56/A1, PR #148, merge 3d15538): analysis/slow_cache.py SlowLayerCache; unwired by design until LY-02. seen: tests/test_slow_cache.py 11 tests OK (gate 874 OK) at head e93829100e1094cb5b8730b33df4561b2c63b7bc. Stays partial until LY-02 exercises it. Residuals: in-memory only, no persistence; context-hash definition owned by LY-02; synthetic LLM-built tests only.
- [ ] **LY-07** `[A]` Visibility policy read from the G-04 result, per signal
- [ ] **LY-08** `[A]` Disagreement monitor: rolling fast-vs-slow disagreement rate in the debug panel

---

## Distillation

- [ ] **DS-01** `[A]` Store every slow-layer verdict as a candidate training label, with model version
- [ ] **DS-02** `[A]` Expert corrections outrank slow-layer labels, which outrank nothing — check: precedence unit test
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
