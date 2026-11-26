// @ts-check
// DE-02: provisional move overlay for the thin demo.
// A sidecar lists [{ block, move }] with a 0-based top-level block index. Moves must be in the
// genre file (examples/demo/genre.json, synthetic placeholders, not the expert's inventory);
// DE-06: colours come from the genre file's stored legend via legendCss, not from here.
import { Decoration, DecorationSet } from '@milkdown/prose/view';
import { Plugin, PluginKey } from '@milkdown/prose/state';
import { keydownHandler } from '@milkdown/prose/keymap';
import { DEFAULT_GRANULARITY, DEFAULT_OFF_SHORTCUT, DEFAULT_OVERLAY, DEFAULT_WEAK_BELOW, GRANULARITIES,
  OVERLAYS } from '../src/decorations.js';

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

/** @param {unknown} level @returns {string} */
function checkLevel(level) {
  const name = level === undefined ? DEFAULT_GRANULARITY : level;
  if (typeof name !== 'string' || !GRANULARITIES.includes(name)) {
    throw new Error(`sidecar level must be one of ${GRANULARITIES.join(', ')}: ${level}`);
  }
  return name;
}

/** RE-10: an overlay name from OVERLAYS; undefined means DEFAULT_OVERLAY. @param {unknown} overlay @returns {string} */
function checkOverlay(overlay) {
  const name = overlay === undefined ? DEFAULT_OVERLAY : overlay;
  if (typeof name !== 'string' || !OVERLAYS.includes(name)) {
    throw new Error(`sidecar overlay must be one of ${OVERLAYS.join(', ')}: ${overlay}`);
  }
  return name;
}

/** RE-10: a non-moves entry's kind; a lower-case slug, not checked against the genre file. @param {unknown} kind */
function checkKind(kind) {
  if (typeof kind !== 'string' || !/^[a-z][a-z0-9-]*$/.test(kind)) {
    throw new Error(`sidecar kind must be a lower-case slug: ${kind}`);
  }
  return kind;
}

/**
 * RE-09: the sentences of a block's text as [start, end) character ranges. Simple documented rule:
 * a sentence ends after `.`, `!` or `?` followed by whitespace or the end of the text; leading
 * whitespace is not part of a sentence. Abbreviations ("e.g. x") split too (known residual).
 * @param {string} text
 * @returns {Array<[number, number]>}
 */
export function splitSentences(text) {
  /** @type {Array<[number, number]>} */
  const out = [];
  let start = 0;
  const push = (from, to) => {
    while (from < to && /\s/.test(text[from])) from++;
    while (to > from && /\s/.test(text[to - 1])) to--;
    if (to > from) out.push([from, to]);
  };
  for (let i = 0; i < text.length; i++) {
    if ('.!?'.includes(text[i]) && (i + 1 === text.length || /\s/.test(text[i + 1]))) {
      push(start, i + 1);
      start = i + 1;
    }
  }
  push(start, text.length);
  return out;
}

/**
 * The block's text with a doc position for every character (text nodes only, in order).
 * @param {import('prosemirror-model').Node} node
 * @param {number} offset
 */
function blockText(node, offset) {
  let text = '';
  /** @type {number[]} */
  const pos = [];
  node.descendants((child, p) => {
    if (child.isText && child.text) {
      for (let k = 0; k < child.text.length; k++) pos.push(offset + 1 + p + k);
      text += child.text;
    }
    return true;
  });
  return { text, pos };
}

/**
 * Decorations for the selected granularity (RE-09). Every entry is validated; only entries whose
 * `level` (default 'paragraph') equals `granularity` are decorated:
 * - paragraph: one node decoration on the block;
 * - section: `block` must be a heading; one node decoration on it and on each following top-level
 *   block up to (not including) the next heading of the same or higher rank;
 * - sentence: one inline decoration over sentence `sentence` (0-based, splitSentences) of the block.
 * A block without an id yet (idPlugin assigns ids on the first transaction) is skipped; the plugin
 * recomputes decorations after that transaction.
 * RE-10: an entry's `overlay` (default 'moves') must be in OVERLAYS; only entries of `overlay`
 * decorate. 'moves' entries carry a genre `move`; other entries carry a slug `kind` and get no
 * legend colour (neutral; I3).
 * @param {import('prosemirror-model').Node} doc
 * @param {{ block: number, move?: string, kind?: string, overlay?: string, level?: string, sentence?: number }[]} moves
 * @param {Parameters<typeof genreMoveIds>[0]} genre
 * @param {string} [granularity]
 * @param {string} [overlay]
 * @returns {DecorationSet}
 */
