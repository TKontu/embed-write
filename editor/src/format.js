// @ts-check
// FM-01: formatting shortcuts. Mod-b strong, Mod-i em, Mod-e inline code, Mod-k link.
// FM-02: heading shortcuts Mod-1..6 and `#`..`######` + space input rule.
// FM-03: block input rules (lists, task items, quotes, code fences, thematic breaks).
// FM-04: inline input rules (*em*, _em_, **strong**, __strong__, `code`).
// FM-06: escape hatch — Backspace right after an input rule restores the typed text.
// FM-07: command-made marks follow the document's prevailing marker; typed rules keep what was typed.
// Production caller: createEditor (itself unwired by design until AP-01).
import { keymap, keydownHandler } from '@milkdown/prose/keymap';
import { toggleMark, setBlockType } from '@milkdown/prose/commands';
import { inputRules, textblockTypeInputRule, wrappingInputRule, InputRule } from '@milkdown/prose/inputrules';
import { TextSelection, Plugin, PluginKey } from '@milkdown/prose/state';
import { closeHistory } from '@milkdown/prose/history';
import { schema } from 'docmodel';

/**
 * FM-07: the marker most used by the document's existing marks (or bullet_list nodes), so a
 * command follows the file's convention; schema default when the document has none. One doc walk,
 * run only when a formatting command is applied, not while typing. FM-03's list rules are input
 * rules and keep the marker the writer typed, so they never call this.
 * @param {import('prosemirror-model').Node} doc
 * @param {'em'|'strong'|'bullet_list'} name
 * @returns {string}
 */
function prevailingMarker(doc, name) {
  /** @type {Map<string, number>} */
  const counts = new Map();
  const bump = (/** @type {string} */ m) => counts.set(m, (counts.get(m) ?? 0) + 1);
  if (name === 'bullet_list') {
    doc.descendants((n) => { if (n.type.name === 'bullet_list') bump(n.attrs.marker); });
  } else {
    const type = schema.marks[name];
    doc.descendants((n) => {
      if (!n.isText) return;
      const m = type.isInSet(n.marks);
      if (m) bump(m.attrs.marker);
    });
  }
  let best = name === 'bullet_list'
    ? schema.nodes.bullet_list.spec.attrs.marker.default
    : schema.marks[name].spec.attrs.marker.default;
  let bestCount = 0;
  for (const [marker, count] of counts) {
    if (count > bestCount) { best = marker; bestCount = count; }
  }
  return best;
}

/**
 * BH-07: run `cmd` so each transaction it dispatches is its own undo step: closeHistory stops it
 * joining the typing run before it, and the next typed character starts a fresh group.
 * Used by formatKeymap and headingKeymap (production caller: createEditor).
 * @param {import('prosemirror-state').Command} cmd @returns {import('prosemirror-state').Command}
 */
const ownStep = (cmd) => (state, dispatch, view) =>
  cmd(state, dispatch && ((tr) => dispatch(closeHistory(tr))), view);

/**
 * @param {{ isRich?: () => boolean, onLinkRequest?: (text: string) => string | null | Promise<string | null> }} [opts]
 * @returns {import('prosemirror-state').Plugin}
 */
export function formatKeymap({ isRich = () => true, onLinkRequest } = {}) {
  /** @param {string} name @returns {import('prosemirror-state').Command} */
  const mark = (name) => (state, dispatch) => {
    if (!isRich()) return false;
    const attrs = dispatch && (name === 'em' || name === 'strong')
      ? { marker: prevailingMarker(state.doc, name) }
      : undefined;
    return toggleMark(state.schema.marks[name], attrs)(state, dispatch);
  };

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
      view.dispatch(closeHistory(view.state.tr.addMark(from, to, type.create({ href }))));
    }, () => {});
    return true;
  };

  return keymap({ 'Mod-b': ownStep(mark('strong')), 'Mod-i': ownStep(mark('em')), 'Mod-e': ownStep(mark('code')), 'Mod-k': ownStep(link) });
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
  for (let n = 1; n <= 6; n++) keys[`Mod-${n}`] = ownStep(heading(n));
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
    const tr = state.tr.replaceWith($s.before(), $s.after(), [
      n.thematic_break.create({ marker: match[1].repeat(3) }), n.paragraph.create(),
    ]);
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

/**
 * FM-04: typing the closing delimiter converts the just-typed span: `*x*`/`_x_` em,
 * `**x**`/`__x__` strong, `` `x` `` inline code; delimiters are removed and em/strong keep their
 * marker so serialization reproduces the typed source. No conversion for empty spans, spans that
 * start or end with whitespace, or intraword `_` (snake_case). Strikethrough is skipped: docmodel's
 * schema has no strike mark. Inactive in source view, code blocks and inline code; undoable (FM-06).
 * @param {{ isRich?: () => boolean }} [opts]
 * @returns {import('prosemirror-state').Plugin}
 */
