#!/usr/bin/env node
// @ts-check
// DE-02/DE-03/DE-05: localhost-only demo server.
// - Serves the demo page, the editor modules and existing node_modules to the browser offline.
// - Saves Markdown through atomicWrite and never outside the configured sample folder.
// - Takes the sample folder from `--dir` or DEMO_DIR, or one report file from `--report`
//   (optionally `--labels`): the one-step swap for a real report (D-011).
// - CO-14 (D-015): with `--report`, `--sections <sections.json>` (intake output) serves that
//   document's inferred sections; the page shows them as provisional markers (demo/sections.js).
// No new dependency is used: the import map is generated from the installed module graph.
import { createServer } from 'node:http';
import { mkdir, realpath, readFile, readdir, stat } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { basename, dirname, extname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { atomicWrite } from '../src/autosave.js';
import { checkCorrections } from '../src/corrections.js';
import { checkSectionCorrection, splitLines } from './sections.js';

const HERE = dirname(fileURLToPath(import.meta.url));
export const EDITOR_DIR = resolve(HERE, '..');
export const REPO_DIR = resolve(EDITOR_DIR, '..');
export const DOCMODEL_DIR = join(REPO_DIR, 'docmodel');
export const DEFAULT_DIR = join(REPO_DIR, 'examples', 'demo');
const MAX_BODY = 5 * 1024 * 1024;
/** IN-05: expert corrections (private, gitignored `edit-log/`), never under examples/. */
export const DEFAULT_CORRECTIONS_DIR = join(REPO_DIR, 'edit-log', 'demo-corrections');
/** CO-14 (c): expert section corrections (private, gitignored), read by experiments/intake.py. */
export const DEFAULT_SECTION_CORRECTIONS_DIR = join(REPO_DIR, 'edit-log', 'section-corrections');

/**
 * The correction file of a sections.json document key (relative POSIX path under CONVERTED):
 * DIR/<key>.json. Python's intake reads the same path.
 * @param {string} dir @param {string} document
 */
export function sectionCorrectionFile(dir, document) {
  const parts = document.split('/');
  if (!document || document.startsWith('/') || parts.some((p) => p === '' || p === '.' || p === '..' || p.includes('\\'))) {
    throw Object.assign(new Error(`bad document key: ${document}`), { status: 400 });
  }
  return join(dir, ...parts) + '.json';
}

/**
 * The document's saved expert correction, or null when none is stored.
 * @param {string} dir @param {string} document
 * @returns {Promise<any[] | null>}
 */
export async function readSectionCorrection(dir, document) {
  const file = sectionCorrectionFile(dir, document);
  if (!existsSync(file)) return null;
  const data = JSON.parse(await readFile(file, 'utf8'));
  if (!data || data.schema !== 1 || data.document !== document || !Array.isArray(data.sections)) {
    throw new Error(`not a section correction for ${document}: ${file}`);
  }
  return data.sections;
}

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.md': 'text/markdown; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
};

/** @param {string} name @returns {string} */
export function sidecarName(name) {
  return name.replace(/\.md$/, '') + '.moves.json';
}

/** A single safe file name in the sample folder. @param {unknown} name @returns {string} */
export function checkSampleName(name) {
  if (typeof name !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9._-]*\.md$/.test(name)) {
    throw Object.assign(new Error(`invalid sample name: ${name}`), { status: 400 });
  }
  return name;
}

/** @param {string} dir @returns {Promise<string[]>} */
export async function listSamples(dir) {
  const names = await readdir(dir);
  return names.filter((name) => name.endsWith('.md')).sort();
}

/** @param {string} dir @param {string} name @returns {Promise<string>} */
export async function readSampleText(dir, name) {
  checkSampleName(name);
  return readFile(join(dir, name), 'utf8');
}

/** @param {string} dir @param {string} name @param {string} text */
export async function writeSampleText(dir, name, text) {
  checkSampleName(name);
  if (typeof text !== 'string') throw Object.assign(new Error('body must be text'), { status: 400 });
  await atomicWrite(join(dir, name), text);
}

/**
 * Single-report mode: exactly one Markdown file, addressed by its own base name (any characters).
 * Labels come from `labels`, else `<report>.moves.json` beside it, else none.
 * @param {string} reportPath @param {string} [labelsPath]
 * @returns {Promise<{ file: string, name: string, labels: string | null }>}
 */
