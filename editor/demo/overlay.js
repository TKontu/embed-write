// @ts-check
// DE-02: provisional move overlay for the thin demo.
// A sidecar lists [{ block, move }] with a 0-based top-level block index. Moves must be in the
// genre file (examples/demo/genre.json, synthetic placeholders, not the expert's inventory);
// DE-06: colours come from the genre file's stored legend via legendCss, not from here.
import { Decoration, DecorationSet } from '@milkdown/prose/view';
import { Plugin, PluginKey } from '@milkdown/prose/state';
import { DEFAULT_OVERLAY, DEFAULT_WEAK_BELOW } from '../src/decorations.js';

export const moveOverlayKey = new PluginKey('demoMoveOverlay');

/** @param {unknown} move @returns {string} */
function checkMove(move) {
  if (typeof move !== 'string' || !/^[a-z][a-z0-9-]*$/.test(move)) {
    throw new Error(`move id must be a lower-case slug: ${move}`);
  }
  return move;
}

/**
 * The genre file's move ids in file order (DE-06). Colours are not read here: the overlay only
 * tags each block with `data-signal-kind`, and LG-02 legendCss's stylesheet colours it (I3).
 * @param {{ moves?: Array<{ id?: unknown }> }} genre
 * @returns {string[]}
 */
export function genreMoveIds(genre) {
  if (!genre || typeof genre !== 'object' || !Array.isArray(genre.moves)) {
    throw new Error('genre must be an object with a moves list');
  }
  return genre.moves.map((m) => checkMove(m && m.id));
}

/**
 * One node decoration per labelled block. A block without an id yet (idPlugin assigns ids on the
 * first transaction) is skipped; the plugin recomputes decorations after that transaction.
 * @param {import('prosemirror-model').Node} doc
 * @param {{ block: number, move: string }[]} moves
 * @param {Parameters<typeof genreMoveIds>[0]} genre
 * @returns {DecorationSet}
 */
export function moveDecorations(doc, moves, genre) {
  if (!Array.isArray(moves)) throw new Error('sidecar moves must be an array');
  const known = new Set(genreMoveIds(genre));
  /** @type {{ node: import('prosemirror-model').Node, offset: number }[]} */
  const top = [];
  doc.forEach((node, offset) => top.push({ node, offset }));
  const decos = [];
  for (const entry of moves) {
    const index = entry && entry.block;
    if (!Number.isInteger(index) || index < 0 || index >= top.length) {
      throw new Error(`sidecar block index out of range: ${index} (doc has ${top.length} top-level blocks)`);
    }
    const move = checkMove(entry.move);
    if (!known.has(move)) throw new Error(`sidecar move has no genre entry: ${move}`);
    const { node, offset } = top[index];
    const id = node.attrs.id;
    if (typeof id !== 'string' || !id) continue;
    // Reuse the decorations module's rendering contract: provisional layer, default overlay and
    // its weak/strong threshold. The colour comes from legendCss's
    // `.signal[data-signal-kind="<move>"] { --signal-color }` rule, never from this decoration.
    const confidence = 1;
    const strength = confidence < DEFAULT_WEAK_BELOW ? 'weak' : 'strong';
    decos.push(Decoration.node(offset, offset + node.nodeSize, {
      class: `signal signal-provisional signal-${strength} move move-${move}`,
      'data-move': move,
      'data-signal-kind': move,
      'data-signal-layer': 'provisional',
      'data-signal-confidence': String(confidence),
      'data-signal-strength': strength,
      'data-signal-overlay': DEFAULT_OVERLAY,
      'data-signal-level': 'paragraph',
    }));
  }
  return DecorationSet.create(doc, decos);
}

/**
 * Plugin wrapper: reads the sidecar and genre file through the getters so a loaded document's
 * decorations follow its current block ids.
 * @param {() => { block: number, move: string }[]} getMoves
 * @param {() => Parameters<typeof genreMoveIds>[0]} getGenre
 * @returns {Plugin}
 */
export function moveOverlayPlugin(getMoves, getGenre) {
  return new Plugin({
    key: moveOverlayKey,
    props: { decorations: (state) => moveDecorations(state.doc, getMoves(), getGenre()) },
  });
}
