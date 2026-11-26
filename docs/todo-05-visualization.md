# TODO — Overlays, Legend & Rendering

**Phase:** 2
**Track:** E for implementation, R for G-09
**Gated by:** G-09 (legibility); individual overlays by their signal's gate
**Depends on:** document model, editor, pattern model

Markers: `[A]` agent-executable with a mechanical check · `[H]` needs the expert's judgment · `[A→H]` agent prepares, human decides.

Colour is the expert's main channel into the pattern model. Revision 2 replaces the continuous projection with a fixed legend: one colour per move, the same in every document of the genre.

---

## Legend

- [ ] **LG-01** `[H]` Colour per move, chosen with the expert (`todo-09` MV-04)
- [ ] **LG-02** `[A]` Legend stored in the genre file, never computed at runtime (invariant I3) — check: test that two documents of one genre render a move identically
  - partial (R163/A1, PR #411, merge 0138995): `editor/src/legend.js` legendCss(genre) emits one `--signal-color` rule per move in genre.moves order plus `other`, colours copied from the genre file (validation mirrors service/genre.py). seen: editor/test/legend.test.js 10 tests incl. two documents of one genre render a move with the same colour (jsdom, LLM-built synthetic fixture), npm test 219/219 and gate 1594 OK at head b5a8675 (rerun by planner). Stays partial: unwired by design until AP-01/LG-07 load the genre file and link the stylesheet.
  - seen in demo (R173/A1, DE-06): editor/demo/app.js injects legendCss(examples/demo/genre.json) into a `<style>`; demo overlay decorations are matched by its rules. seen: editor/test/demo-overlay.test.js (jsdom). No browser run.
- [ ] **LG-03** `[A]` Palette validation: minimum pairwise colour difference, in normal vision and three colour-blind simulations — check: automated, fails the build below threshold
  - partial (R32/A1, PR #84): validator `service/palette.py` (CIEDE2000, Machado CVD sims, CLI exits 1 below threshold) merged; MIN_DELTA_E=20 provisional for the expert under G-09; unwired until LG-02/LG-05; no palette until LG-01 [H], no CI wiring
  - partial (R166/A1, PR #418, merge 5bc987a): `python3 -m service.palette --genre PATH` validates legend.colors (moves order, "_" keys skipped) plus legend.other via genre_palette(); invalid genre file exits 2. seen: tests/test_palette.py 13 tests (LLM-built synthetic genre fixtures, placeholder colours), gate 1599 OK at head 9b1eb54 (rerun by planner). Stays partial: no CI step runs --genre on the real genre file; no palette until LG-01 [H]. Next: LG-04 contrast check reads the genre file via genre_palette.
- [ ] **LG-04** `[A]` Contrast floor: tinted text stays above a set contrast ratio in light and dark themes — check: automated contrast test
  - partial (R33/A1, PR #86): check `service/contrast.py` (WCAG luminance/contrast, tint blended over theme background, CLI exits 1 on shortfall) merged; MIN_CONTRAST=4.5 and alpha provisional for the expert under G-09; unwired until RE-04/LG-05; no theme colours until LG-01 [H]/LG-05, no CI wiring
  - partial (R167/A1, PR #422, merge db1c45f): `python3 -m service.contrast SPEC --genre PATH` takes the palette from genre_palette(load_genre(PATH)) (every move plus `other`); the spec supplies only alpha/themes; palette in spec with --genre, or invalid genre file, exits 2. seen: tests/test_contrast.py GenreCliTests 6 tests (LLM-built synthetic genre fixtures, placeholder colours), gate 1609 OK at head e309147 (rerun by planner). Stays partial: no dark theme (LG-05), no CI step on the real genre file, MIN_CONTRAST/alpha provisional (G-09 expert).
- [ ] **LG-05** `[A]` Separate dark-theme palette, validated the same way
- [ ] **LG-06** `[A]` Neutral rendering for `other` and for unlabeled text
  - partial (R164/A1, PR #414, merge dbbc5dc): tests only, no behaviour change (comment in `editor/src/signals.css`). `other` takes legend.other; unlabeled text and unknown kinds get no `--signal-color` and fall back to transparent (no invented colour, I3). seen: editor/test/neutral.test.js 4 tests (jsdom, LLM-built placeholder colours), npm test 229/229 and gate 1594 OK at head 55953f1 (rerun by planner); combined main dbbc5dc same. Residual: jsdom cannot paint color-mix, fallback rule checked instead. Stays partial: unwired until AP-01/LG-07 and RE-10 link the stylesheets in the app.
- [ ] **LG-07** `[A]` Legend panel, always reachable, with each move's definition from the genre file
  - partial (R165/A1, PR #416, merge 8c7b653): `editor/src/legend.js` renderLegendPanel(genre, { document }) builds an `<aside aria-label="Legend">` with one entry per move in genre.moves order (stored-colour swatch, name, definition via textContent) then `other`; validation shared with legendCss. seen: editor/test/legend-panel.test.js 6 tests (jsdom, LLM-built synthetic fixture), npm test 235/235 and gate 1594 OK at head dbbc53f (rerun by planner); combined main 8c7b653 same. Stays partial: unwired until AP-01/AP-03 load the genre file and RE-10 mounts it (always-reachable placement); no panel CSS (LG-05); colours placeholder (LG-01 [H]).
  - seen in demo (R173/A1, DE-06): editor/demo/app.js mounts renderLegendPanel(examples/demo/genre.json). seen: editor/test/demo-overlay.test.js (jsdom). No browser run.

---

## Rendering

- [ ] **RE-01** `[A]` Decorations built from signals through ProseMirror `DecorationSet`
  - partial (R120/A1, PR #308, merge 18d24d6): editor library half: `editor/src/decorations.js` signalDecorations(doc, signals) -> DecorationSet (one Decoration.node per signal whose node_id matches a block `id`; data-signal-kind/layer/confidence attrs and class "signal signal-<layer>", no colours (I3); unknown node_id skipped; bad layer or confidence outside finite [0,1] throws; one pass over doc into a Map) and signalDecorationsPlugin(getSignals). seen: editor/test/decorations.test.js 5 tests, npm test 43/43 and gate 1430 OK at head d15ca7e7d338f3fce6451d6a482e868c2750ea75 (rerun by planner, node_modules linked). Stays partial: unwired by design until the overlay selector (RE-10) / app shell installs the plugin with real signals.
- [ ] **RE-02** `[A]` Viewport-scoped decoration: visible nodes plus a margin — check: build time under 16 ms for a viewport
- [ ] **RE-03** `[A]` Section level: margin ribbon showing the move sequence, with markers for missing, misplaced and foreign moves
- [ ] **RE-04** `[A]` Paragraph and sentence level: tint by move
  - partial (R163/A2, PR #412, merge ff3a0dd): `editor/src/signals.css` tints paragraph/sentence signals with color-mix(var(--signal-color, transparent) 18%) (18% provisional under G-09; no section tint; no literal colour, I3); RE-08 colour ban narrowed to the strength rules. seen: editor/test/signals-css.test.js 6 tests, npm test 215/215 and gate 1594 OK at head 17e9a62 (rerun by planner); combined main ff3a0dd npm 225/225, gate OK. Stays partial: unwired until RE-10/app shell links signals.css with LG-02's legend.
- [ ] **RE-05** `[A]` Second channel for fit: underline or saturation for off-register, unsupported and out-of-place passages. Shape and colour both carry it, never colour alone
- [ ] **RE-06** `[A]` Provisional vs confirmed: fast-layer results lighter or outlined, confirmed results solid — check: visual regression test for both states
- [ ] **RE-07** `[A]` Transition from provisional to confirmed without layout shift or flicker — check: no reflow on state change
- [ ] **RE-08** `[A]` Low-confidence signals rendered weaker than high-confidence ones
  - partial (R121/A1, PR #310, merge 850c532): editor library half: signalDecorations(doc, signals, {weakBelow}) adds data-signal-strength weak|strong and class signal-weak|signal-strong (DEFAULT_WEAK_BELOW 0.5; bad weakBelow throws); plugin passes opts; `editor/src/signals.css` opacity-only (weak 0.55 < strong 1, no colour, I3). seen: editor/test/decorations.test.js, npm test 47/47 and gate 1430 OK at head 0a9c34176c366a978574e5da8630b6b6bf4be37e (rerun by planner, node_modules linked). Stays partial: unwired by design until RE-10 / app shell installs the plugin and links signals.css.
- [ ] **RE-09** `[A]` Granularity toggle: section, paragraph, sentence
  - partial (R124/A1, PR #316, merge 64d7592): editor library half: GRANULARITIES (frozen section/paragraph/sentence), DEFAULT_GRANULARITY 'paragraph'; signal field level (default paragraph, unknown throws); plugin state {on, overlay, granularity} from opts.initialGranularity; only the selected level's signals decorate (data-signal-level attr); setSignalGranularity(name), selectedSignalGranularity(state); toggle/setSignalOverlay preserve granularity. seen: editor/test/decorations.test.js, npm test 59/59 at head d38bcdacc3016e458fc5fa9d114005f87f5c94fd (rerun by planner, node_modules linked). Stays partial: unwired by design until the app shell installs the plugin with real signals.
  - seen in demo (R176/A1, PR #442, merge bb8efab, reviewed head 6448975; Claude lane, Codex usage-limited): editor/demo/overlay.js sidecar entries take optional `level` (section/paragraph/sentence, default paragraph; unknown throws) and `sentence` (0-based, splitSentences: ends at . ! ? before whitespace/end); section entries must name a heading and cover it up to the next same-or-higher heading; plugin state {on, granularity}, setMoveGranularity (meta-only) and selectedMoveGranularity; editor/demo/app.js labelled granularity select, status names the level, survives sample switch and toggle; synthetic-sample-3 sidecar has level-tagged entries (LLM-built). seen: editor/test/demo-granularity.test.js (jsdom, synthetic), planner rerun npm test 265/265 and gate 1618 OK at head. No browser run (no headless browser on host). Residuals: abbreviations split sentences.
- [ ] **RE-10** `[A]` Overlay selector: moves (default), register, support, redundancy, topic (optional). One at a time
  - partial (R123/A1, PR #314, merge 3effc67): editor library half: OVERLAYS (frozen moves/register/support/redundancy/topic), DEFAULT_OVERLAY 'moves'; signal field overlay (default moves, unknown throws); plugin state {on, overlay} from opts.initialOverlay; only the selected overlay's signals decorate (data-signal-overlay attr); setSignalOverlay(name) command, selectedSignalOverlay(state); toggle preserves overlay. seen: editor/test/decorations.test.js, npm test 55/55 and gate 1430 OK at head 8e02099b1f0473f0e81e4ddb8bf1cf4ff48018bd (rerun by planner, node_modules linked). Stays partial: unwired by design until the app shell installs the plugin with real signals.
  - seen in demo (R177/A1, PR #446, merge 0ddb818, reviewed head 12dba84; Claude subagent lane, Codex usage-limited): editor/demo/overlay.js sidecar entries take optional `overlay` (OVERLAYS, default moves; unknown throws); moves entries keep genre-checked `move`, others carry a slug `kind` with data-signal-overlay/kind and no move class (neutral, no colour, I3); plugin state {on, granularity, overlay}, setMoveOverlaySelection (meta-only), selectedMoveOverlaySelection; editor/demo/app.js labelled Overlay select, status names overlay and level and says when a sample has no entries for it; survives sample switch, off/on and granularity; synthetic-sample-3 sidecar gains 4 LLM-built non-moves entries (topic empty on purpose). seen: editor/test/demo-overlay-select.test.js 6 tests (jsdom, synthetic), planner rerun npm test 271/271 and gate 1623 OK at head and on main. No browser run. Residual: non-moves kinds share data-signal-kind with move ids in legend CSS (a kind named like a move would take its colour). Library plugin still unwired until AP-01.
- [ ] **RE-11** `[A]` Off as a first-class state with a single shortcut
  - partial (R122/A1, PR #312, merge 1917f2f): editor library half: signalDecorationsPlugin keyed by exported signalOverlayKey with state {on} from opts.initiallyOn (default true, non-boolean throws); off returns DecorationSet.empty; toggleSignalOverlay command, isSignalOverlayOn; one shortcut opts.offShortcut (DEFAULT_OFF_SHORTCUT Mod-Shift-o; Mod-Shift-p refused). seen: editor/test/decorations.test.js, npm test 51/51 and gate 1430 OK at head ade0740e55e048493f23e490b2b42fc728e80e1b (rerun by planner, node_modules linked). Stays partial: unwired by design until RE-10 / app shell installs the plugin.
  - seen in demo (R174/A1, PR #438, merge 590a0b9, reviewed head b916013; Claude lane, Codex usage-limited): editor/demo/overlay.js moveOverlayPlugin state {on} with toggleMoveOverlay (meta-only, no doc steps) bound to DEFAULT_OFF_SHORTCUT Mod-Shift-o; editor/demo/app.js "Overlay off/on" button with aria-pressed; on/off survives switching samples. seen: editor/test/demo-overlay-off.test.js (jsdom, synthetic samples), planner rerun npm test 258/258 and gate 1617 OK at head and on main. No browser run. Library plugin still unwired until RE-10/app shell.
- [ ] **RE-12** `[A]` Provenance marks: machine-written and machine-edited text distinguishable on demand

---

## Inspector

- [ ] **IN-01** `[A]` Hover or focus on a mark shows: the signal, its value, confidence, layer, and a link to its method text
- [ ] **IN-02** `[A]` For sequence flags: the corpus evidence ("this move follows that one in 18 of 20 reports")
- [ ] **IN-03** `[A]` For support flags: the candidate evidence found, or the statement that none was found
- [ ] **IN-04** `[A]` For register flags: the feature the slow layer named
- [ ] **IN-05** `[A]` Correction from the inspector: the expert can overrule a label; the correction is stored and outranks both layers (feeds distillation)

---

## Overview

- [ ] **OV-01** `[A]` Document minimap: the move sequence of the whole report as a strip
  - partial (R179/A1, PR #450, merge 0c3148b): `editor/src/minimap.js` minimapSegments/renderMinimap/mountMinimap; one segment per run of same-move blocks, unlabeled gaps uncoloured, unknown ids -> other, colour only via legendCss data-signal-kind (I3); mounted above the editor in `npm run demo`. seen: editor/test/minimap.test.js (jsdom, LLM-built synthetic fixtures + examples/demo samples), npm test 276/276 and gate 1630 OK at head 7ddabbf (rerun by planner). Stays partial: no browser run; app wiring owed to AP-01. Residuals: first label per block wins; demo test mirrors app wiring.
- [ ] **OV-02** `[A]` Comparison strip: the typical sequence for this section type from the corpus, beside the draft's
- [ ] **OV-03** `[A]` Open-issues list: missing moves, unsupported claims, off-register passages; click to navigate
  - partial (R181/A1, PR #454, merge ca07c3b): `editor/src/issues.js` openIssues/renderIssues; missing genre moves (genre order) and unlabeled-block runs (click selects and scrolls to the block) listed under the minimap in `npm run demo`. seen: editor/test/issues.test.js (jsdom, LLM-built synthetic fixtures + examples/demo), npm test 282/282 and gate 1630 OK at head f51fc59 (rerun by planner). Stays partial: unsupported claims and off-register entries need SU/RG signal sources; no browser run; app wiring owed to AP-01. Residual: list not refreshed when labels change.
- [ ] **OV-04** `[A]` Collapsible; the prose keeps the space by default
  - partial (R180/A1, PR #452, merge 21bd94e): `editor/src/minimap.js` mountCollapsibleMinimap; the OV-01 strip sits behind an aria-expanded toggle, collapsed by default, state kept on re-mount. seen: editor/test/minimap.test.js (jsdom), npm test 277/277 and gate 1630 OK at head d0be7d1 (rerun by planner). Stays partial: no browser run; app wiring owed to AP-01. Residual: state not persisted across reloads.

---

## Performance

- [ ] **FP-01** `[A]` Decoration updates batched into single view transactions
- [ ] **FP-02** `[A]` No framework re-render fighting ProseMirror's DOM management — check: profiling shows no full re-render on keystroke
- [ ] **FP-03** `[A]` Profile on a 100 000-word document with overlays on

---

## Human checks *(G-09)*

- [ ] **HC-01** `[H]` Legend recall after one session
- [ ] **HC-02** `[H]` Reading comparison: tint vs plain vs margin-only
- [ ] **HC-03** `[H]` Provisional vs confirmed understood without explanation
- [ ] **HC-04** `[H]` Can the expert find a deliberately misplaced move in a test report faster with the overlay than without?

---

## Acceptance criteria

- A move has the same colour in every document of the genre
- Every palette passes the automated colour-difference and contrast tests
- Provisional and confirmed results are distinguishable at a glance
- Every mark explains itself through the inspector
- The editor is fully usable with overlays off
