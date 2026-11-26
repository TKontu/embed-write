// @ts-check
// FM-01: formatting shortcuts. Mod-b strong, Mod-i em, Mod-e inline code, Mod-k link.
// FM-02: heading shortcuts Mod-1..6 and `#`..`######` + space input rule.
// FM-03: block input rules (lists, task items, quotes, code fences, thematic breaks).
// Production caller: createEditor (itself unwired by design until AP-01).
import { keymap } from '@milkdown/prose/keymap';
import { toggleMark, setBlockType } from '@milkdown/prose/commands';
import { inputRules, textblockTypeInputRule, wrappingInputRule, InputRule } from '@milkdown/prose/inputrules';
import { TextSelection } from '@milkdown/prose/state';
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

/**
 * Gate an inputRules plugin: inactive in source view and outside paragraphs. Wraps rather than
 * replaces handleTextInput so undoInputRule still finds the plugin's state.
 * @param {import('prosemirror-state').Plugin} plugin @param {() => boolean} isRich
 */
function gate(plugin, isRich) {
  const handle = plugin.props.handleTextInput;
  plugin.props.handleTextInput = function (view, from, to, text, deflt) {
    if (!isRich() || view.state.doc.resolve(from).parent.type.name !== 'paragraph') return false;
    return /** @type {any} */ (handle).call(this, view, from, to, text, deflt);
  };
  return plugin;
}

const FENCE = /^```([\w+#.-]*)$/;

/**
 * FM-03: at the start of a paragraph, `- `/`* `/`+ ` make a bullet list (marker kept), `N. ` an
 * ordered list starting at N, `> ` a blockquote, `[ ] `/`[x] ` at a list item's start a task item,
 * ```` ```lang ```` plus space or Enter a code block, and `---`/`***`/`___` on an otherwise empty
 * paragraph a thematic break followed by an empty paragraph. Inactive in source view.
 * @param {{ isRich?: () => boolean }} [opts]
 * @returns {import('prosemirror-state').Plugin[]}
 */
export function blockInputRules({ isRich = () => true } = {}) {
  const n = schema.nodes;
  const task = new InputRule(/^\[([ xX])\]\s$/, (state, match, start, end) => {
    const $s = state.doc.resolve(start);
    const item = $s.node(-1);
    if (!item || item.type !== n.list_item || $s.index(-1) !== 0 || item.attrs.checked != null) return null;
    return state.tr.delete(start, end)
      .setNodeMarkup($s.before(-1), null, { ...item.attrs, checked: match[1] !== ' ' });
  });
  const rule = new InputRule(/^([-*_])\1\1$/, (state, match, start, end) => {
    const $s = state.doc.resolve(start);
    // Only when the paragraph holds nothing but the typed rule characters.
    if ($s.parent.content.size !== end - start) return null;
    const tr = state.tr.replaceWith($s.before(), $s.after(), [n.thematic_break.create(), n.paragraph.create()]);
    return tr.setSelection(TextSelection.create(tr.doc, $s.before() + 2));
  }, { inCodeMark: false });
  const rules = [
    wrappingInputRule(/^\s*([-*+])\s$/, n.bullet_list, (m) => ({ marker: m[1] }),
      (m, node) => node.attrs.marker === m[1]),
    wrappingInputRule(/^(\d+)\.\s$/, n.ordered_list, (m) => ({ start: Number(m[1]) }),
      (m, node) => node.childCount + node.attrs.start === Number(m[1])),
    wrappingInputRule(/^\s*>\s$/, n.blockquote),
    task,
    textblockTypeInputRule(/^```([\w+#.-]*)\s$/, n.code_block, (m) => ({ lang: m[1] || null })),
    rule,
  ];
  /** @type {import('prosemirror-state').Command} */
  const fenceEnter = (state, dispatch) => {
    if (!isRich()) return false;
    const { $from, empty } = state.selection;
    if (!empty || $from.parent.type !== n.paragraph || $from.parentOffset !== $from.parent.content.size) return false;
    const m = FENCE.exec($from.parent.textContent);
    if (!m) return false;
    if (dispatch) {
      const tr = state.tr.delete($from.start(), $from.end())
        .setBlockType($from.start(), $from.start(), n.code_block, { lang: m[1] || null });
      dispatch(tr.scrollIntoView());
    }
    return true;
  };
  return [gate(inputRules({ rules }), isRich), keymap({ Enter: fenceEnter })];
}
