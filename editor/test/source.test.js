// ED-04: source view toggle (raw Markdown in a textarea, parsed back by docmodel).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setupDom } from './dom.js';

setupDom();
const { createEditor, undo } = await import('../src/index.js');
const { serializeMarkdown, parseMarkdown, UnsupportedNodeError } = await import('docmodel');

// Synthetic fixture: heading, list, table, emphasis.
const SRC = '# Report\n\nSome *emphasis* and **strong** text.\n\n- one\n- two\n\n| a | b |\n| - | - |\n| 1 | 2 |\n';
const mount = () => document.body.appendChild(document.createElement('div'));
const textarea = (root) => root.querySelector('textarea.md-source');

test('toggle round trip is byte-identical and isSourceView reflects state', async () => {
  const root = mount();
  const ed = await createEditor({ root, markdown: SRC });
  try {
    const before = ed.getMarkdown();
    assert.equal(ed.isSourceView(), false);
    ed.showSource();
    assert.equal(ed.isSourceView(), true);
    const ta = textarea(root);
    assert.ok(ta, 'textarea inside root');
    assert.equal(ta.value, before);
    assert.equal(ta.hidden, false);
    assert.equal(ed.view.dom.hidden, true);
    assert.equal(ed.getMarkdown(), before);
    ed.showRich();
    assert.equal(ed.isSourceView(), false);
    assert.equal(ta.hidden, true);
    assert.equal(ed.view.dom.hidden, false);
    assert.equal(ed.getMarkdown(), before);
  } finally { await ed.destroy(); }
});

test('textarea edit: getMarkdown verbatim in source, showRich updates doc; undo restores', async () => {
  const root = mount();
  const ed = await createEditor({ root, markdown: SRC });
  try {
    const prior = ed.view.state.doc;
    ed.showSource();
    const edited = '# Changed\n\nNew  *text*.\n';
    textarea(root).value = edited;
    assert.equal(ed.getMarkdown(), edited);
    ed.showRich();
    assert.equal(ed.view.state.doc.textContent, parseMarkdown(edited).textContent);
    assert.equal(ed.getMarkdown(), serializeMarkdown(parseMarkdown(edited)));
    assert.ok(undo(ed));
    assert.equal(serializeMarkdown(ed.view.state.doc), serializeMarkdown(prior)); // ids may be assigned by idPlugin
    assert.equal(ed.getMarkdown(), serializeMarkdown(parseMarkdown(SRC)));
  } finally { await ed.destroy(); }
});

test('throwing parse keeps source view and text', async () => {
  const root = mount();
  const ed = await createEditor({ root, markdown: SRC });
  try {
    ed.showSource();
    const bad = '+++\na = 1\n+++\n\nx\n'; // TOML front matter: parseMarkdown throws
    textarea(root).value = bad;
    assert.throws(() => ed.showRich(), UnsupportedNodeError);
    assert.equal(ed.isSourceView(), true);
    assert.equal(textarea(root).value, bad);
    assert.equal(ed.getMarkdown(), bad);
  } finally { await ed.destroy(); }
});

test('destroy removes the textarea', async () => {
  const root = mount();
  const ed = await createEditor({ root, markdown: SRC });
  ed.showSource();
  assert.ok(textarea(root));
  await ed.destroy();
  assert.equal(textarea(root), null);
});
