// @ts-check
// DE-02: the thin demo page. One document at a time; no corpus loop.
import { createEditor } from '../src/index.js';
import { isMoveOverlayOn, moveOverlayPlugin, selectedMoveGranularity, selectedMoveOverlaySelection,
  setMoveGranularity, setMoveOverlaySelection, toggleMoveOverlay, updateOverlayButton } from './overlay.js';
import { DEFAULT_GRANULARITY, DEFAULT_OFF_SHORTCUT, DEFAULT_OVERLAY, OVERLAYS } from '../src/decorations.js';
import { legendCss, renderLegendPanel } from '../src/legend.js';
import { refreshOverview } from '../src/overview.js';
import { blockEvidence, moveSequence, mountComparison, transitionStats } from '../src/comparison.js';
import { Plugin, Selection } from '@milkdown/prose/state';
import { inspectorPlugin, mountInspector, registerFlag, renderMethodTexts, supportEvidence } from '../src/inspector.js';
import { addCorrection, applyCorrections } from '../src/corrections.js';
import { sectionMarkerPlugin, sectionMarkers } from './sections.js';

const byId = (id) => /** @type {HTMLElement} */ (document.getElementById(id));
const ui = {
  samples: /** @type {HTMLSelectElement} */ (byId('samples')),
  save: /** @type {HTMLButtonElement} */ (byId('save-btn')),
  source: /** @type {HTMLButtonElement} */ (byId('source-btn')),
  overlay: /** @type {HTMLButtonElement} */ (byId('overlay-btn')),
  granularity: /** @type {HTMLSelectElement} */ (byId('granularity-select')),
  overlaySelect: /** @type {HTMLSelectElement} */ (byId('overlay-select')),
  status: byId('status'),
  root: byId('editor'),
  minimap: byId('minimap'),
  legendMount: byId('legend-panel'),
  legendStyle: /** @type {HTMLStyleElement} */ (byId('legend-css')),
};

/** @type {{ editor: Awaited<ReturnType<typeof createEditor>> | null, sample: string | null }} */
const state = { editor: null, sample: null };
/** @type {{ block: number, move: string }[]} */
let moves = [];
/** @type {any} */
let genre = null;
let loadToken = 0;
/** RE-11: overlay on/off survives switching samples. */
let overlayOn = true;
/** RE-09: the selected granularity survives switching samples too. */
let granularity = DEFAULT_GRANULARITY;
/** RE-10: the selected overlay survives switching samples too. */
let overlayName = DEFAULT_OVERLAY;

/** RE-10: overlay and level for the status line; says so when the sample has no entries for it. */
function overlaySummary() {
  const n = moves.filter((e) => (e.overlay ?? DEFAULT_OVERLAY) === overlayName).length;
  return n ? `${overlayName} overlay, ${granularity} level` : `${overlayName} overlay has no entries in this sample, ${granularity} level`;
}

/** @param {string} message @param {boolean} [bad] */
function setStatus(message, bad = false) {
  ui.status.textContent = message;
  ui.status.dataset.bad = bad ? '1' : '0';
}

/** @param {string} url @returns {Promise<any>} */
async function getJson(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  return res.json();
}

/**
 * DE-06: the legend panel is LG-07's renderLegendPanel output and the overlay colours are LG-02's
 * legendCss stylesheet, both read from the stored genre file (I3).
 */
function renderLegend() {
  ui.legendStyle.textContent = legendCss(genre);
  ui.legendMount.replaceChildren(renderLegendPanel(genre, { document }));
}

function updateSourceButton() {
  ui.source.textContent = state.editor?.isSourceView() ? 'Rich view' : 'Source view';
}

/** @param {boolean} on */
function overlayChanged(on) {
  updateOverlayButton(ui.overlay, on);
  setStatus(on ? `Overlay on (${overlaySummary()})` : `Overlay off (${DEFAULT_OFF_SHORTCUT} to show)`);
}

/** @param {string} name */
function granularityChanged(name) {
  granularity = name;
  ui.granularity.value = name;
  setStatus(`Showing ${name}-level labels (${overlaySummary()})`);
}