export async function resolveReport(reportPath, labelsPath) {
  const file = resolve(reportPath);
  if (!file.endsWith('.md')) throw new Error(`report must be a .md file: ${file}`);
  if (!(await stat(file)).isFile()) throw new Error(`report is not a file: ${file}`);
  let labels = null;
  if (labelsPath !== undefined) {
    labels = resolve(labelsPath);
    if (!(await stat(labels)).isFile()) throw new Error(`labels is not a file: ${labels}`);
  } else {
    const beside = join(dirname(file), sidecarName(basename(file)));
    if (existsSync(beside)) labels = beside;
  }
  return { file, name: basename(file), labels };
}

/** @param {{ name: string }} report @param {unknown} name */
function checkReportName(report, name) {
  if (name !== report.name) {
    throw Object.assign(new Error(`only ${report.name} is served in single-report mode`), { status: 404 });
  }
}

/**
 * CO-14: the report's entry in an intake sections.json ({schema: 1, documents: {rel: {status,
 * sections}}}). The entry is the key the report path ends with (longest wins); none -> [].
 * @param {string} sectionsPath @param {string} reportFile
 * @returns {Promise<{ file: string, document: string | null, sections: any[] }>}
 */
export async function resolveSections(sectionsPath, reportFile) {
  const file = resolve(sectionsPath);
  const data = JSON.parse(await readFile(file, 'utf8'));
  if (!data || data.schema !== 1 || typeof data.documents !== 'object' || !data.documents) {
    throw new Error(`not an intake sections.json (schema 1): ${file}`);
  }
  const report = reportFile.split(sep).join('/');
  const keys = Object.keys(data.documents)
    .filter((k) => report === k || report.endsWith('/' + k))
    .sort((a, b) => b.length - a.length);
  const document = keys[0] ?? null;
  const entry = document ? data.documents[document] : null;
  const sections = entry && Array.isArray(entry.sections) ? entry.sections.filter((s) => s && s.inferred === true) : [];
  return { file, document, sections };
}

export const SYNTHETIC_LEGEND = 'Provisional labels: synthetic';
export const REPORT_LEGEND = 'Provisional labels: unreviewed placeholders';

/** @param {string} root @param {string} rel @returns {string} */
function safeJoin(root, rel) {
  const clean = decodeURIComponent(rel);
  if (clean.split('/').some((part) => part === '..')) {
    throw Object.assign(new Error('path traversal refused'), { status: 400 });
  }
  const full = resolve(root, clean);
  if (full !== root && !full.startsWith(root + sep)) {
    throw Object.assign(new Error('path outside the allowed folder refused'), { status: 400 });
  }
  return full;
}

/** @param {string} nmDir @returns {Promise<{ logical: string, real: string }[]>} */
async function packageEntries(nmDir) {
  /** @type {{ logical: string, real: string }[]} */
  const out = [];
  for (const entry of await readdir(nmDir, { withFileTypes: true })) {
    if (entry.name.startsWith('.')) continue;
    if (entry.name.startsWith('@')) {
      for (const sub of await readdir(join(nmDir, entry.name))) {
        const logical = `${entry.name}/${sub}`;
        try {
          out.push({ logical, real: await realpath(join(nmDir, logical)) });
        } catch { /* dangling link */ }
      }
    } else {
      try {
        out.push({ logical: entry.name, real: await realpath(join(nmDir, entry.name)) });
      } catch { /* dangling link */ }
    }
  }
  return out;
}

/**
 * Map an absolute module file to a URL the server can serve. Package files may resolve through
 * symlinks, so match against the real path of each installed package entry.
 * @param {string} file
 * @param {{ logical: string, real: string }[]} packages
 * @param {string} editorReal
 * @param {string} docmodelReal
 * @returns {string | null}
 */
function fileToUrl(file, packages, editorReal, docmodelReal) {
  for (const pkg of packages) {
    if (file === pkg.real || file.startsWith(pkg.real + sep)) {
      return '/@nm/e/' + pkg.logical + '/' + relative(pkg.real, file).split(sep).join('/');
    }
  }
  if (file === docmodelReal || file.startsWith(docmodelReal + sep)) {
    return '/@docmodel/' + relative(docmodelReal, file).split(sep).join('/');
  }
  if (file === editorReal || file.startsWith(editorReal + sep)) {
    return '/@app/' + relative(editorReal, file).split(sep).join('/');
  }
  return null;
}

