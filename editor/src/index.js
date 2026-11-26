// @ts-check
// ED-01: Milkdown editor over docmodel's schema.
// createEditor is the production entry for the app shell; unwired by design until the Tauri
// shell row wires it.
import {
  Editor, rootCtx, defaultValueCtx, schemaCtx, nodesCtx, marksCtx, prosePluginsCtx,
  nodeViewCtx, markViewCtx, editorViewCtx, SchemaReady, parserTimerCtx, serializerTimerCtx,
  editorStateTimerCtx,
} from '@milkdown/core';
import { createTimer } from '@milkdown/ctx';
import { schema, parseMarkdown, serializeMarkdown, overlayPlugin, idPlugin } from 'docmodel';
import { history, undo as pmUndo, closeHistory } from '@milkdown/prose/history';
import { views } from './render.js';
import { proposalRequestKeymap } from './request.js';
import { sourceView } from './source.js';
import { formatKeymap, headingKeymap, headingInputRule } from './format.js';

const DocmodelSchemaReady = createTimer('DocmodelSchemaReady');

/**
 * Milkdown always builds its own Schema from nodesCtx/marksCtx. We feed it docmodel's specs so
 * that build succeeds, then replace schemaCtx with docmodel's own Schema instance before the
 * parser, serializer and editor state read it; documents from parseMarkdown therefore belong
 * to the editor's schema (same object, same node/mark names and attrs).
 * @type {import('@milkdown/ctx').MilkdownPlugin}
 */
const docmodelSchema = (ctx) => {
  ctx.record(DocmodelSchemaReady);
  return async () => {
    await ctx.wait(SchemaReady);
    ctx.set(schemaCtx, schema);
    ctx.done(DocmodelSchemaReady);
    return () => ctx.clearTimer(DocmodelSchemaReady);
  };
};

/** @param {import('orderedmap').default<any>} om @returns {[string, any][]} */
const entries = (om) => { /** @type {[string, any][]} */ const out = []; om.forEach((k, v) => out.push([k, v])); return out; };

/**
 * Build a Milkdown editor in `root` holding `markdown`, parsed by docmodel.
 * One document in memory; no corpus loop.
 * FM-01: Mod-b/i/e/k format the selection (formatKeymap); `onLinkRequest(text)` supplies a link href.
 * FM-02: Mod-1..6 set/toggle heading level; `#`..`######` + space at paragraph start makes a heading.
 * UX-03: when `onRequest` is given, Mod-Shift-p on a selection calls it (proposalRequestKeymap).
 * @param {{ root: HTMLElement, markdown: string, onRequest?: (req: { from: number, to: number, text: string }) => void, onLinkRequest?: (text: string) => string | null | Promise<string | null> }} opts
 * @returns {Promise<{ editor: Editor, view: import('prosemirror-view').EditorView, getMarkdown: () => string, destroy: () => Promise<void>, showSource: () => void, showRich: () => void, isSourceView: () => boolean }>}
 */
export async function createEditor({ root, markdown, onRequest, onLinkRequest }) {
  /** @type {{ isSourceView: () => boolean } | null} */
  let srcRef = null;
  const doc = parseMarkdown(markdown);
  const { nodeViews, markViews } = views(root.ownerDocument);
  const editor = await Editor.make()
    .config((ctx) => {
      ctx.set(rootCtx, root);
      ctx.set(nodesCtx, entries(schema.spec.nodes));
      ctx.set(marksCtx, entries(schema.spec.marks));
      for (const t of [parserTimerCtx, serializerTimerCtx, editorStateTimerCtx]) {
        ctx.update(t, (xs) => [...xs, DocmodelSchemaReady]);
      }
      ctx.set(defaultValueCtx, { type: 'json', value: doc.toJSON() });
      ctx.update(prosePluginsCtx, (xs) => [
        ...xs, history(), overlayPlugin(), idPlugin(),
        formatKeymap({ isRich: () => !srcRef?.isSourceView(), onLinkRequest }),
        headingKeymap({ isRich: () => !srcRef?.isSourceView() }),
        headingInputRule({ isRich: () => !srcRef?.isSourceView() }),
        ...(onRequest ? [proposalRequestKeymap({ onRequest })] : []),
      ]);
      ctx.update(nodeViewCtx, (xs) => [...xs, .../** @type {any[]} */ (nodeViews)]);
      ctx.update(markViewCtx, (xs) => [...xs, .../** @type {any[]} */ (markViews)]);
    })
    .use(docmodelSchema)
    .create();
  const view = editor.ctx.get(editorViewCtx);
  // ED-04: while in source view, getMarkdown returns the textarea text verbatim.
  const src = sourceView(root, () => editor.ctx.get(editorViewCtx));
  srcRef = src;
  return {
    editor,
    view,
    getMarkdown: () => src.text() ?? serializeMarkdown(editor.ctx.get(editorViewCtx).state.doc),
    showSource: src.showSource,
    showRich: src.showRich,
    isSourceView: src.isSourceView,
    destroy: async () => { src.remove(); await editor.destroy(); },
  };
}

/**
 * UX-04: replace [from, to) with candidate `text` in one undoable transaction. closeHistory makes
 * each accept its own undo step even when accepts follow each other within history's group delay.
 * Unwired by design until UX-02 (accept/reject UI) calls it.
 * @param {{ view: import('prosemirror-view').EditorView }} ed
 * @param {{ from: number, to: number, text: string }} proposal
 * @returns {boolean}
 */
export function acceptProposal({ view }, { from, to, text }) {
  const { state } = view;
  if (!(0 <= from && from <= to && to <= state.doc.content.size)) return false;
  const tr = text ? state.tr.insertText(text, from, to) : state.tr.delete(from, to);
  view.dispatch(closeHistory(tr).scrollIntoView());
  return true;
}

/**
 * UX-04: undo the last history step (one accepted proposal). Unwired by design until UX-02.
 * @param {{ view: import('prosemirror-view').EditorView }} ed
 * @returns {boolean} false when there is nothing to undo
 */
export function undo({ view }) {
  return pmUndo(view.state, view.dispatch);
}
export { renderDiff } from './diff.js';
export { showProposal } from './proposal.js';
export { proposalRequestKeymap } from './request.js';
export { formatKeymap, headingKeymap, headingInputRule } from './format.js';
export { signalDecorations, signalDecorationsPlugin, DEFAULT_WEAK_BELOW, DEFAULT_OFF_SHORTCUT,
  signalOverlayKey, toggleSignalOverlay, isSignalOverlayOn, OVERLAYS, DEFAULT_OVERLAY, setSignalOverlay,
  selectedSignalOverlay, GRANULARITIES, DEFAULT_GRANULARITY, setSignalGranularity,
  selectedSignalGranularity } from './decorations.js';
