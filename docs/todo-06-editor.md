# TODO — Editor & App Shell

**Phase:** 0–2
**Track:** E (agents)
**Gated by:** nothing
**Depends on:** document model (`todo-03`)

Markers: `[A]` agent-executable with a mechanical check · `[H]` needs the expert's judgment · `[A→H]` agent prepares, human decides.

A native writing surface over Markdown: the expert sees formatted text, shortcuts inject the Markdown syntax into the file. Built on Milkdown (MIT, ProseMirror), so the whole stack stays open source. No research risk; can start immediately in parallel with the fatal gates.

---

## Foundation

- [x] **ED-01** `[A]` Milkdown setup with a schema covering the Markdown features reports use — check: every schema node has a round-trip test in `todo-03` DM-03
  - done (R87/A1, PR #228, merge 865ef50): new ESM package `editor/` exporting `createEditor({root, markdown})`. It is a Milkdown 7.23.0 editor whose state schema is docmodel's own Schema instance. It loads via docmodel `parseMarkdown`, registers `overlayPlugin` and `idPlugin`, and `getMarkdown()` uses `serializeMarkdown`. New docmodel/test/schema-coverage.test.js covers every schema node and mark; it found `thematic_break` uncovered, so fixture thematic-break.md was added. Ran on Claude (D-008). seen: planner rerun at head 26175d54a92b7ba917a8f69cf5cf86c3adcba21d: editor 15/15 under jsdom, docmodel 207/207, Python gate 1136 OK. Unwired by design until the Tauri shell row. Residuals: DOM rendering lives in editor/src/render.js node views (docmodel schema has no toDOM), structure only, no CSS; prosemirror-state/transform/view are pinned via npm overrides plus `install-links=true` to avoid duplicate prosemirror copies; editor tests are not in CI yet.
- [ ] **ED-02** `[A]` Schema decisions recorded: first-class nodes, passthrough HTML, unsupported constructs and what happens when a file contains them
- [ ] **ED-03** `[A]` One serializer, shared with the document model
- [ ] **ED-04** `[A]` Source view toggle showing the raw Markdown
  - partial (R127/A1, PR #323, merge 504c297): `createEditor` handle gains `showSource()`, `showRich()`, `isSourceView()` (editor/src/source.js); textarea `md-source` holds `serializeMarkdown` output, `showRich` parses with docmodel `parseMarkdown` in one undoable transaction, a throwing parse keeps source view. Ran on Claude (D-008). Tests: planner rerun at head befc91e: editor 63/63 under jsdom, docmodel 256/256, Python gate 1455 OK. Unwired by design: stays partial until AP-01 shell adds the toggle control; not yet seen in the app. Residuals: no CSS, no keyboard shortcut; editor tests not in CI.
- [ ] **ED-05** `[A]` Autosave with atomic writes — check: kill the process mid-save, file is intact
  - partial (R128/A1, PR #325, merge 8951fae): editor/src/autosave.js exports `atomicWrite(path, text)` (same-dir temp, fsync, rename, dir fsync; temp removed on failure) and `createAutosave({ getMarkdown, write, delayMs })` (debounced, serialized, failed write stays dirty). Ran on Claude (D-008). Check: test spawns a child writing several-MB text and SIGKILLs it across 8 iterations; target always equals a whole old or new text. Planner rerun at head 4456e99: editor 72/72, docmodel 256/256, Python gate 1455 OK. Unwired by design until AP-01 owns file I/O; not yet seen in the app. Residuals: editor tests not in CI.

---

## Formatting shortcuts

- [ ] **FM-01** `[A]` `Ctrl/Cmd+B`, `+I`, `+K`, `+E` for bold, italic, link, inline code — check: each produces the expected Markdown
  - partial (R129/A2, PR #328, merge bcfe830): editor/src/format.js `formatKeymap({ isRich, onLinkRequest })` wired in createEditor: Mod-b strong, Mod-i em, Mod-e code toggle the selection; Mod-k removes an existing link or asks `onLinkRequest(text)` for an href (null/empty = no change; a doc change before it resolves cancels it); inactive in source view. Ran on Claude (D-008). Check: jsdom tests assert Markdown after each shortcut and after toggling back. Planner rerun at head 3773a57: editor 80/80, docmodel 256/256, Python gate 1455 OK; combined main bcfe830 Python 1460 OK. Unwired by design until AP-01 supplies the link prompt; not yet seen in the app. Residuals: no link-prompt UI; editor tests not in CI.
- [ ] **FM-02** `[A]` Heading shortcuts `Ctrl/Cmd+1..6` and `#` + space
  - partial (R130/A1, PR #331, merge be46aa8): editor/src/format.js `headingKeymap` (Mod-1..6 set heading level N, toggle back to paragraph when already N) and `headingInputRule` (`#`..`######` + space at paragraph start), wired in createEditor; inactive in source view. Ran on Claude (D-008). Check: editor/test/heading.test.js (jsdom) asserts Markdown after each. Planner rerun at head fea8301: editor 92/92; lane docmodel 256/256, Python 1460 OK; combined main be46aa8 Python 1460 OK. Unwired by design until AP-01; not yet seen in the app. Residuals: jsdom-simulated typing only; editor tests not in CI.
- [ ] **FM-03** `[A]` Input rules for lists, task items, quotes, code fences, rules
  - partial (R131/A1, PR #333, merge c614470): editor/src/format.js `blockInputRules({ isRich })` wired in createEditor: `- `/`* `/`+ ` bullet list (marker kept), `N. ` ordered list from N, `> ` blockquote, `[ ] `/`[x] ` at a list item start a task item, ```` ```lang ```` + space or Enter a code block, `---`/`***`/`___` on an empty paragraph a thematic break; only at paragraph start, inactive in source view. Ran on Claude (D-008). Check: editor/test/blockrules.test.js (jsdom, 18 tests, 15 failed before impl). Planner rerun at head 32e6b54: editor 110/110, docmodel 256/256, Python 1460 OK. Unwired by design until AP-01; not yet seen in the app. Residuals: thematic break always serializes as `***` (FM-07); jsdom-simulated typing only; editor tests not in CI.
- [ ] **FM-04** `[A]` Inline input rules: typing `*text*` converts live
  - partial (R133/A1, PR #337, merge 072e170): editor/src/format.js `inlineInputRules({ isRich })` wired in createEditor: closing delimiter converts `*x*`/`_x_` to em, `**x**`/`__x__` to strong (marker kept), `` `x` `` to inline code; no conversion for empty or whitespace-bounded spans or intraword `_`; inactive in source view, code blocks and inline code. Strikethrough skipped: the schema has no strike mark (needs a decision). FM-06 Backspace undoes inline rules too. Ran on Claude (D-008). Check: editor/test/inlinerules.test.js and escape.test.js (11 failed before impl). Planner rerun at head 06cfc87: editor 144/144, docmodel 256/256, Python 1460 OK. Unwired by design until AP-01; not yet seen in the app. Residuals: spans crossing other inline nodes never convert; jsdom-simulated typing only; editor tests not in CI.
- [ ] **FM-05** `[A]` Paste: Markdown pastes as formatted content, rich HTML converts to Markdown-representable structure, plain text stays plain
- [ ] **FM-06** `[A]` Escape hatch: literal `*` can be typed; one backspace undoes an input rule
  - partial (R132/A1, PR #335, merge 549f746): editor/src/format.js `escapeKeymap({ isRich })` wired first in createEditor's plugins: Backspace right after an FM-02/FM-03 input rule inverts the rule and the transactions appended after it (docmodel idPlugin) and restores the typed literal text; a second Backspace deletes normally; inactive in source view. Ran on Claude (D-008). Check: editor/test/escape.test.js (jsdom, 11 tests, 7 failed before impl). Planner rerun at head 7a51cd6: editor 121/121; lane docmodel 256/256; combined main 549f746 Python 1460 OK. Unwired by design until AP-01; not yet seen in the app. Residuals: after undoing ```` ``` ```` + space the trailing space does not round-trip byte for byte (docmodel drops it on parse); literal `*` against inline rules now covered by escape.test.js (R133/A1); jsdom-simulated typing only; editor tests not in CI.
- [ ] **FM-07** `[A]` Style preservation: new formatting follows the file's existing conventions — check: edit-and-save diff touches only the edited lines

---

## Report-writing behaviours

- [ ] **BH-01** `[A]` Tables: insert and delete rows and columns, Tab navigation
- [ ] **BH-02** `[A]` Figures with captions and automatic numbering
- [ ] **BH-03** `[A]` Cross-references to figures, tables and sections that update on renumbering — check: renumbering test
- [ ] **BH-04** `[A]` Footnotes; link editing without raw syntax
- [ ] **BH-05** `[A]` Images referenced by path, never embedded as base64
- [ ] **BH-06** `[A]` Section templates from the genre file: insert a new report with the genre's section skeleton
- [ ] **BH-07** `[A]` Undo grouping: typing runs coalesce, formatting is its own step

---

## Integration with analysis

- [ ] **IA-01** `[A]` Transaction hook: compute the dirty set, dispatch a debounced request
- [ ] **IA-02** `[A]` Results applied as decorations through plugin state, never by changing the document — check: document hash unchanged by any analysis result
- [ ] **IA-03** `[A]` Typing is never blocked by analysis — check: typing latency unchanged with the analysis service stopped, slow or erroring
- [ ] **IA-04** `[A]` Selection hook: selecting a passage enables "propose rewrite" and shows its signals
- [ ] **IA-05** `[A]` Edit-log hook: accept, reject and manual edits of machine text are reported to the edit log (invariant I7) — check: every provenance change produces a log entry

---

## Performance

- [ ] **EP-01** `[A]` Typing latency at 100 000 words, overlays on and off — check: within a set margin of a plain editor
- [ ] **EP-02** `[A]` Batched view updates; no full re-render per keystroke
- [ ] **EP-03** `[A]` Memory profile over a long session; no leak in decorations or signal cache

---

## App shell

- [x] **AP-01** `[A]` Tauri or Electron shell; choose by whether the model runtime integrates cleanly — check: both analysed in a short decision record
  - done R114 (PR #294): `docs/ap01-shell.md` analyses both; recommends keeping Tauri (D-007). seen: docs/ap01-shell.md. Owed to operator: its open questions, first approving a Rust toolchain + WebKitGTK dev libs install (D-005 pattern), which the shell scaffold needs.
- [ ] **AP-02** `[A]` Open, save, recent files, detection of external changes
- [ ] **AP-03** `[A]` Genre selection per document; genre files loaded from a local folder
- [ ] **AP-04** `[A]` Settings: models, overlay defaults, theme, performance tier, remote-model opt-in
- [ ] **AP-05** `[A]` Debug panel: cache statistics, latency, layer disagreement rate, gate statuses
- [ ] **AP-06** `[A]` Fully functional offline — check: test suite passes with the network disabled

---

## Human checks

- [ ] **HU-01** `[H]` A week of real writing in the editor with overlays off: is it a writing tool the expert would choose?

---

## Acceptance criteria

- Every shortcut produces Markdown the round-trip suite accepts
- An edit-save cycle changes only the lines that were edited
- Typing latency is unaffected by the state of the analysis service
- The app works with the network disabled
- Every change to machine text reaches the edit log
