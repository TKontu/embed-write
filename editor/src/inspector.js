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
 * @returns {{ signal: string, value: string, confidence: string, layer: string, methodId: string, methodText: string, previous?: string } | null}
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
  /** @type {NonNullable<ReturnType<typeof inspectSignal>>} */
  const out = {
    signal: 'Move',
    value: name,
    confidence: String(attrs['data-signal-confidence'] ?? 'unknown'),
    layer: String(attrs['data-signal-layer'] ?? 'unknown'),
    methodId: kind,
    methodText: def,
  };
  // IN-05: an expert correction names the label it overruled.
  const prev = attrs['data-signal-previous'];
  if (typeof prev === 'string' && prev) {
    const was = findMove(genre, prev);
    out.previous = was && typeof was.name === 'string' && was.name ? was.name : prev;
  }
  return out;
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
 * @typedef {{ from: string | null, to: string, count: number, of: number,
 *   fromName?: string, toName?: string }} SequenceEvidence
 */

/**
 * IN-02: the evidence sentence for one transition (pattern fit, not a verdict). Pure.
 * @param {SequenceEvidence} ev
 */
export function evidenceSentence(ev) {
  const to = ev.toName ?? ev.to;
  const from = ev.fromName ?? ev.from;
  if (ev.from === null) return `${to} opens the report in ${ev.count} of ${ev.of} samples`;
  if (!ev.count) return `No sample has ${to} after ${from}`;
  return `${to} follows ${from} in ${ev.count} of ${ev.of} samples`;
}

/**
 * IN-02: the sequence-evidence section of the inspector. Labels say synthetic, LLM-built samples
 * and pattern fit, not a verdict (I8). No colours (I3).
 * @param {Document} doc @param {SequenceEvidence} ev
 */
export function renderSequenceEvidence(doc, ev) {
  const section = doc.createElement('section');
  section.className = 'inspector-evidence';
  const h = doc.createElement('h3');
  h.textContent = 'Sequence evidence (synthetic samples, LLM-built)';
  const p = doc.createElement('p');
  p.className = 'inspector-evidence-text';
  p.textContent = evidenceSentence(ev);
  const note = doc.createElement('p');
  note.className = 'inspector-evidence-note';
  note.textContent = 'Pattern fit, not a verdict.';
  section.append(h, p, note);
  return section;
}

/**
 * @typedef {{ block: number, candidates: { block: number, score: number }[] }} SupportEvidence
 * @typedef {{ evidence: SupportEvidence, excerptOf: (block: number) => string }} SupportView
 */

/** @param {unknown} n */
const isBlock = (n) => Number.isInteger(n) && /** @type {number} */ (n) >= 0;

/**
 * IN-03: the support flag for one block from a support-flag list
 * `[{ block, candidates: [{ block, score }] }]` (empty candidates = none found). Pure; validates
 * the whole list's shape and throws on malformed input. Candidates sorted by score desc, ties by
 * block. Null when the block has no flag. O(flags x candidates).
 * @param {unknown} flags @param {number} block @returns {SupportEvidence | null}
 */
export function supportEvidence(flags, block) {
  if (!Array.isArray(flags)) throw new TypeError('support flags must be an array');
  /** @type {SupportEvidence | null} */
  let found = null;
  for (const f of flags) {
    if (!f || typeof f !== 'object' || !isBlock(f.block) || !Array.isArray(f.candidates)) {
      throw new TypeError('support flag must be { block: int >= 0, candidates: [] }');
    }
    const candidates = f.candidates.map((/** @type {any} */ c) => {
      if (!c || typeof c !== 'object' || !isBlock(c.block) || typeof c.score !== 'number'
        || !Number.isFinite(c.score) || c.score < 0 || c.score > 1) {
        throw new TypeError('support candidate must be { block: int >= 0, score: 0..1 }');
      }
      return { block: c.block, score: c.score };
    });
    if (f.block === block && !found) {
      candidates.sort((a, b) => b.score - a.score || a.block - b.block);
      found = { block, candidates };
    }
  }
  return found;
}