export function inlineInputRules({ isRich = () => true } = {}) {
  const m = schema.marks;
  const body = (d) => `([^${d}\\s\\ufffc](?:[^${d}\\ufffc]*[^${d}\\s\\ufffc])?)`;
  /** @param {RegExp} re @param {import('prosemirror-model').MarkType} type @param {number} len @param {string | null} marker */
  const rule = (re, type, len, marker) => new InputRule(re, (state, match, start, end) => {
    // docmodel's code mark has no spec.code, so inputrules' own inCodeMark check misses it.
    if (state.doc.rangeHasMark(start, end, m.code) || m.code.isInSet(state.doc.resolve(end).marks())) return null;
    const from = start + match[1].length;
    const cFrom = from + len;
    const cTo = cFrom + match[2].length;
    const tr = state.tr.delete(cTo, end)
      .addMark(cFrom, cTo, type.create(marker ? { marker } : null))
      .delete(from, cFrom);
    return tr.removeStoredMark(type);
  }, { inCodeMark: false });
  const rules = [
    rule(new RegExp(`(^|[^*])\\*\\*${body('*')}\\*\\*$`), m.strong, 2, '*'),
    rule(new RegExp(`(^|[^\\w])__${body('_')}__$`), m.strong, 2, '_'),
    rule(new RegExp(`(^|[^*])\\*${body('*')}\\*$`), m.em, 1, '*'),
    rule(new RegExp(`(^|[^\\w])_${body('_')}_$`), m.em, 1, '_'),
    rule(new RegExp(`(^|[^\`])\`${body('`')}\`$`), m.code, 1, null),
  ];
  const plugin = inputRules({ rules });
  const handle = plugin.props.handleTextInput;
  // Wrap rather than replace so FM-06 still finds this plugin's state.
  plugin.props.handleTextInput = function (view, from, to, text, deflt) {
    if (!isRich()) return false;
    return /** @type {any} */ (handle).call(this, view, from, to, text, deflt);
  };
  return plugin;
}

/**
 * FM-06: Backspace immediately after any input rule (FM-02 heading, FM-03 block rules) undoes the
 * conversion and leaves the typed literal text; otherwise it falls through to the other Backspace
 * bindings, so it must precede them. Inactive in source view.
 *
 * prosemirror-inputrules' own undoInputRule forgets the rule as soon as any later transaction
 * changes the doc — including the id-fixing transaction docmodel's idPlugin appends to every
 * conversion. So this plugin records the rule itself, plus the steps of transactions appended
 * after it, and inverts both.
 * @param {{ isRich?: () => boolean }} [opts]
 * @returns {import('prosemirror-state').Plugin}
 */
export function escapeKeymap({ isRich = () => true } = {}) {
  /** @typedef {{ transform: import('prosemirror-transform').Transform, from: number, to: number, text: string }} Undoable */
  /** @typedef {{ rule: Undoable, extra: { step: import('prosemirror-transform').Step, doc: import('prosemirror-model').Node }[] } | null} Last */
  const key = new PluginKey('fm06-escape');
  /** @type {import('prosemirror-state').Command} */
  const undo = (state, dispatch) => {
    if (!isRich()) return false;
    /** @type {Last} */
    const last = key.getState(state);
    if (!last) return false;
    if (dispatch) {
      const tr = state.tr;
      for (let j = last.extra.length - 1; j >= 0; j--) tr.step(last.extra[j].step.invert(last.extra[j].doc));
      const { transform, from, to, text } = last.rule;
      for (let j = transform.steps.length - 1; j >= 0; j--) tr.step(transform.steps[j].invert(transform.docs[j]));
      if (text) {
        tr.replaceWith(from, to, state.schema.text(text, tr.doc.resolve(from).marks()));
        tr.setSelection(TextSelection.create(tr.doc, from + text.length));
      } else tr.delete(from, to);
      dispatch(tr);
    }
    return true;
  };
  return new Plugin({
    key,
    state: {
      init: () => null,
      /** @returns {Last} */
      apply(tr, /** @type {Last} */ prev, state) {
        const rule = state.plugins.reduce((r, p) => r ?? (p.spec.isInputRules ? tr.getMeta(p) : null), null);
        if (rule) return { rule, extra: [] };
        if (prev && tr.getMeta('appendedTransaction')) {
          return { rule: prev.rule, extra: [...prev.extra, ...tr.steps.map((step, i) => ({ step, doc: tr.docs[i] }))] };
        }
        return tr.selectionSet || tr.docChanged ? null : prev;
      },
    },
    props: { handleKeyDown: keydownHandler({ Backspace: undo }) },
  });
}
