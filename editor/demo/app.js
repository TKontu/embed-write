// @ts-check
// DE-02: the thin demo page. One document at a time; no corpus loop.
import { createEditor } from '../src/index.js';
import { moveOverlayPlugin, legendItems } from './overlay.js';

const byId = (id) => /** @type {HTMLElement} */ (document.getElementById(id));
const ui = {
  samples: /** @type {HTMLSelectElement} */ (byId('samples')),
  save: /** @type {HTMLButtonElement} */ (byId('save-btn')),
  source: /** @type {HTMLButtonElement} */ (byId('source-btn')),
  status: byId('status'),
  root: byId('editor'),
  legendList: /** @type {HTMLUListElement} */ (byId('legend-list')),
};

/** @type {{ editor: Awaited<ReturnType<typeof createEditor>> | null, sample: string | null }} */
const state = { editor: null, sample: null };
/** @type {{ block: number, move: string }[]} */
let moves = [];
/** @type {any} */
let legend = null;
let loadToken = 0;

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

function renderLegend() {
  ui.legendList.replaceChildren();
  for (const item of legendItems(legend)) {
    const li = document.createElement('li');
    li.dataset.move = item.move;
    const swatch = document.createElement('span');
    swatch.className = 'swatch';
    swatch.style.background = item.colour;
    const text = document.createElement('span');
    text.textContent = `${item.label} — ${item.move}`;
    li.append(swatch, text);
    ui.legendList.append(li);
  }
}

function updateSourceButton() {
  ui.source.textContent = state.editor?.isSourceView() ? 'Rich view' : 'Source view';
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
  const plugin = moveOverlayPlugin(() => moves, () => legend);
  editor.view.updateState(editor.view.state.reconfigure({
    plugins: [...editor.view.state.plugins, plugin],
  }));
  // idPlugin assigns block ids on this transaction; the overlay then has nodes to decorate.
  editor.view.dispatch(editor.view.state.tr.setMeta('demo:loaded', true));
  state.editor = editor;
  ui.samples.value = name;
  updateSourceButton();
  setStatus(`Loaded ${name} — ${moves.length} provisional label${moves.length === 1 ? '' : 's'}`);
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
    legend = await getJson('/api/legend');
    if (legend.provisional !== true) setStatus('Legend is not marked provisional', true);
    renderLegend();
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
    await load(listing.samples[0]);
  } catch (err) {
    setStatus(`Demo failed: ${err instanceof Error ? err.message : String(err)}`, true);
  }
}

init();
