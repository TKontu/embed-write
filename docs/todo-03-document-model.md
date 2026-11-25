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
- [x] **DM-02** `[A]` Serializer preserving the author's conventions (`*` or `_`, heading style, list markers, wrap width)
  - done (R76/A1, PR #191, merge 52e3656): `serializeMarkdown(doc, opts?)` in docmodel/src/serialize.js, exported from index.js; preserves the conventions DM-01 records (em/strong marker, setext/ATX, bullet marker, ``` / ~~~ / indented fences, reference links with definitions, footnotes, table align, front matter, html_block, task boxes, ordered start); escapes Markdown-special text; optional wrapWidth (default no rewrap). Ran on Claude (D-008, Codex at usage limit). seen: docmodel/test/serialize.test.js 38 pass + parse 29 (67/67, reviewer rerun at head 1d6e1c6cd1ee03f706fed993518674f1e1faa3d2 and on main after merge), Python gate 1108 OK; reviewer ran ~55 adversarial round-trips. Unwired by design until DM-03 and ED-01. Residuals: (fixed in R77/A1, PR #195: a `|` inside a table-cell code span is now escaped); adjacent identical footnote refs collapse; reference definitions move to document end and collapsed/shortcut forms become full; unrecorded conventions are normalized (thematic break `---`, backslash hard break, setext underline length, loose-list blank lines, blank-line runs, ordered delimiter, source escapes); GFM autolink literals in schema-built text reparse as links.
- [x] **DM-03** `[A]` Round-trip idempotence suite: parse → serialize → parse is stable — check: passes on a corpus including nested emphasis, reference links, footnotes, aligned tables, code fences containing Markdown, HTML blocks, hard breaks, front matter, setext headings
  - done (R77/A1, PR #195, merge 882b7de): docmodel/test/roundtrip.test.js over 11 LLM-built fixtures in docmodel/test/fixtures/roundtrip/ (nested emphasis, reference links, footnotes, aligned tables, code fences with Markdown, HTML blocks, hard breaks, YAML front matter, setext headings, lists/quotes, pipe in a table code span); asserts parse→serialize→parse doc JSON equality and a serialize fixed point; inline HTML and strikethrough asserted to throw UnsupportedNodeError. Fix: serialize.js codeSpan escapes `|` in table cells. Ran on Claude (D-008). seen: docmodel 83/83 and Python gate 1127 OK, reviewer rerun at head f5718672929c5a805762a1c3aaf3060a51673fdc. Residual (fixed in R78/A2, PR #199, merge 9ee8be9: TOML front matter now throws UnsupportedNodeError and openMarkdown opens it read-only, bytes unchanged; seen: docmodel 92/92, Python gate 1127 OK, reviewer rerun at head 1273a1bbdc2f30dfc28659860c9bd71dca0a51eb).
- [x] **DM-04** `[A]` Property-based fuzzing of the round-trip
  - done (R78/A1, PR #200, merge b02b399): seeded generator docmodel/test/fuzz-gen.js and docmodel/test/fuzz.test.js (in npm test; DOCMODEL_FUZZ_RUNS / DOCMODEL_FUZZ_SEED for longer runs) with a line/block-deletion shrinker; fixes in serialize.js: a leading thematic break is written `***` (`---` reopened as YAML front matter), an already-escaped trailing `#` in ATX heading text is not double-escaped. Ran on Claude (D-008). seen: docmodel 97/97 and Python gate 1127 OK on main combined with PR #199 (reviewer rerun at head 8a032d00446a1786d461abea7994b4c82964072c); long run seed 777, 10000 cases pass (executor). Residuals: nested same-type marks excluded (schema holds one mark per type); not generated: inline HTML, strikethrough, TOML front matter, html_block, indented code, autolink literals, adjacent identical footnote refs; shrinker is deletion-only.
- [x] **DM-05** `[A]` Failure policy: a file that does not round-trip opens read-only with a warning; it is never silently rewritten — check: test with a known-bad file leaves its bytes unchanged
  - done (R77/A2, PR #197, merge bcd21b4): `openMarkdown(src, opts?)` in docmodel/src/open.js returns `{doc, readOnly, warnings}`; read-only with a warning naming the cause on UnsupportedNodeError, on parse→serialize→parse doc drift, or when serialize is not a fixed point; never returns rewritten bytes, never writes files. Ran on Claude (D-008). seen: docmodel/test/open.test.js (known-bad inline-HTML and strikethrough fixtures byte-identical by SHA-256 before/after), docmodel 89/89 and Python gate 1127 OK, reviewer rerun at head fa3f56e17f274963a8271f111da098a679cc1b2d. Unwired by design; ED-01/ED-02 wire it. Residuals: no natural non-fixed-point input found, so that path is tested only with an injected serializer; the "equal doc, differing bytes" branch has no separate test; unsupported files return doc null, so ED-01/ED-02 decide the read-only view; TOML front matter is rejected since R78/A2 (PR #199).
- [ ] **DM-06** `[A]` Report-specific elements: numbered figures and tables, captions, cross-references, units — check: each has a round-trip test

---

## Node identity

- [x] **NI-01** `[A]` ULID per block node in node attributes
  - done (R79/A2, PR #206, merge f03ed3e): `id` attr (default null) on every block-group node plus list_item, table_row, table_cell in docmodel/src/schema.js; docmodel/src/ids.js exports `ulid(now?, rand?)` (Crockford base32, monotonic within one ms, injectable clock/random, no dependency) and `assignIds(doc, opts?)` (new doc, existing ids kept, duplicates first-wins); parseMarkdown leaves ids null; serialize output byte-identical with ids on all round-trip fixtures. parse.test.js json helper strips null ids (scope deviation accepted in review; no assertions changed). Ran on Claude (D-008, Codex at usage limit). seen: docmodel/test/ids.test.js, docmodel 135/135 combined with HI-02 at reviewed head 547b76974263a446840e25b2a5bb6a08fb54443b and on main, Python gate 1127 OK. Unwired by design; NI-02/ED-01 wire it. Residuals: ulid monotonic state is module-global; RangeError on random overflow within one ms.
- [ ] **NI-02** `[A]` Sidecar file `<doc>.stw.json`: node IDs, structural paths, content hashes
- [ ] **NI-03** `[A]` Reattachment after an external edit: match by hash, then path, then fuzzy content; unmatched nodes get new IDs — check: test matrix of external changes
- [ ] **NI-04** `[A]` Split: the first half keeps the ID. Merge: the first node's ID survives. Move: all descendant IDs survive — check: tests for each, including undo
- [ ] **NI-05** `[A]` Sentence identity inside a block: stable sentence keys derived from block ID and content hash, so signals and edit-log entries can address a sentence
  - partial (R34/A1, PR #88): key function `service/sentence_keys.py` (`<block_id>:<hash>`, repeats get `#n`) merged; caller supplies hashes (HS-01 owns hashing); unwired until HI-03 and the edit log; residual: repeat-sentence keys depend on order in the block

---

## Hierarchy

- [x] **HI-01** `[A]` Section tree from headings, tolerating skipped levels and documents without headings
  - done (R78/A3, PR #202, merge 52024b5): `sectionTree(doc)` in docmodel/src/sections.js, exported from index.js; derived nested tree (root level 0; sections hold heading text and top-level index, block indices, children); skipped levels nest under the nearest lower level; only top-level headings count; pure, nothing stored in the doc. Ran on Claude (D-008, Codex at usage limit). seen: docmodel/test/sections.test.js 11 pass, docmodel 108/108 and Python gate 1127 OK at reviewed head 87ee88a151b3c10dc2f5486e5b9c766c3fa66e84 and on main. Unwired by design; HI-02/ED-01 wire it. Residual: indices are positional, so they shift on edits until node IDs (NI-01) exist.
- [x] **HI-02** `[A]` Block layer: paragraphs, list items, tables, figures, code, quotes
  - done (R79/A1, PR #205, merge 3c570b3): `blockLayer(doc)` in docmodel/src/blocks.js, exported from index.js; flat document-ordered entries `{kind, path, text, section}` (kinds paragraph, list_item, table, figure, code, quote, heading, html, front_matter, footnote, thematic_break; image-only paragraph is a figure; lists are containers, nested items get own entries; quote/table/code one entry); section from sectionTree. Ran on Claude (D-008). seen: docmodel/test/blocks.test.js 7 pass, docmodel 115/115 reviewer rerun at head 55ab8e79ab66c7182cfd5f658d00e421ac21ad5d, 135/135 on main, Python gate 1127 OK. Unwired by design; HI-03/ED-01 wire it. Residuals: paths positional (NI-01 ids not yet used); lists nested in a quote/footnote inside an item are not separate entries; html and front_matter entries have empty text.
- [ ] **HI-03** `[A]` Sentence layer: lazy, cached by block hash, not stored in the ProseMirror doc
- [ ] **HI-04** `[A]` Section type mapping: map a heading to a section type of the genre ("Findings", "Conclusions"), using the genre file — check: mapping test on corpus headings; unmapped headings reported

---

## Hashing and dirty sets

- [x] **HS-01** `[A]` Normalized text per node (whitespace collapsed, marks stripped) and blake3 hash
  - done (R80/A1, PR #208, merge f428af3): `normalizeText(node)`, `hashText(str)`, `nodeHash(node)` in docmodel/src/hash.js, exported from index.js; text content with marks and all attrs (ids, markers) ignored, hard breaks and block boundaries as one space, Unicode whitespace runs collapsed, trimmed; blake3 (@noble/hashes 1.8.0, pinned) over UTF-8, 64-char lowercase hex. Ran on Claude (D-008, Codex at usage limit). seen: docmodel/test/hash.test.js (acceptance a-g incl. blake3 empty vector), docmodel 142/142 reviewer rerun at head a61a5baad891cb50a0b90ce088031c687edc0b4a and on main, Python gate 1127 OK (coordinator .venv; lane lacked pysbd). Unwired by design; NI-02/HI-03/PM-02 wire it. Residuals: no NFC normalization; atoms (image, html_block, front_matter, thematic_break) hash as empty text, so all such nodes share one hash.
- [x] **HS-02** `[A]` Dirty set from a transaction: changed nodes plus ancestors
  - done (R81/A2, PR #210, merge f10c902): `dirtySet(tr)` (final-doc node ids whose node differs from tr.before, by id + ProseMirror eq, plus id-bearing ancestors; null-id nodes reported via nearest id-bearing ancestor; mark-only and attr-only edits dirty their node) and `dirtyRanges(tr)` (step-map ranges mapped to final coordinates, sorted, touching ranges merged) in docmodel/src/dirty.js; prosemirror-transform 1.10.4 pinned. Ran on Codex (D-001). seen: docmodel/test/dirty.test.js (acceptance a-h), docmodel 153/153 executor and reviewer rerun at head 15cd95189b04994aca15e14aba1cac1f413124a7, Python gate 1127 OK (executor). Unwired by design; HS-03/HS-04/ED-01 wire it. Residuals: dirtySet indexes tr.before in O(document nodes) per call (not range-bounded); deleting a top-level block yields an empty set (only dirtyRanges reports the point).
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
