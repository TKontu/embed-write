// @ts-check
// ED-04: source view toggle. The textarea holds raw Markdown; docmodel's parseMarkdown and
// serializeMarkdown stay the only conversion (architecture I1). Unwired by design until AP-01.
import { parseMarkdown, serializeMarkdown } from 'docmodel';
import { closeHistory } from '@milkdown/prose/history';

/**
 * @param {HTMLElement} root
 * @param {() => import('prosemirror-view').EditorView} getView
 */
export function sourceView(root, getView) {
  /** @type {HTMLTextAreaElement | null} */
  let ta = null;
  let on = false;
  return {
    isSourceView: () => on,
    /** @returns {string | null} textarea text while in source view */
    text: () => (on && ta ? ta.value : null),
    showSource() {
      if (on) return;
      const view = getView();
      if (!ta) {
        ta = root.ownerDocument.createElement('textarea');
        ta.className = 'md-source';
        root.appendChild(ta);
      }
      ta.value = serializeMarkdown(view.state.doc);
      ta.hidden = false;
      view.dom.hidden = true;
      on = true;
    },
    showRich() {
      if (!on || !ta) return;
      const view = getView();
      const text = ta.value;
      if (text !== serializeMarkdown(view.state.doc)) {
        const doc = parseMarkdown(text); // throws: stay in source view, text kept
        const { state } = view;
        view.dispatch(closeHistory(state.tr.replaceWith(0, state.doc.content.size, doc.content)));
      }
      ta.hidden = true;
      view.dom.hidden = false;
      on = false;
    },
    remove() { ta?.remove(); ta = null; on = false; },
  };
}
