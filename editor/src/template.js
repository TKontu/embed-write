// @ts-check
// BH-06: start a new report from the genre's section skeleton.
// Unwired by design until ED-01 (app shell) exposes it.
import { parseMarkdown, serializeMarkdown, sectionSkeleton } from 'docmodel';
import { closeHistory } from '@milkdown/prose/history';

/**
 * When the editor document is empty (only whitespace), replace it with
 * sectionSkeleton(sectionTypes, opts) as one undoable step and return true. Otherwise change
 * nothing and return false (never destroys text). Also returns false in source view, where the
 * textarea, not the rich document, holds the text. Invalid opts.level throws sectionSkeleton's
 * TypeError before any change.
 * @param {{ view: import('prosemirror-view').EditorView, isSourceView?: () => boolean }} ed
 * @param {Parameters<typeof sectionSkeleton>[0]} sectionTypes
 * @param {Parameters<typeof sectionSkeleton>[1]} [opts]
 * @returns {boolean}
 */
export function insertSectionTemplate(ed, sectionTypes, opts) {
  const skeleton = sectionSkeleton(sectionTypes, opts);
  const { view } = ed;
  if (ed.isSourceView?.()) return false;
  const { state } = view;
  if (serializeMarkdown(state.doc).trim() !== '') return false;
  const doc = parseMarkdown(skeleton);
  const tr = state.tr.replaceWith(0, state.doc.content.size, doc.content);
  view.dispatch(closeHistory(tr).scrollIntoView());
  return true;
}
