// FM-05: paste. Markdown text pastes as formatted nodes, HTML converts to Markdown-representable
// structure (no raw HTML enters the doc), plain prose stays plain. Inactive in source view.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setupDom } from './dom.js';

setupDom();
const { createEditor } = await import('../src/index.js');
const { Slice } = await import('@milkdown/prose/model');
const { TextSelection } = await import('@milkdown/prose/state');

const mount = () => document.body.appendChild(document.createElement('div'));
/** Paste into an empty doc; returns whether a plugin handled it. */
function paste(ed, data) {
  const ev = { clipboardData: { getData: (t) => data[t] ?? '', types: Object.keys(data) }, preventDefault() {} };
  return ed.view.someProp('handlePaste', (f) => f(ed.view, /** @type {any} */ (ev), Slice.empty)) ?? false;
}
async function withEd(md, fn) {
  const ed = await createEditor({ root: mount(), markdown: md });
  try { return await fn(ed); } finally { await ed.destroy(); }
}
const types = (ed) => { const out = []; ed.view.state.doc.descendants((n) => { out.push(n.type.name); for (const m of n.marks) out.push(`mark:${m.type.name}`); }); return out; };

test('Markdown text pastes as heading, list, bold, link and code fence nodes', () => withEd('', (ed) => {
  const md = '# Title\n\n- one **bold**\n- [link](https://example.com)\n\n```js\nlet x = 1;\n```\n';
  assert.equal(paste(ed, { 'text/plain': md }), true);
  const t = types(ed);
  for (const k of ['heading', 'bullet_list', 'list_item', 'mark:strong', 'mark:link', 'code_block']) assert.ok(t.includes(k), k);
  assert.equal(ed.getMarkdown(), md);
}));

test('HTML converts to representable Markdown; tables become tables; no raw HTML', () => withEd('', (ed) => {
  const html = '<meta charset="utf-8"><h2 style="color:red">Head</h2><ul><li><b>B</b> and <i>I</i></li>' +
    '<li><a href="https://e.com" class="x">L</a></li></ul><pre><code>a &lt; b\n</code></pre>' +
    '<p><span style="font-weight:normal;color:blue">styled</span> text</p><script>evil()</script>' +
    '<table><thead><tr><th>A</th><th>B</th></tr></thead><tbody><tr><td>1</td><td>2</td></tr></tbody></table>';
  assert.equal(paste(ed, { 'text/html': html, 'text/plain': 'Head B and I L' }), true);
  const out = ed.getMarkdown();
  assert.match(out, /^## Head\n/);
  assert.match(out, /- \*\*B\*\* and \*I\*\n/);
  assert.match(out, /- \[L\]\(https:\/\/e\.com\)\n/);
  assert.match(out, /```\na < b\n```/);
  assert.match(out, /\nstyled text\n/);
  assert.match(out, /\| A \| B \|/);
  assert.match(out, /\| 1 \| 2 \|/);
  assert.doesNotMatch(out, /evil|<span|<b>|style=|<table|<meta/);
  assert.ok(!types(ed).includes('html_block'));
}));

test('plain prose stays one paragraph of literal text', () => withEd('', (ed) => {
  const text = 'Rates rose 5 * 3 times; a_b and c_d stay as typed.';
  assert.equal(paste(ed, { 'text/plain': text }), true);
  assert.deepEqual(types(ed), ['paragraph', 'text']);
  assert.equal(ed.view.state.doc.textContent, text);
}));

test('plain text pasted mid-paragraph inserts inline', () => withEd('ab\n', (ed) => {
  ed.view.dispatch(ed.view.state.tr.setSelection(TextSelection.create(ed.view.state.doc, 2)));
  assert.equal(paste(ed, { 'text/plain': 'X * Y' }), true);
  assert.equal(ed.view.state.doc.textContent, 'aX * Yb');
}));

test('source view: paste plugin does not handle the event', () => withEd('x\n', (ed) => {
  ed.showSource();
  assert.equal(paste(ed, { 'text/plain': '# H' }), false);
  assert.equal(ed.getMarkdown(), 'x\n');
}));

test('pasted HTML is parsed in an inert document, never in the live one', () => withEd('', (ed) => {
  const orig = document.createElement;
  let live = 0;
  document.createElement = function (...a) { live++; return orig.apply(this, a); };
  const desc = Object.getOwnPropertyDescriptor(Element.prototype, 'innerHTML');
  let liveHtml = 0;
  Object.defineProperty(Element.prototype, 'innerHTML', { ...desc, set(v) { if (this.ownerDocument === document) liveHtml++; desc.set.call(this, v); } });
  try {
    assert.equal(paste(ed, { 'text/html': '<p>a<img src="x" onerror="globalThis.__pwned=1">b</p>' }), true);
  } finally {
    document.createElement = orig;
    Object.defineProperty(Element.prototype, 'innerHTML', desc);
  }
  assert.equal(liveHtml, 0, 'innerHTML set on a live-document element');
  assert.equal(globalThis.__pwned, undefined);
  assert.equal(ed.getMarkdown(), 'ab\n');
}));
