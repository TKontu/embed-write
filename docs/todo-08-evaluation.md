# TODO — Evaluation Harness

**Phase:** 0, then continuous
**Track:** E for the harness, R for judgments
**Gated by:** nothing
**Blocks:** every gate

Markers: `[A]` agent-executable with a mechanical check · `[H]` needs the expert's judgment · `[A→H]` agent prepares, human decides.

The gates in `todo-01` say what is tested. This file builds the machinery that runs them and keeps them honest. Annotation and corpus work are in `todo-09`.

---

## Harness

- [~] **EV-01** `[A]` Reproducible runner: pinned seeds, pinned model versions, recorded hardware — check: two runs give identical numbers
  - partial (R1/A1, PR #3, merge c3c90ce): implemented with X-00; seen when the first gate runs.
- [~] **EV-02** `[A]` Result store: `{gate, arm, metric, value, n, interval, timestamp, commit, modelVersion, inventoryVersion}`
  - partial (R2/A1, PR #7, merge b8ac3d0): SQLite result store merged; unit tests pass. Unwired until EV-03 reads it. Seen when G-01 runs.
- [~] **EV-03** `[A]` Report generator producing `experiments/results/G-XX.md` from the store
  - partial (R3/A1, PR #17, merge c24d8ba): `experiments/report.py` + CLI merged; synthetic-store tests pass; never writes a verdict. Unwired until the G-01 run. Seen when G-01 runs. Residual: CLI cannot pass question/hypothesis/threshold/method; negative intervals render ambiguously as `lo-hi`.
- [~] **EV-04** `[A]` Comparison view across arms with intervals
  - partial (R4/A1, PR #19, merge 17cd9e2): `experiments/compare.py` + CLI merged; all arms listed, `[lo, hi]` intervals, latest row per arm; synthetic-store tests pass. Unwired until G-01 runs. Residual: distinct metric/arm pairs unbounded; malformed stored timestamps raise without context. Seen when G-01 runs.
- [~] **EV-05** `[A]` Document-level split enforcement: a metric computed on a training document fails the run — check: leak test
  - partial (R2/A3, PR #9, merge 8229f8a): split enforcement + leak test merged. Seen when G-01 runs.

---

## Metrics library

- [~] **MT-01** `[A]` Agreement: Cohen's κ, confusion matrix, per-class F1
  - partial (R2/A2, PR #8, merge 053021a): kappa, confusion matrix, per-class F1 merged; hand-computed tests pass. Residual: confusion_matrix needs sized sequences. Seen when G-01 runs.
- [~] **MT-02** `[A]` Calibration: reliability diagram, expected calibration error
  - partial (R2/A4, PR #10, merge f63c1d2): reliability bins + ECE merged; tests pass. Seen when G-01 runs.
- [~] **MT-03** `[A]` Retrieval: recall@k, same-move rate of nearest neighbours
  - partial (R3/A2, PR #15, merge 05de555): streaming recall@k + same-move rate merged; tests pass. Residual: a query with no neighbours scores 0 in same_move_rate (G-03 author to note); not benchmarked at corpus scale. Seen when G-03 runs.
- [~] **MT-04** `[A]` Preference: win rate with a bootstrap interval for blind pairs
  - partial (R2/A5, PR #11, merge 8baa224): win rate + seeded bootstrap merged; tests pass. Residual: large-n runtime unbenchmarked. Seen when G-01 runs.
- [~] **MT-05** `[A]` Layer disagreement rate, overall and per move
  - partial (R3/A3, PR #14, merge a48a88c): streaming disagreement overall and per move merged; tests pass. Residual: not benchmarked at corpus scale. Seen when G-01 runs.
- [~] **MT-06** `[A]` Correction rate per draft and per move, from the edit log
  - partial (R4/A2, PR #20, merge d3aa97a): streaming `correction_rate` over (draft, move, candidate, final) entries merged; exact-string comparison; hand-computed tests pass. Input shape is provisional until the todo-07 edit log exists. Residual: not benchmarked at corpus scale. Seen when G-10 runs.
- [x] **MT-07** `[A]` Unit tests for every metric against hand-computed cases
  - done (R5/A1, PR #23, merge 2265d33): `tests/test_metrics_hand_computed.py`, 20 worked cases covering all 13 public metric functions, hand arithmetic in comments; no implementation disagreements found. seen: `python3 -m unittest discover -s tests` at main 25380c0, 199 tests OK.

---

## Blind judgment

- [~] **BJ-01** `[A]` Blind-pair tool (`todo-01` X-04): random order, arm hidden, choice plus optional reason
  - partial (R6/A1, PR #26, merge e9d37cf): `experiments/blind_pair.py` (make_pair, render_html, record_choice, to_preference_choices); tests show no arm label or key in the rendered HTML across 100 seeds; synthetic texts only. Unwired by design until BJ-02. Residuals: to_preference_choices counts any non-arm_a winner as 'b'; no write locking; session binding left to BJ-02. Seen when G-02 runs.
- [~] **BJ-02** `[A]` Session design: pairs interleaved across arms, with repeated pairs to measure the expert's consistency
  - partial (R7/A1, PR #29, merge b191ce2): `experiments/blind_session.py` (build_session, save_session, load_session, record_session_choice, consistency_pairs) wires blind_pair; originals interleaved with no adjacent same comparison, ceil(fraction·total) repeats ≥ min_gap after their original with re-randomised order, repeat links server-side only; synthetic tests pass (sweep 0/900 adjacent clashes after the review fix). Unwired until a G-02 session runs (BJ-03 [H]). Residuals: after 200 placement attempts the fewest-clash session is kept silently; session JSON holds keys and arms (private storage); no write locking. Seen when G-02 runs.
- [ ] **BJ-03** `[H]` The judgments themselves
- [~] **BJ-04** `[A]` Consistency report: how often the expert agrees with their own earlier choice. Low consistency loosens every threshold that depends on it
  - partial (R8/A1, PR #31, merge 6bfa273): `experiments/consistency.py` (consistency_report, to_store_record, CLI `python3 -m experiments.consistency CHOICES.jsonl`) over blind_session.consistency_pairs; seeded bootstrap interval; caution line below `--low-threshold` (default 0.8), never loosens anything; synthetic tests pass. Unwired until a G-02 session runs (BJ-03 [H]). Residuals: percentile bootstrap collapses to a point at all-agree/none-agree; CLI raises a traceback on a file with no repeated pairs. Seen when G-02 runs.

---

## Statistical discipline

- [ ] **ST-01** `[A]` Pre-registration: a gate cannot run until its threshold is recorded and confirmed — check: the runner refuses otherwise
  - partial (R5/A2, PR #22, merge 25380c0): `experiments/preregistration.py` + `run_gate` refuses a missing, malformed, mismatched or unconfirmed `experiments/preregistration/<gate>.json` before calling the gate; only `sample` exempt; tests pass. No real record exists; confirming each threshold is the expert's [H] act. Residual: validation cannot tell who wrote `confirmed_by` (process-enforced). Seen when G-01 runs.
- [~] **ST-02** `[A]` Sample size and interval on every reported number
  - partial (R6/A2, PR #25, merge d1fc314): `render_report` refuses a row with no interval (ValueError naming gate, arm, metric) unless `allow_missing_interval` / `--allow-missing-interval`, which marks the row and lists it under "## Missing intervals"; store already rejects n<1. Seen when G-01 runs.
- [~] **ST-03** `[A]` Multiple arms: report all arms, not only the winner
  - partial (R7/A2, PR #28, merge bd96382): `render_report(expected_arms=, allow_missing_arms=)` and CLI `--expected-arm`/`--allow-missing-arms`: a missing expected arm raises, or with the flag is marked and listed under "## Missing arms"; unexpected arms are rendered and listed; default output byte-identical; permutation tests show report and compare render every arm. Seen when G-01 runs.
- [~] **ST-04** `[A]` Negative results kept in the store and in the result documents
  - partial (R8/A2, PR #32, merge d56837d): tests pin the store as append-only (API exactly add/add_many/close/query) and round-trip zero/negative values and intervals; render_report renders every row incl. worse earlier/later ones; intervals now render `95% CI [lo, hi]` (fixes the EV-03 ambiguity); compare output footer counts earlier rows not shown. Residual: experiments/results/TEMPLATE.md still shows `low-high`. Seen when G-01 runs.
- [ ] **ST-05** `[H]` One-annotator limit acknowledged in every result document; a second expert's labels on a sample when one is available

---

## Component sanity checks on public data

Used only to confirm that components work at all. They do not replace the gates on the own corpus.

- [ ] **BM-01** `[A]` Embedding candidates: published MTEB numbers recorded as reference
- [ ] **BM-02** `[A]` Entailment and consistency checkers: run on SummaC or AggreFact samples
- [ ] **BM-03** `[A]` Style embeddings: run on STEL
- [ ] **BM-04** `[A]` Move classification method: run the same pipeline on a public argumentative-zoning or rhetorical-role dataset, to see whether it works on a genre where labels already exist

---

## Continuous evaluation

- [ ] **CE-01** `[A]` Gates re-run on model, inventory or method change; a regressing gate turns its flag off — check: simulated regression disables the flag
- [ ] **CE-02** `[A]` Nightly small-corpus run in CI
- [ ] **CE-03** `[A]` Gate statuses visible in the app's debug panel
- [ ] **CE-04** `[A→H]` `EVIDENCE.md`: for each shipped feature, the gate, the numbers and the known limits. A feature that cannot be described there does not ship

---

## Acceptance criteria

- Every gate runs from one command and reproduces its numbers
- No gate runs without a confirmed threshold
- No metric is ever computed on training documents
- A regressing gate disables its feature without manual action
- `EVIDENCE.md` covers every enabled feature