const SPEC_RE = /\b(?:import|export)\s+(?:[^'"]*?\bfrom\s*)?['"]([^'"]+)['"]|\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)/g;
const EMPTY_URL = '/@empty.js';

/** @param {string} source @returns {string[]} */
function specifiers(source) {
  // Drop comments first: JSDoc `import('mdast')` type references are not real browser imports.
  const clean = source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
  /** @type {string[]} */
  const out = [];
  for (const match of clean.matchAll(SPEC_RE)) out.push(match[1] ?? match[2]);
  return out;
}

/** @param {string} spec @returns {{ name: string, subpath: string }} */
function parseSpecifier(spec) {
  const parts = spec.split('/');
  const name = spec.startsWith('@') ? parts.slice(0, 2).join('/') : parts[0];
  const rest = parts.slice(spec.startsWith('@') ? 2 : 1);
  return { name, subpath: '.' + (rest.length ? '/' + rest.join('/') : '') };
}

/** @param {any} entry @returns {string | null} */
function resolveConditions(entry) {
  if (typeof entry === 'string') return entry;
  if (Array.isArray(entry)) {
    for (const item of entry) {
      const result = resolveConditions(item);
      if (result) return result;
    }
    return null;
  }
  if (!entry || typeof entry !== 'object') return null;
  // Browser first: never take Node's `node` condition for a page module.
  for (const condition of ['browser', 'import', 'default', 'module']) {
    if (Object.hasOwn(entry, condition)) {
      const result = resolveConditions(entry[condition]);
      if (result) return result;
    }
  }
  return null;
}

/** @param {Record<string, any>} map @param {string} key @returns {string | null} */
function resolveMap(map, key) {
  if (Object.hasOwn(map, key)) return resolveConditions(map[key]);
  for (const pattern of Object.keys(map)) {
    if (!pattern.includes('*')) continue;
    const [prefix, suffix] = pattern.split('*');
    if (!key.startsWith(prefix) || !key.endsWith(suffix)) continue;
    const replacement = key.slice(prefix.length, key.length - suffix.length);
    const target = resolveConditions(map[pattern]);
    if (target) return target.replace(/\*/g, replacement);
  }
  return null;
}

/** @param {any} exportsField @param {string} subpath @returns {string | null} */
function resolveExportsTarget(exportsField, subpath) {
  if (exportsField === undefined || exportsField === null) return null;
  if (typeof exportsField === 'string' || Array.isArray(exportsField)) {
    return subpath === '.' ? resolveConditions(exportsField) : null;
  }
  if (typeof exportsField !== 'object') return null;
  const keys = Object.keys(exportsField);
  if (!keys.some((key) => key.startsWith('.'))) {
    return subpath === '.' ? resolveConditions(exportsField) : null;
  }
  return resolveMap(exportsField, subpath);
}

/** Nearest package.json above an installed module (for `#subpath` imports). @param {string} file */
async function nearestPackage(file) {
  let dir = dirname(file);
  while (true) {
    const candidate = join(dir, 'package.json');
    if (existsSync(candidate)) {
      return { dir, pkg: JSON.parse(await readFile(candidate, 'utf8')) };
    }
    const up = dirname(dir);
    if (up === dir) throw new Error(`no package.json above ${file}`);
    dir = up;
  }
}

/** First existing file among a candidate path and its usual extensions. @param {string} candidate */
function resolveExistingFile(candidate) {
  const candidates = [candidate, `${candidate}.js`, `${candidate}.mjs`, join(candidate, 'index.js')];
  for (const file of candidates) if (existsSync(file)) return file;
  return candidate;
}

/**
 * Resolve a bare specifier the way a browser would: `exports` with browser/import/default
 * conditions first, then the legacy `browser` field, then module/main. Node's resolver cannot be
 * used here because it selects `node` conditions (e.g. @noble/hashes/crypto -> cryptoNode.js).
 * `#subpath` imports use the importing package's `imports` map with the same conditions.
 * @param {string} spec
 * @param {Map<string, string>} packageByName
 * @param {string} importerFile
 * @returns {Promise<string>}
 */
async function resolveBrowserSpecifier(spec, packageByName, importerFile) {
  if (spec === 'docmodel') return join(await realpath(DOCMODEL_DIR), 'src', 'index.js');
  if (spec.startsWith('#')) {
    const { dir, pkg } = await nearestPackage(importerFile);
    const target = pkg.imports ? resolveMap(pkg.imports, spec) : null;
    if (!target) throw new Error(`package ${dir} has no imports mapping for ${spec}`);
    return target.startsWith('.')
      ? resolveExistingFile(join(dir, target))
      : resolveBrowserSpecifier(target, packageByName, importerFile);
  }
  const { name, subpath } = parseSpecifier(spec);
  const pkgDir = packageByName.get(name);
  if (!pkgDir) throw new Error(`package ${name} (needed by ${spec}) is not installed`);
  const pkg = JSON.parse(await readFile(join(pkgDir, 'package.json'), 'utf8'));
  // Modern packages describe the browser build with an `exports` condition; legacy packages use
  // the `browser` field. Prefer `exports` (browser/import/default) so an ESM file wins over a
  // legacy CJS redirect such as @noble/hashes `./crypto` -> `./crypto.js`.
  const fromExports = resolveExportsTarget(pkg.exports, subpath);
  if (fromExports) return resolveExistingFile(join(pkgDir, fromExports));
  const browser = pkg.browser;
  if (browser && typeof browser === 'object') {
    for (const key of [spec, subpath]) {
      if (!Object.hasOwn(browser, key)) continue;
      const target = browser[key];
      if (target === false) return EMPTY_URL;
      if (typeof target === 'string') {
        return target.startsWith('.')
          ? resolveExistingFile(join(pkgDir, target))
          : resolveBrowserSpecifier(target, packageByName, importerFile);
      }
    }
  }
  if (typeof browser === 'string' && subpath === '.') return resolveExistingFile(join(pkgDir, browser));
  if (subpath !== '.') return resolveExistingFile(join(pkgDir, subpath));
  return resolveExistingFile(join(pkgDir, pkg.module ?? pkg.main ?? 'index.js'));
}

let importMapCache = null;

/**
 * Walk the modules reachable from the demo page and build a browser import map from the existing
 * node_modules. `docmodel` is pinned to this checkout's source, not a stale installed copy.
 * @returns {Promise<{ imports: Record<string, string> }>}
 */
export async function buildImportMap() {
  if (importMapCache) return importMapCache;
  const editorReal = await realpath(EDITOR_DIR);
  const docmodelReal = await realpath(DOCMODEL_DIR);
  const packages = await packageEntries(join(EDITOR_DIR, 'node_modules'));
  packages.sort((a, b) => b.real.length - a.real.length);
  const packageByName = new Map(packages.map((pkg) => [pkg.logical, pkg.real]));

  /** @type {Map<string, string>} */
  const imports = new Map();
  const seen = new Set();
  /** @type {string[]} */
  const queue = [join(EDITOR_DIR, 'demo', 'app.js'), join(EDITOR_DIR, 'src', 'index.js')];
  while (queue.length) {
    const file = /** @type {string} */ (queue.pop());
    if (seen.has(file)) continue;
    seen.add(file);
    if (!/\.(m?js)$/.test(file)) continue;
    const source = await readFile(file, 'utf8');
    for (const spec of specifiers(source)) {
      if (spec.startsWith('node:') || spec.startsWith('http:') || spec.startsWith('https:') || spec.startsWith('data:')) {
        throw new Error(`module ${file} imports ${spec}, which a browser cannot load`);
      }
      if (spec.startsWith('.') || spec.startsWith('/')) {
        queue.push(fileURLToPath(new URL(spec, pathToFileURL(file))));
        continue;
      }
      let resolved;
      try {
        resolved = await resolveBrowserSpecifier(spec, packageByName, file);
      } catch (err) {
        throw new Error(`cannot resolve browser import ${spec} from ${file}: ${err instanceof Error ? err.message : err}`);
      }
      if (resolved === EMPTY_URL) {
        imports.set(spec, EMPTY_URL);
        continue;
      }
      const url = fileToUrl(resolved, packages, editorReal, docmodelReal);
      if (!url) throw new Error(`resolved ${spec} to ${resolved}, which is outside the served folders`);
      const prior = imports.get(spec);
      if (prior && prior !== url) throw new Error(`import ${spec} resolves to two files: ${prior} and ${url}`);
      imports.set(spec, url);
      if (process.env.DEMO_DEBUG_IMPORT) console.error(`import ${spec} <- ${file} => ${url}`);
      queue.push(resolved);
    }
  }
  importMapCache = { imports: Object.fromEntries([...imports].sort(([a], [b]) => a.localeCompare(b))) };
  return importMapCache;
}

/**
 * A single-file CommonJS module with no requires cannot be loaded by a browser. Wrap it in a
 * module scope and export its default. This is deliberately narrow: anything with require() or
 * Node globals is left alone so a broken load is visible rather than silently wrong.
 * @param {string} file @param {string} source @returns {Promise<string | null>}
 */
async function wrapCommonJs(file, source) {
  if (!/\.(?:c?js|mjs)$/.test(file)) return null;
  if (!/\bmodule\.exports\b|\bexports\.[A-Za-z_$]/.test(source)) return null;
  if (/\brequire\s*\(|^\s*(?:import|export)\b/m.test(source)) return null;
  if (/\b__dirname\b|\b__filename\b|\bprocess\.|\bBuffer\./.test(source)) return null;
  const { pkg } = await nearestPackage(file);
  if (pkg.type === 'module') return null;
  return `const module = { exports: {} }; const exports = module.exports;\n${source}\n;export default module.exports;\n`;
}

/** @param {import('node:http').IncomingMessage} req @returns {Promise<string>} */
function readBody(req) {
  return new Promise((resolveBody, reject) => {
    /** @type {Buffer[]} */
    const chunks = [];
    let size = 0;
    req.on('data', (chunk) => {
      size += chunk.length;
      if (size > MAX_BODY) {
        reject(Object.assign(new Error('body too large'), { status: 413 }));
        req.destroy();
        return;
      }
      chunks.push(chunk);
    });
    req.on('end', () => resolveBody(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}

/** @param {import('node:http').ServerResponse} res @param {number} status @param {string} type @param {string|Buffer} body */
function send(res, status, type, body) {
  res.writeHead(status, { 'content-type': type, 'cache-control': 'no-store' });
  res.end(body);
}

/** @param {import('node:http').ServerResponse} res @param {number} status @param {string} message */
function sendError(res, status, message) {
  send(res, status, 'application/json; charset=utf-8', JSON.stringify({ error: message }));
}

/**
 * DNS-rebinding guard: Host must be a loopback name at the listening port, and a state-changing
 * request carrying Origin must come from one of those same origins. Absent Origin is allowed
 * (same-origin fetch PUTs and non-browser clients may omit it).
 * @param {import('node:http').IncomingMessage} req @param {number} port @returns {string | null}
 */
export function refusalReason(req, port) {
  const allowed = [`127.0.0.1:${port}`, `localhost:${port}`, `[::1]:${port}`];
  const host = (req.headers.host ?? '').toLowerCase();
  if (!allowed.includes(host)) return 'forbidden host';
  const origin = req.headers.origin;
  if (req.method !== 'GET' && req.method !== 'HEAD' && origin !== undefined) {
    if (!allowed.some((h) => origin.toLowerCase() === `http://${h}`)) return 'forbidden origin';
  }
  return null;
}

/**
 * @param {import('node:http').IncomingMessage} req
 * @param {import('node:http').ServerResponse} res
 * @param {{ dir: string, correctionsDir: string, sectionCorrectionsDir: string, genreFallback?: string | null, report: { file: string, name: string, labels: string | null } | null, sections?: { file: string, document: string | null, sections: any[] } | null, importMap: { imports: Record<string, string> } }} ctx
 */
/**
 * The genre file: the sample folder's own genre.json, else the fallback (the demo's by default;
 * `startServer({ genreFallback: null })` disables it). Null when neither exists.
 * @param {{ dir: string, genreFallback?: string | null }} ctx
 * @returns {string | null}
 */
function genrePath(ctx) {
  const own = join(ctx.dir, 'genre.json');
  if (existsSync(own)) return own;
  const fallback = ctx.genreFallback;
  return fallback && existsSync(fallback) ? fallback : null;
}

async function handle(req, res, ctx) {
  const url = new URL(req.url ?? '/', 'http://127.0.0.1');
  const pathname = url.pathname;

  if (pathname === '/' || pathname === '/index.html') {
    const html = await readFile(join(EDITOR_DIR, 'demo', 'index.html'), 'utf8');
    const map = JSON.stringify(ctx.importMap).replace(/</g, '\\u003c');
    const page = ctx.report || ctx.dir !== DEFAULT_DIR ? html.replace(SYNTHETIC_LEGEND, REPORT_LEGEND) : html;
    return send(res, 200, MIME['.html'], page.replace('<!--IMPORTMAP-->', `<script type="importmap">${map}</script>`));
  }
  if (pathname === '/favicon.ico') return send(res, 204, MIME['.ico'], '');
  if (pathname === EMPTY_URL) return send(res, 200, MIME['.js'], 'export {};\n');

  if (ctx.report && pathname === '/api/samples') {
    return send(res, 200, MIME['.json'], JSON.stringify({ mode: 'report', samples: [ctx.report.name] }));
  }
  if (ctx.report && pathname.startsWith('/api/sample/')) {
    const name = decodeURIComponent(pathname.slice('/api/sample/'.length));
    checkReportName(ctx.report, name);
    if (req.method === 'GET') return send(res, 200, MIME['.md'], await readFile(ctx.report.file, 'utf8'));
    if (req.method === 'PUT') {
      const text = await readBody(req);
      await atomicWrite(ctx.report.file, text);
      return send(res, 200, MIME['.json'], JSON.stringify({ saved: name, bytes: Buffer.byteLength(text) }));
    }
    return sendError(res, 405, 'method not allowed');
  }
  if (ctx.report && pathname.startsWith('/api/moves/')) {
    const name = decodeURIComponent(pathname.slice('/api/moves/'.length));
    checkReportName(ctx.report, name);
    if (!ctx.report.labels) return sendError(res, 404, `no labels for ${name}`);
    return send(res, 200, MIME['.json'], await readFile(ctx.report.labels, 'utf8'));
  }
  if (ctx.report && pathname.startsWith('/api/sections/')) {
    const name = decodeURIComponent(pathname.slice('/api/sections/'.length));
    checkReportName(ctx.report, name);
    if (!ctx.sections) return sendError(res, 404, `no sections for ${name}`);
    // CO-14 (c): a saved expert correction replaces the inferred set.
    const corrected = ctx.sections.document
      ? await readSectionCorrection(ctx.sectionCorrectionsDir, ctx.sections.document) : null;
    return send(res, 200, MIME['.json'], JSON.stringify(corrected ?? ctx.sections.sections));
  }
  if (ctx.report && pathname.startsWith('/api/section-corrections/')) {
    const name = decodeURIComponent(pathname.slice('/api/section-corrections/'.length));
    checkReportName(ctx.report, name);
    if (!ctx.sections) return sendError(res, 404, `no sections for ${name}`);
    if (!ctx.sections.document) return sendError(res, 409, `${name} is not in the sections file`);
    if (req.method !== 'PUT') return sendError(res, 405, 'method not allowed');
    let body;
    try { body = JSON.parse(await readBody(req)); } catch { return sendError(res, 400, 'body must be JSON'); }
    let sections;
    try {
      sections = checkSectionCorrection(body, splitLines(await readFile(ctx.report.file, 'utf8')).length);
    } catch (err) {
      return sendError(res, 400, /** @type {Error} */ (err).message);
    }
    const file = sectionCorrectionFile(ctx.sectionCorrectionsDir, ctx.sections.document);
    const text = JSON.stringify({ schema: 1, document: ctx.sections.document, sections }, null, 2) + '\n';
    await mkdir(dirname(file), { recursive: true });
    await atomicWrite(file, text);
    return send(res, 200, MIME['.json'], JSON.stringify({ saved: name, sections: sections.length }));
  }
  if (pathname === '/api/samples') {
    return send(res, 200, MIME['.json'], JSON.stringify({ dir: ctx.dir, samples: await listSamples(ctx.dir) }));
  }
  if (pathname === '/api/legend') {
    const own = join(ctx.dir, 'legend.json');
    const fallback = join(DEFAULT_DIR, 'legend.json');
    const file = existsSync(own) ? own : (existsSync(fallback) ? fallback : null);
    if (!file) return sendError(res, 404, 'legend.json not found');
    return send(res, 200, MIME['.json'], await readFile(file, 'utf8'));
  }
  if (pathname === '/api/genre') {
    // DE-06: the genre file (moves + stored legend, I3); same folder/fallback lookup as legend.json.
    const file = genrePath(ctx);
    if (!file) return sendError(res, 404, 'genre.json not found');
    return send(res, 200, MIME['.json'], await readFile(file, 'utf8'));
  }
  if (pathname.startsWith('/api/sample/')) {
    const name = decodeURIComponent(pathname.slice('/api/sample/'.length));
    if (req.method === 'GET') {
      try {
        return send(res, 200, MIME['.md'], await readSampleText(ctx.dir, name));
      } catch (err) {
        if (/** @type {any} */ (err).code === 'ENOENT') return sendError(res, 404, `${name} not found`);
        throw err;
      }
    }
    if (req.method === 'PUT') {
      const text = await readBody(req);
      await writeSampleText(ctx.dir, name, text);
      return send(res, 200, MIME['.json'], JSON.stringify({ saved: name, bytes: Buffer.byteLength(text) }));
    }
    return sendError(res, 405, 'method not allowed');
  }
  if (pathname.startsWith('/api/moves/')) {
    const name = decodeURIComponent(pathname.slice('/api/moves/'.length));
    checkSampleName(name);
    const file = join(ctx.dir, sidecarName(name));
    if (!existsSync(file)) return sendError(res, 404, `${sidecarName(name)} not found`);
    return send(res, 200, MIME['.json'], await readFile(file, 'utf8'));
  }

  if (!ctx.report && pathname.startsWith('/api/support/')) {
    // IN-03 (D-009 slice): synthetic, LLM-built support flags, `<sample>.support.json`.
    const name = checkSampleName(decodeURIComponent(pathname.slice('/api/support/'.length)));
    const file = join(ctx.dir, name.replace(/\.md$/, '') + '.support.json');
    if (!existsSync(file)) return sendError(res, 404, 'no support flags');
    return send(res, 200, MIME['.json'], await readFile(file, 'utf8'));
  }

  if (!ctx.report && pathname.startsWith('/api/register/')) {
    // IN-04 (D-009 slice): synthetic, LLM-built register flags, `<sample>.register.json`.
    const name = checkSampleName(decodeURIComponent(pathname.slice('/api/register/'.length)));
    const file = join(ctx.dir, name.replace(/\.md$/, '') + '.register.json');
    if (!existsSync(file)) return sendError(res, 404, 'no register flags');
    return send(res, 200, MIME['.json'], await readFile(file, 'utf8'));
  }

  if (!ctx.report && pathname.startsWith('/api/corrections/')) {
    // IN-05 (D-009 slice): expert move-label corrections, one whole-file JSON per sample.
    const name = checkSampleName(decodeURIComponent(pathname.slice('/api/corrections/'.length)));
    const file = join(ctx.correctionsDir, name.replace(/\.md$/, '') + '.corrections.json');
    if (req.method === 'GET') {
      if (!existsSync(file)) return send(res, 200, MIME['.json'], '[]');
      return send(res, 200, MIME['.json'], await readFile(file, 'utf8'));
    }
    if (req.method === 'PUT') {
      const text = await readBody(req);
      let list;
      try { list = JSON.parse(text); } catch { return sendError(res, 400, 'body must be JSON'); }
      // IN-05 residual: a missing or malformed genre.json is a clear JSON error, not a crash.
      const genreFile = genrePath(ctx);
      if (!genreFile) return sendError(res, 404, 'genre.json not found');
      let genre;
      try { genre = JSON.parse(await readFile(genreFile, 'utf8')); } catch {
        return sendError(res, 400, 'genre.json is not valid JSON');
      }
      const ids = new Set((Array.isArray(genre.moves) ? genre.moves : []).map((/** @type {any} */ m) => m && m.id));
      try { checkCorrections(list, ids); } catch (err) {
        return sendError(res, 400, /** @type {Error} */ (err).message);
      }
      const body = JSON.stringify(list, null, 2) + '\n';
      await mkdir(ctx.correctionsDir, { recursive: true });
      await atomicWrite(file, body);
      return send(res, 200, MIME['.json'], JSON.stringify({ saved: name, corrections: list.length }));
    }
    return sendError(res, 405, 'method not allowed');
  }

  const mounts = [
    ['/@app/', EDITOR_DIR],
    ['/@docmodel/', DOCMODEL_DIR],
    ['/@nm/e/', join(EDITOR_DIR, 'node_modules')],
    ['/@nm/d/', join(DOCMODEL_DIR, 'node_modules')],
  ];
  for (const [prefix, root] of mounts) {
    if (!pathname.startsWith(prefix)) continue;
    let full;
    try {
      full = safeJoin(root, pathname.slice(prefix.length));
    } catch (err) {
      return sendError(res, /** @type {any} */ (err).status ?? 400, /** @type {Error} */ (err).message);
    }
    try {
      const info = await stat(full);
      if (!info.isFile()) return sendError(res, 404, 'not a file');
      const body = await readFile(full);
      let out = body;
      if (/\.[cm]?js$/.test(full)) {
        const wrapped = await wrapCommonJs(full, body.toString('utf8'));
        if (wrapped) out = wrapped;
      }
      return send(res, 200, MIME[/** @type {keyof MIME} */ (extname(full))] ?? 'application/octet-stream', out);
    } catch (err) {
      if (/** @type {any} */ (err).code === 'ENOENT') return sendError(res, 404, 'not found');
      throw err;
    }
  }
  return sendError(res, 404, 'not found');
}

/**
 * @param {{ dir?: string, report?: string, labels?: string, sections?: string, port?: number, host?: string, correctionsDir?: string, sectionCorrectionsDir?: string, genreFallback?: string | null }} [opts]
 * @returns {Promise<{ server: import('node:http').Server, url: string, port: number, dir: string, report: { file: string, name: string, labels: string | null } | null, sections: { file: string, document: string | null, sections: any[] } | null, importMap: { imports: Record<string, string> }, close: () => Promise<void> }>}
 */
export async function startServer(opts = {}) {
  const report = opts.report !== undefined ? await resolveReport(opts.report, opts.labels) : null;
  if (!report && opts.labels !== undefined) throw new Error('--labels needs --report');
  if (!report && opts.sections !== undefined) throw new Error('--sections needs --report');
  const sections = report && opts.sections !== undefined ? await resolveSections(opts.sections, report.file) : null;
  // In single-report mode the legend/genre lookup uses the report's folder (legend.json/genre.json there, else the demo's).
  const dir = report ? dirname(report.file) : resolve(opts.dir ?? DEFAULT_DIR);
  const info = await stat(dir);
  if (!info.isDirectory()) throw new Error(`sample folder is not a directory: ${dir}`);
  const correctionsDir = resolve(opts.correctionsDir ?? process.env.DEMO_CORRECTIONS_DIR ?? DEFAULT_CORRECTIONS_DIR);
  const sectionCorrectionsDir = resolve(opts.sectionCorrectionsDir ?? process.env.SECTION_CORRECTIONS_DIR ?? DEFAULT_SECTION_CORRECTIONS_DIR);
  const genreFallback = opts.genreFallback === undefined ? join(DEFAULT_DIR, 'genre.json') : opts.genreFallback;
  const port = opts.port ?? 0;
  const host = opts.host ?? '127.0.0.1';
  const importMap = await buildImportMap();
  let listenPort = 0;
  const server = createServer((req, res) => {
    const refused = refusalReason(req, listenPort);
    if (refused) {
      res.writeHead(403, { 'content-type': 'text/plain; charset=utf-8', 'cache-control': 'no-store' });
      res.end(`${refused}\n`);
      req.resume();
      return;
    }
    handle(req, res, { dir, correctionsDir, sectionCorrectionsDir, genreFallback, report, sections, importMap }).catch((err) => {
      if (!res.headersSent) sendError(res, /** @type {any} */ (err).status ?? 500, err instanceof Error ? err.message : String(err));
      else res.end();
    });
  });
  await new Promise((resolveListen, reject) => {
    server.once('error', reject);
    server.listen(port, host, () => {
      server.off('error', reject);
      resolveListen(undefined);
    });
  });
  const address = server.address();
  const actualPort = typeof address === 'object' && address ? address.port : port;
  listenPort = actualPort;
  return {
    server,
    url: `http://${host}:${actualPort}/`,
    port: actualPort,
    dir,
    report,
    sections,
    importMap,
    close: () => new Promise((done) => server.close(() => done(undefined))),
  };
}

/** @param {string} flag @returns {string | undefined} */
function argValue(flag) {
  const index = process.argv.indexOf(flag);
  return index >= 0 ? process.argv[index + 1] : undefined;
}

const isMain = process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (isMain) {
  if (argValue('--report') === undefined && argValue('--labels') !== undefined) {
    console.error('usage error: --labels needs --report (e.g. npm run demo -- --report <file.md> --labels <labels.json>)');
    process.exit(2);
  }
  if (argValue('--report') === undefined && argValue('--sections') !== undefined) {
    console.error('usage error: --sections needs --report (e.g. npm run demo -- --report <file.md> --sections <sections.json>)');
    process.exit(2);
  }
  const reportArg = argValue('--report');
  const labels = argValue('--labels');
  const sectionsArg = argValue('--sections');
  const dir = resolve(argValue('--dir') ?? process.env.DEMO_DIR ?? DEFAULT_DIR);
  const port = Number(argValue('--port') ?? process.env.PORT ?? 0);
  const run = await startServer(reportArg !== undefined ? { report: reportArg, labels, sections: sectionsArg, port } : { dir, labels, port });
  if (run.report) {
    console.log(`Demo report: ${run.report.file}`);
    console.log(`Demo labels: ${run.report.labels ?? '(none)'}`);
    if (run.sections) console.log(`Demo inferred sections: ${run.sections.sections.length} (${run.sections.document ?? 'document not in sections file'})`);
  } else console.log(`Demo samples: ${run.dir}`);
  console.log(`Demo URL: ${run.url}`);
  const stop = async () => { await run.close(); process.exit(0); };
  process.on('SIGINT', stop);
  process.on('SIGTERM', stop);
}
