// @ts-check
// RE-01: decorations built from analysis signals through a ProseMirror DecorationSet.
// Only data attributes and classes are emitted; no colours or styles (colour comes from the fixed
// genre legend, LG-01/LG-02, never computed here). Unwired by design until the overlay selector
// (RE-10) / app shell provides signals; createEditor does not install the plugin.
import { Decoration, DecorationSet } from '@milkdown/prose/view';
import { Plugin, PluginKey } from '@milkdown/prose/state';
import { keydownHandler } from '@milkdown/prose/keymap';

const LAYERS = new Set(['provisional', 'confirmed']);
// RE-08: confidence below this renders weak (lower opacity via signals.css). Rendering words only (I8).
export const DEFAULT_WEAK_BELOW = 0.5;

/**
 * @typedef {{ node_id: string, kind: string, confidence: number, layer: string }} Signal
 * @param {import('prosemirror-model').Node} doc
 * @param {Signal[]} signals
 * @param {{ weakBelow?: number }} [opts]
 * @returns {DecorationSet}
 */
export function signalDecorations(doc, signals, opts = {}) {
  const weakBelow = opts.weakBelow === undefined ? DEFAULT_WEAK_BELOW : opts.weakBelow;
  if (typeof weakBelow !== 'number' || !Number.isFinite(weakBelow) || weakBelow < 0 || weakBelow > 1) {
    throw new Error(`weakBelow must be a finite number in [0,1]: ${weakBelow}`);
  }
  /** @type {Map<string, { pos: number, size: number }>} */
  const byId = new Map();
  doc.descendants((node, pos) => {
    const id = node.attrs.id;
    if (typeof id === 'string' && !byId.has(id)) byId.set(id, { pos, size: node.nodeSize });
  });
  const decos = [];
  for (const s of signals) {
    if (!LAYERS.has(s.layer)) throw new Error(`signal layer must be provisional or confirmed: ${s.layer}`);
    const c = s.confidence;
    if (typeof c !== 'number' || !Number.isFinite(c) || c < 0 || c > 1) {
      throw new Error(`signal confidence must be a finite number in [0,1]: ${c}`);
    }
    const hit = byId.get(s.node_id);
    if (!hit) continue;
    const strength = c < weakBelow ? 'weak' : 'strong';
    decos.push(Decoration.node(hit.pos, hit.pos + hit.size, {
      'data-signal-kind': String(s.kind),
      'data-signal-layer': s.layer,
      'data-signal-confidence': String(c),
      'data-signal-strength': strength,
      class: `signal signal-${s.layer} signal-${strength}`,
    }));
  }
  return DecorationSet.create(doc, decos);
}

// RE-11: overlay off is a first-class plugin state, toggled by one shortcut. Unwired by design until
// RE-10 / the app shell installs signalDecorationsPlugin.
export const DEFAULT_OFF_SHORTCUT = 'Mod-Shift-o';
const RESERVED = new Set(['mod-shift-p']); // UX-03 proposal request (request.js)
/** @type {PluginKey<{ on: boolean }>} */
export const signalOverlayKey = new PluginKey('signalOverlay');

/** @param {import('prosemirror-state').EditorState} state @returns {boolean} */
export function isSignalOverlayOn(state) {
  const s = signalOverlayKey.getState(state);
  return !!(s && s.on);
}

/**
 * ProseMirror command: flip the overlay on/off.
 * @param {import('prosemirror-state').EditorState} state
 * @param {(tr: import('prosemirror-state').Transaction) => void} [dispatch]
 * @returns {boolean}
 */
export function toggleSignalOverlay(state, dispatch) {
  if (!signalOverlayKey.getState(state)) return false;
  if (dispatch) dispatch(state.tr.setMeta(signalOverlayKey, { on: !isSignalOverlayOn(state) }));
  return true;
}

/**
 * @param {() => Signal[]} getSignals
 * @param {{ weakBelow?: number, initiallyOn?: boolean, offShortcut?: string }} [opts]
 * @returns {Plugin}
 */
export function signalDecorationsPlugin(getSignals, opts = {}) {
  const initiallyOn = opts.initiallyOn === undefined ? true : opts.initiallyOn;
  if (typeof initiallyOn !== 'boolean') throw new Error(`initiallyOn must be a boolean: ${initiallyOn}`);
  const shortcut = opts.offShortcut === undefined ? DEFAULT_OFF_SHORTCUT : opts.offShortcut;
  if (typeof shortcut !== 'string' || !shortcut || RESERVED.has(shortcut.toLowerCase())) {
    throw new Error(`offShortcut must be a non-empty string other than Mod-Shift-p: ${shortcut}`);
  }
  const { weakBelow } = opts;
  return new Plugin({
    key: signalOverlayKey,
    state: {
      init: () => ({ on: initiallyOn }),
      apply: (tr, prev) => tr.getMeta(signalOverlayKey) || prev,
    },
    props: {
      decorations: (state) => (isSignalOverlayOn(state)
        ? signalDecorations(state.doc, getSignals(), { weakBelow }) : DecorationSet.empty),
      handleKeyDown: keydownHandler({ [shortcut]: toggleSignalOverlay }),
    },
  });
}