export function moveDecorations(doc, moves, genre, granularity = DEFAULT_GRANULARITY, overlay = DEFAULT_OVERLAY) {
  if (!Array.isArray(moves)) throw new Error('sidecar moves must be an array');
  const selected = checkLevel(granularity);
  const selectedOverlay = checkOverlay(overlay);
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
    const entryOverlay = checkOverlay(entry.overlay);
    const isMove = entryOverlay === 'moves';
    const kind = isMove ? checkMove(entry.move) : checkKind(entry.kind);
    if (isMove && !known.has(kind)) throw new Error(`sidecar move has no genre entry: ${kind}`);
    const level = checkLevel(entry.level);
    const { node, offset } = top[index];
    /** @type {number[]} */
    let blocks = [index];
    /** @type {[number, number] | null} */
    let range = null;
    if (level === 'section') {
      if (node.type.name !== 'heading') throw new Error(`sidecar section entry must name a heading block: ${index}`);
      const rank = node.attrs.level;
      blocks = [];
      for (let i = index; i < top.length; i++) {
        const n = top[i].node;
        if (i > index && n.type.name === 'heading' && n.attrs.level <= rank) break;
        blocks.push(i);
      }
    } else if (level === 'sentence') {
      const n = entry.sentence;
      if (!Number.isInteger(n) || n < 0) throw new Error(`sidecar sentence entry needs a 0-based integer sentence: ${n}`);
      const { text, pos } = blockText(node, offset);
      const sentences = splitSentences(text);
      if (n >= sentences.length) {
        throw new Error(`sidecar sentence out of range: ${n} (block ${index} has ${sentences.length})`);
      }
      const [from, to] = sentences[n];
      range = [pos[from], pos[to - 1] + 1];
    }
    if (level !== selected || entryOverlay !== selectedOverlay) continue;
    // Reuse the decorations module's rendering contract: provisional layer, default overlay and
    // its weak/strong threshold. The colour comes from legendCss's
    // `.signal[data-signal-kind="<move>"] { --signal-color }` rule, never from this decoration.
    const confidence = 1;
    const strength = confidence < DEFAULT_WEAK_BELOW ? 'weak' : 'strong';
    /** @type {Record<string, string>} */
    const attrs = {
      class: `signal signal-provisional signal-${strength}${isMove ? ` move move-${kind}` : ''}`,
      'data-signal-kind': kind,
      // IN-05: an expert correction (applyCorrections) carries its own layer; styling is unchanged (I3).
      'data-signal-layer': entry.layer === 'expert correction' ? entry.layer : 'provisional',
      'data-signal-confidence': String(confidence),
      'data-signal-strength': strength,
      'data-signal-overlay': entryOverlay,
      'data-signal-level': level,
    };
    if (isMove) attrs['data-move'] = kind;
    if (isMove && entry.layer === 'expert correction' && typeof entry.previous === 'string') {
      attrs['data-signal-previous'] = entry.previous;
    }
    if (range) {
      const id = node.attrs.id;
      if (typeof id !== 'string' || !id) continue;
      decos.push(Decoration.inline(range[0], range[1], attrs));
      continue;
    }
    for (const i of blocks) {
      const b = top[i];
      const id = b.node.attrs.id;
      if (typeof id !== 'string' || !id) continue;
      decos.push(Decoration.node(b.offset, b.offset + b.node.nodeSize, attrs));
    }
  }
  return DecorationSet.create(doc, decos);
}

/**
 * RE-11: whether the demo overlay is on. False when the plugin is absent.
 * @param {import('prosemirror-state').EditorState} state
 */
export function isMoveOverlayOn(state) {
  return moveOverlayKey.getState(state)?.on === true;
}

/**
 * RE-11 command: flip the overlay on/off. A meta-only transaction: no doc steps.
 * Production callers: the demo's overlay button and its keymap (editor/demo/app.js, below).
 * @param {import('prosemirror-state').EditorState} state
 * @param {(tr: import('prosemirror-state').Transaction) => void} [dispatch]
 */
export function toggleMoveOverlay(state, dispatch) {
  const s = moveOverlayKey.getState(state);
  if (!s) return false;
  if (dispatch) dispatch(state.tr.setMeta(moveOverlayKey, { ...s, on: !s.on }));
  return true;
}

/**
 * RE-09: the overlay's selected granularity; DEFAULT_GRANULARITY when the plugin is absent.
 * Production caller: editor/demo/app.js (status line, sample switching).
 * @param {import('prosemirror-state').EditorState} state
 * @returns {string}
 */
export function selectedMoveGranularity(state) {
  return moveOverlayKey.getState(state)?.granularity ?? DEFAULT_GRANULARITY;
}

/**
 * RE-09 command factory: select which level's labels are decorated. Meta-only: no doc steps.
 * Unknown names throw. Production caller: the demo's granularity select (editor/demo/app.js).
 * @param {string} name
 */
