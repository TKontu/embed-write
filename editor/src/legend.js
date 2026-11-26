// @ts-check
// LG-02: legend CSS read straight from the genre file, one rule per move in file order
// (invariant I3: the legend is fixed per genre and never computed). Colours are copied from
// legend.colors / legend.other verbatim (lowercased hex); nothing here derives, generates or
// defaults a colour. Unwired by design until AP-01 / LG-07 load the genre file in the app and link
// this stylesheet; createEditor does not install it.
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
 * Turn a parsed genre file's stored legend into deterministic CSS: one custom-property rule per
 * move in `genre.moves` order, then the neutral `other` rule. Validation mirrors service/genre.py
 * and every failure names the offending field.
 * @param {{ moves: Array<{ id: string }>, legend: { colors: Record<string, string>, other: string } }} genre
 * @returns {string}
 */
export function legendCss(genre) {
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
  const lines = ids.map((id) => {
    const where = `legend.colors.${id}`;
    if (!Object.prototype.hasOwnProperty.call(colors, id)) fail(where, 'move missing from legend');
    return `.signal[data-signal-kind="${attr(id)}"] { --signal-color: ${storedHex(colors[id], where)}; }`;
  });
  lines.push(`.signal[data-signal-kind="other"] { --signal-color: ${storedHex(legend.other, 'legend.other')}; }`);
  return `${lines.join('\n')}\n`;
}
