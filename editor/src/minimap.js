// @ts-check
// OV-01: document minimap — the move sequence of the whole report as one strip. Colours come only
// from LG-02 legendCss rules keyed on data-signal-kind (invariant I3); nothing here sets a colour.
// Production caller: editor/demo/app.js (D-009 thin demo); AP-01 wires it in the app. O(blocks).

/**
 * @typedef {{ move: string, start: number, count: number }} MinimapSegment
 * `move` is a genre move id, `other` for an id the genre does not know, or `unlabeled` for a gap.
 */

/**
 * One segment per run of consecutive top-level blocks with the same move, in document order.
 * The first entry for a block wins; entries outside [0, blockCount) are ignored.
 * @param {Array<{ block: number, move: string }>} moves sidecar entries (examples/demo/*.moves.json)
 * @param {number} blockCount number of top-level blocks in the document
 * @param {Iterable<string>} [knownIds] genre move ids; when given, other ids map to `other`
 * @returns {MinimapSegment[]}
 */
export function minimapSegments(moves, blockCount, knownIds) {
  const known = knownIds ? new Set(knownIds) : null;
  /** @type {(string | undefined)[]} */
  const perBlock = new Array(Math.max(0, blockCount));
  for (const e of moves) {
    if (!Number.isInteger(e.block) || e.block < 0 || e.block >= blockCount) continue;
    if (perBlock[e.block] !== undefined) continue;
    perBlock[e.block] = known && !known.has(e.move) ? 'other' : e.move;
  }
  /** @type {MinimapSegment[]} */
  const out = [];
  for (let i = 0; i < perBlock.length; i += 1) {
    const move = perBlock[i] ?? 'unlabeled';
    const last = out[out.length - 1];
    if (last && last.move === move) last.count += 1;
    else out.push({ move, start: i, count: 1 });
  }
  return out;
}

/**
 * Render segments as a strip. Labelled segments carry `.signal[data-signal-kind]` so the legendCss
 * stylesheet colours them; `unlabeled` gaps carry no kind and get no colour.
 * @param {Document} doc
 * @param {MinimapSegment[]} segments
 * @param {any} genre parsed genre file (labels for titles)
 * @returns {HTMLElement}
 */
export function renderMinimap(doc, segments, genre) {
  /** @type {Map<string, string>} */
  const names = new Map((genre?.moves ?? []).map((/** @type {any} */ m) => [m.id, m.name ?? m.id]));
  const strip = doc.createElement('div');
  strip.className = 'minimap';
  strip.setAttribute('role', 'img');
  strip.setAttribute('aria-label', 'Document minimap: move sequence');
  for (const s of segments) {
    const seg = doc.createElement('span');
    seg.style.flexGrow = String(s.count);
    seg.setAttribute('data-start', String(s.start));
    seg.setAttribute('data-count', String(s.count));
    if (s.move === 'unlabeled') {
      seg.className = 'minimap-segment minimap-unlabeled';
      seg.title = 'Unlabeled';
    } else {
      seg.className = 'minimap-segment signal';
      seg.setAttribute('data-signal-kind', s.move);
      seg.title = s.move === 'other' ? 'Other' : (names.get(s.move) ?? s.move);
    }
    strip.append(seg);
  }
  return strip;
}

/**
 * Demo wiring: build and mount the strip for one loaded document.
 * @param {HTMLElement} mount
 * @param {Array<{ block: number, move: string }>} moves
 * @param {number} blockCount
 * @param {any} genre
 */
export function mountMinimap(mount, moves, blockCount, genre) {
  const ids = (genre?.moves ?? []).map((/** @type {any} */ m) => m.id);
  mount.replaceChildren(renderMinimap(mount.ownerDocument, minimapSegments(moves, blockCount, ids), genre));
}
