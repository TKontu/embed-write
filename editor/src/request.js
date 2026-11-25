// @ts-check
// UX-03: proposals on request only. The writer asks explicitly (Mod-Shift-p on a selection);
// nothing is requested or rendered on typing or selection change, so there is no ghost text.
// Unwired by design until the app shell connects onRequest to the service propose call and
// showProposal.
import { keymap } from '@milkdown/prose/keymap';

/**
 * @param {{ onRequest: (req: { from: number, to: number, text: string }) => void }} opts
 * @returns {import('prosemirror-state').Plugin}
 */
export function proposalRequestKeymap({ onRequest }) {
  return keymap({
    'Mod-Shift-p': (state) => {
      const { from, to, empty } = state.selection;
      if (empty) return false;
      onRequest({ from, to, text: state.doc.textBetween(from, to) });
      return true;
    },
  });
}