/** @param {string} name */
function overlaySelectionChanged(name) {
  overlayName = name;
  ui.overlaySelect.value = name;
  setStatus(`Showing ${overlaySummary()}`);
}

function selectOverlay() {
  if (!state.editor) return;
  setMoveOverlaySelection(ui.overlaySelect.value)(state.editor.view.state, state.editor.view.dispatch);
  state.editor.view.focus();
}

function selectGranularity() {
  if (!state.editor) return;
  setMoveGranularity(ui.granularity.value)(state.editor.view.state, state.editor.view.dispatch);
  state.editor.view.focus();
}

function toggleOverlay() {
  if (!state.editor) return;
  toggleMoveOverlay(state.editor.view.state, state.editor.view.dispatch);
  state.editor.view.focus();
}

/** @param {string} name */
async function load(name) {
  const token = ++loadToken;
  setStatus(`Loading ${name}…`);
  const sampleRes = await fetch(`/api/sample/${encodeURIComponent(name)}`);
  if (!sampleRes.ok) throw new Error(`cannot load ${name}: HTTP ${sampleRes.status}`);
  const markdown = await sampleRes.text();
  let sidecar = [];
  const movesRes = await fetch(`/api/moves/${encodeURIComponent(name)}`);
  if (movesRes.ok) sidecar = await movesRes.json();
  else if (movesRes.status !== 404) throw new Error(`cannot load labels for ${name}: HTTP ${movesRes.status}`);
  let flags = [];
  const supportRes = await fetch(`/api/support/${encodeURIComponent(name)}`);
  if (supportRes.ok) flags = await supportRes.json();
  // IN-05: expert corrections for this sample (GET returns [] when none are stored).
  const corrRes = await fetch(`/api/corrections/${encodeURIComponent(name)}`);
  const corr = corrRes.ok ? await corrRes.json() : [];
  let regFlags = [];
  const registerRes = await fetch(`/api/register/${encodeURIComponent(name)}`);
  if (registerRes.ok) regFlags = await registerRes.json();
  // CO-14 (D-015): inferred sections (only with --report --sections); shown as provisional markers.
  let inferred = null;
  const sectionsRes = await fetch(`/api/sections/${encodeURIComponent(name)}`);
  if (sectionsRes.ok) inferred = await sectionsRes.json();
  if (token !== loadToken) return;

  if (state.editor) await state.editor.destroy();
  state.editor = null;
  sidecarMoves = sidecar;
  corrections = corr;
  moves = applyCorrections(sidecar, corr);
  supportFlags = flags;
  registerFlags = regFlags;
  state.sample = name;
  ui.root.replaceChildren();
  const editor = await createEditor({ root: ui.root, markdown });
  if (token !== loadToken) { await editor.destroy(); return; }
  const plugin = moveOverlayPlugin(() => moves, () => genre, {
    initiallyOn: overlayOn,
    initialGranularity: granularity,
    initialOverlay: overlayName,
    onToggle: (on) => { overlayOn = on; overlayChanged(on); },
    onGranularity: granularityChanged,
    onOverlay: overlaySelectionChanged,
  });
  // IN-01 (D-009 slice): hover or selection inside a move mark fills the inspector panel.
  inspector?.destroy();
  // IN-02 (D-009 slice): plus the sample support for (previous move -> this move).
  inspector = mountInspector(editor.view.dom, inspectorMount(), () => genre,
    (el) => evidenceFor(editor.view, el),
    // IN-03 (D-009 slice): synthetic, LLM-built support flags for this block (no support model).
    (el) => supportFor(editor.view, el),
    // IN-04 (D-009 slice): synthetic, LLM-built register flags for this block (no register model).
    (el) => registerFor(editor.view, el),
    // IN-05 (D-009 slice): the expert overrules a move label; stored, outranks the sidecar.
    (el, label) => { correctLabel(editor.view, el, label); });
  const current = inspector;
  const markers = inferred ? sectionMarkers(markdown, inferred) : null;
  mountSectionControls(name, markers);
  editor.view.updateState(editor.view.state.reconfigure({
    plugins: [...editor.view.state.plugins, plugin, inspectorPlugin(Plugin, () => current),
      ...(markers ? [sectionMarkerPlugin(markers)] : [])],
  }));
  // idPlugin assigns block ids on this transaction; the overlay then has nodes to decorate.
  editor.view.dispatch(editor.view.state.tr.setMeta('demo:loaded', true));
  state.editor = editor;
  // OV-02 (D-009 slice): the draft's move order beside the typical order of all demo samples.
  mountComparisonStrip();
  // OV-01/OV-04 minimap (collapsed until toggled) and OV-03 open issues under it.
  mountIssues(editor);
  ui.samples.value = name;
  updateSourceButton();
  updateOverlayButton(ui.overlay, isMoveOverlayOn(editor.view.state));
  ui.granularity.value = selectedMoveGranularity(editor.view.state);
  ui.overlaySelect.value = selectedMoveOverlaySelection(editor.view.state);
  setStatus(`Loaded ${name} — ${moves.length} provisional label${moves.length === 1 ? '' : 's'}; ${overlaySummary()}${markers ? `; ${markers.length} provisional inferred section${markers.length === 1 ? '' : 's'}` : ''}`);
}

