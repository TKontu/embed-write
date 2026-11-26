// @ts-check
// DE-02: the thin demo page. One document at a time; no corpus loop.
import { createEditor } from '../src/index.js';
import { isMoveOverlayOn, moveOverlayPlugin, selectedMoveGranularity, selectedMoveOverlaySelection,
  setMoveGranularity, setMoveOverlaySelection, toggleMoveOverlay, updateOverlayButton } from './overlay.js';
import { DEFAULT_GRANULARITY, DEFAULT_OFF_SHORTCUT, DEFAULT_OVERLAY, OVERLAYS } from '../src/decorations.js';
import { legendCss, renderLegendPanel } from '../src/legend.js';

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
  if (token !== loadToken) return;

  if (state.editor) await state.editor.destroy();
  state.editor = null;
  moves = sidecar;
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
  editor.view.updateState(editor.view.state.reconfigure({
    plugins: [...editor.view.state.plugins, plugin],
  }));
  // idPlugin assigns block ids on this transaction; the overlay then has nodes to decorate.
  editor.view.dispatch(editor.view.state.tr.setMeta('demo:loaded', true));
  state.editor = editor;
  ui.samples.value = name;
  updateSourceButton();
  updateOverlayButton(ui.overlay, isMoveOverlayOn(editor.view.state));
  ui.granularity.value = selectedMoveGranularity(editor.view.state);
  ui.overlaySelect.value = selectedMoveOverlaySelection(editor.view.state);
  setStatus(`Loaded ${name} — ${moves.length} provisional label${moves.length === 1 ? '' : 's'}; ${overlaySummary()}`);
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
