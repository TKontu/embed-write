// @ts-check
// Unwired by design: DM-03 and ED-01 consume parseMarkdown, serializeMarkdown and schema.
// openMarkdown (DM-05) is unwired by design; ED-01/ED-02 wire it.
export { parseMarkdown } from './parse.js';
export { serializeMarkdown } from './serialize.js';
export { schema } from './schema.js';
// ulid/assignIds (NI-01) unwired by design; NI-02/ED-01 wire them.
export { ulid, assignIds } from './ids.js';
export { UnsupportedNodeError } from './errors.js';
export { openMarkdown } from './open.js';
// sectionTree (HI-01) is unwired by design; HI-02/ED-01 wire it.
export { sectionTree } from './sections.js';
// blockLayer (HI-02) is unwired by design; HI-03/ED-01 wire it.
export { blockLayer } from './blocks.js';
// normalizeText/nodeHash/hashText (HS-01) are unwired by design; NI-02/HI-03/PM-02 wire them.
export { normalizeText, nodeHash, hashText } from './hash.js';
// dirtySet/dirtyRanges (HS-02) are unwired by design; HS-03/HS-04 and ED-01 wire them.
export { dirtySet, dirtyRanges } from './dirty.js';
// Sidecar helpers (NI-02) are unwired by design; NI-03/ED-01 wire them.
export { buildSidecar, serializeSidecar, parseSidecar, sidecarPath } from './sidecar.js';
// createCoalescer (HS-03) is unwired by design; ED-01 wires it, HS-04 tests it.
export { createCoalescer } from './coalesce.js';
// reattachIds (NI-03) is unwired by design; ED-01 wires document open.
export { reattachIds } from './reattach.js';
// idPlugin/fixIds (NI-04) are unwired by design; ED-01 wires the plugin into the editor.
export { idPlugin, fixIds } from './idplugin.js';
// admitResult/filterFresh (PM-02) are unwired by design; ED-01 and the overlay rows wire them.
export { admitResult, filterFresh } from './stale.js';
