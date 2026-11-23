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
- [ ] **PT-06** `[A]` Paragraph and section labels by aggregation of sentence labels; never by comparing vectors across levels (invariant I2)
- [ ] **PT-07** `[A→H]` Error review: the 50 most confident disagreements with expert labels, for the expert to judge whether the label or the model is wrong

---

## Sequence model *(G-05)*

- [ ] **SQ-01** `[A]` Move-transition statistics per section type from the corpus
- [ ] **SQ-02** `[A]` Expected-move set per section type: which moves are near-universal, which optional
- [ ] **SQ-03** `[A]` Detectors: missing expected move, move out of order, move foreign to the section — each returns the evidence (how often the pattern occurs in the corpus)
- [ ] **SQ-04** `[A]` Confidence from corpus support: a pattern seen in 5 reports is not a rule — check: flags below a minimum support count are suppressed
- [ ] **SQ-05** `[A]` Perturbation generator for G-05
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

- [ ] **SP-01** `[A]` Identify claims that need support: sentences labeled as conclusion or interpretation
- [ ] **SP-02** `[A]` Fast layer: retrieve candidate evidence within the document and from linked source items (same-level retrieval)
- [ ] **SP-03** `[A]` Slow layer: entailment check between candidates and the claim
- [ ] **SP-04** `[A]` Number-and-unit consistency between a claim and its sources — check: unit tests on tolerances and unit variants
- [ ] **SP-05** `[A]` Signals: unsupported claim; evidence never used

---

## Redundancy *(G-04)*

- [ ] **RD-01** `[A]` Within-level similarity across sections; adjacent sentences are excluded
- [ ] **RD-02** `[A]` Slow layer separates repetition from an intentional recap (summary and conclusion sections restate by design)
- [ ] **RD-03** `[A]` Per-document suppression: the expert marks a pair as intentional

---

## Two-layer orchestration *(G-04)*

- [ ] **LY-01** `[A]` Fast path: on each dirty set, embed, classify, update sequence and register signals — check: under 100 ms end to end, warm
- [ ] **LY-02** `[A]` Slow path: LLM section review started in parallel for the edited section — check: never blocks the fast path
- [ ] **LY-03** `[A]` Triage: only sentences below a confidence cutoff, plus the edited section, go to the slow layer — check: slow-layer call count logged per session
- [ ] **LY-04** `[A]` Reconciliation: a confirmed result replaces the provisional one; both carry their layer — check: state-machine tests
- [ ] **LY-05** `[A]` Staleness: slow results for changed text are discarded — check: test with edits during an in-flight review
- [ ] **LY-06** `[A]` Slow-layer cache keyed by content hash plus context hash
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
