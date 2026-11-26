// @ts-check
// FM-01: formatting shortcuts. Mod-b strong, Mod-i em, Mod-e inline code, Mod-k link.
// Production caller: createEditor (itself unwired by design until AP-01).
import { keymap } from '@milkdown/prose/keymap';
import { toggleMark } from '@milkdown/prose/commands';

/**
 * @param {{ isRich?: () => boolean, onLinkRequest?: (text: string) => string | null | Promise<string | null> }} [opts]
 * @returns {import('prosemirror-state').Plugin}
 */
export function formatKeymap({ isRich = () => true, onLinkRequest } = {}) {
  /** @param {string} name @returns {import('prosemirror-state').Command} */
  const mark = (name) => (state, dispatch) =>
    isRich() && toggleMark(state.schema.marks[name])(state, dispatch);

  /** @type {import('prosemirror-state').Command} */
  const link = (state, dispatch, view) => {
    if (!isRich()) return false;
    const { from, to, empty } = state.selection;
    const type = state.schema.marks.link;
    if (empty) return false;
    if (state.doc.rangeHasMark(from, to, type)) {
      dispatch?.(state.tr.removeMark(from, to, type));
      return true;
    }
    if (!onLinkRequest || !view) return false;
    const doc0 = state.doc;
    Promise.resolve(onLinkRequest(state.doc.textBetween(from, to))).then((href) => {
      // Apply only to the document the request was made on; a later edit cancels it.
      if (!href || view.isDestroyed || view.state.doc !== doc0) return;
      view.dispatch(view.state.tr.addMark(from, to, type.create({ href })));
    }, () => {});
    return true;
  };

  return keymap({ 'Mod-b': mark('strong'), 'Mod-i': mark('em'), 'Mod-e': mark('code'), 'Mod-k': link });
}
