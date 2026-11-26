// DE-02: the provisional overlay renders one decoration per labelled block with its move class
// and legend colour, and the legend lists every move.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { setupDom } from './dom.js';

setupDom();
const { createEditor } = await import('../src/index.js');
const { moveDecorations, moveOverlayPlugin, legendItems } = await import('../demo/overlay.js');
const { parseMarkdown, assignIds } = await import('docmodel');

const dir = fileURLToPath(new URL('../../examples/demo/', import.meta.url));
const name = 'synthetic-sample-1.md';
const source = readFileSync(join(dir, name), 'utf8');
const moves = JSON.parse(readFileSync(join(dir, name.replace(/\.md$/, '.moves.json')), 'utf8'));
const legend = JSON.parse(readFileSync(join(dir, 'legend.json'), 'utf8'));

test('one decoration per labelled block carries the move class and legend colour', () => {
  const doc = assignIds(parseMarkdown(source));
  const found = moveDecorations(doc, moves, legend).find();
  assert.equal(found.length, moves.length);
  for (let i = 0; i < moves.length; i++) {
    const { move } = moves[i];
    const colour = legend.moves[move].colour;
    const attrs = found[i].type.attrs;
    assert.ok(new RegExp(`\\bmove-${move}\\b`).test(attrs.class), `class ${attrs.class} lacks move-${move}`);
    assert.ok(attrs.class.includes('signal-provisional'));
    assert.equal(attrs['data-move'], move);
    assert.equal(attrs['data-move-colour'], colour);
    assert.equal(attrs.style, `--move-colour: ${colour}`);
  }
});

test('the mounted editor renders the decorations and the legend lists each move', async () => {
  const root = document.body.appendChild(document.createElement('div'));
  const editor = await createEditor({ root, markdown: source });
  try {
    const plugin = moveOverlayPlugin(() => moves, () => legend);
    editor.view.updateState(editor.view.state.reconfigure({
      plugins: [...editor.view.state.plugins, plugin],
    }));
    // idPlugin assigns block ids on this transaction; decorations follow it.
    editor.view.dispatch(editor.view.state.tr.setMeta('demo:loaded', true));

    const nodes = [...root.querySelectorAll('[data-move]')];
    assert.equal(nodes.length, moves.length);
    for (const node of nodes) {
      const move = node.getAttribute('data-move');
      assert.ok(move && Object.hasOwn(legend.moves, move), `unexpected move ${move}`);
      assert.ok(node.classList.contains(`move-${move}`), `missing class move-${move}`);
      assert.ok(node.classList.contains('signal-provisional'));
      assert.equal(node.getAttribute('data-move-colour'), legend.moves[move].colour);
    }

    assert.equal(legend.provisional, true);
    const items = legendItems(legend);
    assert.deepEqual(items.map((item) => item.move).sort(), Object.keys(legend.moves).sort());
    for (const item of items) {
      assert.equal(item.colour, legend.moves[item.move].colour);
      assert.equal(item.label, legend.moves[item.move].label);
    }
  } finally {
    await editor.destroy();
    root.remove();
  }
});

test('a sidecar block outside the document is rejected', () => {
  const doc = assignIds(parseMarkdown(source));
  assert.throws(() => moveDecorations(doc, [{ block: 999, move: 'context' }], legend), /out of range/);
  assert.throws(() => moveDecorations(doc, [{ block: 0, move: 'missing' }], legend), /no legend entry/);
});
