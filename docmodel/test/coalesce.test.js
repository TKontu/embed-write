import { test } from 'node:test';
import assert from 'node:assert/strict';
import { Transform } from 'prosemirror-transform';
import * as api from '../src/index.js';

const doc = md => api.assignIds(api.parseMarkdown(md));
const insert = (d, pos, text = 'X') => new Transform(d).insert(pos, api.schema.text(text));
function setup() {
  let time = 0;
  let next = 0;
  const timers = new Map();
  const calls = [];
  assert.equal(typeof api.createCoalescer, 'function');
  const coalescer = api.createCoalescer({
    delayMs: 100, onFlush: value => calls.push(value), now: () => time,
    setTimer: (fn, delay) => { const id = next++; timers.set(id, { fn, at: time + delay }); return id; },
    clearTimer: id => timers.delete(id),
  });
  const tick = ms => {
    const end = time + ms;
    while (true) {
      const due = [...timers].filter(([, t]) => t.at <= end).sort((a, b) => a[1].at - b[1].at)[0];
      if (!due) break;
      time = due[1].at;
      timers.delete(due[0]);
      due[1].fn();
    }
    time = end;
  };
  return { coalescer, calls, timers, tick };
}

test('ten rapid keystrokes flush one union after the trailing delay', () => {
  const { coalescer: c, calls, tick, timers } = setup();
  let d = doc('one');
  const expected = new Set();
  for (let i = 0; i < 10; i++) {
    const tr = insert(d, 2 + i);
    for (const id of api.dirtySet(tr)) expected.add(id);
    c.add(tr);
    d = tr.doc;
    tick(10);
  }
  assert.equal(timers.size, 1);
  assert.deepEqual(c.pending(), expected);
  c.pending().clear();
  assert.deepEqual(c.pending(), expected);
  tick(89);
  assert.equal(calls.length, 0);
  tick(1);
  assert.deepEqual(calls, [{ ids: expected, ranges: [{ from: 2, to: 12 }] }]);
  assert.deepEqual(c.pending(), new Set());
  assert.equal(timers.size, 0);
});

test('edits in two nested blocks flush their ids and ancestors together', () => {
  const { coalescer: c, calls, tick } = setup();
  const d = doc('> one\n>\n> two');
  const first = insert(d, 3);
  const second = insert(first.doc, 9);
  c.add(first);
  tick(50);
  c.add(second);
  tick(100);
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0].ids, new Set([d.firstChild.attrs.id,
    d.firstChild.firstChild.attrs.id, d.firstChild.lastChild.attrs.id]));
});

test('a gap beyond the delay creates separate flushes without retained ids', () => {
  const { coalescer: c, calls, tick } = setup();
  const first = insert(doc('one\n\ntwo'), 2);
  c.add(first);
  tick(101);
  const second = insert(first.doc, 8);
  c.add(second);
  tick(100);
  assert.deepEqual(calls.map(call => call.ids), [api.dirtySet(first), api.dirtySet(second)]);
});

test('manual flush emits immediately and cancels the timer; empty flush is silent', () => {
  const { coalescer: c, calls, tick, timers } = setup();
  c.flush();
  assert.equal(calls.length, 0);
  c.add(insert(doc('one'), 2));
  c.flush();
  assert.equal(calls.length, 1);
  assert.equal(timers.size, 0);
  c.flush();
  tick(200);
  assert.equal(calls.length, 1);
});

test('dispose cancels and discards pending edits without emitting', () => {
  const { coalescer: c, calls, tick, timers } = setup();
  const tr = insert(doc('one'), 2);
  c.add(tr);
  c.dispose();
  c.dispose();
  assert.equal(timers.size, 0);
  assert.deepEqual(c.pending(), new Set());
  c.flush();
  c.add(insert(tr.doc, 3));
  tick(200);
  assert.equal(calls.length, 0);
});

test('later transforms shift old ranges into current coordinates and merge touching edits', () => {
  const { coalescer: c, calls } = setup();
  const first = insert(doc('one\n\ntwo'), 7);
  const second = insert(first.doc, 2, 'YY');
  const third = insert(second.doc, 10);
  c.add(first);
  c.add(second);
  c.add(third);
  c.flush();
  assert.deepEqual(calls[0].ranges, [{ from: 2, to: 4 }, { from: 9, to: 11 }]);
});

test('a no-op starts no timer and does not postpone existing work', () => {
  const { coalescer: c, calls, tick, timers } = setup();
  const d = doc('one');
  c.add(new Transform(d));
  assert.equal(timers.size, 0);
  c.flush();
  tick(200);
  assert.equal(calls.length, 0);
  const tr = insert(d, 2);
  c.add(tr);
  tick(50);
  c.add(new Transform(tr.doc));
  tick(50);
  assert.equal(calls.length, 1);
});

test('deletion-only ranges flush even when there are no dirty ids', () => {
  const { coalescer: c, calls, tick } = setup();
  const d = doc('one\n\ntwo');
  c.add(new Transform(d).delete(0, d.firstChild.nodeSize));
  assert.deepEqual(c.pending(), new Set());
  tick(100);
  assert.deepEqual(calls, [{ ids: new Set(), ranges: [{ from: 0, to: 0 }] }]);
});

test('deleting a previously edited block collapses its range and retains its id', () => {
  const { coalescer: c, calls } = setup();
  const d = doc('one\n\ntwo');
  const first = insert(d, 2);
  c.add(first);
  c.add(new Transform(first.doc).delete(0, first.doc.firstChild.nodeSize));
  c.flush();
  assert.deepEqual(calls, [{ ids: new Set([d.firstChild.attrs.id]), ranges: [{ from: 0, to: 0 }] }]);
});

test('mark-only changes flush ids even without mapped ranges', () => {
  const { coalescer: c, calls, tick } = setup();
  const d = doc('one');
  c.add(new Transform(d).addMark(1, 3, api.schema.marks.em.create()));
  tick(100);
  assert.deepEqual(calls, [{ ids: new Set([d.firstChild.attrs.id]), ranges: [] }]);
});

test('flush resets state before a callback adds the next edit', () => {
  const { coalescer: c, calls } = setup();
  const first = insert(doc('one'), 2);
  const second = insert(first.doc, 3);
  const originalPush = calls.push.bind(calls);
  calls.push = value => { originalPush(value); if (calls.length === 1) c.add(second); };
  c.add(first);
  c.flush();
  assert.deepEqual(c.pending(), api.dirtySet(second));
  c.flush();
  assert.equal(calls.length, 2);
  assert.deepEqual(calls[0].ranges, [{ from: 2, to: 3 }]);
  assert.deepEqual(calls[1].ranges, [{ from: 3, to: 4 }]);
});

test('default timers emit pending edits', async () => {
  const tr = insert(doc('one'), 2);
  const result = await new Promise(resolve => {
    const c = api.createCoalescer({ delayMs: 0, onFlush: resolve });
    c.add(tr);
  });
  assert.deepEqual(result, { ids: api.dirtySet(tr), ranges: [{ from: 2, to: 3 }] });
});
