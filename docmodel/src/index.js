// @ts-check
// Unwired by design: DM-03 and ED-01 consume parseMarkdown, serializeMarkdown and schema.
// openMarkdown (DM-05) is unwired by design; ED-01/ED-02 wire it.
export { parseMarkdown } from './parse.js';
export { serializeMarkdown } from './serialize.js';
export { schema } from './schema.js';
export { UnsupportedNodeError } from './errors.js';
export { openMarkdown } from './open.js';
// sectionTree (HI-01) is unwired by design; HI-02/ED-01 wire it.
export { sectionTree } from './sections.js';
// blockLayer (HI-02) is unwired by design; HI-03/ED-01 wire it.
export { blockLayer } from './blocks.js';
