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
- [ ] **LG-04** `[A]` Contrast floor: tinted text stays above a set contrast ratio in light and dark themes — check: automated contrast test
- [ ] **LG-05** `[A]` Separate dark-theme palette, validated the same way
- [ ] **LG-06** `[A]` Neutral rendering for `other` and for unlabeled text
- [ ] **LG-07** `[A]` Legend panel, always reachable, with each move's definition from the genre file

---

## Rendering

- [ ] **RE-01** `[A]` Decorations built from signals through ProseMirror `DecorationSet`
- [ ] **RE-02** `[A]` Viewport-scoped decoration: visible nodes plus a margin — check: build time under 16 ms for a viewport
- [ ] **RE-03** `[A]` Section level: margin ribbon showing the move sequence, with markers for missing, misplaced and foreign moves
- [ ] **RE-04** `[A]` Paragraph and sentence level: tint by move
- [ ] **RE-05** `[A]` Second channel for fit: underline or saturation for off-register, unsupported and out-of-place passages. Shape and colour both carry it, never colour alone
- [ ] **RE-06** `[A]` Provisional vs confirmed: fast-layer results lighter or outlined, confirmed results solid — check: visual regression test for both states
- [ ] **RE-07** `[A]` Transition from provisional to confirmed without layout shift or flicker — check: no reflow on state change
- [ ] **RE-08** `[A]` Low-confidence signals rendered weaker than high-confidence ones
- [ ] **RE-09** `[A]` Granularity toggle: section, paragraph, sentence
- [ ] **RE-10** `[A]` Overlay selector: moves (default), register, support, redundancy, topic (optional). One at a time
- [ ] **RE-11** `[A]` Off as a first-class state with a single shortcut
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
