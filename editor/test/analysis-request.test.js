// IA-01: docChanged transactions feed one coalescer; after delayMs of quiet onRequest gets the dirty set.
// LLM-built synthetic document only; fake clock and timers.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { setupDom } from './dom.js';

setupDom();
const { analysisRequestPlugin } = await import('../src/analysis.js');
const { signalDecorationsPlugin, setSignals } = await import('../src/decorations.js');
const { EditorState, TextSelection } = await import('@milkdown/prose/state');
const { parseMarkdown, assignIds } = await import('docmodel');

const doc = assignIds(parseMarkdown('# Title\n\nFirst para.\n\nSecond para.\n'));
/** @type {{id: string, pos: number}[]} */
const paras = [];
doc.descendants((n, pos) => { if (n.type.name === 'paragraph') paras.push({ id: n.attrs.id, pos }); });

function clock() {
  let t = 0; let seq = 0;
  /** @type {Map<number, {at: number, fn: () => void}>} */
  const timers = new Map();
  return {
    now: () => t,
    setTimer: (fn, ms) => { timers.set(++seq, { at: t + ms, fn }); return seq; },
    clearTimer: (id) => { timers.delete(id); },
    advance(ms) {
      const end = t + ms;
      for (;;) {
        const due = [...timers].filter(([, v]) => v.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        timers.delete(due[0]); t = due[1].at; due[1].fn();
      }
      t = end;
    },
    count: () => timers.size,
  };
}

function setup(extra = {}) {
  const c = clock();
  const calls = [];
  const plugin = analysisRequestPlugin({ delayMs: 100, onRequest: (r) => calls.push(r),
    now: c.now, setTimer: c.setTimer, clearTimer: c.clearTimer, ...extra });
  let state = EditorState.create({ doc, plugins: [plugin, signalDecorationsPlugin(() => [])] });
  const pv = plugin.spec.view({ get state() { return state; } });
  const apply = (tr) => { state = state.apply(tr); return state; };
  return { c, calls, pv, apply, get state() { return state; } };
}

test('(a) several typing transactions within delayMs give exactly one request', () => {
  const s = setup();
  for (let i = 0; i < 3; i++) { s.apply(s.state.tr.insertText('x', paras[0].pos + 1 + i)); s.c.advance(50); }
  assert.equal(s.calls.length, 0);
  s.c.advance(100);
  assert.equal(s.calls.length, 1);
  assert.ok(s.calls[0].ids.has(paras[0].id));
  assert.ok(s.calls[0].ranges.length >= 1);
  assert.equal(s.calls[0].doc, s.state.doc);
  s.c.advance(1000);
  assert.equal(s.calls.length, 1);
});

test('(b) selection-only and setSignals transactions add nothing and do not extend the timer', () => {
  const s = setup();
  s.apply(s.state.tr.setSelection(TextSelection.create(s.state.doc, paras[1].pos + 2)));
  setSignals([])(s.state, s.apply);
  s.c.advance(500);
  assert.equal(s.calls.length, 0);
  assert.equal(s.c.count(), 0);
  s.apply(s.state.tr.insertText('y', paras[0].pos + 1));
  s.c.advance(90);
  s.apply(s.state.tr.setSelection(TextSelection.create(s.state.doc, paras[1].pos + 2)));
  setSignals([])(s.state, s.apply);
  s.c.advance(10);
  assert.equal(s.calls.length, 1);
});

test('(c) edits in two blocks yield both ids', () => {
  const s = setup();
  s.apply(s.state.tr.insertText('a', paras[0].pos + 1));
  s.apply(s.state.tr.insertText('b', s.state.tr.mapping.map(paras[1].pos + 2)));
  s.c.advance(100);
  assert.equal(s.calls.length, 1);
  assert.ok(s.calls[0].ids.has(paras[0].id));
  assert.ok(s.calls[0].ids.has(paras[1].id));
});

test('(d) no request fires after destroy', () => {
  const s = setup();
  s.apply(s.state.tr.insertText('z', paras[0].pos + 1));
  s.pv.destroy();
  s.c.advance(1000);
  s.apply(s.state.tr.insertText('z', paras[0].pos + 1));
  s.c.advance(1000);
  assert.equal(s.calls.length, 0);
});

test('(e) a throwing onRequest is caught, reported to onError, and the next edit still requests', () => {
  const errors = [];
  let n = 0;
  const s = setup({ onRequest: () => { n++; if (n === 1) throw new Error('boom'); },
    onError: (e) => errors.push(e) });
  s.apply(s.state.tr.insertText('q', paras[0].pos + 1));
  assert.doesNotThrow(() => s.c.advance(100));
  assert.equal(errors.length, 1);
  assert.equal(errors[0].message, 'boom');
  s.apply(s.state.tr.insertText('q', paras[0].pos + 1));
  s.c.advance(100);
  assert.equal(n, 2);
  assert.equal(errors.length, 1);
});

test('(e2) without onError a throwing onRequest is swallowed', () => {
  const s = setup({ onRequest: () => { throw new Error('boom'); } });
  s.apply(s.state.tr.insertText('q', paras[0].pos + 1));
  assert.doesNotThrow(() => s.c.advance(100));
});
