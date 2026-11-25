#!/usr/bin/env node
// CO-04: round-trip check for ingested Markdown. Usage: node check-roundtrip.js FILE.md...
// Prints a JSON array, one {path, parses, roundtrip_idempotent, section_count[, error]} per arg.
// section_count = number of heading sections in docmodel's sectionTree (root excluded).
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { parseMarkdown, serializeMarkdown, sectionTree } from '../src/index.js';

function countSections(section) {
  return section.children.reduce((n, c) => n + 1 + countSections(c), 0);
}

/** @param {string} md */
export function checkFile(md) {
  const doc = parseMarkdown(md);
  const once = serializeMarkdown(doc);
  const twice = serializeMarkdown(parseMarkdown(once));
  return { parses: true, roundtrip_idempotent: once === twice, section_count: countSections(sectionTree(doc)) };
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const out = process.argv.slice(2).map((path) => {
    try {
      return { path, ...checkFile(readFileSync(path, 'utf8')) };
    } catch (e) {
      return { path, parses: false, roundtrip_idempotent: false, section_count: 0, error: String(e && e.message || e) };
    }
  });
  process.stdout.write(JSON.stringify(out) + '\n');
}
