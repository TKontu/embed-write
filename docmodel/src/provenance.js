// @ts-check
// SL-03: draft provenance per id-bearing node. Feeds the edit log (architecture I7, §5.10).
// Unwired by design: ED-01 wires provenancePlugin into the editor and sidecar save/open;
// AD-06/generation insert machine nodes via the meta; EL-02/IA-05 consume change events.
//
// Kinds: 'human' (no entry; the default), 'machine' (generated, untouched), 'machine-edited'
// (generated, then its text altered by the expert). Machine kinds always carry their run id.
//
// Meta (tr.setMeta(provenanceKey, ...)); ids refer to nodes in tr.doc unless noted:
//   { restore?: SidecarProvenance[]   replace all entries (sidecar load); no change events;
//                                     entries whose node is not in tr.doc are ignored
//     machine?: {run: string, ids: string[]}  generation inserted these nodes -> 'machine'
//                                     (cause 'insert'); every id must exist in tr.doc
//     accept?: string[]               expert kept machine text: kind is unchanged ('machine' stays
//                                     'machine', 'machine-edited' stays so); one 'accept' event each
//     reject?: string[]               expert rejected machine text (the tr deletes the node or
//                                     replaces its text): entry dropped, one 'reject' event each,
//                                     to = 'human' if the node survives, null if deleted }
//   accept/reject ids must have a machine entry before the transaction; ids named there are
//   exempt from edit detection in that transaction.
//
// Rules for doc-changing transactions (per step, over the step's changed ranges only):
// - Edit: a 'machine' node whose text changes becomes 'machine-edited', run kept (cause 'edit').
//   'machine-edited' and 'human' never change through edits.
// - Split: when the text of the touched textblocks is unchanged overall, the change is
//   structural. The second half gets a fresh id from idPlugin (an id attribute step); the new id
//   inherits the source entry (cause 'insert'). Neither half counts as edited.
// - Merge: a change that removes ids (structural, or a cross-block delete that joins blocks and
//   alters the survivor's text) folds each removed entry into the surviving
//   node before it (else after it). The result is 'machine' only if every merged node was
//   'machine' with the same run; otherwise 'machine-edited' with the first machine run in
//   document order if any merged node was machine-kind; else 'human'. A kind change on the
//   survivor emits cause 'edit'. A removed node with no entry and no text (an empty human
//   paragraph) is not folded: removing it leaves the survivor unchanged. (Deliberately not "machine wins": human text merged in is an
//   expert change and must read as edited.)
// - Deletion: a node that disappears loses its entry (event to: null, cause 'edit'). The
//   entry is kept in a tombstone map; if a node with that id reappears (undo, redo, cut and
//   paste) its entry is restored (cause 'insert').
// - Undo/redo: plugin state only follows the document. Undo of an edit does NOT turn
//   'machine-edited' back into 'machine' (its text was still changed by the expert at some
//   point; the edit log records both). Undo of a reject does NOT restore provenance: reject
//   clears the tombstone, so the reappearing node is human. Undo of a machine insertion deletes the nodes (entries
//   dropped); redo brings them back with their tombstoned entries.
// Cost: apply is O(nodes in changed ranges) per step; meta `machine`/`restore` walk the doc
// once. Tombstones grow with deleted machine nodes for the life of the state. Large-doc cost
// is unmeasured.
import { Plugin, PluginKey } from 'prosemirror-state';
import { AttrStep } from 'prosemirror-transform';

/** @typedef {'human' | 'machine' | 'machine-edited'} Kind */
/** @typedef {{kind: 'machine' | 'machine-edited', run: string}} Entry */
/** @typedef {{node: string, from: Kind | null, to: Kind | null, run: string | null,
 *   cause: 'accept' | 'reject' | 'edit' | 'insert'}} Change */
/** @typedef {{entries: Map<string, Entry>, tombs: Map<string, Entry>, changes: Change[]}} PState */
/** @typedef {import('prosemirror-model').Node} PMNode */

export const provenanceKey = new PluginKey('provenance');

const MACHINE_KINDS = ['machine', 'machine-edited'];
const nonempty = (/** @type {unknown} */ v) => typeof v === 'string' && v.length > 0;
/** @param {PMNode} node */
const idOf = (node) => (node.type.spec.attrs && 'id' in node.type.spec.attrs ? node.attrs.id ?? null : null);
/** @param {PMNode} node */
const textOf = (node) => node.textBetween(0, node.content.size, '\n', '￼');

/** @param {PMNode} doc @returns {Set<string>} */
function allIds(doc) {
  const ids = new Set();
  doc.descendants((n) => { const id = idOf(n); if (id != null) ids.add(id); });
  return ids;
}

