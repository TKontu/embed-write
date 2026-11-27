# TODO — Experiments & Gates

**Track:** R (research), with agent-built infrastructure
**Blocks:** G-01 and G-02 block everything except Track E engineering

Markers: `[A]` agent-executable with a mechanical check · `[H]` needs the expert's judgment · `[A→H]` agent prepares, human decides.

Every gate is a notebook or script, not product code. Thresholds below are **proposals**: confirm or change each before its run, then it is fixed. Results go to `experiments/results/G-XX.md` with a verdict of `passed`, `failed` or `inconclusive`. Inconclusive counts as failed.

**Rule:** product code for a gated capability stays behind its flag until the gate reads `passed`.

---

## Infrastructure

- [~] **X-00** `[A]` `experiments/` package: runner, corpus loader, seed pinning — check: a sample gate runs twice with identical output
  - partial (R1/A1, PR #3, merge c3c90ce): runner + streaming loader + seed pinning merged; unit tests pass. Not yet seen on a real gate: seen when the first gate (G-01) runs. Residual: the loader holds the sorted path list in memory.
- [x] **X-01** `[A]` Gate registry `experiments.config.ts`: `{id, status, threshold, resultDoc, flagsUnlocked[]}` — check: schema test
  - done (R87/A2, PR #229, merge 54c61d9): the registry is Python/TOML because experiments/ is Python (routine mapping, no design change): experiments/gates/registry.toml (G-01..G-11, all `pending`, threshold null until the expert confirms it, result_doc experiments/results/G-XX.md, flags_unlocked empty) plus `load_registry()` in experiments/gates/registry.py, which validates the schema, including that `passed` requires an existing result doc. Ran on Claude (D-008). seen: planner rerun at head 71f8b7fba4aaaa1ae9d5b1b3ce9f245bc2e8f374: tests/test_gate_registry.py 15 OK, Python gate 1151 OK. Unwired by design until X-02 wires it into CI. Residuals: no flags defined yet, so flags_unlocked is empty everywhere; titles are copied by hand from this file, and no test checks them against it.
- [x] **X-02** `[A]` CI check failing the build when a flag is on and its gate is not `passed` — check: a deliberately wrong flag fails CI
  - done (R88/A1, PR #232, merge a1bb7f1): experiments/gates/flags.toml (no flags yet) + load_flags()/check() in experiments/gates/flags.py + scripts/check_flags.py (exit 0 ok / 1 enabled flag with unpassed gate / 2 schema error), run by tests/test_check_flags.py inside the configured gate and as a nightly.yml step. Ran on Claude (D-008). seen: planner rerun at head 794436a22742b57828e04cb3e612e41a903e4ce0: Python gate OK, check_flags exit 0; the deliberately-wrong-flag subprocess test exits 1 naming flag and gate. load_flags has no product caller: unwired by design until the first gated capability lands. Residuals: nightly step not yet observed on GitHub Actions.
- [x] **X-03** `[A]` Result template: hypothesis, threshold, method, numbers with sample sizes and intervals, verdict, fallback taken — check: template lint
  - partial (R1/A2, PR #4, merge 7211c82): `experiments/results/TEMPLATE.md` + `scripts/lint_result.py` merged; lint tests pass. Unwired until X-02 (CI) / EV-03. Residual: lint does not enforce intervals or basis fields.
  - done (R89/A1, PR #234, merge 6b4388e): lint_result.py now requires a `95% CI [lo, hi]` interval and a complete Basis line (population, metric, reference, built by) in Numbers; TEMPLATE.md gained the Basis placeholder; scripts/check_results.py lints TEMPLATE.md (--template), every passed/failed gate result_doc and any G-*.md (exit 0/1, 2 schema error), run by tests/test_check_results.py in the configured gate and as a nightly.yml step after the flag check. Ran on Claude (D-008). seen: planner venv rerun at head 8633d3d786703d152004f54edabb4d906dd3f1cc: Python gate OK, check_results exit 0; review-lens approve. Residuals: EV-03 render_report emits no Basis line (owner adds it); nightly step not yet observed on Actions.
- [~] **X-04** `[A]` Blind-comparison tool: shows two texts in random order, records the expert's choice without revealing the arm — check: arm labels absent from the UI and from the DOM
  - partial (R104/A1, PR #273, merge 963cec1): `experiments/blind_ui.py` localhost-only front end over a saved BJ-02 session; tests show no arm name, key, pair/item id or repeat flag in any GET body/header, nonce-bound POSTs, resume. Synthetic texts only; real use is BJ-03 [H]. Planner rerun at b2f3b7f: gate OK. Residuals (closed by R115/A2): no cross-process write lock on CHOICES; a malformed CHOICES line aborts start. Seen when an expert session runs (BJ-03).
  - residuals closed (R115/A2, PR #297, merge 201f22e): flock on CHOICES.jsonl.lock sidecar (second server fails fast); torn final line skipped with a fresh-line append; malformed lines reported on stderr and skipped. seen: tests/test_blind_ui.py, gate 1424 tests OK at head 4cb3800c5473c456884ce156b6fdbdea67148f10. Row stays partial until BJ-03.
  - partial via todo-08 BJ-01 (R6/A1, PR #26): rendering and recording module merged, arm labels absent from the HTML in tests; session design merged via BJ-02 (R7/A1, PR #29); no browser front end yet.

---

## G-01 — Can the genre's moves be recovered? *(FATAL)*

Depends on: corpus and move inventory (`todo-09`).

- [ ] **G-01.1** `[H]` Confirm thresholds
- [ ] **G-01.2** `[H]` Annotate ~300 sentences from held-out reports with moves (`todo-09` AN-03)
- [ ] **G-01.3** `[H]` Re-annotate a 10 % sample at least a week later
- [ ] **G-01.4** `[A]` LLM labels the same sentences, with section context — check: every sentence has exactly one label from the inventory or `other`
  - partial (R96/A2, PR #252, merge eec7f43): `experiments/prelabel.py` `prelabel`/`iter_prelabel` over items `{sentence_id, doc_id, section_type, text, context}` with an injectable `model(prompt)->str`; prompt = inventory moves + `other` + the sentence's own section context; invalid replies retried then `other` with `invalid_reply: true`; JSONL appended per record, resumable per model+genre version; `llm_labels` gives g01's `config["llm"]` map; `summarize` checks exactly one label per id; `local_model(base_url)` gated by network_guard (loopback only); CLI `python -m experiments.prelabel`. Ran on Claude (D-008). seen: tests/test_prelabel.py 10 pass (synthetic, fake model; output fed to g01.run); main gate 1225 OK. Real local-model run skipped (none provisioned): done when run on the AN-02 sample for G-01.6. Residuals: CLI reads an items JSONL; wire AN-01 `resolve_items` in; truncated last output line breaks resume; model exceptions abort the run (no backoff); `parse_reply` token heuristic; CLI untested.
  - partial (R97/A1, PR #256, merge 1748f0a): prelabel CLI takes `--manifest`/`--documents` (`--pass`) via `annotate.resolve_items`, `--items` kept; resume skips a torn last line and appends start on a fresh line. Ran on Claude (D-008). seen: tests 28 pass (synthetic, fake model); main gate 1245 OK at a143956. Real local-model run still skipped: done when G-01.6 runs it on the AN-02 sample. Residuals: CLI calls private `annotate._documents`; `summarize` re-resolves documents (O(n) ids); new test classes sit after `__main__` blocks; model exceptions still abort (no backoff).
  - partial (R99/A1, PR #263, merge b836be8): public `annotate.load_documents` (prelabel CLI uses it; `_documents` kept as alias); a raising model call is retried with bounded backoff (injectable `sleep`, up to `max_retries`), then re-raised with earlier records already on disk so resume continues. Ran on Claude (D-008). seen: tests/test_prelabel.py + test_annotate.py new tests pass (synthetic, fake model); main gate 1264 OK at b836be8. Real local-model run still skipped: done when G-01.6 runs it on the AN-02 sample. Residuals: backoff nests inside the invalid-reply retry loop (worst case (max_retries+1)² calls); `summarize` re-resolves documents; test classes after `__main__`; `parse_reply` heuristic.
  - partial (R101/A1, PR #267, merge b25e59c): one call budget per item: raising calls and invalid replies together make at most `max_retries + 1` model calls; a raise sleeps per `BACKOFF_DELAYS`, an invalid reply retries without sleep; `attempts` counts all calls. Ran on Claude (D-008). seen: tests/test_prelabel.py ModelErrorTests budget tests (synthetic, scripted fake model); main gate 1267 OK at b25e59c. Residual from R99/A1 on nested backoff closed. Remaining residuals: `summarize` re-resolves documents; test classes after `__main__`; `parse_reply` heuristic; real local-model run waits on G-01.6.
  - partial (R102/A1, PR #269, merge 5ffb9ee): the prelabel CLI resolves its item source once per run; summary ids are collected while the labelling pass streams (only ids held). Ran on Claude (D-008). seen: tests/test_prelabel.py once-per-run tests for --manifest and --items (synthetic, fake model); gate 1269 OK at head 902dc9e. Residual `summarize` re-resolves documents closed. Remaining residuals: test classes after `__main__`; `parse_reply` heuristic; real local-model run waits on G-01.6.
  - partial (R103/A1, PR #271, merge c836049): tests/test_prelabel.py `__main__` guard moved to the end of the file; `python tests/test_prelabel.py` now runs all 26 tests (was 11). Ran on Claude (D-008). seen: planner gate rerun 1269 OK at head 40ddb14. Residual test classes after `__main__` closed. Remaining residuals: `parse_reply` heuristic; real local-model run waits on G-01.6.
  - partial (R196/A2, PR #490, merge c11180e, reviewed head 87a4276; Claude lane, Codex usage-limited; D-009 item 1(b)): tests/test_local_endpoint_contract.py runs the prelabel, g02_notes and g02_generate CLIs as subprocesses against a stdlib stub of the OpenAI-compatible /v1/chat/completions shape (llama.cpp / Ollama style) on 127.0.0.1; asserts path, JSON body keys {model, temperature, messages}, temperature (0; 0.7 for arm C candidates), call counts, response parsing; non-loopback URLs fail closed with no request. No client bug found; prelabel.py unchanged. seen: 4 OK, planner gate 1701 OK at head. No real model run (local-llm owed to operator). Residuals: real server timeouts/streaming and Ollama URL without /v1 untested; error/malformed replies via CLI retry path untested.
- [ ] **G-01.5** `[A]` Compute Cohen's κ expert vs LLM, expert vs self, per-move confusion matrix, share of `other`
  - partial (R95/A1, PR #249, merge 77d093e): `experiments/gates/g01.py` (`gate_id = "g01"`, `run(rng, config)` via run_gate): κ expert-vs-LLM and expert-vs-self (bootstrap 95 %), confusion matrix expert rows × LLM columns with per-move P/R/F1, `other` share per rater, missing-id counts, DocumentSplit leak check, `verdict_hint` against the proposed thresholds (never a gate status). Ran on Claude (D-008). seen: tests/test_gate_g01.py 11 pass on LLM-built synthetic fixtures; main gate 1204 OK. Not yet exercised on real labels: done when G-01.6 runs it on AN-03/G-01.4 data. Residuals: thresholds=None raises TypeError; method name claims bootstrap when n_resamples ≤ 0; `other` share is over all labelled, not the paired set; degenerate resamples give κ 1.0; interval percentiles untested.
  - partial (R98/A2, PR #260, merge f5a9deb): g01 residuals fixed: thresholds=None gives verdict_hint n/a; `other` share over the paired ids (all-labelled kept as `value_all_labelled`); n_resamples ≤ 0 reports `cohens_kappa_point` with no interval; single-class resamples excluded and counted in `degenerate_resamples`. Ran on Claude (D-008). seen: tests/test_gate_g01.py 16 pass (synthetic); main gate 1257 OK at f5a9deb. Still not run on real labels: done when G-01.6 runs. Residuals: full-sample single-class κ still 1.0; new output fields for G-01.6 consumers.
  - partial (R99/A2, PR #262, merge 9f32368): single-label paired sample (p_e = 1) gives κ value None, interval None, verdict_hint n/a, `degenerate: true`, `degenerate_reason`. Ran on Claude (D-008). seen: tests/test_gate_g01.py 18 pass (synthetic); main gate 1264 OK at b836be8. Still not run on real labels: done when G-01.6 runs. Residuals: new output fields for G-01.6 consumers.
  - partial (R145/A1, PR #372, merge a677783): `experiments/g01_inputs.py` `build_config(store, genre, manifest, prelabel_path, *, annotator, model_id)` + CLI builds the g01 config from AnnotationStore (retracted labels absent), manifest passes and prelabel JSONL (genre version/model filtered, torn line skipped). Unwired by design until G-01.6. Lane wrote it on Claude (Codex usage-limited) but could not run Python; planner took over, tested and committed. seen: tests/test_g01_inputs.py 9 pass (LLM-built synthetic); main gate 1501 OK at 49f1e57. Not run on real labels: done when G-01.6 runs. Residual: ambiguous multi-model/annotator ids raise G01InputsError instead of choosing.
  - partial (R147/A1, PR #378, merge 642ee27, reviewed head 7d09add; Claude lane, Codex usage-limited): `build_config` excludes non-blind expert labels (records carrying `prelabel`, from AN-01 pre-label mode) from `expert`/`expert_repeat` by default, before the one-annotator check; `include_non_blind=True` / `--include-non-blind` keeps them; config `non_blind` reports excluded/included per pass and the CLI prints them. Prelabel reader public as `iter_llm_records` (callers: `build_config`, `annotate.load_prelabels`; `_llm_records` alias). Still unwired by design until G-01.6. seen: tests/test_g01_inputs.py NonBlindTest 5 pass (LLM-built synthetic); main gate 1515 OK at 642ee27. Not run on real labels: done when G-01.6 runs. Residuals: a repeat pass whose labels are all non-blind silently omits `expert_repeat` (visible only in counts); CLI docstring still says 'label maps only'; whether AN-03 may use pre-labels is owed to the expert/operator.
  - partial (R149/A1, PR #381, merge fb708bf, reviewed head d0a36f2; Claude lane, Codex usage-limited): R147 residuals closed: when every repeat-pass label is excluded as non-blind, `build_config` sets `expert_repeat_omitted: 'all repeat labels non-blind'` and the CLI warns on stderr; docstring no longer says 'label maps only'. Still unwired by design until G-01.6. seen: tests/test_g01_inputs.py 18 pass (LLM-built synthetic); planner gate 1520 run at d0a36f2, only the 2 known test_ingest node env failures. Not run on real labels: done when G-01.6 runs. Residual: whether AN-03 may use pre-labels is owed to the expert/operator.
- [ ] **G-01.6** `[A→H]` Result document and verdict
  - partial (R150/A1, PR #383, merge b35737b, reviewed head 64f5876; Claude lane, Codex usage-limited): `experiments/g01_draft.py` `draft(...)` + CLI `python -m experiments.g01_draft` builds the config via `g01_inputs.build_config`, runs only through `run_gate(g01.run)` (confirmed g01 preregistration required, else exit 2), writes `<out>.json` and a DRAFT `<out>.md` (population, reference, LLM-built labels, κ with intervals, `other` share, per-move P/R/F1, missing/degenerate/non-blind counts, `verdict_hint` as hint, 'Verdict: owed to the expert'); refuses any output under experiments/results/. Unwired by design until the real run. seen: tests/test_g01_draft.py 7 pass (LLM-built synthetic, temp preregistration); planner gate 1527 run at 64f5876, only the 2 known test_ingest node env failures. Not run on real labels: needs AN-03 labels, a G-01.4 local-model run and G-01.1 confirmed thresholds. Expert verdict half stays [H].
  - chain rehearsal (R231/A3, PR #572, merge 8bc3612, reviewed head b761f70; Fable review D-014 NEEDS-FIX then APPROVE; Claude lane, Codex usage-limited): `tests/test_g01_chain.py` runs intake (loopback stub model) -> the annotate lines intake prints (first and repeat pass, scripted synthetic labels) -> the g01_draft line intake prints, each stage on the files the previous one wrote. It found three breaks, all fixed here: (1) the printed first-pass annotate line carried `--prelabels`, which makes labels non-blind, and g01_inputs drops non-blind labels by default, so the printed chain ended with no usable labels; the printed line is now blind; (2) `g01_draft` without `--preregistration-root` crashed with a TypeError (from R225); it now exits 2 naming the missing confirmation; (3) an empty expert/LLM pairing was a traceback; it is now exit 2 with a hint. seen: synthetic LLM-built run, 72 first-pass and 7 repeat sentences paired with 0 missing ids, draft written (reviewer ran the printed lines verbatim by hand); gate 1902 OK (skipped=4) on main 8bc3612. Not gate evidence. Residuals: the empty-pairing hint prints for any cause and is matched by message text; `--seed 0` and `--annotator EXPERT` are fixed in the printed lines; whether AN-03 may ever use shown pre-labels stays owed to the expert/operator; a stale g01-draft survives `intake --force`.

**Proposed threshold:** expert vs LLM κ ≥ 0.6; expert self-agreement κ ≥ 0.7; `other` ≤ 15 %.
**If failed:** merge the most-confused moves and rerun once. If it fails again, the genre is less regular than assumed: stop and rethink.
**Unlocks:** corpus-wide LLM labeling, the pattern model.

---

## G-02 — Can LLM output be steered to the genre? *(FATAL)*

Needs no editor. Can run before the classifier exists by using the LLM as critic.

- [ ] **G-02.1** `[H]` Confirm thresholds
- [ ] **G-02.2** `[A→H]` Pick ~30 sections from held-out reports; extract their content as neutral notes (facts only, no phrasing) — the expert checks a sample for leaked phrasing
  - partial (R113/A1, PR #292, merge 5e01a59): `experiments/g02_notes.py` seeded type-stratified selection of ~30 test-split sections (SplitLeakError on non-test docs, two-pass streaming), neutral-notes prompt via injectable/loopback `prelabel.local_model`, resumable NotesRecord JSONL feeding `g02_generate.iter_generate`, mechanical 6-gram leak flags + seeded expert sample in `<out>.review.json` (verdict left null). Ran on Claude (D-008). seen: tests/test_g02_notes.py 7 pass (synthetic LLM-built fixtures, fake model); main gate 1421 OK at 77a3d4d. Owed: real run on corpus + local model (operator), then the expert's leak check [H].
- [ ] **G-02.3** `[A]` Generate each section three ways: (A) plain instruction, (B) with retrieved exemplars, (C) exemplars plus critic rerank — check: 30 × 3 outputs, exemplars never drawn from the same report
  - partial (R97/A2, PR #257, merge a143956): `experiments/g02_generate.py` arms A plain, B retrieved exemplars, C exemplars + critic rerank of k candidates; injectable model/critic/retriever; same-report exemplars filtered twice and flagged by `summarize`; resumable per (section_id, arm, model, prompt version); CLI `python -m experiments.g02_generate` via loopback `prelabel.local_model`. Ran on OpenCode (D-008). seen: tests/test_g02_generate.py 13 pass (synthetic, fake model/critic); main gate 1245 OK. Real 30×3 run skipped: needs G-02.2 notes and a local model. Residuals: summary counts stale model/prompt-version records as duplicates; temperature 0 makes C's candidates differ only by prompt suffix; summary does not check model uniformity; duplicate section ids collapse silently.
  - partial (R98/A1, PR #259, merge a387bf4): `summarize(model, prompt_version)` counts only the current run's records (CLI passes the model id); `--temperature` reaches arm C candidate calls, default path unchanged; `local_sampling_model` loopback helper. Ran on Claude (D-008). seen: tests/test_g02_generate.py 20 pass (synthetic); main gate 1257 OK at f5a9deb. Residuals: `local_sampling_model` duplicates prelabel.local_model.
  - partial (R100/A1, PR #265, merge db8cae4): `local_sampling_model` removed; `prelabel.local_model` now takes an optional per-call `temperature` (0 when None) and serves both CLIs. Ran on Claude (D-008). seen: tests/test_prelabel.py test_local_model_sends_temperature; main gate 1264 OK at db8cae4. Residual from R98/A1 on the duplicate client closed; G-02.3 stays open until the run on G-02.2 notes.
  - partial (R151/A1, PR #385, merge ac084a8): `summarize` reports `models`/`prompt_versions` and `complete` is false for a mixed set; `iter_generate` raises ValueError on a repeated input section_id before writing it, CLI exits 2. Ran on Claude (D-008). seen: tests/test_g02_generate.py 23 pass (synthetic, fake model/critic); gate 1531 run at b25c6d2, only the 2 known test_ingest node env failures. Residuals closed: model uniformity, duplicate section ids. Open: temperature 0 makes C's candidates differ only by prompt suffix; real 30×3 run on G-02.2 notes.
  - partial (R152/A1, PR #387, merge 6da1fe8): arm C samples at `DEFAULT_C_TEMPERATURE` 0.7 when n_candidates > 1 and no temperature is given (recorded per record); explicit 0 honoured; `summarize` reports `c_deterministic`. Ran on Claude (D-008). seen: tests/test_g02_generate.py 26 pass (synthetic, fake model/critic); gate 1534 run at b1acbdc, only the 2 known test_ingest node env failures. Residual temperature-0 closed. Open: 0.7 untested on a real local model; PROMPT_VERSION not bumped (old arm C records flag c_deterministic on reuse); real 30×3 run on G-02.2 notes.
  - partial (R159/A1, PR #401, merge 7dc1823): PROMPT_VERSION bumped to `g02.3-v2`, so pre-R152 arm-C records regenerate on resume. Ran on Claude (D-008, Codex usage-limited). seen: tests/test_g02_generate.py test_resume_regenerates_pre_r152_v1_records_and_skips_v2; gate 1582 OK at 8c2cfb2. Residual PROMPT_VERSION closed. Open: 0.7 untested on a real local model; real 30×3 run on G-02.2 notes.
- [ ] **G-02.4** `[H]` Blind pairwise judgments with X-04: A vs C, A vs B, and C vs the original section
  - agent enabler, partial (R231/A1, PR #570, merge 60656b5, reviewed head 2c66a10, Fable review D-014 APPROVE; Claude lane, Codex usage-limited): `experiments/g02_session.py` (CLI `python -m experiments.g02_session`) turns a complete G-02.3 generation file plus the original sections into a saved blind session (comparisons `A_vs_C`, `A_vs_B`, `C_vs_original`; arms `A`, `B`, `C`, `original`; pair_id `<comparison>:<section_id>`) and prints the `blind_ui` line; it is the first production caller of `blind_session.build_session`. `g02_notes --sections-out` writes the private originals file (0600, no overwrite). Incomplete input is exit 2 with ids and counts only; an existing session is never replaced once its choices file is non-empty. seen: tests/test_g02_session.py 17 pass (LLM-built synthetic; session served through blind_ui in a test); gate 1880 OK (skipped=4) at head. Not run on a real G-02.3 output: seen when G-02.4 runs. Residuals: a generation run that stopped early (fewer sections than originals) builds a smaller session without a warning (wants `--expected-sections` or a strict refusal); `--out` equal to `--choices`/`--originals` is not refused; a record missing `section_id`/`arm` or a missing `--out` directory tracebacks (exit 1, nothing written); 0600 mode untested; repeat-fraction 0.1 and min-gap 3 are executor defaults, not the expert's; `--sections-out` is written before notes extraction, so a resumed g02_notes run is refused until the file is removed.
- [ ] **G-02.5** `[A→H]` Preference rates with intervals; verdict
  - agent half, partial (R231/A2, PR #571, merge aad1262, reviewed head 0f4aa87; Fable review D-014 found a choice/winner mismatch tallied instead of refused, fixed and re-reviewed APPROVE; Claude lane, Codex usage-limited): `experiments/gates/g02.py` (`run(rng, config)`: per comparison the reported arm's win rate with ties at half credit, n, wins/losses/ties, seeded bootstrap 95 % interval, first presentations only; repeats feed one pooled self-consistency figure; completeness counts; `verdict_hint` for `A_vs_C` against the proposed 0.70, never a gate status) and `experiments/g02_draft.py` (CLI `python -m experiments.g02_draft`: only through `run_gate` with a confirmed `g02` preregistration, DRAFT json + md with a Basis line and 'Verdict: owed to the expert (G-02.5 [H])', refuses output under experiments/results/, says 'judge' unless `--judge-is-expert`). Contradicting choices and sessions that break the R231/A1 contract are errors with no numbers. seen: tests 55 pass (LLM-built synthetic); gate 1880 OK (skipped=4) at head; reviewer built a session with main's g02_session CLI, recorded choices and the draft's numbers matched a hand count. Not run on real judgments: seen when G-02.5 runs after BJ-03. Residuals: the hint always uses the proposed 0.70 (the CLI cannot take the expert's confirmed threshold from the preregistration record); the session does not record the generating model (Basis gets it only from `--text-model`); consistency is pooled, not per comparison; non-string ids/arms in a hand-corrupted session traceback; an empty session writes a draft marked complete; registry.toml says `G-02` while gate modules and record files say `g02`.
  - chain rehearsal (R232/A1, PR #575, merge 812ab89, reviewed head 9263c86, Fable review D-014 APPROVE; Claude lane, Codex usage-limited): tests/test_g02_chain.py drives the G-02 CLIs end to end on a loopback stub, each stage consuming the previous stage's printed line; g02_notes now prints the g02_generate line, g02_generate takes `--originals` and prints the g02_session line when complete, g02_session prints the g02_draft line. seen: test_g02_chain OK (6 sections, A_vs_C 0.333 [0.0, 0.796], LLM-built synthetic); gate 1913 OK (skipped=4) on main 812ab89. Residuals: no stage writes the g02_generate `--pool` exemplar pool (the rehearsal substitutes the originals, a guess for the planner or expert); g02_notes prints `next:` even when its run is incomplete (g02_notes.py:237); the ORIGINALS_JSONL placeholder is printed with no note (g02_generate.py:351); the draft seed falls back to 0; blind_ui ran in-process, not as a subprocess. Expert run sheet: docs/expert-run-sheet.md (R232/A2, PR #574, merge 263c989); its Gaps section is stale after #575.

**Proposed threshold:** C preferred over A in ≥ 70 % of pairs.
**Also report:** B vs A (what exemplars alone give) and C vs original (distance still to go).
**If failed:** fine-tuning is the only route to stage 2. Stage 1 continues as data collection, provided G-01 passed.
**Unlocks:** proposal generation, automatic drafting.

---

## G-03 — Embedding model and chunking strategy

- [ ] **G-03.1** `[A]` Candidates: BGE-M3, Jina v3, Nomic Embed, a ModernBERT-based model, one Qwen3-Embedding size
- [ ] **G-03.2** `[A]` Arms: independent sentence embedding; late chunking; contextual prefix; each with and without per-level whitening
- [ ] **G-03.3** `[A]` Task 1: move classification, macro-F1 with a fixed classifier head, documents split train/test
- [ ] **G-03.4** `[A]` Task 2: exemplar retrieval, does the nearest neighbour perform the same move?
- [ ] **G-03.5** `[A]` Latency and memory per 1 000 words; quality at truncated dimensions
- [ ] **G-03.6** `[A→H]` Verdict and chosen default

**Proposed threshold:** winner beats the general-purpose baseline on both tasks at under 2 s per 1 000 words cold.
**If failed:** use the best general-purpose model; drop late chunking and whitening.

---

## G-04 — Is the fast layer close enough to the slow layer?

- [ ] **G-04.1** `[A]` Train the classifier head on LLM labels; test on held-out documents
- [ ] **G-04.2** `[A]` Disagreement rate fast vs slow, per signal (move, redundancy) and per move
- [ ] **G-04.3** `[A]` Accuracy of each layer against expert labels
- [ ] **G-04.4** `[A]` Confidence calibration of the fast layer: is low confidence where the disagreements are?
- [ ] **G-04.5** `[H]` Precision audit of ~50 redundancy flags
- [ ] **G-04.6** `[A→H]` Verdict and visibility policy

**Proposed policy:** disagreement ≤ 10 %: show provisional results immediately. 10–30 %: show only above a confidence cutoff. Above 30 %: hide until confirmed.
**If failed:** that signal comes from the slow layer only.

---

## G-05 — Sequence fit

- [ ] **G-05.1** `[A]` Perturb held-out good reports: delete a move, swap two, insert a foreign one — check: perturbation log with ground truth
  - partial (R36/A1, PR #92): gate runner `experiments/gates/g05.py` (perturb → detectors → sequence_fit, Wilson/bootstrap intervals, perturbation log) merged; synthetic tests only; run_gate refuses until g05 preregistration [H]; residuals: reference sections default to the held-out set (G-05.2 run must pass a separate reference split), held-out sections held in memory untested at corpus scale
- [ ] **G-05.2** `[A]` Detection precision and recall on perturbations; false flags on unperturbed reports
  - partial (R31/A1, PR #82): offline scorer `experiments/metrics/sequence_fit.py` merged; unwired until the G-05 runner; shown only by the G-05 gate run on the held-out split
- [ ] **G-05.3** `[H]` Review 20 flags raised on real drafts
- [ ] **G-05.4** `[A→H]` Verdict

**Proposed threshold:** precision ≥ 0.7 at recall ≥ 0.5; at most one false flag per good report.
**If failed:** sequence fit from the slow layer only.

---

## G-06 — Register fit

- [ ] **G-06.1** `[A]` Build content-controlled pairs: a corpus sentence and an LLM rewrite of it in default style
- [ ] **G-06.2** `[A]` Arms: style-embedding distance to the genre profile; corpus-vs-LLM classifier on sentence embeddings; both
- [ ] **G-06.3** `[A]` AUC on held-out pairs; check the score does not simply track topic
- [ ] **G-06.4** `[H]` Review 30 passages flagged off-register in real drafts
- [ ] **G-06.5** `[A→H]` Verdict

**Proposed threshold:** AUC ≥ 0.8 on content-controlled pairs.
**If failed:** register judged by the slow layer only.

---

## G-07 — Support mapping

- [ ] **G-07.1** `[H]` For ~50 conclusions, mark the passages and source items that support them (`todo-09` AN-05)
- [ ] **G-07.2** `[A]` Retrieval recall@5 of supporting passages
- [ ] **G-07.3** `[A]` Unsupported-conclusion detection: remove the evidence from a copy, check the flag appears
- [ ] **G-07.4** `[A→H]` Verdict

**Proposed threshold:** recall@5 ≥ 0.8; unsupported-conclusion precision ≥ 0.6.
**If failed:** links are made by hand; no automatic support flags.

---

## G-08 — Meaning-preservation check

- [ ] **G-08.1** `[A→H]` Build ~200 rewrite pairs, some preserving meaning and some subtly not; expert labels them (`todo-09` AN-06)
- [ ] **G-08.2** `[A]` Arms: bidirectional entailment; AlignScore; number-and-unit consistency; combined
  - partial (R37/A1, PR #94): offline scorer `experiments/metrics/meaning.py` (RewritePair, number-and-unit arm on service/support_check, score with balanced accuracy/TPR/TNR and Wilson 95% intervals, calibrate for the silent-filter threshold, weighted combine) merged; also covers the G-08.3 computation; synthetic LLM-built pairs only; unwired until the G-08 gate runner; residuals: entailment and AlignScore arms need local models, real pairs wait for G-08.1/AN-06 [A→H]
- [ ] **G-08.3** `[A]` Balanced accuracy; calibrate the silent-filter threshold
  - partial (R38/A1, PR #96): gate runner `experiments/gates/g08.py` (separate required calibration split, calibrated threshold or disabled filter, tpr/tnr/balanced-accuracy/flagged-precision rows with n and intervals) merged; synthetic LLM-built tests only; not run: real pairs wait for G-08.1/AN-06 [A→H] and the g08 preregistration [H]
- [ ] **G-08.4** `[A→H]` Verdict

**Proposed threshold:** agreement ≥ 0.6; silent filter only at ≥ 0.95 precision.
**If failed:** every candidate is shown with its result; nothing is filtered.

---

## G-09 — Overlay legibility

- [ ] **G-09.1** `[A]` Colour-blind simulation on the legend — check: minimum pairwise colour difference above threshold in all three simulations
- [ ] **G-09.2** `[H]` Legend recall after one session
- [ ] **G-09.3** `[H]` Reading comparison: tinted prose vs plain vs margin-only
- [ ] **G-09.4** `[H]` Can the expert tell provisional from confirmed without reading the inspector?
- [ ] **G-09.5** `[A→H]` Verdict

**Proposed threshold:** legend recall ≥ 90 %; no significant reading penalty; colour-blind check passes.
**If failed:** margin ribbons and gutter marks only, no text tint.

---

## G-10 — Fine-tuning *(stage 2, starts when the edit log has enough pairs)*

- [ ] **G-10.1** `[H]` Confirm the minimum pair count (proposed: 500)
- [ ] **G-10.2** `[A]` Train LoRA adapters on corpus plus edit-log pairs, documents held out
- [ ] **G-10.3** `[A]` Leakage test: longest verbatim overlap between outputs and training text
- [ ] **G-10.4** `[H]` Blind pairs: fine-tuned vs exemplars + critic
- [ ] **G-10.5** `[A→H]` Verdict

**Proposed threshold:** expert prefers fine-tuned in the majority of pairs with the interval excluding 50 %; no verbatim leakage beyond a set length.
**If failed:** keep exemplars + critic.

---

## G-11 — Topic overlay *(optional, non-blocking)*

- [ ] **G-11.1** `[H]` Before looking, write down the weak spots of a draft you know well
- [ ] **G-11.2** `[A]` Static topic-cluster view of the draft
- [ ] **G-11.3** `[H]` Verdict

**Proposed threshold:** at least 3 findings not already known.
**If failed:** leave the overlay out.

---

## Mapping from revision 1

| Old | Now |
|---|---|
| E-01 premise | Replaced by G-01 and G-02; the old test survives as optional G-11 |
| E-02 model selection | G-03, measured on new tasks |
| E-03 whitening | An arm of G-03 |
| E-04 segmentation | Dropped; structure comes from Markdown and move labels |
| E-05 cohesion | Replaced by move and sequence fit (G-01, G-05) |
| E-06 colour encoding | Reduced to G-09 |
| E-07 word attribution | Dropped |
| E-08 meaning preservation | G-08 |
| E-09 projection stability | Dropped; the legend is fixed. Layer disagreement is covered by G-04 |

---

## Progress

| Gate | Status | Result doc |
|---|---|---|
| G-01 | ☐ not started | — |
| G-02 | ☐ | — |
| G-03 | ☐ | — |
| G-04 | ☐ | — |
| G-05 | ☐ | — |
| G-06 | ☐ | — |
| G-07 | ☐ | — |
| G-08 | ☐ | — |
| G-09 | ☐ | — |
| G-10 | ☐ | — |
| G-11 | ☐ | — |
