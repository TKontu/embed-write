// @ts-check
// OV-01/OV-03: re-render the minimap and the open-issues list from the current labels, so a saved
// expert correction shows at once without reload. The minimap keeps its collapsed/expanded state
// (mountCollapsibleMinimap reads it from the mount). No colours are set here (I3). Production
// caller: editor/demo/app.js (load path and correctLabel); AP-01 wires the app. O(blocks + moves).
import { mountCollapsibleMinimap } from './minimap.js';
import { openIssues, renderIssues } from './issues.js';

/**
 * @param {{ minimapMount: HTMLElement, issuesMount: HTMLElement,
 *   moves: Array<{ block: number, move: string }>, blockCount: number, genre: any,
 *   onNavigate: (block: number) => void }} opts
 * @returns {import('./issues.js').Issue[]} the issues now shown
 */
export function refreshOverview({ minimapMount, issuesMount, moves, blockCount, genre, onNavigate }) {
  mountCollapsibleMinimap(minimapMount, moves, blockCount, genre);
  const issues = openIssues(moves, blockCount, genre);
  issuesMount.replaceChildren(renderIssues(issuesMount.ownerDocument, issues, onNavigate));
  return issues;
}
