import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseMarkdown, serializeMarkdown, schema, UnsupportedNodeError } from '../src/index.js';

// toJSON() attrs use null-prototype objects; round-trip through JSON for plain deepEqual.
// NI-01: block nodes carry `id: null` after parse; drop it (and emptied attrs) so the literal
// expectations below stay about parse semantics, not the id attr.
const stripNullIds = (_k, v) => {
  if (v && typeof v === 'object' && !Array.isArray(v) && v.attrs && v.attrs.id === null) {
    const { id, ...rest } = v.attrs;
    const out = { ...v, attrs: rest };
    if (Object.keys(rest).length === 0) delete out.attrs;
    return out;
  }
  return v;
};
const json = (md) => JSON.parse(JSON.stringify(parseMarkdown(md).toJSON()), stripNullIds);
const blocks = (md) => json(md).content ?? [];
const first = (md) => blocks(md)[0];

test('doc + paragraph + text', () => {
  assert.deepEqual(json('hello'), {
    type: 'doc',
    content: [{ type: 'paragraph', content: [{ type: 'text', text: 'hello' }] }],
  });
});

test('returns a Node of the exported schema', () => {
  assert.equal(parseMarkdown('x').type.schema, schema);
});

test('empty input gives empty doc', () => {
  assert.deepEqual(json(''), { type: 'doc' });
});

test('ATX heading: level, setext false', () => {
  assert.deepEqual(first('## Title'), {
    type: 'heading', attrs: { level: 2, setext: false },
    content: [{ type: 'text', text: 'Title' }],
  });
});

test('setext heading: setext true', () => {
  assert.deepEqual(first('Title\n=====\n'), {
    type: 'heading', attrs: { level: 1, setext: true },
    content: [{ type: 'text', text: 'Title' }],
  });
  assert.equal(first('Sub\n---\n').attrs.level, 2);
  assert.equal(first('Sub\n---\n').attrs.setext, true);
});

test('blockquote', () => {
  assert.deepEqual(first('> quoted'), {
    type: 'blockquote',
    content: [{ type: 'paragraph', content: [{ type: 'text', text: 'quoted' }] }],
  });
});

test('bullet_list records marker; list_item', () => {
  for (const m of ['-', '*', '+']) {
    const list = first(`${m} a\n${m} b\n`);
    assert.equal(list.type, 'bullet_list');
    assert.equal(list.attrs.marker, m);
    assert.equal(list.content.length, 2);
    assert.deepEqual(list.content[0], {
      type: 'list_item', attrs: { checked: null },
      content: [{ type: 'paragraph', content: [{ type: 'text', text: 'a' }] }],
    });
  }
});

test('ordered_list records start', () => {
  const list = first('3. a\n4. b\n');
  assert.equal(list.type, 'ordered_list');
  assert.equal(list.attrs.start, 3);
  assert.equal(list.content[1].content[0].content[0].text, 'b');
});

test('task list item keeps checked', () => {
  const list = first('- [x] done\n- [ ] todo\n');
  assert.equal(list.content[0].attrs.checked, true);
  assert.equal(list.content[1].attrs.checked, false);
});

test('fenced code_block: lang and fence', () => {
  assert.deepEqual(first('```js\nlet a = 1;\n```\n'), {
    type: 'code_block', attrs: { lang: 'js', fence: '```' },
    content: [{ type: 'text', text: 'let a = 1;' }],
  });
  assert.equal(first('~~~~\nx\n~~~~\n').attrs.fence, '~~~~');
});

test('indented code_block has empty fence', () => {
  assert.deepEqual(first('    code\n'), {
    type: 'code_block', attrs: { lang: null, fence: '' },
    content: [{ type: 'text', text: 'code' }],
  });
});

test('code fence containing Markdown stays one literal code_block', () => {
  const src = '```md\n# not a heading\n\n- not a list\n*not em*\n```\n';
  const b = blocks(src);
  assert.equal(b.length, 1);
  assert.equal(b[0].type, 'code_block');
  assert.deepEqual(b[0].content, [
    { type: 'text', text: '# not a heading\n\n- not a list\n*not em*' },
  ]);
});

test('thematic_break', () => {
  assert.deepEqual(blocks('a\n\n***\n\nb')[1], { type: 'thematic_break', attrs: { marker: '***' } });
});

// FM-07: the source rule marker is recorded so serialization can reproduce it.
test('thematic_break records its source marker', () => {
  for (const m of ['---', '***', '___']) {
    assert.equal(blocks(`a\n\n${m}\n\nb`)[1].attrs.marker, m);
  }
});

test('html_block', () => {
  assert.deepEqual(first('<div>\nhi\n</div>\n'), {
    type: 'html_block', attrs: { value: '<div>\nhi\n</div>' },
  });
});

test('table / table_row / table_cell with align', () => {
  const t = first('| a | b | c |\n| :- | :-: | -- |\n| 1 | 2 | 3 |\n');
  assert.equal(t.type, 'table');
  assert.equal(t.content.length, 2);
  assert.equal(t.content[0].type, 'table_row');
  assert.deepEqual(t.content[0].content.map((c) => c.attrs.align), ['left', 'center', null]);
  assert.deepEqual(t.content[1].content[2], {
    type: 'table_cell', attrs: { align: null }, content: [{ type: 'text', text: '3' }],
  });
});

