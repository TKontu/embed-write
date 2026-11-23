# TODO — Embedding Service & Cache

**Phase:** 0–1
**Track:** E (agents)
**Gated by:** G-03 for the model default only; the service itself is ungated
**Depends on:** `todo-03-document-model.md` for node IDs and hashes (develop against a stub)

Markers: `[A]` agent-executable with a mechanical check · `[H]` needs the expert's judgment · `[A→H]` agent prepares, human decides.

The service embeds sentences and blocks, caches by content hash, and hosts the fast layer's inference. The pattern model itself is in `todo-04-analysis.md`.

---

## Service

- [x] **SV-01** `[A]` Local analysis service: HTTP or IPC, batched requests — check: integration test with a stub client
  - done (R14/A1): `service/server.py` (AnalysisService, echo_handler); stdlib ThreadingHTTPServer on loopback, `POST /v1/batch` (one handler call per batch, results in order), `GET /v1/health`, 400/404/413/500 JSON errors, `max_batch`/`max_body_bytes` bounds. SV-05 is now wired by service/server.py: bind host checked with `check_host` (fail closed) and `guard_sockets` active for the service lifetime. seen: tests/test_server.py, 308 tests OK at base 7190f7e + this change. AnalysisService unwired by design until SV-02/SV-03. Residuals: `guard_sockets` patches process-wide while the service runs (not per-thread); no auth; oversize bodies are rejected without draining.
- [ ] **SV-02** `[A]` Model loading through ONNX Runtime, CPU and GPU paths; warm start — check: startup test on both
- [x] **SV-03** `[A]` Client contract: the client sends dirty node sets, never whole documents — check: contract test
  - done (R15/A1): `service/contract.py` (node_hash, dirty_nodes, build_request, validate_items, ContractError) and `service/client.py` (AnalysisClient). `POST /v1/batch` now enforces the contract by default (`contract=True`, `max_node_chars=20000`): missing/mismatched hash, duplicate ids and over-long node text → 400. AnalysisService now has a production client (AnalysisClient), which checks its base URL with SV-05 `check_url` and sends no request for an empty dirty set. seen: tests/test_contract.py, 317 tests OK at base 8fec3ee + this change. AnalysisClient unwired by design until the editor client (todo-03/todo-05) calls it. Residuals: `node_hash` is a sha256 stub until todo-03 supplies node hashes; the client does not split dirty sets larger than `max_batch` (service returns 400); SV-01 tests run with `contract=False` to keep testing framing alone.
- [x] **SV-04** `[A]` Cancellation: an in-flight request is dropped when its text changes — check: test with interleaved edits
  - done (R16/A1): `service/client.py` (AnalysisClient.analyze, submit, close) tracks generations and hashes for active dirty nodes, filters superseded results per node, cancels fully superseded queued futures, and joins its two executor workers on close. At most 64 outstanding calls; tracking is released on completion/cancellation/error. seen: tests/test_cancellation.py (8 deterministic loopback tests), `python3 -m unittest tests.test_cancellation tests.test_contract` → 17 tests OK at base 622356b + this change. Production caller: AnalysisClient; submit/close unwired by design until the editor client (todo-03/todo-05). Residuals: callers must notify edits through analyze/submit; completed futures are delivered snapshots; running HTTP is discarded locally, not aborted on the server, and close waits for running exchanges (socket timeout applies). Existing per-request service size bounds remain; no model/private-corpus path exercised.
- [x] **SV-05** `[A]` Network guard: no outbound connection unless a remote model is explicitly enabled (invariant I9) — check: test fails closed
  - done (R13/A1): `service/network_guard.py` (NetworkPolicy, NetworkPolicy.allow_remote, check_url, check_host, guard_sockets, NetworkGuardError); loopback only by default, no DNS in checks. seen: tests/test_network_guard.py, 300 tests OK at base f593e96 + this change. Unwired by design until SV-01 wires it. Residuals: guard patches only `socket.socket.connect`/`connect_ex` and `socket.create_connection` (raw `_socket` or subprocess traffic is not covered); opt-in hosts match by exact name, not by resolved IP.

---

## Chunking

- [ ] **CK-01** `[A]` Structural chunking from the document model hierarchy; no re-derivation of structure
- [ ] **CK-02** `[A]` Sentence segmentation with PySBD or spaCy — check: test set with abbreviations, decimals, units, quotations, inline code, footnote markers
- [ ] **CK-03** `[A]` Segmentation cache keyed by block hash
- [ ] **CK-04** `[A]` Late chunking (embed the section once, pool per sentence), as an arm for G-03
- [ ] **CK-05** `[A]` Contextual-prefix arm for G-03
- [ ] **CK-06** `[A]` Policy for tables, code, figures and captions: skipped, embedded as caption, or summarized — check: each type has a tested path

---

## Embedding

