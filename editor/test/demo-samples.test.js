// DE-01: synthetic demo samples round-trip byte for byte and their sidecars use the legend.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { parseMarkdown, serializeMarkdown } from 'docmodel';

const dir = fileURLToPath(new URL('../../examples/demo/', import.meta.url));
const samples = readdirSync(dir).filter((name) => name.endsWith('.md')).sort();
const legend = JSON.parse(readFileSync(join(dir, 'legend.json'), 'utf8'));

test('there are 2-3 named synthetic samples, each saying so on its first line', () => {
  assert.ok(samples.length >= 2 && samples.length <= 3, `expected 2-3 samples, got ${samples.length}`);
  for (const name of samples) {
    assert.match(name, /^synthetic-sample-\d+\.md$/);
    const first = readFileSync(join(dir, name), 'utf8').split('\n')[0].toLowerCase();
    assert.ok(first.includes('synthetic sample'), `${name} first line must say synthetic sample: ${first}`);
    assert.ok(first.includes('not real data'), `${name} first line must say not real data: ${first}`);
  }
});

for (const name of samples) {
  test(`docmodel round-trips ${name} byte for byte`, () => {
    const source = readFileSync(join(dir, name), 'utf8');
    assert.equal(serializeMarkdown(parseMarkdown(source)), source);
  });

  test(`${name} uses headings, a list, emphasis, a rule and a code block`, () => {
    const doc = parseMarkdown(readFileSync(join(dir, name), 'utf8'));
    let heading = false;
    let list = false;
    let rule = false;
    let code = false;
    let em = false;
    let strong = false;
    doc.descendants((node) => {
      if (node.type.name === 'heading') heading = true;
      if (node.type.name === 'bullet_list' || node.type.name === 'ordered_list') list = true;
      if (node.type.name === 'thematic_break') rule = true;
      if (node.type.name === 'code_block') code = true;
      for (const mark of node.marks) {
        if (mark.type.name === 'em') em = true;
        if (mark.type.name === 'strong') strong = true;
      }
    });
    assert.deepEqual({ heading, list, rule, code, em, strong },
      { heading: true, list: true, rule: true, code: true, em: true, strong: true });
  });

  test(`${name} sidecar labels in-range blocks with legend moves`, () => {
    const sidecar = JSON.parse(readFileSync(join(dir, name.replace(/\.md$/, '.moves.json')), 'utf8'));
    assert.ok(Array.isArray(sidecar) && sidecar.length > 0, 'sidecar must be a non-empty array');
    const doc = parseMarkdown(readFileSync(join(dir, name), 'utf8'));
    const topLevel = doc.childCount;
    const blocks = new Set();
    for (const entry of sidecar) {
      assert.ok(Number.isInteger(entry.block) && entry.block >= 0 && entry.block < topLevel,
        `block ${entry.block} out of range 0..${topLevel - 1}`);
      // RE-09: a block may carry one label per level (and per sentence).
      // RE-10: and one per overlay; only 'moves' (the default) entries name legend moves.
      const overlay = entry.overlay ?? 'moves';
      const key = `${overlay}/${entry.block}/${entry.level ?? 'paragraph'}/${entry.sentence ?? ''}`;
      assert.ok(!blocks.has(key), `duplicate block ${key}`);
      blocks.add(key);
      if (overlay === 'moves') {
        assert.ok(Object.hasOwn(legend.moves, entry.move), `move ${entry.move} missing from legend.json`);
      } else {
        assert.match(entry.kind, /^[a-z][a-z0-9-]*$/);
      }
    }
  });
}

test('legend.json is provisional and names every move with a label and colour', () => {
  assert.equal(legend.provisional, true);
  const moves = Object.entries(legend.moves ?? {});
  assert.ok(moves.length >= 3);
  for (const [move, value] of moves) {
    assert.match(move, /^[a-z][a-z0-9-]*$/);
    assert.equal(typeof value.label, 'string');
    assert.ok(value.label.length > 0);
    assert.match(value.colour, /^#[0-9a-fA-F]{6}$/);
  }
});
