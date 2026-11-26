// FP-03: the profiling script stays working (small ~2 000-word synthetic document).
import { test } from 'node:test';
import assert from 'node:assert/strict';

const { profile, syntheticMarkdown } = await import('../bench/fp03-profile.js');

test('synthetic document is deterministic and near the requested size', () => {
  const a = syntheticMarkdown(2000);
  assert.equal(a.markdown, syntheticMarkdown(2000).markdown);
  assert.ok(a.words >= 2000 && a.words < 2100);
});

test('profile reports all operations on a 2 000-word document', async () => {
  const r = await profile({ words: 2000, reps: 5 });
  assert.ok(r.blocks > 10 && r.signalled_blocks > 0);
  for (const k of ['mount', 'overlay_on', 'keystroke', 'granularity_change']) {
    assert.equal(r[k].runs_ms.length, 5, k);
    assert.ok(r[k].median_ms >= 0 && r[k].max_ms >= r[k].median_ms, k);
  }
  assert.ok(r.peak_heap_used_mb > 0);
});