/** Touched id-bearing nodes in [from, to] (widened by one), in document order.
 * @param {PMNode} doc @param {number} from @param {number} to */
function touched(doc, from, to) {
  /** @type {Map<string, string[]>} */
  const byId = new Map();
  let blocks = '';
  doc.nodesBetween(Math.max(0, from - 1), Math.min(doc.content.size, to + 1), (node) => {
    const id = idOf(node);
    if (id != null) {
      if (!byId.has(id)) byId.set(id, []);
      byId.get(id)?.push(textOf(node));
    }
    if (node.isTextblock) blocks += textOf(node);
    return !node.isTextblock;
  });
  return { order: [...byId.keys()], text: new Map([...byId].map(([k, v]) => [k, v.join('')])), blocks };
}

/** @param {(Entry | undefined)[]} parts @returns {Entry | undefined} */
function mergeEntries(parts) {
  const machine = parts.filter(Boolean);
  if (machine.length === 0) return undefined;
  const first = /** @type {Entry} */ (machine[0]);
  const pure = machine.length === parts.length &&
    machine.every((e) => e?.kind === 'machine' && e.run === first.run);
  return { kind: pure ? 'machine' : 'machine-edited', run: first.run };
}

/** @param {unknown} ids @param {string} name @returns {string[]} */
function idList(ids, name) {
  if (!Array.isArray(ids) || !ids.every(nonempty)) throw new Error(`provenance: ${name} must be an array of non-empty ids`);
  return ids;
}

/**
 * @param {{onChange?: (changes: Change[]) => void}} [opts] onChange is called once per applied
 *   transaction (including appended ones) that produced at least one change.
 * @returns {Plugin}
 */
