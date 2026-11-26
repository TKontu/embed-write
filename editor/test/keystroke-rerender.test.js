// FP-02: one typed character mutates only the edited block. Untouched top-level blocks keep their
// DOM node identity, a MutationObserver sees mutations only inside the edited block, and no
// render.js node view is constructed for an untouched block. jsdom check, not a browser profile.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setupDom } from './dom.js';

setupDom();
const { createEditor, signalDecorationsPlugin } = await import('../src/index.js');

// LLM-built synthetic document: heading, 22 paragraphs, a code block, a closing paragraph.
const paras = Array.from({ length: 22 }, (_, i) => `Paragraph number ${i + 1} with some words.`);
const markdown = ['# Synthetic heading', ...paras, '```js\nconst x = 1;\n```', 'Closing paragraph.'].join('\n\n') + '\n';

test('one keystroke mutates only the edited block; node views of untouched blocks are not rebuilt', async () => {
  const root = document.body.appendChild(document.createElement('div'));
  const editor = await createEditor({ root, markdown });
  try {
    const { view } = editor;
    // Spy on every node view constructor (the render.js views Milkdown installed), keyed by node id.
    const built = [];
    const orig = view.someProp('nodeViews');
    assert.ok(orig && orig.paragraph && orig.heading && orig.code_block, 'render.js node views installed');
    const spied = Object.fromEntries(Object.entries(orig).map(([name, f]) => [name, (node, ...rest) => {
      built.push({ name, id: node.attrs.id });
      return f(node, ...rest);
    }]));
    view.setProps({ nodeViews: spied });

    // docmodel's idPlugin assigns block ids on the first transaction; settle them before measuring.
    view.dispatch(view.state.tr);
    // Signals on several blocks, overlay on.
    const ids = [];
    view.state.doc.forEach((n) => ids.push(n.attrs.id));
    assert.ok(ids.length >= 24 && ids.every((id) => typeof id === 'string'));
    const signalled = [0, 3, 5, 6, 11, 23];
    const signals = signalled.map((i) => ({ node_id: ids[i], kind: 'k', confidence: 0.9, layer: 'provisional' }));
    view.updateState(view.state.reconfigure({ plugins: [...view.state.plugins, signalDecorationsPlugin(() => signals)] }));
    assert.equal(root.querySelectorAll('.signal').length, signalled.length);

    const pm = view.dom;
    const before = [...pm.children];
    assert.equal(before.length, view.state.doc.childCount);
    const edited = 5; // a signalled paragraph
    let pos = 0;
    for (let i = 0; i < edited; i += 1) pos += view.state.doc.child(i).nodeSize;
    const editedDom = before[edited];

    const records = [];
    const mo = new MutationObserver((rs) => records.push(...rs));
    mo.observe(pm, { subtree: true, childList: true, attributes: true, characterData: true });
    built.length = 0;
    // As a keystroke: one character inserted inside the block's text through a view transaction.
    view.dispatch(view.state.tr.insertText('Z', pos + 3));
    records.push(...mo.takeRecords());
    mo.disconnect();

    assert.match(view.state.doc.child(edited).textContent, /^PaZr/);
    const untouched = built.filter((b) => b.id !== ids[edited]);
    assert.deepEqual(untouched, [], 'no node view rebuilt for untouched blocks');
    const after = [...pm.children];
    assert.equal(after.length, before.length);
    for (let i = 0; i < before.length; i += 1) {
      if (i !== edited) assert.equal(after[i], before[i], `block ${i} DOM node identity kept`);
    }
    assert.ok(records.length > 0, 'the edit is observed');
    for (const r of records) {
      assert.ok(r.target !== pm && editedDom.contains(r.target) || after[edited].contains(r.target),
        `mutation outside the edited block: ${r.type} on ${r.target.nodeName}`);
    }
  } finally {
    await editor.destroy();
    root.remove();
  }
});
