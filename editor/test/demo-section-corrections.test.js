// CO-14 (c, D-015): the expert's section correction (kept, removed, added boundaries) is saved as a
// private whole-file JSON (line numbers, levels, method "expert", inferred false; no text) and
// replaces the inferred set on reload. Demo line numbers match Python str.splitlines().
// Synthetic, LLM-built fixture text only; temp dirs, never the real edit-log/.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setupDom } from './dom.js';

setupDom();
const { lineStarts, sectionMarkers, splitLines, checkSectionCorrection } = await import('../demo/sections.js');
const { startServer } = await import('../demo/server.js');

test('lines are numbered as Python str.splitlines() (\\f, \\r\\n, U+2028, trailing break)', () => {
  // Python: 'a\fb\r\nc\u2028d\re\n'.splitlines() == ['a', 'b', 'c', 'd', 'e']
  assert.deepEqual(splitLines('a\fb\r\nc\u2028d\re\n'), ['a', 'b', 'c', 'd', 'e']);
  assert.deepEqual(splitLines('x\n\ny'), ['x', '', 'y']);
  assert.deepEqual(splitLines(''), []);
  assert.deepEqual(splitLines('a\v\x1cb\x85c\u2029'), ['a', '', 'b', 'c']);
  assert.deepEqual(lineStarts('a\r\nb'), [0, 3]);
});

test('a form feed before a boundary does not shift the marker', () => {
  const md = 'First invented paragraph.\f\nSecond invented paragraph.\n\nThird invented paragraph.\n';
  // splitlines: ['First invented paragraph.', '', 'Second invented paragraph.', '', 'Third ...']
  const m = sectionMarkers(md, [{ start_line: 4, level: 1, inferred: true, method: 'formatting' }]);
  assert.deepEqual(m.map((x) => [x.line, x.block]), [[4, 1]]); // 'First...\f' and 'Second...' are one paragraph
  const crlf = 'One.\r\n\r\nTwo.\r\n\r\nThree.\r\n';
  assert.deepEqual(sectionMarkers(crlf, [{ start_line: 4, level: 1, inferred: true, method: 'numbering' }])
    .map((x) => x.block), [2]);
});

test('invalid correction entries are refused', () => {
  for (const body of [null, [], { sections: 'x' }, { sections: [{ start_line: -1, level: 1 }] },
    { sections: [{ start_line: 99, level: 1 }] }, { sections: [{ start_line: 1, level: 0 }] },
    { sections: [{ start_line: 1, level: 1 }, { start_line: 1, level: 2 }] },
    { sections: [{ start_line: 1, level: 1, title: 'leak' }] }]) {
    assert.throws(() => checkSectionCorrection(body, 10), undefined, JSON.stringify(body));
  }
  assert.deepEqual(checkSectionCorrection({ sections: [{ start_line: 4, level: 1 }, { start_line: 0, level: 2 }] }, 10),
    [{ start_line: 0, level: 2, method: 'expert', inferred: false },
      { start_line: 4, level: 1, method: 'expert', inferred: false }]);
});

const source = ['Invented quay notes open here.', '', 'Cranes rest at noon.', '', 'Bakers knead rye.', '',
  'Ovens warm the lane.', '', 'Invented closing paragraph.', ''].join('\n');
const inferred = [
  { start_line: 0, level: 1, title_line: null, inferred: true, method: 'topic_shift' },
  { start_line: 4, level: 1, title_line: null, inferred: true, method: 'topic_shift' },
];

test('server: a saved correction round-trips and replaces the inference', async () => {
  const dir = mkdtempSync(join(tmpdir(), 'demo-seccorr-'));
  const corrDir = join(dir, 'edit-log', 'section-corrections');
  try {
    mkdirSync(join(dir, 'converted', 'sub'), { recursive: true });
    const report = join(dir, 'converted', 'sub', 'note.md');
    writeFileSync(report, source);
    const file = join(dir, 'sections.json');
    writeFileSync(file, JSON.stringify({ schema: 1, documents: { 'sub/note.md': { status: 'inferred', sections: inferred } } }));
    const run = await startServer({ report, sections: file, port: 0, sectionCorrectionsDir: corrDir });
    const api = (p) => new URL(`api/${p}/${encodeURIComponent('note.md')}`, run.url);
    const put = (body) => fetch(api('section-corrections'), { method: 'PUT', body: typeof body === 'string' ? body : JSON.stringify(body) });
    try {
      assert.deepEqual(await (await fetch(api('sections'))).json(), inferred);
      // keep line 0, remove line 4, add line 8
      const ok = await put({ sections: [{ start_line: 0, level: 1 }, { start_line: 8, level: 2 }] });
      assert.equal(ok.status, 200);
      assert.deepEqual(await ok.json(), { saved: 'note.md', sections: 2 });
      const saved = JSON.parse(readFileSync(join(corrDir, 'sub', 'note.md.json'), 'utf8'));
      const expected = [{ start_line: 0, level: 1, method: 'expert', inferred: false },
        { start_line: 8, level: 2, method: 'expert', inferred: false }];
      assert.deepEqual(saved, { schema: 1, document: 'sub/note.md', sections: expected });
      assert.ok(!readFileSync(join(corrDir, 'sub', 'note.md.json'), 'utf8').includes('Invented'), 'no text stored');
      const reloaded = await (await fetch(api('sections'))).json();
      assert.deepEqual(reloaded, expected);
      assert.deepEqual(sectionMarkers(source, reloaded).map((m) => [m.line, m.method]), [[0, 'expert'], [8, 'expert']]);
      // invalid payloads: 4xx, stored file unchanged
      for (const bad of ['not json', { sections: [{ start_line: 50, level: 1 }] }, { sections: [{ start_line: 2 }] }]) {
        const r = await put(bad);
        assert.ok(r.status >= 400 && r.status < 500, `status ${r.status}`);
      }
      assert.deepEqual(JSON.parse(readFileSync(join(corrDir, 'sub', 'note.md.json'), 'utf8')).sections, expected);
      assert.equal((await fetch(api('section-corrections'))).status, 405);
      assert.equal(readFileSync(report, 'utf8'), source, 'report text unchanged');
    } finally { await run.close(); }
    // a report not in the sections file cannot be corrected
    const other = join(dir, 'converted', 'other.md');
    writeFileSync(other, source);
    const run2 = await startServer({ report: other, sections: file, port: 0, sectionCorrectionsDir: corrDir });
    try {
      const r = await fetch(new URL('api/section-corrections/other.md', run2.url), { method: 'PUT', body: '{"sections":[]}' });
      assert.equal(r.status, 409);
      assert.ok(!existsSync(join(corrDir, 'other.md.json')));
    } finally { await run2.close(); }
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});