/**
 * CO-14 (c, D-015): the expert keeps or removes each shown boundary and adds one at a source line;
 * "Save sections" stores the kept + added set (line numbers and levels only) as the document's
 * expert correction, which then replaces the inference. Reload shows them as expert boundaries.
 * @type {{ name: string, removed: Set<number>, added: Map<number, number>, markers: Array<{ line: number, level: number }> } | null}
 */
let sectionDraft = null;
/** @type {HTMLElement | null} */
let sectionControls = null;

/** @param {string} name @param {Array<{ line: number, level: number }> | null} markers */
function mountSectionControls(name, markers) {
  sectionControls?.remove();
  sectionControls = null;
  sectionDraft = null;
  if (!markers) return;
  sectionDraft = { name, removed: new Set(), added: new Map(), markers };
  const box = document.createElement('span');
  box.className = 'section-controls';
  const line = document.createElement('input');
  line.type = 'number';
  line.min = '0';
  line.setAttribute('aria-label', 'Source line (0-based) for a new section boundary');
  const add = document.createElement('button');
  add.type = 'button';
  add.textContent = 'Add boundary';
  add.addEventListener('click', () => {
    const n = Number(line.value);
    if (!sectionDraft || !Number.isInteger(n) || n < 0) return setStatus('Enter a 0-based source line');
    sectionDraft.added.set(n, 1);
    sectionDraft.removed.delete(n);
    setStatus(`Boundary at line ${n} added (unsaved)`);
  });
  const save = document.createElement('button');
  save.type = 'button';
  save.textContent = 'Save sections';
  save.addEventListener('click', () => { void saveSections(); });
  box.append(line, add, save);
  ui.status.before(box);
  sectionControls = box;
}

async function saveSections() {
  if (!sectionDraft) return;
  const { name, removed, added, markers } = sectionDraft;
  const keep = new Map(markers.filter((m) => !removed.has(m.line)).map((m) => [m.line, m.level]));
  for (const [l, level] of added) keep.set(l, level);
  const sections = [...keep].map(([start_line, level]) => ({ start_line, level }));
  const res = await fetch(`/api/section-corrections/${encodeURIComponent(name)}`, {
    method: 'PUT', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ sections }) });
  if (!res.ok) return setStatus(`Section correction refused: ${(await res.json().catch(() => ({}))).error ?? res.status}`);
  await load(name);
  setStatus(`Saved ${sections.length} expert section boundar${sections.length === 1 ? 'y' : 'ies'} for ${name}`);
}

ui.root.addEventListener('click', (event) => {
  const button = /** @type {HTMLElement} */ (event.target).closest?.('.provisional-section button');
  if (!button || !sectionDraft) return;
  const badgeEl = /** @type {HTMLElement} */ (button.closest('.provisional-section'));
  const lineNo = Number(badgeEl.dataset.line);
  const remove = button.dataset.action === 'remove';
  if (remove) sectionDraft.removed.add(lineNo); else sectionDraft.removed.delete(lineNo);
  badgeEl.classList.toggle('section-removed', remove);
  badgeEl.classList.toggle('section-confirmed', !remove);
  setStatus(`Boundary at line ${lineNo} ${remove ? 'removed' : 'kept'} (unsaved)`);
});