test('front_matter', () => {
  const b = blocks('---\ntitle: x\n---\n\nbody\n');
  assert.deepEqual(b[0], { type: 'front_matter', attrs: { value: 'title: x' } });
  assert.equal(b[1].type, 'paragraph');
});

test('footnote_definition and footnote_reference mark', () => {
  const b = blocks('See[^n1].\n\n[^n1]: The note.\n');
  assert.deepEqual(b[0].content[1], {
    type: 'text', text: 'n1', marks: [{ type: 'footnote_reference', attrs: { label: 'n1' } }],
  });
  assert.deepEqual(b[1], {
    type: 'footnote_definition', attrs: { label: 'n1' },
    content: [{ type: 'paragraph', content: [{ type: 'text', text: 'The note.' }] }],
  });
});

test('image', () => {
  assert.deepEqual(first('![alt text](a.png "T")').content[0], {
    type: 'image', attrs: { src: 'a.png', alt: 'alt text', title: 'T', ref: null },
  });
});

test('hard_break', () => {
  assert.deepEqual(first('a  \nb').content, [
    { type: 'text', text: 'a' }, { type: 'hard_break' }, { type: 'text', text: 'b' },
  ]);
  assert.equal(first('a\\\nb').content[1].type, 'hard_break');
});

test('em marker * vs _', () => {
  assert.deepEqual(first('*a*').content, [
    { type: 'text', text: 'a', marks: [{ type: 'em', attrs: { marker: '*' } }] },
  ]);
  assert.deepEqual(first('_a_').content, [
    { type: 'text', text: 'a', marks: [{ type: 'em', attrs: { marker: '_' } }] },
  ]);
});

test('strong marker ** vs __', () => {
  assert.deepEqual(first('**a**').content[0].marks, [{ type: 'strong', attrs: { marker: '*' } }]);
  assert.deepEqual(first('__a__').content[0].marks, [{ type: 'strong', attrs: { marker: '_' } }]);
});

test('nested marks combine', () => {
  const t = first('**a _b_**').content[1];
  assert.equal(t.text, 'b');
  assert.deepEqual(t.marks.map((m) => m.type).sort(), ['em', 'strong']);
});

test('code mark', () => {
  assert.deepEqual(first('`x*y*`').content, [
    { type: 'text', text: 'x*y*', marks: [{ type: 'code' }] },
  ]);
});

test('inline link: href, title, ref null', () => {
  assert.deepEqual(first('[go](http://x.test "T")').content, [
    { type: 'text', text: 'go', marks: [{ type: 'link', attrs: { href: 'http://x.test', title: 'T', ref: null } }] },
  ]);
});

test('reference link resolves href and keeps ref label', () => {
  const b = blocks('[go][Site]\n\n[site]: http://x.test "T"\n');
  assert.equal(b.length, 1, 'definition is absorbed into the link');
  assert.deepEqual(b[0].content[0].marks, [
    { type: 'link', attrs: { href: 'http://x.test', title: 'T', ref: 'Site' } },
  ]);
});

test('reference image resolves src and keeps ref', () => {
  const img = blocks('![a][pic]\n\n[pic]: p.png\n')[0].content[0];
  assert.deepEqual(img.attrs, { src: 'p.png', alt: 'a', title: null, ref: 'pic' });
});

test('reference without definition stays literal text', () => {
  // remark parses "[x][nope]" as text when no definition exists, so this stays text.
  assert.equal(first('[x][nope]').content[0].text, '[x][nope]');
});

test('unsupported mdast node throws UnsupportedNodeError naming the type', () => {
  assert.throws(() => parseMarkdown('~~gone~~'), (e) => {
    assert.ok(e instanceof UnsupportedNodeError);
    assert.ok(e instanceof Error);
    assert.equal(e.name, 'UnsupportedNodeError');
    assert.equal(e.nodeType, 'delete');
    assert.match(e.message, /delete/);
    return true;
  });
  assert.throws(() => parseMarkdown('a <b>x</b>'), (e) => e instanceof UnsupportedNodeError && e.nodeType === 'html');
});

test('schema declares every DM-01 node and mark', () => {
  const nodes = ['doc', 'paragraph', 'heading', 'blockquote', 'bullet_list', 'ordered_list',
    'list_item', 'code_block', 'thematic_break', 'html_block', 'table', 'table_row', 'table_cell',
    'front_matter', 'footnote_definition', 'image', 'hard_break', 'text'];
  const marks = ['em', 'strong', 'code', 'link', 'footnote_reference'];
  for (const n of nodes) assert.ok(schema.nodes[n], n);
  for (const m of marks) assert.ok(schema.marks[m], m);
});

test('TOML front matter throws UnsupportedNodeError naming TOML front matter', () => {
  assert.throws(() => parseMarkdown('+++\ntitle = "x"\n+++\n\nBody\n'),
    (e) => e instanceof UnsupportedNodeError && /TOML front matter/.test(e.message));
});

test('+++ not at document start still parses and round-trips', () => {
  for (const src of ['Body\n\n+++\n\nmore +++ here\n', '# Title\n\n+++\nx = 1\n+++\n']) {
    const doc = parseMarkdown(src);
    assert.equal(doc.type.name, 'doc');
    assert.deepEqual(parseMarkdown(serializeMarkdown(doc)).toJSON(), doc.toJSON());
  }
});
