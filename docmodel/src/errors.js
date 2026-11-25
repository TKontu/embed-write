// @ts-check
/** Thrown when the parser meets an mdast node it has no mapping for (never silently dropped). */
export class UnsupportedNodeError extends Error {
  /** @param {string} nodeType @param {{line?: number, column?: number}} [at] */
  constructor(nodeType, at) {
    const where = at && at.line ? ` at ${at.line}:${at.column}` : '';
    super(`Unsupported mdast node type "${nodeType}"${where}`);
    this.name = 'UnsupportedNodeError';
    this.nodeType = nodeType;
  }
}