/** @type {HTMLElement | null} */
let issuesMount = null;
/** @type {HTMLElement | null} */
let comparisonMount = null;
/** OV-02: every demo sample's labels (synthetic, LLM-built), fetched once in init(). */
/** @type {Array<Array<{ block: number, move: string }>>} */
let sampleMoves = [];

function mountComparisonStrip() {
  if (!comparisonMount) {
    comparisonMount = document.createElement('div');
    comparisonMount.className = 'comparison-mount';
    ui.minimap.after(comparisonMount);
  }
  mountComparison(comparisonMount, moves, sampleMoves, genre);
}

/** IN-02: transition stats over all demo samples (synthetic, LLM-built), built once in init(). */
let sampleStats = transitionStats([]);

/** IN-02: the top-level block index of a decorated element, then its sequence evidence. */
function evidenceFor(/** @type {any} */ view, /** @type {Element} */ el) {
  try {
    const block = view.state.doc.resolve(view.posAtDOM(el, 0)).index(0);
    return blockEvidence(sampleStats, moves, block, genre);
  } catch { return null; }
}

/** IN-03: this sample's support flags (synthetic, LLM-built), `<sample>.support.json`. */
/** @type {unknown} */
let supportFlags = [];

/** IN-03: a short text excerpt of a top-level block. */
function blockExcerpt(/** @type {any} */ doc, /** @type {number} */ block, max = 60) {
  if (block >= doc.childCount) return '(block not in document)';
  const t = doc.child(block).textContent.replace(/\s+/g, ' ').trim();
  return t.length > max ? `${t.slice(0, max - 1)}…` : t;
}

/** IN-03: the support view for a decorated element's top-level block, or null. */
function supportFor(/** @type {any} */ view, /** @type {Element} */ el) {
  try {
    const block = view.state.doc.resolve(view.posAtDOM(el, 0)).index(0);
    const evidence = supportEvidence(supportFlags, block);
    return evidence ? { evidence, excerptOf: (/** @type {number} */ b) => blockExcerpt(view.state.doc, b) } : null;
  } catch { return null; }
}

/** IN-04: this sample's register flags (synthetic, LLM-built), `<sample>.register.json`. */
/** @type {unknown} */
let registerFlags = [];

/** IN-04: the register flag for a decorated element's top-level block, or null. */
function registerFor(/** @type {any} */ view, /** @type {Element} */ el) {
  try {
    const block = view.state.doc.resolve(view.posAtDOM(el, 0)).index(0);
    return registerFlag(registerFlags, block);
  } catch { return null; }
}

/** IN-05: the sample's sidecar labels (fast layer) and the stored expert corrections. */
/** @type {any[]} */
let sidecarMoves = [];
/** @type {import('../src/corrections.js').Correction[]} */
let corrections = [];

