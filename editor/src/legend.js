// @ts-check
// LG-02: legend CSS read straight from the genre file, one rule per move in file order
// (invariant I3: the legend is fixed per genre and never computed). Colours are copied from
// legend.colors / legend.other verbatim (lowercased hex); nothing here derives, generates or
// defaults a colour. Production caller: editor/demo/app.js (DE-06); AP-01 wires it in the app.
// createEditor does not install it.
const HEX = /^#[0-9a-fA-F]{6}$/;

/**
 * @param {string} field
 * @param {string} why
 * @returns {never}
 */
const fail = (field, why) => { throw new Error(`${field}: ${why}`); };

/**
 * Read one stored colour; only a #rrggbb string passes.
 * @param {unknown} value
 * @param {string} field
 * @returns {string} the stored colour, lowercased
 */
function storedHex(value, field) {
  if (typeof value !== 'string' || !HEX.test(value)) fail(field, 'must be a colour hex "#rrggbb"');
  return value.toLowerCase();
}

/**
 * Escape a move id for a double-quoted CSS attribute-selector value.
 * @param {string} id
 * @returns {string}
 */
const attr = (id) => id.replace(/[\\"]/g, '\\$&');

/**
 * Validate a parsed genre file's moves and stored legend (mirrors service/genre.py; every failure
 * names the offending field) and return the moves with their stored colours in file order.
 * @param {any} genre
 * @returns {{ moves: any[], colors: string[], other: string }}
 */
function readLegend(genre) {
  if (genre === null || typeof genre !== 'object' || Array.isArray(genre)) fail('genre', 'must be an object');
  const moves = genre.moves;
  if (!Array.isArray(moves) || moves.length === 0) fail('moves', 'must be a non-empty list');
  const legend = genre.legend;
  if (legend === null || typeof legend !== 'object' || Array.isArray(legend)) fail('legend', 'must be an object');
  const colors = legend.colors;
  if (colors === null || typeof colors !== 'object' || Array.isArray(colors)) fail('legend.colors', 'must be an object');
  if (!('other' in legend)) fail('legend.other', 'required field missing');

  const ids = [];
  for (let i = 0; i < moves.length; i += 1) {
    const m = moves[i];
    const where = `moves[${i}]`;
    if (m === null || typeof m !== 'object') fail(where, 'must be an object');
    if (typeof m.id !== 'string' || !m.id.trim()) fail(`${where}.id`, 'must be a non-empty string');
    if (m.id === 'other') fail(`${where}.id`, '"other" is reserved for the neutral class');
    ids.push(m.id);
  }
  const known = new Set(ids);
  for (const key of Object.keys(colors)) {
    if (key.startsWith('_')) continue; // comment key: ignored by validation, like service/genre.py
    if (!known.has(key)) fail(`legend.colors.${key}`, 'legend entry for unknown move');
  }
  const hexes = ids.map((id) => {
    const where = `legend.colors.${id}`;
    if (!Object.prototype.hasOwnProperty.call(colors, id)) fail(where, 'move missing from legend');
    return storedHex(colors[id], where);
  });
  return { moves, colors: hexes, other: storedHex(legend.other, 'legend.other') };
}

/**
 * Turn a parsed genre file's stored legend into deterministic CSS: one custom-property rule per
 * move in `genre.moves` order, then the neutral `other` rule. Validation mirrors service/genre.py
 * and every failure names the offending field.
 * @param {{ moves: Array<{ id: string }>, legend: { colors: Record<string, string>, other: string } }} genre
 * @returns {string}
 */
export function legendCss(genre) {
  const { moves, colors, other } = readLegend(genre);
  const lines = moves.map((m, i) => `.signal[data-signal-kind="${attr(m.id)}"] { --signal-color: ${colors[i]}; }`);
  lines.push(`.signal[data-signal-kind="other"] { --signal-color: ${other}; }`);
  return `${lines.join('\n')}\n`;
}

/**
 * LG-07: the legend panel, one entry per move in `genre.moves` order (swatch in the stored colour,
 * name, definition), then the neutral `other` entry. All text goes through textContent; nothing is
 * parsed as HTML and no colour is derived. Same validation and errors as legendCss, plus
 * moves[i].name / moves[i].definition must be non-empty strings (service/genre.py).
 * Production caller: editor/demo/app.js (DE-06); AP-01/AP-03 and RE-10 wire it in the app.
 * @param {any} genre
 * @param {{ document: Document }} opts
 * @returns {HTMLElement}
 */
export function renderLegendPanel(genre, { document }) {
  const { moves, colors, other } = readLegend(genre);
  moves.forEach((m, i) => {
    for (const key of ['name', 'definition']) {
      if (typeof m[key] !== 'string' || !m[key].trim()) fail(`moves[${i}].${key}`, 'must be a non-empty string');
    }
  });
  const aside = document.createElement('aside');
  aside.className = 'legend-panel';
  aside.setAttribute('role', 'complementary');
  aside.setAttribute('aria-label', 'Legend');
  const list = document.createElement('ul');
  list.className = 'legend-list';
  /** @param {string} kind @param {string} color @param {string} name @param {string | null} definition */
  const entry = (kind, color, name, definition) => {
    const li = document.createElement('li');
    li.className = 'legend-entry';
    li.setAttribute('data-signal-kind', kind);
    const sw = document.createElement('span');
    sw.className = 'legend-swatch';
    sw.setAttribute('aria-hidden', 'true');
    sw.setAttribute('data-color', color);
    sw.style.backgroundColor = color;
    const nm = document.createElement('span');
    nm.className = 'legend-name';
    nm.textContent = name;
    li.append(sw, nm);
    if (definition !== null) {
      const def = document.createElement('span');
      def.className = 'legend-definition';
      def.textContent = definition;
      li.append(def);
    }
    list.append(li);
  };
  moves.forEach((m, i) => entry(m.id, colors[i], m.name, m.definition));
  entry('other', other, 'Other', null);
  aside.append(list);
  return aside;
}
