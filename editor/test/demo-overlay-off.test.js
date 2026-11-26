// RE-11 (demo): the provisional move overlay switches off and on with one command, one button and
// one shortcut (DEFAULT_OFF_SHORTCUT); toggling never changes the document.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { setupDom } from './dom.js';

setupDom();
const { createEditor, DEFAULT_OFF_SHORTCUT } = await import('../src/index.js');
const { moveOverlayPlugin, moveOverlayKey, moveOverlayBindings, isMoveOverlayOn, toggleMoveOverlay,
  updateOverlayButton } = await import('../demo/overlay.js');

const dir = fileURLToPath(new URL('../../examples/demo/', import.meta.url));
const name = 'synthetic-sample-1.md';
const source = readFileSync(join(dir, name), 'utf8');
const moves = JSON.parse(readFileSync(join(dir, name.replace(/\.md$/, '.moves.json')), 'utf8'));
const genre = JSON.parse(readFileSync(join(dir, 'genre.json'), 'utf8'));

const decoSnapshot = (state) => moveOverlayKey.get(state).props.decorations.call(null, state)
  .find().map((d) => ({ from: d.from, to: d.to, attrs: d.type.attrs }));

test('overlay off hides every decoration, leaves the doc untouched, and back on restores them', async () => {
  const root = document.body.appendChild(document.createElement('div'));
  const button = document.body.appendChild(document.createElement('button'));
  const editor = await createEditor({ root, markdown: source });
  try {
    const seen = [];
    const plugin = moveOverlayPlugin(() => moves, () => genre, {
      onToggle: (on) => { seen.push(on); updateOverlayButton(button, on); },
    });
    const view = editor.view;
    view.updateState(view.state.reconfigure({ plugins: [...view.state.plugins, plugin] }));
    view.dispatch(view.state.tr.setMeta('demo:loaded', true));
    updateOverlayButton(button, isMoveOverlayOn(view.state));

    assert.equal(isMoveOverlayOn(view.state), true);
    const before = decoSnapshot(view.state);
    assert.equal(before.length, moves.length);
    assert.equal(root.querySelectorAll('[data-move]').length, moves.length);
    assert.equal(button.textContent, 'Overlay off');
    assert.equal(button.getAttribute('aria-pressed'), 'false');
    const markdown = editor.getMarkdown();
    const docJson = JSON.stringify(view.state.doc.toJSON());

    let steps = -1;
    assert.equal(toggleMoveOverlay(view.state, (tr) => { steps = tr.steps.length; view.dispatch(tr); }), true);
    assert.equal(steps, 0);
    assert.equal(isMoveOverlayOn(view.state), false);
    assert.equal(decoSnapshot(view.state).length, 0);
    assert.equal(root.querySelectorAll('[data-move], .signal').length, 0);
    assert.equal(editor.getMarkdown(), markdown);
    assert.equal(JSON.stringify(view.state.doc.toJSON()), docJson);
    assert.equal(button.textContent, 'Overlay on');
    assert.equal(button.getAttribute('aria-pressed'), 'true');

    toggleMoveOverlay(view.state, (tr) => { steps = tr.steps.length; view.dispatch(tr); });
    assert.equal(steps, 0);
    assert.equal(isMoveOverlayOn(view.state), true);
    assert.deepEqual(decoSnapshot(view.state), before);
    assert.equal(root.querySelectorAll('[data-move]').length, moves.length);
    assert.equal(editor.getMarkdown(), markdown);
    assert.equal(JSON.stringify(view.state.doc.toJSON()), docJson);
    assert.equal(button.textContent, 'Overlay off');
    assert.equal(button.getAttribute('aria-pressed'), 'false');
    assert.deepEqual(seen, [false, true]);
  } finally {
    await editor.destroy();
    root.remove();
    button.remove();
  }
});

test('the keymap binds exactly Mod-Shift-o to the toggle', () => {
  assert.equal(DEFAULT_OFF_SHORTCUT, 'Mod-Shift-o');
  assert.deepEqual(Object.keys(moveOverlayBindings), [DEFAULT_OFF_SHORTCUT]);
  assert.equal(moveOverlayBindings[DEFAULT_OFF_SHORTCUT], toggleMoveOverlay);
});

test('the shortcut keydown toggles the overlay in a live view', async () => {
  const root = document.body.appendChild(document.createElement('div'));
  const editor = await createEditor({ root, markdown: source });
  try {
    const view = editor.view;
    view.updateState(view.state.reconfigure({
      plugins: [...view.state.plugins, moveOverlayPlugin(() => moves, () => genre)],
    }));
    view.dispatch(view.state.tr.setMeta('demo:loaded', true));
    const plugin = moveOverlayKey.get(view.state);
    const key = (init) => new window.KeyboardEvent('keydown', { key: 'O', code: 'KeyO', keyCode: 79, shiftKey: true, bubbles: true, cancelable: true, ...init });
    // jsdom's navigator is not a Mac, so Mod is Ctrl.
    assert.equal(plugin.props.handleKeyDown.call(plugin, view, key({ ctrlKey: true })), true);
    assert.equal(isMoveOverlayOn(view.state), false);
    assert.equal(plugin.props.handleKeyDown.call(plugin, view, key({ ctrlKey: true, altKey: true })), false);
    assert.equal(isMoveOverlayOn(view.state), false);
  } finally {
    await editor.destroy();
    root.remove();
  }
});

test('initiallyOn is validated', () => {
  assert.throws(() => moveOverlayPlugin(() => [], () => genre, { initiallyOn: 'yes' }), /boolean/);
});