export function provenancePlugin(opts = {}) {
  return new Plugin({
    key: provenanceKey,
    state: {
      init: () => ({ entries: new Map(), tombs: new Map(), changes: [] }),
      apply(tr, /** @type {PState} */ prev) {
        const meta = tr.getMeta(provenanceKey) ?? {};
        const accept = new Set(meta.accept ? idList(meta.accept, 'accept') : []);
        const reject = new Set(meta.reject ? idList(meta.reject, 'reject') : []);
        for (const id of [...accept, ...reject]) {
          if (!prev.entries.has(id)) throw new Error(`provenance: ${id} has no machine entry to accept or reject`);
        }
        if (!tr.docChanged && !meta.restore && !meta.machine && !accept.size && !reject.size) {
          return prev.changes.length ? { ...prev, changes: [] } : prev;
        }
        const entries = new Map(prev.entries);
        const tombs = new Map(prev.tombs);
        /** @type {Change[]} */
        const changes = [];
        const exempt = new Set([...accept, ...reject]);
        const removedNow = new Set();
        const kindOf = (/** @type {string} */ id) => entries.get(id)?.kind ?? 'human';
        /** @param {string} id @param {Entry | undefined} next @param {Change['cause']} cause */
        const set = (id, next, cause) => {
          const before = entries.get(id);
          if (next) entries.set(id, next); else entries.delete(id);
          if (before?.kind !== next?.kind || before?.run !== next?.run) {
            changes.push({ node: id, from: before?.kind ?? 'human', to: next?.kind ?? 'human', run: (next ?? before)?.run ?? null, cause });
          }
        };

        tr.steps.forEach((step, i) => {
          const before = tr.docs[i];
          const after = i + 1 < tr.docs.length ? tr.docs[i + 1] : tr.doc;
          if (step instanceof AttrStep) {
            if (step.attr !== 'id') return;
            const old = before.nodeAt(step.pos);
            const oldId = old ? idOf(old) : null;
            const newId = step.value;
            const source = oldId != null ? entries.get(oldId) ?? tombs.get(oldId) : undefined;
            if (newId != null && source && !entries.has(newId)) set(newId, { ...source }, 'insert');
            // A renamed id that no longer exists anywhere loses its entry (split keeps the original).
            if (oldId != null && entries.has(oldId) && !allIdsCache(after).has(oldId)) {
              tombs.set(oldId, /** @type {Entry} */ (entries.get(oldId)));
              entries.delete(oldId);
            }
            return;
          }
          step.getMap().forEach((oldStart, oldEnd, newStart, newEnd) => {
            const o = touched(before, oldStart, oldEnd);
            const n = touched(after, newStart, newEnd);
            const structural = o.blocks === n.blocks;
            const removed = o.order.filter((id) => !n.text.has(id));
            // Reappearing ids (undo/redo/paste) take back their tombstoned entry.
            for (const id of n.order) {
              if (!o.text.has(id) && !entries.has(id) && tombs.has(id) && !exempt.has(id)) {
                set(id, tombs.get(id), 'insert');
                tombs.delete(id);
              }
            }
            for (const id of removed) {
              const gone = entries.get(id);
              if (gone) tombs.set(id, gone);
              removedNow.add(id);
              entries.delete(id);
              if (gone && !exempt.has(id)) changes.push({ node: id, from: gone.kind, to: null, run: gone.run, cause: 'edit' });
              // Merge: fold the removed entry into the surviving neighbour. A removed human node
              // folds only when it carried text (structural joins); an empty one changes nothing.
              // A non-structural delete folds only into a neighbour whose own text changed (a
              // cross-block join), never into an untouched neighbour of a deleted whole node.
              if (!gone && !(structural && o.text.get(id))) continue;
              const at = o.order.indexOf(id);
              const target = o.order.slice(0, at).reverse().find((x) => n.text.has(x)) ??
                o.order.slice(at + 1).find((x) => n.text.has(x)) ?? n.order[0];
              if (target === undefined || exempt.has(target)) continue;
              if (!structural && o.text.get(target) === n.text.get(target)) continue;
              const merged = o.text.has(target) ? mergeEntries([entries.get(target), gone]) : gone ?? entries.get(target);
              set(target, merged, 'edit');
            }
            if (structural) return;
            for (const id of n.order) {
              if (exempt.has(id) || !o.text.has(id) || o.text.get(id) === n.text.get(id)) continue;
              const entry = entries.get(id);
              if (entry?.kind === 'machine') set(id, { kind: 'machine-edited', run: entry.run }, 'edit');
            }
          });
        });

        if (meta.restore) {
          if (!Array.isArray(meta.restore)) throw new Error('provenance: restore must be an array');
          const present = allIds(tr.doc);
          entries.clear();
          for (const e of meta.restore) {
            if (!e || !MACHINE_KINDS.includes(e.kind) || !nonempty(e.run) || !nonempty(e.node)) {
              if (e?.kind === 'human') continue;
              throw new Error('provenance: restore entries need node, a machine kind and a run id');
            }
            if (present.has(e.node)) entries.set(e.node, { kind: e.kind, run: e.run });
          }
        }
        if (meta.machine) {
          const { run } = meta.machine;
          if (!nonempty(run)) throw new Error('provenance: machine.run must be a non-empty string');
          const ids = idList(meta.machine.ids, 'machine.ids');
          const present = allIds(tr.doc);
          for (const id of ids) {
            if (!present.has(id)) throw new Error(`provenance: machine node ${id} is not in the document`);
            set(id, { kind: 'machine', run }, 'insert');
          }
        }
        for (const id of accept) {
          const e = /** @type {Entry} */ (prev.entries.get(id));
          if (!removedNow.has(id)) entries.set(id, e);
          changes.push({ node: id, from: e.kind, to: e.kind, run: e.run, cause: 'accept' });
        }
        for (const id of reject) {
          const e = /** @type {Entry} */ (prev.entries.get(id));
          entries.delete(id);
          tombs.delete(id);
          changes.push({ node: id, from: e.kind, to: removedNow.has(id) ? null : 'human', run: e.run, cause: 'reject' });
        }
        if (changes.length && opts.onChange) opts.onChange(changes.map((c) => ({ ...c })));
        return { entries, tombs, changes };
      },
    },
  });
}

/** @type {WeakMap<PMNode, Set<string>>} */
const idCache = new WeakMap();
/** @param {PMNode} doc */
function allIdsCache(doc) {
  let ids = idCache.get(doc);
  if (!ids) { ids = allIds(doc); idCache.set(doc, ids); }
  return ids;
}

/** @param {import('prosemirror-state').EditorState} state @param {string} id
 * @returns {{kind: Kind, run: string | null}} */
export function provenanceOf(state, id) {
  const e = /** @type {PState | undefined} */ (provenanceKey.getState(state))?.entries.get(id);
  return e ? { kind: e.kind, run: e.run } : { kind: 'human', run: null };
}

/** Sidecar entries (machine kinds only; human is implicit), sorted by node id.
 * @param {import('prosemirror-state').EditorState} state
 * @returns {import('./sidecar.js').SidecarProvenance[]} */
export function currentProvenance(state) {
  const entries = /** @type {PState | undefined} */ (provenanceKey.getState(state))?.entries ?? new Map();
  return [...entries].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([node, e]) => ({ node, kind: e.kind, run: e.run }));
}

/** Transitions produced by the transaction that created `state` (the edit-log feed).
 * @param {import('prosemirror-state').EditorState} state @returns {Change[]} */
export function provenanceChanges(state) {
  return (/** @type {PState | undefined} */ (provenanceKey.getState(state))?.changes ?? []).map((c) => ({ ...c }));
}
