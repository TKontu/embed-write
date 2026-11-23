# TODO — Evaluation Harness

**Phase:** 0, then continuous
**Track:** E for the harness, R for judgments
**Gated by:** nothing
**Blocks:** every gate

Markers: `[A]` agent-executable with a mechanical check · `[H]` needs the expert's judgment · `[A→H]` agent prepares, human decides.

The gates in `todo-01` say what is tested. This file builds the machinery that runs them and keeps them honest. Annotation and corpus work are in `todo-09`.

---

## Harness

- [ ] **EV-01** `[A]` Reproducible runner: pinned seeds, pinned model versions, recorded hardware — check: two runs give identical numbers
- [ ] **EV-02** `[A]` Result store: `{gate, arm, metric, value, n, interval, timestamp, commit, modelVersion, inventoryVersion}`
- [ ] **EV-03** `[A]` Report generator producing `experiments/results/G-XX.md` from the store
- [ ] **EV-04** `[A]` Comparison view across arms with intervals
- [ ] **EV-05** `[A]` Document-level split enforcement: a metric computed on a training document fails the run — check: leak test

---

## Metrics library

- [ ] **MT-01** `[A]` Agreement: Cohen's κ, confusion matrix, per-class F1
- [ ] **MT-02** `[A]` Calibration: reliability diagram, expected calibration error
- [ ] **MT-03** `[A]` Retrieval: recall@k, same-move rate of nearest neighbours
- [ ] **MT-04** `[A]` Preference: win rate with a bootstrap interval for blind pairs
- [ ] **MT-05** `[A]` Layer disagreement rate, overall and per move
- [ ] **MT-06** `[A]` Correction rate per draft and per move, from the edit log
- [ ] **MT-07** `[A]` Unit tests for every metric against hand-computed cases

---

## Blind judgment

- [ ] **BJ-01** `[A]` Blind-pair tool (`todo-01` X-04): random order, arm hidden, choice plus optional reason
- [ ] **BJ-02** `[A]` Session design: pairs interleaved across arms, with repeated pairs to measure the expert's consistency
- [ ] **BJ-03** `[H]` The judgments themselves
- [ ] **BJ-04** `[A]` Consistency report: how often the expert agrees with their own earlier choice. Low consistency loosens every threshold that depends on it

---

## Statistical discipline

- [ ] **ST-01** `[A]` Pre-registration: a gate cannot run until its threshold is recorded and confirmed — check: the runner refuses otherwise
- [ ] **ST-02** `[A]` Sample size and interval on every reported number
- [ ] **ST-03** `[A]` Multiple arms: report all arms, not only the winner
- [ ] **ST-04** `[A]` Negative results kept in the store and in the result documents
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
