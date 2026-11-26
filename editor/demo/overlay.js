// @ts-check
// DE-02: provisional move overlay for the thin demo.
// A sidecar lists [{ block, move }] with a 0-based top-level block index. The legend maps each
// move to a label and colour. Labels and colours are placeholders ("provisional": true), not the
// expert's inventory (LG-01 owns the real legend).
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
 * The legend's moves as a stable list; the panel and the decorations share this one reading.
 * @param {{ provisional?: boolean, moves?: Record<string, { label?: unknown, colour?: unknown }> }} legend
 * @returns {{ move: string, label: string, colour: string }[]}
 */
export function legendItems(legend) {
  if (!legend || typeof legend !== 'object' || !legend.moves || typeof legend.moves !== 'object') {
    throw new Error('legend must be an object with a moves map');
  }
  return Object.entries(legend.moves).map(([move, value]) => {
    checkMove(move);
    const label = value && typeof value.label === 'string' ? value.label : null;
    const colour = value && typeof value.colour === 'string' ? value.colour : null;
    if (!label || !colour) throw new Error(`legend move ${move} needs label and colour`);
    return { move, label, colour };
  });
}

/**
 * One node decoration per labelled block. A block without an id yet (idPlugin assigns ids on the
 * first transaction) is skipped; the plugin recomputes decorations after that transaction.
 * @param {import('prosemirror-model').Node} doc
 * @param {{ block: number, move: string }[]} moves
 * @param {Parameters<typeof legendItems>[0]} legend
 * @returns {DecorationSet}
 */
export function moveDecorations(doc, moves, legend) {
  if (!Array.isArray(moves)) throw new Error('sidecar moves must be an array');
  const styles = new Map(legendItems(legend).map((item) => [item.move, item]));
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
    const style = styles.get(move);
    if (!style) throw new Error(`sidecar move has no legend entry: ${move}`);
    const { node, offset } = top[index];
    const id = node.attrs.id;
    if (typeof id !== 'string' || !id) continue;
    // Reuse the decorations module's rendering contract: provisional layer, default overlay and
    // its weak/strong threshold. The move class and legend colour are the demo's addition.
    const confidence = 1;
    const strength = confidence < DEFAULT_WEAK_BELOW ? 'weak' : 'strong';
    decos.push(Decoration.node(offset, offset + node.nodeSize, {
      class: `signal signal-provisional signal-${strength} move move-${move}`,
      'data-move': move,
      'data-move-label': style.label,
      'data-move-colour': style.colour,
      'data-signal-kind': move,
      'data-signal-layer': 'provisional',
      'data-signal-confidence': String(confidence),
      'data-signal-strength': strength,
      'data-signal-overlay': DEFAULT_OVERLAY,
      'data-signal-level': 'paragraph',
      style: `--move-colour: ${style.colour}`,
    }));
  }
  return DecorationSet.create(doc, decos);
}

/**
 * Plugin wrapper: reads the sidecar and legend through the getters so a loaded document's
 * decorations follow its current block ids.
 * @param {() => { block: number, move: string }[]} getMoves
 * @param {() => Parameters<typeof legendItems>[0]} getLegend
 * @returns {Plugin}
 */
export function moveOverlayPlugin(getMoves, getLegend) {
  return new Plugin({
    key: moveOverlayKey,
    props: { decorations: (state) => moveDecorations(state.doc, getMoves(), getLegend()) },
  });
}