export function setMoveGranularity(name) {
  const granularity = checkLevel(name);
  /**
   * @param {import('prosemirror-state').EditorState} state
   * @param {(tr: import('prosemirror-state').Transaction) => void} [dispatch]
   */
  return (state, dispatch) => {
    const s = moveOverlayKey.getState(state);
    if (!s) return false;
    if (dispatch) dispatch(state.tr.setMeta(moveOverlayKey, { ...s, granularity }));
    return true;
  };
}

/**
 * RE-10: the overlay's selected overlay name; DEFAULT_OVERLAY when the plugin is absent.
 * Production caller: editor/demo/app.js (status line, sample switching).
 * @param {import('prosemirror-state').EditorState} state
 * @returns {string}
 */
export function selectedMoveOverlaySelection(state) {
  return moveOverlayKey.getState(state)?.overlay ?? DEFAULT_OVERLAY;
}

/**
 * RE-10 command factory: select which overlay's entries are decorated (one at a time). Meta-only:
 * no doc steps. Unknown names throw. Production caller: the demo's overlay select (editor/demo/app.js).
 * @param {string} name
 */
export function setMoveOverlaySelection(name) {
  const overlay = checkOverlay(name);
  /**
   * @param {import('prosemirror-state').EditorState} state
   * @param {(tr: import('prosemirror-state').Transaction) => void} [dispatch]
   */
  return (state, dispatch) => {
    const s = moveOverlayKey.getState(state);
    if (!s) return false;
    if (dispatch) dispatch(state.tr.setMeta(moveOverlayKey, { ...s, overlay }));
    return true;
  };
}

/** RE-11: the single off/on shortcut, shared with the library overlay (DEFAULT_OFF_SHORTCUT). */
export const moveOverlayBindings = Object.freeze({ [DEFAULT_OFF_SHORTCUT]: toggleMoveOverlay });

/**
 * Plugin wrapper: reads the sidecar and genre file through the getters so a loaded document's
 * decorations follow its current block ids. State is { on, granularity, overlay }; off renders no
 * decorations; on renders only the selected overlay's (RE-10) entries at the selected granularity (RE-09).
 * @param {() => Parameters<typeof moveDecorations>[1]} getMoves
 * @param {() => Parameters<typeof genreMoveIds>[0]} getGenre
 * @param {{ initiallyOn?: boolean, initialGranularity?: string, initialOverlay?: string,
 *   onToggle?: (on: boolean) => void, onGranularity?: (name: string) => void, onOverlay?: (name: string) => void }} [opts]
 * @returns {Plugin}
 */
export function moveOverlayPlugin(getMoves, getGenre, opts = {}) {
  const initiallyOn = opts.initiallyOn === undefined ? true : opts.initiallyOn;
  if (typeof initiallyOn !== 'boolean') throw new Error(`initiallyOn must be a boolean: ${initiallyOn}`);
  const initialGranularity = checkLevel(opts.initialGranularity);
  const initialOverlay = checkOverlay(opts.initialOverlay);
  const { onToggle, onGranularity, onOverlay } = opts;
  return new Plugin({
    key: moveOverlayKey,
    state: {
      init: () => ({ on: initiallyOn, granularity: initialGranularity, overlay: initialOverlay }),
      apply: (tr, prev) => tr.getMeta(moveOverlayKey) || prev,
    },
    view: () => ({
      update: (view, prevState) => {
        const on = isMoveOverlayOn(view.state);
        if (onToggle && on !== isMoveOverlayOn(prevState)) onToggle(on);
        const g = selectedMoveGranularity(view.state);
        if (onGranularity && g !== selectedMoveGranularity(prevState)) onGranularity(g);
        const o = selectedMoveOverlaySelection(view.state);
        if (onOverlay && o !== selectedMoveOverlaySelection(prevState)) onOverlay(o);
      },
    }),
    props: {
      decorations: (state) => (isMoveOverlayOn(state)
        ? moveDecorations(state.doc, getMoves(), getGenre(), selectedMoveGranularity(state),
          selectedMoveOverlaySelection(state))
        : DecorationSet.empty),
      handleKeyDown: keydownHandler(moveOverlayBindings),
    },
  });
}

/**
 * RE-11: the demo button's label and aria-pressed follow the overlay state (pressed = off).
 * Production caller: editor/demo/app.js.
 * @param {HTMLButtonElement} button
 * @param {boolean} on
 */
export function updateOverlayButton(button, on) {
  button.textContent = on ? 'Overlay off' : 'Overlay on';
  button.setAttribute('aria-pressed', on ? 'false' : 'true');
  button.title = `${on ? 'Hide' : 'Show'} the provisional overlay (${DEFAULT_OFF_SHORTCUT})`;
}
