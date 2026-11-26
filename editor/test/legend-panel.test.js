// LG-07: legend panel read from the genre file (I3: fixed per genre, never computed).
// Synthetic genre fixture (LLM-built): placeholder colours, not an expert palette (LG-01 is [H]).
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setupDom } from './dom.js';

setupDom();
const { renderLegendPanel, legendCss } = await import('../src/index.js');

/** @returns {any} */
const genre = () => ({
  genre: 'synthetic-fixture',
  version: 1,
  moves: [
    { id: 'thesis', name: 'Thesis', definition: 'States the claim.' },
    { id: 'evidence', name: 'Evidence', definition: 'Supports <b>the</b> claim & more.' },
  ],
  legend: { colors: { evidence: '#4D5E6F', thesis: '#1a2b3c' }, other: '#7A8B9C' },
});

const render = (g = genre()) => renderLegendPanel(g, { document });
const entries = (el) => [...el.querySelectorAll('.legend-entry')];

function errorOf(fn) {
  try { fn(); } catch (e) { return e; }
  assert.fail('expected a throw');
}

test('panel is a labelled complementary aside', () => {
  const el = render();
  assert.equal(el.tagName, 'ASIDE');
  assert.equal(el.className, 'legend-panel');
  assert.equal(el.getAttribute('role'), 'complementary');
  assert.equal(el.getAttribute('aria-label'), 'Legend');
});

test('(a) entries follow genre.moves order, then other', () => {
  const kinds = entries(render()).map((e) => e.getAttribute('data-signal-kind'));
  assert.deepEqual(kinds, ['thesis', 'evidence', 'other']);
});

test('(b) each swatch colour is the stored colour, nothing derived', () => {
  const g = genre();
  const got = entries(render(g)).map((e) => e.querySelector('.legend-swatch').getAttribute('data-color'));
  assert.deepEqual(got, ['#1a2b3c', '#4d5e6f', '#7a8b9c']);
  const styles = entries(render(g)).map((e) => e.querySelector('.legend-swatch').style.backgroundColor);
  assert.deepEqual(styles, ['rgb(26, 43, 60)', 'rgb(77, 94, 111)', 'rgb(122, 139, 156)']);
});

test('(c) name and definition are text; HTML in a definition is not parsed', () => {
  const [t, e, o] = entries(render());
  assert.equal(t.querySelector('.legend-name').textContent, 'Thesis');
  assert.equal(t.querySelector('.legend-definition').textContent, 'States the claim.');
  const def = e.querySelector('.legend-definition');
  assert.equal(def.textContent, 'Supports <b>the</b> claim & more.');
  assert.equal(def.querySelector('b'), null);
  assert.equal(def.childNodes.length, 1);
  assert.equal(o.querySelector('.legend-name').textContent, 'Other');
});

test('(d) invalid genre throws the same field-named error as legendCss', () => {
  const cases = [
    (g) => { g.legend.other = 'red'; },
    (g) => { delete g.legend.colors.thesis; },
    (g) => { g.legend.colors.ghost = '#000000'; },
    (g) => { g.moves[0].id = 'other'; },
    (g) => { g.moves = []; },
  ];
  for (const mutate of cases) {
    const g = genre(); mutate(g);
    const a = errorOf(() => legendCss(g)); const b = errorOf(() => render(g));
    assert.equal(b.constructor, Error);
    assert.equal(b.message, a.message);
  }
  const g = genre(); g.moves[1].definition = ' ';
  assert.equal(errorOf(() => render(g)).message, 'moves[1].definition: must be a non-empty string');
  const h = genre(); delete h.moves[0].name;
  assert.equal(errorOf(() => render(h)).message, 'moves[0].name: must be a non-empty string');
});

test('(e) two calls with one genre give identical markup', () => {
  const g = genre();
  assert.equal(render(g).outerHTML, render(g).outerHTML);
});
