// @ts-check
// IN-01 (D-009 thin-demo slice): hover or focus on a move mark shows its signal, value,
// confidence, layer and a link to its method text. Only move marks are inspected here; the
// app-shell wiring is owed to AP-01. Production caller: editor/demo/app.js. No colours (I3).

const NO_METHOD = 'No method text for this signal';
const NO_SIGNAL = 'No signal here';

/** @param {any} genre @param {string} id */
function findMove(genre, id) {
  const list = genre && Array.isArray(genre.moves) ? genre.moves : [];
  return list.find((/** @type {any} */ m) => m && m.id === id) ?? null;
}

/**
 * Pure: the inspector fields for one decorated element's data-signal-* attributes (I4).
 * Returns null when the attributes do not describe a move mark.
 * @param {Record<string, string | null | undefined> | null | undefined} attrs
 * @param {any} genre
 * @returns {{ signal: string, value: string, confidence: string, layer: string, methodId: string, methodText: string } | null}
 */
export function inspectSignal(attrs, genre) {
  if (!attrs) return null;
  const kind = attrs['data-signal-kind'];
  if (typeof kind !== 'string' || !kind) return null;
  const overlay = attrs['data-signal-overlay'];
  const isMove = typeof attrs['data-move'] === 'string' || overlay === 'moves' || overlay == null;
  if (!isMove) return null;
  const move = findMove(genre, kind);
  const name = move && typeof move.name === 'string' && move.name ? move.name : kind;
  const def = move && typeof move.definition === 'string' && move.definition ? move.definition : NO_METHOD;
  return {
    signal: 'Move',
    value: name,
    confidence: String(attrs['data-signal-confidence'] ?? 'unknown'),
    layer: String(attrs['data-signal-layer'] ?? 'unknown'),
    methodId: kind,
    methodText: def,
  };
}

/** The data-signal-* attribute map of an element (and data-move). @param {Element} el */
export function signalAttrs(el) {
  /** @type {Record<string, string>} */
  const out = {};
  for (const a of Array.from(el.attributes)) {
    if (a.name.startsWith('data-signal-') || a.name === 'data-move') out[a.name] = a.value;
  }
  return out;
}

/** @param {string} id */
const anchorId = (id) => `method-${id}`;

/**
 * The inspector panel for one signal, or "No signal here" for null. I8: says pattern fit.
 * @param {Document} doc
 * @param {ReturnType<typeof inspectSignal>} info
 */
export function renderInspector(doc, info) {
  const aside = doc.createElement('aside');
  aside.className = 'inspector';
  aside.setAttribute('aria-live', 'polite');
  aside.setAttribute('aria-label', 'Signal inspector');
  if (!info) {
    const p = doc.createElement('p');
    p.className = 'inspector-empty';
    p.textContent = NO_SIGNAL;
    aside.append(p);
    return aside;
  }
  const dl = doc.createElement('dl');
  for (const [k, v] of [['Signal', info.signal], ['Value', info.value],
    ['Confidence', info.confidence], ['Layer', info.layer]]) {
    const dt = doc.createElement('dt');
    dt.textContent = k;
    const dd = doc.createElement('dd');
    dd.textContent = v;
    dd.dataset.field = k.toLowerCase();
    dl.append(dt, dd);
  }
  const note = doc.createElement('p');
  note.className = 'inspector-note';
  note.textContent = 'Pattern fit, not a verdict.';
  const link = doc.createElement('a');
  link.href = `#${anchorId(info.methodId)}`;
  link.textContent = 'Method';
  aside.append(dl, note, link);
  return aside;
}

/**
 * The anchored method-text list: one entry per genre move holding its definition.
 * @param {Document} doc @param {any} genre
 */
export function renderMethodTexts(doc, genre) {
  const section = doc.createElement('section');
  section.className = 'method-texts';
  const h = doc.createElement('h2');
  h.textContent = 'Method text';
  const dl = doc.createElement('dl');
  const list = genre && Array.isArray(genre.moves) ? genre.moves : [];
  for (const m of list) {
    if (!m || typeof m.id !== 'string') continue;
    const dt = doc.createElement('dt');
    dt.id = anchorId(m.id);
    dt.textContent = typeof m.name === 'string' && m.name ? m.name : m.id;
    const dd = doc.createElement('dd');
    dd.textContent = typeof m.definition === 'string' && m.definition ? m.definition : NO_METHOD;
    dl.append(dt, dd);
  }
  section.append(h, dl);
  return section;
}

/**
 * Wire an inspector panel to an editor DOM: mouseover shows the hovered mark, mouseleave falls
 * back to the selection's mark; `update(view)` reads the selection. O(1) per event.
 * @param {HTMLElement} editorDom @param {HTMLElement} mount @param {() => any} getGenre
 */
export function mountInspector(editorDom, mount, getGenre) {
  const doc = mount.ownerDocument;
  /** @type {Element | null} */
  let selected = null;
  /** @param {Element | null} el */
  const show = (el) => {
    const info = el ? inspectSignal(signalAttrs(el), getGenre()) : null;
    mount.replaceChildren(renderInspector(doc, info));
  };
  /** @param {Event} e */
  const over = (e) => {
    const t = /** @type {any} */ (e.target);
    const el = t && typeof t.closest === 'function' ? t.closest('[data-signal-kind]') : null;
    show(el && editorDom.contains(el) ? el : selected);
  };
  const leave = () => show(selected);
  editorDom.addEventListener('mouseover', over);
  editorDom.addEventListener('mouseleave', leave);
  show(null);
  return {
    /** @param {any} view */
    update(view) {
      let el = null;
      try {
        const { node } = view.domAtPos(view.state.selection.from);
        const base = node && node.nodeType === 1 ? node : node && node.parentElement;
        el = base && typeof base.closest === 'function' ? base.closest('[data-signal-kind]') : null;
      } catch { el = null; }
      selected = el;
      show(el);
    },
    destroy() {
      editorDom.removeEventListener('mouseover', over);
      editorDom.removeEventListener('mouseleave', leave);
    },
  };
}

/**
 * A ProseMirror plugin whose view update re-reads the selection into the inspector. `PluginCtor`
 * is passed in so this module stays free of editor imports. @param {any} PluginCtor
 * @param {() => ReturnType<typeof mountInspector> | null} getInspector
 */
export function inspectorPlugin(PluginCtor, getInspector) {
  return new PluginCtor({
    view: (/** @type {any} */ view) => {
      getInspector()?.update(view);
      return {
        update: (/** @type {any} */ v, /** @type {any} */ prev) => {
          if (prev && v.state.selection.eq(prev.selection) && v.state.doc.eq(prev.doc)) return;
          getInspector()?.update(v);
        },
      };
    },
  });
}