/** IN-05: store an expert correction for the element's block, then relabel the mark. */
async function correctLabel(/** @type {any} */ view, /** @type {Element} */ el, /** @type {string} */ label) {
  const sample = state.sample;
  if (!sample) return;
  try {
    const block = view.state.doc.resolve(view.posAtDOM(el, 0)).index(0);
    const next = addCorrection(corrections, sidecarMoves, block, label);
    const res = await fetch(`/api/corrections/${encodeURIComponent(sample)}`, {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(next),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
    if (state.sample !== sample || state.editor?.view !== view) return;
    corrections = next;
    moves = applyCorrections(sidecarMoves, corrections);
    view.dispatch(view.state.tr.setMeta('demo:corrected', true));
    inspector?.update(view);
    // OV-01/OV-03: the minimap and the open-issues list follow the corrected labels.
    if (state.editor) mountIssues(state.editor);
    setStatus(`Saved expert correction for block ${block}: ${label}`);
  } catch (err) {
    setStatus(`Correction failed: ${err instanceof Error ? err.message : String(err)}`, true);
  }
}

/** @param {string[]} names */
async function loadSampleMoves(names) {
  const all = [];
  for (const name of names) {
    const res = await fetch(`/api/moves/${encodeURIComponent(name)}`);
    if (res.ok) all.push(await res.json());
  }
  return all;
}
/** @type {ReturnType<typeof mountInspector> | null} */
let inspector = null;
/** @type {HTMLElement | null} */
let inspectorEl = null;

/** IN-01: the inspector panel and the anchored method texts, at the top of the legend column. */
function inspectorMount() {
  if (!inspectorEl) {
    inspectorEl = document.createElement('div');
    inspectorEl.className = 'inspector-mount';
    ui.legendMount.before(inspectorEl);
    ui.legendMount.after(renderMethodTexts(document, genre));
  }
  return inspectorEl;
}

/** OV-01/OV-03: render the minimap and the open-issues list; clicking an unlabeled passage selects and reveals its block. */
function mountIssues(/** @type {any} */ editor) {
  if (!issuesMount) {
    issuesMount = document.createElement('div');
    issuesMount.className = 'issues-mount';
    ui.minimap.after(issuesMount);
  }
  refreshOverview({ minimapMount: ui.minimap, issuesMount, moves, blockCount: editor.view.state.doc.childCount, genre, onNavigate: (block) => {
    const view = editor.view;
    if (block >= view.state.doc.childCount) return;
    let pos = 0;
    for (let i = 0; i < block; i += 1) pos += view.state.doc.child(i).nodeSize;
    const sel = Selection.near(view.state.doc.resolve(pos + 1));
    view.dispatch(view.state.tr.setSelection(sel).scrollIntoView());
    view.focus();
  } });
}

async function save() {
  if (!state.editor || !state.sample) return;
  ui.save.disabled = true;
  try {
    const text = state.editor.getMarkdown();
    const res = await fetch(`/api/sample/${encodeURIComponent(state.sample)}`, {
      method: 'PUT',
      headers: { 'content-type': 'text/markdown; charset=utf-8' },
      body: text,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${await res.text()}`);
    const saved = await res.json();
    setStatus(`Saved ${saved.saved} (${saved.bytes} bytes)`);
  } catch (err) {
    setStatus(`Save failed: ${err instanceof Error ? err.message : String(err)}`, true);
  } finally {
    ui.save.disabled = false;
  }
}

function toggleSource() {
  if (!state.editor) return;
  try {
    if (state.editor.isSourceView()) {
      state.editor.showRich();
      setStatus('Rich view');
    } else {
      state.editor.showSource();
      setStatus('Source view (raw Markdown, byte-for-byte)');
    }
    updateSourceButton();
  } catch (err) {
    setStatus(`Cannot leave source view: ${err instanceof Error ? err.message : String(err)}`, true);
  }
}

async function init() {
  try {
    // legend.json stays the provisional-marking record (and a report folder's own override);
    // its colours are no longer read. The genre file drives panel and overlay colours.
    const legend = await getJson('/api/legend');
    if (legend.provisional !== true) setStatus('Legend is not marked provisional', true);
    genre = await getJson('/api/genre');
    renderLegend();
    for (const name of OVERLAYS) {
      const option = document.createElement('option');
      option.value = name;
      option.textContent = name;
      ui.overlaySelect.append(option);
    }
    ui.overlaySelect.value = overlayName;
    const listing = await getJson('/api/samples');
    for (const name of listing.samples) {
      const option = document.createElement('option');
      option.value = name;
      option.textContent = name;
      ui.samples.append(option);
    }
    if (!listing.samples.length) {
      setStatus('No .md samples in the demo folder', true);
      return;
    }
    sampleMoves = await loadSampleMoves(listing.samples);
    sampleStats = transitionStats(sampleMoves.map(moveSequence));
    ui.samples.addEventListener('change', () => {
      load(ui.samples.value).catch((err) => setStatus(`Load failed: ${err.message}`, true));
    });
    ui.save.addEventListener('click', () => { save(); });
    ui.source.addEventListener('click', toggleSource);
    ui.overlay.addEventListener('click', toggleOverlay);
    ui.granularity.addEventListener('change', selectGranularity);
    ui.overlaySelect.addEventListener('change', selectOverlay);
    await load(listing.samples[0]);
  } catch (err) {
    setStatus(`Demo failed: ${err instanceof Error ? err.message : String(err)}`, true);
  }
}

init();