- [x] **EM-01** `[A]` Embedder interface: `embed(texts, level) → Vec<Level>`
  - done (R18/A1): `service/embedder.py` (Embedder, EmbedderError, embed, HashEmbedder); model-agnostic protocol, validated level-tagged results and bounded batches (default 64), empty-input fast path, deterministic normalized stdlib hash stub for tests/development only. seen: tests/test_embedder.py, `python3 -m unittest tests.test_embedder` → 11 tests OK at base 8202622d5d990fd1569150a008dccc711d320940 + this change; `python3 scripts/lint_levels.py service analysis` → exit 0. HashEmbedder calls NM-01 l2_normalize and returns EM-03 LevelVector; unwired by design until EM-02/SV-02 provide a model and the service handler calls embed. Residuals: caller holds the full input and output; wrapper holds at most batch_size input references plus output; backend must preserve semantic order (vectors carry no input identity to verify it); no real model/private-corpus path exercised.
- [ ] **EM-02** `[A]` Candidate models for G-03 behind the interface
- [x] **EM-03** `[A]` Level-tagged vector types; comparing across levels is a type error (invariant I2) — check: a cross-level comparison fails to compile or lint
  - done (R17/A1): `service/vectors.py` (Level, LevelVector, CrossLevelError, dot, cosine, normalized) and `scripts/lint_levels.py`; frozen finite non-empty float tuples, runtime cross-level rejection including equality, literal-level AST checks and known raw-similarity import checks. seen: tests/test_vectors.py and tests/test_lint_levels.py (12 tests OK); full offline gate `python3 -m unittest discover -s tests` → 350 tests OK at base e2a028b6605c68ba1cb31db3bf7ebd36c6e4d0e9 + this change; `python3 scripts/lint_levels.py service analysis` → exit 0. Unwired by design until EM-01 returns LevelVector. Per-vector O(d) memory. Residuals: CI lint wiring deferred to a later row; lint does not infer variable levels, resolve aliases, detect custom raw-similarity imports or math on `.values`; raw dot products retain float overflow limits; no local-model/private-corpus path exercised.
- [ ] **EM-04** `[A]` Truncated-dimension support where the model allows it
- [x] **EM-05** `[A]` Determinism: same input, model and version give the same vector — check: repeated-run test
  - done (R19/A2): `service/determinism.py` (DeterminismError, check_determinism); exact float-tuple, level and dimension comparisons across repeated runs, reversed input order and optional batch_size=1, with first differing input index/run and available model identity in errors. seen: tests/test_determinism.py, `python3 -m unittest tests.test_determinism` → 8 tests OK at base 4a85d410b27d109a442ffec44cf9fbad6414aaf8 + this change. Production caller: unwired by design until EM-02 runs it on each candidate model. Caller supplies a bounded text list; retains baseline/current vectors and reversed input references, independent of run count. Residuals: bit-identity checked only for the in-process backend, GPU nondeterminism untested; exact float tuple equality treats signed zeros as equal; no real model/private-corpus path exercised.

---

## Cache

- [ ] **CA-01** `[A]` LMDB store keyed `(modelId, modelVersion, level, contentHash, dims)`
- [ ] **CA-02** `[A]` Append-only entries; a new model version is a new keyspace
- [ ] **CA-03** `[A]` Size-capped eviction — check: test at the cap
- [ ] **CA-04** `[A]` Corruption handling: a bad entry fails loudly — check: fault-injection test
- [ ] **CA-05** `[A]` Benchmark: cold analysis of a 100 000-word document; record the number

---

## Normalization

Reduced in revision 2. L2 normalization is the default. Whitening is an arm of G-03 and is built into the product only if it wins there.

- [x] **NM-01** `[A]` L2 normalization
  - done (R16/A2): `service/normalize.py` (NormalizationError, l2_normalize, l2_normalize_batch); stdlib-only, scale-before-squaring normalization rejects empty, zero and non-finite vectors. Batch yields lazily with O(1) batch overhead and O(d) current output memory. seen: tests/test_normalize.py (13 tests OK), full offline gate 330 tests OK at base 622356bca33b46224938d097feba88d734da8e01 + this change. Unwired by design until EM-01 embedder calls it. Residuals: no local-model path exercised; level typing remains EM-03; components below floating-point range may underflow to zero.
- [ ] **NM-02** `[A]` Whitening and all-but-the-top as experiment arms, fitted per level on the corpus
- [ ] **NM-03** `[A]` If adopted: persist the fitted transform with the genre so results are reproducible — check: reload gives identical vectors

---

## Incremental recompute

- [ ] **IR-01** `[A]` Dirty-set protocol: `{changedNodeIds, newHashes}` in, affected signals out
- [ ] **IR-02** `[A]` Ancestor invalidation: a changed sentence dirties its block and section
- [ ] **IR-03** `[A]` Late-chunking invalidation: one changed sentence changes all sibling vectors in the section. Measure the cost; if too high, the live path uses independent embedding and late chunking runs on idle — check: benchmark recorded, decision documented
- [ ] **IR-04** `[A]` Latency benchmark, keystroke to updated fast-layer signal, p50 and p95 on a 100 000-word document

---

## Acceptance criteria

- Warm recompute after a one-sentence edit returns fast-layer signals in under 100 ms
- Cross-level comparison cannot be written without defeating the type system
- The model default traces to a recorded G-03 result
- No outbound network traffic in the default configuration
