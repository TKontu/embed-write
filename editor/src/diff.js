// @ts-check
// UX-01: render service/word_diff.py DiffOp rows as a visible word-level diff (invariant I5).
// Unwired by design until UX-02 (accept/reject UI) shows it next to a proposal.
// The diff algorithm lives in service/word_diff.py; this only renders its rows.

/**
 * @typedef {{ kind: string, original_text: string, candidate_text: string }} DiffOp
 */

/**
 * Render DiffOp rows into one element. equal -> text node; delete -> <del>; insert -> <ins>;
 * replace -> <del> then <ins>. Text is inserted as text nodes, never parsed as HTML.
 * @param {DiffOp[]} ops
 * @param {Document} [doc]
 * @returns {HTMLElement}
 */
export function renderDiff(ops, doc = document) {
  const root = doc.createElement('span');
  root.className = 'diff';
  /** @param {'del'|'ins'} tag @param {string} kind @param {string} text */
  const part = (tag, kind, text) => {
    const el = doc.createElement(tag);
    el.dataset.kind = kind;
    el.textContent = text;
    root.appendChild(el);
  };
  for (const op of ops) {
    switch (op.kind) {
      case 'equal': root.appendChild(doc.createTextNode(op.original_text)); break;
      case 'delete': part('del', 'delete', op.original_text); break;
      case 'insert': part('ins', 'insert', op.candidate_text); break;
      case 'replace':
        part('del', 'delete', op.original_text);
        part('ins', 'insert', op.candidate_text);
        break;
      default: throw new Error(`renderDiff: unknown DiffOp kind ${JSON.stringify(op.kind)}`);
    }
  }
  return root;
}
