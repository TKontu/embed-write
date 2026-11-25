// @ts-check
// PM-01: overlay decorations whose positions survive transactions.
// Unwired by design: ED-01 wires overlayPlugin into the editor; no DOM rendering here.
import { Plugin, PluginKey } from 'prosemirror-state';
import { Decoration, DecorationSet } from 'prosemirror-view';

export const overlayKey = new PluginKey('overlay');

/**
 * Plugin state: a DecorationSet of inline decorations, mapped through every transaction.
 * Meta (tr.setMeta(overlayKey, ...)): { clear?: boolean, add?: Array<{from:number,to:number,spec?:object}> }.
 * `clear` is applied before `add`; positions in `add` refer to tr.doc.
 */
export function overlayPlugin() {
  return new Plugin({
    key: overlayKey,
    state: {
      init: () => DecorationSet.empty,
      apply(tr, set) {
        let next = set.map(tr.mapping, tr.doc);
        const meta = tr.getMeta(overlayKey);
        if (meta) {
          if (meta.clear) next = DecorationSet.empty;
          if (meta.add && meta.add.length) {
            const decos = meta.add
              .filter((o) => o.from < o.to)
              .map((o) => Decoration.inline(o.from, o.to, {}, o.spec || {}));
            next = next.add(tr.doc, decos);
          }
        }
        return next;
      },
    },
    props: {
      decorations(state) { return overlayKey.getState(state); },
    },
  });
}

/**
 * Current overlays as [{from,to,spec}] sorted by from, then to.
 * @param {import('prosemirror-state').EditorState} state
 */
export function overlayRanges(state) {
  const set = overlayKey.getState(state);
  if (!set) return [];
  return set.find()
    .map((d) => ({ from: d.from, to: d.to, spec: d.spec }))
    .sort((a, b) => a.from - b.from || a.to - b.to);
}
