# TODO — Document Model & Node Identity

**Phase:** 0–2
**Track:** E (agents)
**Gated by:** nothing
**Blocks:** editor, corpus ingestion, incremental recompute, overlays

Markers: `[A]` agent-executable with a mechanical check · `[H]` needs the expert's judgment · `[A→H]` agent prepares, human decides.

No research risk and total structural risk. If node IDs are not stable, the cache thrashes, overlays jump and the edit log cannot say which passage was corrected. Almost every task here has a mechanical check, so this file is well suited to agent execution.

---

## Markdown ⇄ ProseMirror

- [x] **DM-01** `[A]` Parse pipeline: remark → mdast → ProseMirror doc
  - done (R75/A1, PR #189, merge 5e0d2bf): new ESM package `docmodel/` (plain JS + JSDoc) exporting `parseMarkdown`, `schema`, `UnsupportedNodeError`; remark-parse + remark-gfm + remark-frontmatter(yaml), pinned exact versions. Source conventions kept as attrs (em/strong marker, heading setext, code fence, bullet marker, link/image `ref`). Ran on Claude (D-008 fallback, Codex at usage limit). seen: docmodel/test/parse.test.js 29 pass (reviewer rerun at head 0f50924864ac6969408ca1a73fb54e1f08e2234a), Python gate 1108 OK. Unwired by design until DM-02/DM-03 and ED-01. Residuals: strikethrough, inline HTML and TOML front matter throw UnsupportedNodeError (real documents with inline HTML do not parse yet); footnote_reference is a mark on text equal to its label; not recorded: list spread, ordered delimiter, table header row, escapes, link destination form, code fence meta; extra attrs list_item.checked, image.ref; docmodel CI step is only in nightly.yml (schedule/dispatch), not yet run in CI.
- [ ] **DM-02** `[A]` Serializer preserving the author's conventions (`*` or `_`, heading style, list markers, wrap width)
- [ ] **DM-03** `[A]` Round-trip idempotence suite: parse → serialize → parse is stable — check: passes on a corpus including nested emphasis, reference links, footnotes, aligned tables, code fences containing Markdown, HTML blocks, hard breaks, front matter, setext headings
- [ ] **DM-04** `[A]` Property-based fuzzing of the round-trip
- [ ] **DM-05** `[A]` Failure policy: a file that does not round-trip opens read-only with a warning; it is never silently rewritten — check: test with a known-bad file leaves its bytes unchanged
- [ ] **DM-06** `[A]` Report-specific elements: numbered figures and tables, captions, cross-references, units — check: each has a round-trip test

---

## Node identity

- [ ] **NI-01** `[A]` ULID per block node in node attributes
- [ ] **NI-02** `[A]` Sidecar file `<doc>.stw.json`: node IDs, structural paths, content hashes
- [ ] **NI-03** `[A]` Reattachment after an external edit: match by hash, then path, then fuzzy content; unmatched nodes get new IDs — check: test matrix of external changes
- [ ] **NI-04** `[A]` Split: the first half keeps the ID. Merge: the first node's ID survives. Move: all descendant IDs survive — check: tests for each, including undo
- [ ] **NI-05** `[A]` Sentence identity inside a block: stable sentence keys derived from block ID and content hash, so signals and edit-log entries can address a sentence
  - partial (R34/A1, PR #88): key function `service/sentence_keys.py` (`<block_id>:<hash>`, repeats get `#n`) merged; caller supplies hashes (HS-01 owns hashing); unwired until HI-03 and the edit log; residual: repeat-sentence keys depend on order in the block

---

## Hierarchy

- [ ] **HI-01** `[A]` Section tree from headings, tolerating skipped levels and documents without headings
- [ ] **HI-02** `[A]` Block layer: paragraphs, list items, tables, figures, code, quotes
- [ ] **HI-03** `[A]` Sentence layer: lazy, cached by block hash, not stored in the ProseMirror doc
- [ ] **HI-04** `[A]` Section type mapping: map a heading to a section type of the genre ("Findings", "Conclusions"), using the genre file — check: mapping test on corpus headings; unmapped headings reported

---

## Hashing and dirty sets

- [ ] **HS-01** `[A]` Normalized text per node (whitespace collapsed, marks stripped) and blake3 hash
- [ ] **HS-02** `[A]` Dirty set from a transaction: changed nodes plus ancestors
- [ ] **HS-03** `[A]` Coalescing of rapid keystrokes into one dirty set
- [ ] **HS-04** `[A]` Correctness under undo and redo — check: property test comparing incremental dirty sets with a full recompute

---

## Position mapping

- [ ] **PM-01** `[A]` Overlay positions survive transactions — check: apply a decoration, make 100 random edits elsewhere, assert it covers the same text
- [ ] **PM-02** `[A]` Stale-result policy: a result for a node whose hash has changed is discarded, never drawn

---

## Genre binding and source links

- [ ] **SL-01** `[A]` Sidecar field binding a document to a genre and inventory version
- [ ] **SL-02** `[A]` Span-to-source links: a sentence or span references source item IDs; links survive edits elsewhere and are dropped when their text is deleted — check: link-survival tests
- [ ] **SL-03** `[A]` Draft provenance per node: `human`, `machine`, or `machine-edited`, with the generation run ID — check: provenance updates correctly on accept, reject and manual edit (feeds the edit log)

---

## Acceptance criteria

- Round-trip idempotent on at least 50 real documents and the whole reference corpus
- IDs survive split, merge, move, delete, undo, reopen and external edit
- Dirty sets equal a full recompute under any edit sequence
- No overlay is ever drawn against text it does not belong to
- Provenance of every block is known
