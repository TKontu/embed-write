// CO-14 (D-015) demo half: an intake sections.json yields provisional "inferred · <method>"
// markers before the blocks at the inferred lines; without --sections there are none, and the
// document text is never rewritten. Synthetic, LLM-built fixture text only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setupDom } from './dom.js';

setupDom();
const { createEditor } = await import('../src/index.js');
const { sectionMarkers, sectionMarkerPlugin } = await import('../demo/sections.js');
const { startServer } = await import('../demo/server.js');
const { serializeMarkdown } = await import('docmodel');

// Source lines: 0, 2, 4, 6 paragraphs; 8 a numbered title line; 10 a paragraph.
const source = [
  'Invented harbour cranes lift crates at dawn.', // 0
  '',
  'The cranes rest while gulls circle the quay.', // 2
  '',
  'Bakers in the old town knead rye dough.', // 4
  '',
  'Ovens warm the street before sunrise.', // 6
  '',
  '2 Results', // 8
  '',
  'Invented results paragraph closes the note.', // 10
  '',
].join('\n');
const inferred = [
  { start_line: 0, level: 1, title_line: null, inferred: true, method: 'topic_shift_embedding' },
  { start_line: 4, level: 1, title_line: null, inferred: true, method: 'topic_shift_embedding' },
  { start_line: 8, level: 1, title_line: 8, inferred: true, method: 'numbering' },
];

test('markers land on the blocks starting at the inferred lines and carry the method', () => {
  assert.deepEqual(sectionMarkers(source, inferred).map((m) => [m.block, m.line, m.method]),
    [[0, 0, 'topic_shift_embedding'], [2, 4, 'topic_shift_embedding'], [4, 8, 'numbering']]);
  assert.deepEqual(sectionMarkers(source, []), []);
  assert.deepEqual(sectionMarkers(source, [{ ...inferred[1], inferred: false }]), []);
});

test('the editor shows one provisional badge per inferred section, text unchanged', async () => {
  const root = document.body.appendChild(document.createElement('div'));
  const editor = await createEditor({ root, markdown: source });
  try {
    const before = serializeMarkdown(editor.view.state.doc);
    assert.equal(root.querySelectorAll('.provisional-section').length, 0, 'none without sections');
    const markers = sectionMarkers(source, inferred);
    editor.view.updateState(editor.view.state.reconfigure({
      plugins: [...editor.view.state.plugins, sectionMarkerPlugin(markers)] }));
    const badges = [...root.querySelectorAll('.provisional-section')];
    assert.deepEqual(badges.map((b) => [b.textContent, b.dataset.line]), [
      ['inferred · topic_shift_embedding', '0'], ['inferred · topic_shift_embedding', '4'],
      ['inferred · numbering', '8']]);
    const lines = source.split('\n');
    for (const b of badges) {
      assert.equal(b.getAttribute('contenteditable'), 'false');
      assert.equal(b.nextElementSibling?.textContent, lines[Number(b.dataset.line)]);
    }
    assert.equal(serializeMarkdown(editor.view.state.doc), before, 'markers do not rewrite the text');
  } finally {
    await editor.destroy();
    root.remove();
  }
});

test('server: --sections serves the report entry; without it, 404', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'demo-sections-'));
  try {
    mkdirSync(join(dir, 'converted', 'sub'), { recursive: true });
    const report = join(dir, 'converted', 'sub', 'note.md');
    writeFileSync(report, source);
    writeFileSync(join(dir, 'converted', 'note.md'), source);
    const file = join(dir, 'sections.json');
    writeFileSync(file, JSON.stringify({ schema: 1, documents: {
      'note.md': { status: 'none_found', sections: [] },
      'sub/note.md': { status: 'inferred', sections: inferred },
    } }));
    const url = (run) => new URL(`api/sections/${encodeURIComponent('note.md')}`, run.url);
    let run = await startServer({ report, sections: file, port: 0 });
    try {
      assert.equal(run.sections?.document, 'sub/note.md');
      const r = await fetch(url(run));
      assert.equal(r.status, 200);
      assert.deepEqual(await r.json(), inferred);
      assert.equal(readFileSync(report, 'utf8'), source);
    } finally { await run.close(); }
    run = await startServer({ report, port: 0 });
    try {
      assert.equal(run.sections, null);
      assert.equal((await fetch(url(run))).status, 404);
    } finally { await run.close(); }
    await assert.rejects(startServer({ sections: file, port: 0 }), /--sections needs --report/);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