/**
 * IN-03: the candidate-evidence section: each candidate's block number, a short excerpt and
 * score, or "No candidate evidence found". Labels say synthetic support flags, LLM-built, and
 * pattern fit, not a verdict (I8). No colours (I3).
 * @param {Document} doc @param {SupportEvidence} ev @param {(block: number) => string} excerptOf
 */
export function renderSupportEvidence(doc, ev, excerptOf) {
  const section = doc.createElement('section');
  section.className = 'inspector-support';
  const h = doc.createElement('h3');
  h.textContent = 'Candidate evidence (synthetic support flags, LLM-built)';
  section.append(h);
  if (!ev.candidates.length) {
    const p = doc.createElement('p');
    p.className = 'inspector-support-none';
    p.textContent = 'No candidate evidence found';
    section.append(p);
  } else {
    const ul = doc.createElement('ul');
    for (const c of ev.candidates) {
      const li = doc.createElement('li');
      li.className = 'inspector-support-candidate';
      li.dataset.block = String(c.block);
      const excerpt = excerptOf(c.block);
      li.textContent = `Block ${c.block}: "${excerpt}" (score ${c.score.toFixed(2)})`;
      ul.append(li);
    }
    section.append(ul);
  }
  const note = doc.createElement('p');
  note.className = 'inspector-support-note';
  note.textContent = 'Pattern fit, not a verdict.';
  section.append(note);
  return section;
}

/**
 * @typedef {{ block: number, feature: string, note?: string, distance?: number }} RegisterFlag
 */

/**
 * IN-04: the register flag for one block from a register-flag list
 * `[{ block, feature, note?, distance? }]` (the feature the slow layer named; D-009 slice: a
 * synthetic, LLM-built file). Pure; validates the whole list and throws on malformed input or a
 * duplicate block. Null when the block has no flag. O(flags).
 * @param {unknown} flags @param {number} block @returns {RegisterFlag | null}
 */
export function registerFlag(flags, block) {
  if (!Array.isArray(flags)) throw new TypeError('register flags must be an array');
  const seen = new Set();
  /** @type {RegisterFlag | null} */
  let found = null;
  for (const f of flags) {
    if (!f || typeof f !== 'object' || !isBlock(f.block) || typeof f.feature !== 'string'
      || !f.feature.trim()) {
      throw new TypeError('register flag must be { block: int >= 0, feature: non-empty string }');
    }
    if (f.note !== undefined && typeof f.note !== 'string') {
      throw new TypeError('register flag note must be a string');
    }
    if (f.distance !== undefined && (typeof f.distance !== 'number' || !Number.isFinite(f.distance)
      || f.distance < 0 || f.distance > 1)) {
      throw new TypeError('register flag distance must be a number 0..1');
    }
    if (seen.has(f.block)) throw new TypeError(`duplicate register flag for block ${f.block}`);
    seen.add(f.block);
    if (f.block === block) {
      /** @type {RegisterFlag} */
      const out = { block: f.block, feature: f.feature };
      if (f.note !== undefined) out.note = f.note;
      if (f.distance !== undefined) out.distance = f.distance;
      found = out;
    }
  }
  return found;
}

/**
 * IN-04: the register section: the named off-register feature, plus note and distance when given.
 * Labels say synthetic register flags, LLM-built, and pattern fit, not a verdict (I8). No colours.
 * @param {Document} doc @param {RegisterFlag} flag
 */
export function renderRegisterFlag(doc, flag) {
  const section = doc.createElement('section');
  section.className = 'inspector-register';
  const h = doc.createElement('h3');
  h.textContent = 'Register (synthetic register flags, LLM-built)';
  const feature = doc.createElement('p');
  feature.className = 'inspector-register-feature';
  feature.textContent = `Feature: ${flag.feature}`;
  section.append(h, feature);
  if (flag.note !== undefined) {
    const p = doc.createElement('p');
    p.className = 'inspector-register-detail';
    p.textContent = `Note: ${flag.note}`;
    section.append(p);
  }
  if (flag.distance !== undefined) {
    const p = doc.createElement('p');
    p.className = 'inspector-register-distance';
    p.textContent = `Distance: ${flag.distance.toFixed(2)}`;
    section.append(p);
  }
  const note = doc.createElement('p');
  note.className = 'inspector-register-note';
  note.textContent = 'Pattern fit, not a verdict.';
  section.append(note);
  return section;
}

