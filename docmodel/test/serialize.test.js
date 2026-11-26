import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseMarkdown, serializeMarkdown, schema } from '../src/index.js';

const plain = (doc) => JSON.parse(JSON.stringify(doc.toJSON()));
const rt = (src) => serializeMarkdown(parseMarkdown(src));

// (a) canonical sample per node and mark; (b) convention variants.
const SAMPLES = {
  'paragraph + text': 'hello world\n',
  'two paragraphs': 'one\n\ntwo\n',
  'soft line break kept': 'line one\nline two\n',
  'heading ATX': '## Title\n',
  'heading setext h1': 'Title\n=====\n',
  'heading setext h2': 'Sub\n---\n',
  blockquote: '> quoted\n>\n> more\n',
  'bullet -': '- a\n- b\n',
  'bullet *': '* a\n* b\n',
  'bullet +': '+ a\n+ b\n',
  'nested list': '- a\n  - b\n',
  'ordered_list start': '3. a\n4. b\n',
  'list_item checked': '- [x] done\n- [ ] todo\n',
  'code fence ```': '```js\nconst a = 1;\n```\n',
  'code fence ~~~': '~~~\nx\n~~~\n',
  'code indented': '    code line\n',
  thematic_break: 'a\n\n---\n\nb\n',
  html_block: '<div>\nhi\n</div>\n',
  'table + align': '| a | b | c | d |\n| --- | :-- | :-: | --: |\n| 1 | 2 | 3 | 4 |\n',
  front_matter: '---\ntitle: x\n---\n\nbody\n',
  footnote: 'Text[^1].\n\n[^1]: Note.\n',
  image: '![alt](a.png "T")\n',
  'image ref': '![alt][logo]\n\n[logo]: a.png\n',
  hard_break: 'a\\\nb\n',
  link: '[x](http://e.com)\n',
  'link title': '[x](http://e.com "T")\n',
  'em *': '*a*\n',
  'em _': '_a_\n',
  'strong **': '**a**\n',
  'strong __': '__a__\n',
  'nested marks': '*a **b** c*\n',
  code: 'use `c` here\n',
  'empty doc': '',
};
for (const [name, src] of Object.entries(SAMPLES)) {
  test(`round-trip: ${name}`, () => assert.equal(rt(src), src));
}

// FM-07: thematic breaks keep the marker the source used, including at the top of a document.
test('thematic break markers round-trip byte for byte', () => {
  for (const m of ['---', '***', '___']) {
    assert.equal(rt(`${m}\n`), `${m}\n`, `leading ${m}`);
    assert.equal(rt(`a\n\n${m}\n\nb\n`), `a\n\n${m}\n\nb\n`, `middle ${m}`);
  }
  assert.equal(rt('---\n\n***\n\n___\n'), '---\n\n***\n\n___\n');
});

// A leading `---` would reopen as YAML front matter if a later line closed it, so it falls back
// to `***`; documents from parseMarkdown never take this branch (such a source is front matter).
test('leading --- falls back to *** when a later line would close front matter', () => {
  const doc = schema.node('doc', null, [
    schema.node('thematic_break', { marker: '---' }),
    schema.node('paragraph', null, schema.text('body')),
    schema.node('thematic_break', { marker: '---' }),
  ]);
  const out = serializeMarkdown(doc);
  assert.ok(out.startsWith('***\n\nbody\n\n---\n'), out);
  assert.equal(parseMarkdown(out).firstChild.type.name, 'thematic_break');
});

test('(c) reference link keeps style and definition', () => {
  assert.equal(rt('[x][r]\n\n[r]: http://e.com\n'), '[x][r]\n\n[r]: http://e.com\n');
  assert.equal(rt('[x][r]\n\n[r]: http://e.com "T"\n'), '[x][r]\n\n[r]: http://e.com "T"\n');
});

test('(d) code block containing Markdown is literal', () => {
  const src = '```\n# not heading\n*x* [y](z)\n```\n';
  assert.equal(rt(src), src);
  // Inner fence forces a longer outer fence.
  const doc = schema.node('doc', null, [schema.node('code_block', { fence: '```' }, schema.text('```\nin\n```'))]);
  const back = parseMarkdown(serializeMarkdown(doc)).firstChild;
  assert.equal(back.type.name, 'code_block');
  assert.equal(back.textContent, '```\nin\n```');
});

test('(e) special characters are escaped and reparse identically', () => {
  const texts = ['*not em*', '_x_ and __y__', '[a](b)', '# not heading', '- not list', '+ x', '1. not ordered',
    '> not quote', 'a `b` c', 'back\\slash', '<span>', '~~del~~', '===', '![i](j)', '&amp; entity', 'x | y'];
  for (const t of texts) {
    const doc = schema.node('doc', null, [schema.node('paragraph', null, schema.text(t))]);
    assert.deepEqual(plain(parseMarkdown(serializeMarkdown(doc))), plain(doc), t);
  }
  const em = schema.node('doc', null, [schema.node('paragraph', null,
    schema.text('a*b', [schema.marks.em.create({ marker: '_' })]))]);
  assert.deepEqual(plain(parseMarkdown(serializeMarkdown(em))), plain(em));
  const code = schema.node('doc', null, [schema.node('paragraph', null, schema.text('a`b', [schema.marks.code.create()]))]);
  assert.deepEqual(plain(parseMarkdown(serializeMarkdown(code))), plain(code));
});

test('mixed document round-trips', () => {
  const src = '---\nk: v\n---\n\nTitle\n=====\n\nSome _em_ and __strong__ with [ref][r] and `code`.\n\n'
    + '* one\n* two\n  1. inner\n\n> quote with ![img](p.png)\n\n~~~py\nprint(1)\n~~~\n\n[r]: http://e.com\n';
  assert.equal(rt(src), src);
});

test('opts.wrapWidth rewraps paragraphs at spaces only', () => {
  const doc = parseMarkdown('aaa bbb ccc `d e` fff\n');
  assert.equal(serializeMarkdown(doc, { wrapWidth: 8 }), 'aaa bbb\nccc\n`d e`\nfff\n');
});
