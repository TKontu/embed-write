// RE-01: signal decorations through a ProseMirror DecorationSet.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setupDom } from './dom.js';

setupDom();
import { readFileSync } from 'node:fs';
const { createEditor, signalDecorations, signalDecorationsPlugin, DEFAULT_WEAK_BELOW, signalOverlayKey,
  toggleSignalOverlay, isSignalOverlayOn, DEFAULT_OFF_SHORTCUT, OVERLAYS, DEFAULT_OVERLAY, setSignalOverlay,
  selectedSignalOverlay, GRANULARITIES, DEFAULT_GRANULARITY, setSignalGranularity,
  selectedSignalGranularity } = await import('../src/index.js');
const { EditorState } = await import('@milkdown/prose/state');
const { parseMarkdown, assignIds } = await import('docmodel');

const doc = assignIds(parseMarkdown('# Title\n\nFirst para.\n\nSecond para.\n'));
const blocks = [];
doc.descendants((n, pos) => { if (n.attrs.id) blocks.push({ id: n.attrs.id, pos, node: n }); });
const sig = (node_id, over = {}) => ({ node_id, level: 'paragraph', kind: 'readability', value: 1,
  confidence: 0.5, method_ref: 'm@1', layer: 'provisional', ...over });

test('decoration lands on the matching node with data attributes and class', () => {
  const b = blocks[1];
  const found = signalDecorations(doc, [sig(b.id)]).find();
  assert.equal(found.length, 1);
  const d = found[0];
  assert.equal(d.from, b.pos);
  assert.equal(d.to, b.pos + b.node.nodeSize);
  assert.deepEqual(d.type.attrs, { 'data-signal-kind': 'readability', 'data-signal-layer': 'provisional',
    'data-signal-confidence': '0.5', 'data-signal-strength': 'strong', 'data-signal-overlay': 'moves',
    'data-signal-level': 'paragraph',
    class: 'signal signal-provisional signal-strong' });
});

test('unknown node_id is skipped', () => {
  assert.equal(signalDecorations(doc, [sig('NOPE')]).find().length, 0);
});

test('bad layer and bad confidence throw', () => {
  const id = blocks[0].id;
  assert.throws(() => signalDecorations(doc, [sig(id, { layer: 'final' })]));
  for (const c of [NaN, -0.1, 1.5, '0.5', Infinity, undefined]) {
    assert.throws(() => signalDecorations(doc, [sig(id, { confidence: c })]), String(c));
  }
});

test('two signals on two nodes give two decorations', () => {
  const s = [sig(blocks[1].id), sig(blocks[2].id, { layer: 'confirmed', confidence: 1 })];
  assert.equal(signalDecorations(doc, s).find().length, 2);
});

test('plugin with a view renders the attributes on the DOM element', async () => {
  const ed = await createEditor({ root: document.body.appendChild(document.createElement('div')),
    markdown: '# Title\n\nFirst para.\n\nSecond para.\n' });
  try {
    ed.view.dispatch(ed.view.state.tr.setMeta('touch', true)); // let idPlugin assign ids
    let target = null;
    ed.view.state.doc.descendants((n) => { if (!target && n.textContent === 'Second para.' && n.attrs.id) target = n.attrs.id; });
    assert.ok(target);
    const plugin = signalDecorationsPlugin(() => [sig(target, { layer: 'confirmed', confidence: 0.25 })]);
    ed.view.updateState(ed.view.state.reconfigure({ plugins: [...ed.view.state.plugins, plugin] }));
    const els = ed.view.dom.querySelectorAll('[data-signal-kind]');
    assert.equal(els.length, 1);
    const el = els[0];
    assert.equal(el.getAttribute('data-signal-layer'), 'confirmed');
    assert.equal(el.getAttribute('data-signal-confidence'), '0.25');
    assert.ok(el.classList.contains('signal') && el.classList.contains('signal-confirmed'));
    assert.equal(el.getAttribute('data-signal-strength'), 'weak');
    assert.ok(el.classList.contains('signal-weak'));
    assert.match(el.textContent, /Second para/);
  } finally { await ed.destroy(); }
});

