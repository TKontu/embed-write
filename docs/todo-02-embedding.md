# TODO — Embedding Service & Cache

**Phase:** 0–1
**Track:** E (agents)
**Gated by:** G-03 for the model default only; the service itself is ungated
**Depends on:** `todo-03-document-model.md` for node IDs and hashes (develop against a stub)

Markers: `[A]` agent-executable with a mechanical check · `[H]` needs the expert's judgment · `[A→H]` agent prepares, human decides.

The service embeds sentences and blocks, caches by content hash, and hosts the fast layer's inference. The pattern model itself is in `todo-04-analysis.md`.

---

## Service

- [ ] **SV-01** `[A]` Local analysis service: HTTP or IPC, batched requests — check: integration test with a stub client
- [ ] **SV-02** `[A]` Model loading through ONNX Runtime, CPU and GPU paths; warm start — check: startup test on both
- [ ] **SV-03** `[A]` Client contract: the client sends dirty node sets, never whole documents — check: contract test
- [ ] **SV-04** `[A]` Cancellation: an in-flight request is dropped when its text changes — check: test with interleaved edits
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

- [ ] **EM-01** `[A]` Embedder interface: `embed(texts, level) → Vec<Level>`
- [ ] **EM-02** `[A]` Candidate models for G-03 behind the interface
- [ ] **EM-03** `[A]` Level-tagged vector types; comparing across levels is a type error (invariant I2) — check: a cross-level comparison fails to compile or lint
- [ ] **EM-04** `[A]` Truncated-dimension support where the model allows it
- [ ] **EM-05** `[A]` Determinism: same input, model and version give the same vector — check: repeated-run test

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

- [ ] **NM-01** `[A]` L2 normalization
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
