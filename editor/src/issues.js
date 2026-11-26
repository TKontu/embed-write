// @ts-check
// OV-03: open-issues list. D-009 thin-demo slice: missing genre moves and unlabeled passages only;
// unsupported claims and off-register passages have no data source in the demo yet (residual).
// No colours are set here (invariant I3). Production caller: editor/demo/app.js; AP-01 wires the
// app. O(blocks + moves).

/**
 * @typedef {{ kind: 'missing-move' | 'unlabeled', moveId?: string, block?: number, text: string }} Issue
 */

/**
 * Missing moves in genre order, then one entry per run of unlabeled blocks in document order.
 * Sidecar entries with move ids the genre does not know are ignored (they neither count as present
 * nor label a block); entries outside [0, blockCount) are ignored.
 * @param {Array<{ block: number, move: string }>} moves
 * @param {number} blockCount
 * @param {any} genre parsed genre file
 * @returns {Issue[]}
 */
export function openIssues(moves, blockCount, genre) {
  const genreMoves = /** @type {any[]} */ (genre?.moves ?? []);
  const known = new Set(genreMoves.map((m) => m.id));
  const present = new Set();
  const labeled = new Array(Math.max(0, blockCount)).fill(false);
  for (const e of moves) {
    if (!known.has(e.move)) continue;
    if (!Number.isInteger(e.block) || e.block < 0 || e.block >= blockCount) continue;
    present.add(e.move);
    labeled[e.block] = true;
  }
  /** @type {Issue[]} */
  const out = [];
  for (const m of genreMoves) {
    if (!present.has(m.id)) out.push({ kind: 'missing-move', moveId: m.id, text: `Missing move: ${m.name ?? m.id}` });
  }
  for (let i = 0; i < labeled.length; i += 1) {
    if (!labeled[i] && (i === 0 || labeled[i - 1])) out.push({ kind: 'unlabeled', block: i, text: 'Unlabeled passage' });
  }
  return out;
}

/**
 * Render issues as a list; items with a block are buttons calling onNavigate(block).
 * @param {Document} doc
 * @param {Issue[]} issues
 * @param {(block: number) => void} onNavigate
 * @returns {HTMLUListElement}
 */
export function renderIssues(doc, issues, onNavigate) {
  const ul = doc.createElement('ul');
  ul.className = 'issues';
  ul.setAttribute('aria-label', 'Open issues');
  if (!issues.length) {
    const li = doc.createElement('li');
    li.className = 'issues-empty';
    li.textContent = 'No open issues';
    ul.append(li);
    return ul;
  }
  for (const issue of issues) {
    const li = doc.createElement('li');
    li.dataset.kind = issue.kind;
    const block = issue.block;
    if (block !== undefined) {
      const btn = doc.createElement('button');
      btn.type = 'button';
      btn.textContent = issue.text;
      btn.dataset.block = String(block);
      btn.addEventListener('click', () => onNavigate(block));
      li.append(btn);
    } else {
      li.textContent = issue.text;
    }
    ul.append(li);
  }
  return ul;
}
