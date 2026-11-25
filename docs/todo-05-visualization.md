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
- [ ] **LG-03** `[A]` Palette validation: minimum pairwise colour difference, in normal vision and three colour-blind simulations — check: automated, fails the build below threshold
  - partial (R32/A1, PR #84): validator `service/palette.py` (CIEDE2000, Machado CVD sims, CLI exits 1 below threshold) merged; MIN_DELTA_E=20 provisional for the expert under G-09; unwired until LG-02/LG-05; no palette until LG-01 [H], no CI wiring
- [ ] **LG-04** `[A]` Contrast floor: tinted text stays above a set contrast ratio in light and dark themes — check: automated contrast test
  - partial (R33/A1, PR #86): check `service/contrast.py` (WCAG luminance/contrast, tint blended over theme background, CLI exits 1 on shortfall) merged; MIN_CONTRAST=4.5 and alpha provisional for the expert under G-09; unwired until RE-04/LG-05; no theme colours until LG-01 [H]/LG-05, no CI wiring
- [ ] **LG-05** `[A]` Separate dark-theme palette, validated the same way
- [ ] **LG-06** `[A]` Neutral rendering for `other` and for unlabeled text
- [ ] **LG-07** `[A]` Legend panel, always reachable, with each move's definition from the genre file

---

## Rendering

- [ ] **RE-01** `[A]` Decorations built from signals through ProseMirror `DecorationSet`
  - partial (R120/A1, PR #308, merge 18d24d6): editor library half: `editor/src/decorations.js` signalDecorations(doc, signals) -> DecorationSet (one Decoration.node per signal whose node_id matches a block `id`; data-signal-kind/layer/confidence attrs and class "signal signal-<layer>", no colours (I3); unknown node_id skipped; bad layer or confidence outside finite [0,1] throws; one pass over doc into a Map) and signalDecorationsPlugin(getSignals). seen: editor/test/decorations.test.js 5 tests, npm test 43/43 and gate 1430 OK at head d15ca7e7d338f3fce6451d6a482e868c2750ea75 (rerun by planner, node_modules linked). Stays partial: unwired by design until the overlay selector (RE-10) / app shell installs the plugin with real signals.
- [ ] **RE-02** `[A]` Viewport-scoped decoration: visible nodes plus a margin — check: build time under 16 ms for a viewport
- [ ] **RE-03** `[A]` Section level: margin ribbon showing the move sequence, with markers for missing, misplaced and foreign moves
- [ ] **RE-04** `[A]` Paragraph and sentence level: tint by move
- [ ] **RE-05** `[A]` Second channel for fit: underline or saturation for off-register, unsupported and out-of-place passages. Shape and colour both carry it, never colour alone
- [ ] **RE-06** `[A]` Provisional vs confirmed: fast-layer results lighter or outlined, confirmed results solid — check: visual regression test for both states
- [ ] **RE-07** `[A]` Transition from provisional to confirmed without layout shift or flicker — check: no reflow on state change
- [ ] **RE-08** `[A]` Low-confidence signals rendered weaker than high-confidence ones
  - partial (R121/A1, PR #310, merge 850c532): editor library half: signalDecorations(doc, signals, {weakBelow}) adds data-signal-strength weak|strong and class signal-weak|signal-strong (DEFAULT_WEAK_BELOW 0.5; bad weakBelow throws); plugin passes opts; `editor/src/signals.css` opacity-only (weak 0.55 < strong 1, no colour, I3). seen: editor/test/decorations.test.js, npm test 47/47 and gate 1430 OK at head 0a9c34176c366a978574e5da8630b6b6bf4be37e (rerun by planner, node_modules linked). Stays partial: unwired by design until RE-10 / app shell installs the plugin and links signals.css.
- [ ] **RE-09** `[A]` Granularity toggle: section, paragraph, sentence
- [ ] **RE-10** `[A]` Overlay selector: moves (default), register, support, redundancy, topic (optional). One at a time
  - partial (R123/A1, PR #314, merge 3effc67): editor library half: OVERLAYS (frozen moves/register/support/redundancy/topic), DEFAULT_OVERLAY 'moves'; signal field overlay (default moves, unknown throws); plugin state {on, overlay} from opts.initialOverlay; only the selected overlay's signals decorate (data-signal-overlay attr); setSignalOverlay(name) command, selectedSignalOverlay(state); toggle preserves overlay. seen: editor/test/decorations.test.js, npm test 55/55 and gate 1430 OK at head 8e02099b1f0473f0e81e4ddb8bf1cf4ff48018bd (rerun by planner, node_modules linked). Stays partial: unwired by design until the app shell installs the plugin with real signals.
- [ ] **RE-11** `[A]` Off as a first-class state with a single shortcut
  - partial (R122/A1, PR #312, merge 1917f2f): editor library half: signalDecorationsPlugin keyed by exported signalOverlayKey with state {on} from opts.initiallyOn (default true, non-boolean throws); off returns DecorationSet.empty; toggleSignalOverlay command, isSignalOverlayOn; one shortcut opts.offShortcut (DEFAULT_OFF_SHORTCUT Mod-Shift-o; Mod-Shift-p refused). seen: editor/test/decorations.test.js, npm test 51/51 and gate 1430 OK at head ade0740e55e048493f23e490b2b42fc728e80e1b (rerun by planner, node_modules linked). Stays partial: unwired by design until RE-10 / app shell installs the plugin.
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
- [ ] **OV-02** `[A]` Comparison strip: the typical sequence for this section type from the corpus, beside the draft's
- [ ] **OV-03** `[A]` Open-issues list: missing moves, unsupported claims, off-register passages; click to navigate
- [ ] **OV-04** `[A]` Collapsible; the prose keeps the space by default

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
