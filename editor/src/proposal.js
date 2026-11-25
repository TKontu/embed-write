// @ts-check
// UX-02: accept / reject / edit-then-accept panel for one proposal. The word diff (UX-01) is in
// the panel before any button can act (invariant I5); the applied text goes through
// acceptProposal (UX-04) so each accept is one undo step. onAction reports the user action for
// the edit log (I7, EL-*); this module never writes the log itself.
// Unwired by design until the app shell / proposal flow (GE-*/UX-03) opens panels.
import { acceptProposal } from './index.js';
import { renderDiff } from './diff.js';

/**
 * @typedef {{ action: 'accept'|'reject'|'edit', original: string, candidate: string,
 *   final: string|null, from: number, to: number }} ProposalAction
 */

/**
 * Build the panel for `proposal`. Escape inside the panel rejects; Ctrl/Cmd+Enter accepts.
 * Exactly one action is taken; the panel is then disabled and removed.
 * @param {{ view: import('prosemirror-view').EditorView }} ed
 * @param {{ from: number, to: number, original: string, text: string,
 *   ops: import('./diff.js').DiffOp[] }} proposal
 * @param {{ doc?: Document, onAction?: (a: ProposalAction) => void }} [opts]
 * @returns {HTMLElement}
 */
export function showProposal(ed, proposal, { doc = document, onAction } = {}) {
  const { from, to, original, text, ops } = proposal;
  const panel = doc.createElement('div');
  panel.className = 'proposal';
  panel.appendChild(renderDiff(ops, doc));
  const field = doc.createElement('textarea');
  field.value = text;
  panel.appendChild(field);
  /** @param {'accept'|'reject'} action @param {string} label */
  const button = (action, label) => {
    const b = doc.createElement('button');
    b.type = 'button';
    b.dataset.action = action;
    b.textContent = label;
    panel.appendChild(b);
    return b;
  };
  const acceptBtn = button('accept', 'Accept');
  const rejectBtn = button('reject', 'Reject');

  let done = false;
  /** @param {boolean} accept */
  const act = (accept) => {
    if (done) return;
    done = true;
    /** @type {string|null} */
    let final = null;
    /** @type {ProposalAction['action']} */
    let action = 'reject';
    if (accept) {
      final = field.value;
      if (!acceptProposal(ed, { from, to, text: final })) { done = false; return; }
      action = final === text ? 'accept' : 'edit';
    }
    field.disabled = acceptBtn.disabled = rejectBtn.disabled = true;
    panel.remove();
    onAction?.({ action, original, candidate: text, final, from, to });
  };
  acceptBtn.addEventListener('click', () => act(true));
  rejectBtn.addEventListener('click', () => act(false));
  panel.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') { e.preventDefault(); act(false); }
    else if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); act(true); }
  });
  return panel;
}