// RE-08: strength rendering from confidence.
const strength = (c, opts) => signalDecorations(doc, [sig(blocks[1].id, { confidence: c })], opts).find()[0].type.attrs;

test('default threshold: 0.2 weak, 0.5 and 0.9 strong', () => {
  assert.equal(DEFAULT_WEAK_BELOW, 0.5);
  assert.equal(strength(0.2)['data-signal-strength'], 'weak');
  assert.match(strength(0.2).class, /\bsignal-weak\b/);
  for (const c of [0.5, 0.9]) {
    assert.equal(strength(c)['data-signal-strength'], 'strong');
    assert.match(strength(c).class, /\bsignal-strong\b/);
  }
});

test('custom weakBelow 0.8 makes 0.5 weak', () => {
  assert.equal(strength(0.5, { weakBelow: 0.8 })['data-signal-strength'], 'weak');
  assert.equal(strength(0.8, { weakBelow: 0.8 })['data-signal-strength'], 'strong');
});

test('bad weakBelow throws', () => {
  for (const w of [NaN, -0.1, 1.1, Infinity, '0.5', null]) {
    assert.throws(() => strength(0.5, { weakBelow: w }), String(w));
  }
});

test('signals.css is opacity-only, weak lower than strong', () => {
  const css = readFileSync(new URL('../src/signals.css', import.meta.url), 'utf8');
  const bare = css.replace(/\/\*[\s\S]*?\*\//g, '');
  assert.doesNotMatch(bare, /#[0-9a-f]{3,8}\b/i);
  assert.doesNotMatch(bare, /\b(rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\s*\(/i);
  assert.doesNotMatch(bare, /(^|[\s;{])(color|background(-color)?|border(-color)?|outline(-color)?|fill|stroke)\s*:/im);
  const op = (cls) => {
    const m = bare.match(new RegExp(`\\.${cls}\\s*\\{([^}]*)\\}`));
    assert.ok(m, cls);
    const v = m[1].match(/opacity\s*:\s*([0-9.]+)/);
    assert.ok(v, `${cls} opacity`);
    return Number(v[1]);
  };
  assert.ok(op('signal-weak') < op('signal-strong'));
});

// RE-11: off as a first-class state with a single shortcut.
const mkState = (opts) => EditorState.create({ doc,
  plugins: [signalDecorationsPlugin(() => [sig(blocks[1].id)], opts)] });
const decoCount = (st) => signalOverlayKey.get(st).props.decorations.call(signalOverlayKey.get(st), st).find().length;
const toggled = (st) => { let out = st; assert.equal(toggleSignalOverlay(st, (tr) => { out = st.apply(tr); }), true); return out; };

test('overlay defaults on; toggle off empties; toggle again restores', () => {
  let st = mkState();
  assert.equal(isSignalOverlayOn(st), true);
  assert.equal(decoCount(st), 1);
  st = toggled(st);
  assert.equal(isSignalOverlayOn(st), false);
  assert.equal(decoCount(st), 0);
  st = toggled(st);
  assert.equal(isSignalOverlayOn(st), true);
  assert.equal(decoCount(st), 1);
});

test('initiallyOn false starts empty; bad initiallyOn throws', () => {
  const st = mkState({ initiallyOn: false });
  assert.equal(isSignalOverlayOn(st), false);
  assert.equal(decoCount(st), 0);
  for (const v of [0, 1, 'true', null]) assert.throws(() => signalDecorationsPlugin(() => [], { initiallyOn: v }), String(v));
});

test('default shortcut is Mod-Shift-o, distinct from Mod-Shift-p', () => {
  assert.equal(DEFAULT_OFF_SHORTCUT, 'Mod-Shift-o');
  assert.notEqual(DEFAULT_OFF_SHORTCUT.toLowerCase(), 'mod-shift-p');
  assert.throws(() => signalDecorationsPlugin(() => [], { offShortcut: 'Mod-Shift-p' }));
});

test('toggle and shortcut remove and restore data-signal-* in a view', async () => {
  const ed = await createEditor({ root: document.body.appendChild(document.createElement('div')),
    markdown: '# Title\n\nFirst para.\n\nSecond para.\n' });
  try {
    ed.view.dispatch(ed.view.state.tr.setMeta('touch', true));
    let target = null;
    ed.view.state.doc.descendants((n) => { if (!target && n.textContent === 'Second para.' && n.attrs.id) target = n.attrs.id; });
    const plugin = signalDecorationsPlugin(() => [sig(target)]);
    ed.view.updateState(ed.view.state.reconfigure({ plugins: [...ed.view.state.plugins, plugin] }));
    const n = () => ed.view.dom.querySelectorAll('[data-signal-kind]').length;
    assert.equal(n(), 1);
    assert.equal(toggleSignalOverlay(ed.view.state, ed.view.dispatch), true);
    assert.equal(n(), 0);
    assert.equal(ed.view.dom.querySelectorAll('[data-signal-layer],[data-signal-strength]').length, 0);
    const ev = new window.KeyboardEvent('keydown', { key: 'O', code: 'KeyO', keyCode: 79, ctrlKey: true, metaKey: false, shiftKey: true, bubbles: true, cancelable: true });
    assert.equal(ed.view.someProp('handleKeyDown', (f) => f(ed.view, ev)), true);
    assert.equal(isSignalOverlayOn(ed.view.state), true);
    assert.equal(n(), 1);
  } finally { await ed.destroy(); }
});

// RE-10: overlay selector, one overlay at a time.
const mixed = () => [sig(blocks[1].id), sig(blocks[2].id, { overlay: 'register' }),
  sig(blocks[0].id, { overlay: 'support' })];
const mkSel = (opts) => EditorState.create({ doc, plugins: [signalDecorationsPlugin(mixed, opts)] });
const decos = (st) => signalOverlayKey.get(st).props.decorations.call(signalOverlayKey.get(st), st).find();
const run = (st, cmd) => { let out = st; assert.equal(cmd(st, (tr) => { out = st.apply(tr); }), true); return out; };

test('OVERLAYS frozen list with moves default', () => {
  assert.deepEqual([...OVERLAYS], ['moves', 'register', 'support', 'redundancy', 'topic']);
  assert.ok(Object.isFrozen(OVERLAYS));
  assert.equal(DEFAULT_OVERLAY, 'moves');
});

test('default overlay moves decorates only moves signals (absent overlay = moves)', () => {
  const st = mkSel();
  assert.equal(selectedSignalOverlay(st), 'moves');
  const d = decos(st);
  assert.equal(d.length, 1);
  assert.equal(d[0].from, blocks[1].pos);
  assert.equal(d[0].type.attrs['data-signal-overlay'], 'moves');
});

test('setSignalOverlay switches which signals show; toggle preserves overlay', () => {
  let st = run(mkSel(), setSignalOverlay('register'));
  assert.equal(selectedSignalOverlay(st), 'register');
  let d = decos(st);
  assert.equal(d.length, 1);
  assert.equal(d[0].from, blocks[2].pos);
  assert.equal(d[0].type.attrs['data-signal-overlay'], 'register');
  st = run(st, toggleSignalOverlay);
  assert.equal(isSignalOverlayOn(st), false);
  assert.equal(decos(st).length, 0);
  assert.equal(selectedSignalOverlay(st), 'register');
  st = run(st, toggleSignalOverlay);
  assert.equal(isSignalOverlayOn(st), true);
  assert.equal(selectedSignalOverlay(st), 'register');
  assert.equal(decos(st)[0].from, blocks[2].pos);
  st = run(st, setSignalOverlay('topic'));
  assert.equal(decos(st).length, 0);
});

test('initialOverlay honoured; bad names throw', () => {
  const st = mkSel({ initialOverlay: 'support' });
  assert.equal(selectedSignalOverlay(st), 'support');
  assert.equal(decos(st)[0].from, blocks[0].pos);
  for (const v of ['bogus', '', null, 1]) {
    assert.throws(() => signalDecorationsPlugin(() => [], { initialOverlay: v }), String(v));
    assert.throws(() => setSignalOverlay(v), String(v));
  }
  assert.throws(() => signalDecorations(doc, [sig(blocks[1].id, { overlay: 'bogus' })]));
});

// RE-09: granularity toggle (section, paragraph, sentence); one level at a time.
const leveled = () => [sig(blocks[1].id), sig(blocks[0].id, { level: 'section' }),
  sig(blocks[2].id, { level: 'sentence' }), { ...sig(blocks[2].id), level: undefined }];
const mkGran = (opts) => EditorState.create({ doc, plugins: [signalDecorationsPlugin(leveled, opts)] });

test('GRANULARITIES frozen list with paragraph default', () => {
  assert.deepEqual([...GRANULARITIES], ['section', 'paragraph', 'sentence']);
  assert.ok(Object.isFrozen(GRANULARITIES));
  assert.equal(DEFAULT_GRANULARITY, 'paragraph');
});

test('default granularity paragraph; other levels not decorated (absent level = paragraph)', () => {
  const st = mkGran();
  assert.equal(selectedSignalGranularity(st), 'paragraph');
  const d = decos(st);
  assert.deepEqual(d.map((x) => x.from).sort((a, b) => a - b), [blocks[1].pos, blocks[2].pos]);
  for (const x of d) assert.equal(x.type.attrs['data-signal-level'], 'paragraph');
  assert.equal(signalDecorations(doc, leveled()).find().length, 4);
  assert.equal(signalDecorations(doc, leveled(), { granularity: 'section' }).find().length, 1);
});

test('setSignalGranularity switches signals; toggle and setSignalOverlay preserve granularity', () => {
  let st = run(mkGran(), setSignalGranularity('sentence'));
  assert.equal(selectedSignalGranularity(st), 'sentence');
  let d = decos(st);
  assert.equal(d.length, 1);
  assert.equal(d[0].from, blocks[2].pos);
  assert.equal(d[0].type.attrs['data-signal-level'], 'sentence');
  st = run(st, toggleSignalOverlay);
  assert.equal(isSignalOverlayOn(st), false);
  assert.equal(selectedSignalGranularity(st), 'sentence');
  st = run(st, toggleSignalOverlay);
  st = run(st, setSignalOverlay('register'));
  assert.equal(selectedSignalGranularity(st), 'sentence');
  assert.equal(decos(st).length, 0);
  st = run(st, setSignalOverlay('moves'));
  assert.equal(decos(st)[0].from, blocks[2].pos);
  st = run(run(st, toggleSignalOverlay), setSignalGranularity('section'));
  assert.equal(isSignalOverlayOn(st), false);
  assert.equal(selectedSignalOverlay(st), 'moves');
  st = run(st, toggleSignalOverlay);
  assert.equal(decos(st)[0].from, blocks[0].pos);
  assert.equal(setSignalGranularity('section')(EditorState.create({ doc })), false);
});

test('initialGranularity honoured; bad granularity names and signal levels throw', () => {
  assert.equal(decos(mkGran({ initialGranularity: 'section' }))[0].from, blocks[0].pos);
  for (const v of ['bogus', '', null, 1, 'Paragraph']) {
    assert.throws(() => signalDecorationsPlugin(() => [], { initialGranularity: v }), String(v));
    assert.throws(() => setSignalGranularity(v), String(v));
    assert.throws(() => signalDecorations(doc, [], { granularity: v }), String(v));
  }
  assert.throws(() => signalDecorations(doc, [sig(blocks[1].id, { level: 'word' })]));
});