/**
 * IN-05: the "Correct label" control: a labelled select of the genre's moves (current preselected)
 * and a Save button that calls `onSave(id)`. The expert's choice is stored by the caller. No colours.
 * @param {Document} doc
 * @param {{ moves: { id: string, name?: string }[], current: string, onSave: (id: string) => void }} opts
 */
export function renderCorrectionControl(doc, { moves, current, onSave }) {
  const section = doc.createElement('section');
  section.className = 'inspector-correct';
  const label = doc.createElement('label');
  label.textContent = 'Correct label';
  const select = doc.createElement('select');
  select.className = 'inspector-correct-select';
  for (const m of moves) {
    if (!m || typeof m.id !== 'string') continue;
    const o = doc.createElement('option');
    o.value = m.id;
    o.textContent = typeof m.name === 'string' && m.name ? m.name : m.id;
    select.append(o);
  }
  select.value = current;
  label.append(select);
  const btn = doc.createElement('button');
  btn.type = 'button';
  btn.className = 'inspector-correct-save';
  btn.textContent = 'Save';
  btn.addEventListener('click', () => onSave(select.value));
  section.append(label, btn);
  return section;
}

/**
 * The inspector panel for one signal, or "No signal here" for null. I8: says pattern fit.
 * IN-02: an optional `evidence` adds the sequence-evidence section.
 * @param {Document} doc
 * @param {ReturnType<typeof inspectSignal>} info
 * @param {SequenceEvidence | null} [evidence]
 * @param {SupportView | null} [support] IN-03: adds the candidate-evidence section.
 * @param {RegisterFlag | null} [register] IN-04: adds the register section.
 */
export function renderInspector(doc, info, evidence = null, support = null, register = null) {
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
  aside.append(dl);
  if (info.previous !== undefined) {
    const p = doc.createElement('p');
    p.className = 'inspector-corrected';
    p.textContent = `Corrected by expert (was ${info.previous})`;
    aside.append(p);
  }
  aside.append(note, link);
  if (evidence) aside.append(renderSequenceEvidence(doc, evidence));
  if (support) aside.append(renderSupportEvidence(doc, support.evidence, support.excerptOf));
  if (register) aside.append(renderRegisterFlag(doc, register));
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
 * IN-02: optional `getEvidence(el)` supplies sequence evidence for a move mark.
 * @param {HTMLElement} editorDom @param {HTMLElement} mount @param {() => any} getGenre
 * @param {(el: Element) => SequenceEvidence | null} [getEvidence]
 * @param {(el: Element) => SupportView | null} [getSupport] IN-03: support flag for a move mark.
 * @param {(el: Element) => RegisterFlag | null} [getRegister] IN-04: register flag for a move mark.
 * @param {(el: Element, label: string) => void} [onCorrect] IN-05: adds the "Correct label"
 *   control to a move mark's panel; called with the chosen genre move id on Save.
 */
export function mountInspector(editorDom, mount, getGenre, getEvidence, getSupport, getRegister, onCorrect) {
  const doc = mount.ownerDocument;
  /** @type {Element | null} */
  let selected = null;
  /** @param {Element | null} el */
  const show = (el) => {
    const info = el ? inspectSignal(signalAttrs(el), getGenre()) : null;
    const ev = el && info && getEvidence ? getEvidence(el) : null;
    const sup = el && info && getSupport ? getSupport(el) : null;
    const reg = el && info && getRegister ? getRegister(el) : null;
    const panel = renderInspector(doc, info, ev, sup, reg);
    if (el && info && onCorrect) {
      const genre = getGenre();
      const moves = genre && Array.isArray(genre.moves) ? genre.moves : [];
      const target = el;
      panel.append(renderCorrectionControl(doc, { moves, current: info.methodId,
        onSave: (id) => onCorrect(target, id) }));
    }
    mount.replaceChildren(panel);
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
