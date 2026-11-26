// @ts-check
// FM-01: formatting shortcuts. Mod-b strong, Mod-i em, Mod-e inline code, Mod-k link.
// FM-02: heading shortcuts Mod-1..6 and `#`..`######` + space input rule.
// Production caller: createEditor (itself unwired by design until AP-01).
import { keymap } from '@milkdown/prose/keymap';
import { toggleMark, setBlockType } from '@milkdown/prose/commands';
import { inputRules, textblockTypeInputRule } from '@milkdown/prose/inputrules';
import { schema } from 'docmodel';

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

/**
 * FM-02: Mod-1..Mod-6 set the selected textblocks to heading level N; when every selected
 * textblock is already a level-N heading, they become paragraphs again. Inactive in source view.
 * @param {{ isRich?: () => boolean }} [opts]
 * @returns {import('prosemirror-state').Plugin}
 */
export function headingKeymap({ isRich = () => true } = {}) {
  /** @param {number} level @returns {import('prosemirror-state').Command} */
  const heading = (level) => (state, dispatch) => {
    if (!isRich()) return false;
    const { heading: h, paragraph: p } = state.schema.nodes;
    const { from, to } = state.selection;
    let all = true;
    state.doc.nodesBetween(from, to, (n) => {
      if (n.isTextblock && !(n.type === h && n.attrs.level === level)) all = false;
    });
    return all ? setBlockType(p)(state, dispatch) : setBlockType(h, { level })(state, dispatch);
  };
  /** @type {Record<string, import('prosemirror-state').Command>} */
  const keys = {};
  for (let n = 1; n <= 6; n++) keys[`Mod-${n}`] = heading(n);
  return keymap(keys);
}

/**
 * FM-02: `#`..`######` then a space at the start of a paragraph turns it into a heading of that
 * level. Inactive in source view.
 * @param {{ isRich?: () => boolean }} [opts]
 * @returns {import('prosemirror-state').Plugin}
 */
export function headingInputRule({ isRich = () => true } = {}) {
  const rule = textblockTypeInputRule(/^(#{1,6})\s$/, schema.nodes.heading, (m) => ({ level: m[1].length }));
  const plugin = inputRules({ rules: [rule] });
  const handle = plugin.props.handleTextInput;
  // Wrap rather than replace so undoInputRule still finds this plugin's state.
  plugin.props.handleTextInput = function (view, from, to, text, deflt) {
    if (!isRich() || view.state.doc.resolve(from).parent.type.name !== 'paragraph') return false;
    return /** @type {any} */ (handle).call(this, view, from, to, text, deflt);
  };
  return plugin;
}
