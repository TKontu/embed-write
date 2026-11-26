// @ts-check
// IA-01: transaction hook that turns document edits into debounced analysis requests.
import { Plugin, PluginKey } from '@milkdown/prose/state';
import { createCoalescer } from 'docmodel';

const analysisRequestKey = new PluginKey('analysisRequest');

/**
 * IA-01. Every docChanged transaction is added to one docmodel coalescer (HS-03); after `delayMs`
 * of quiet, `onRequest({ ids, ranges, doc })` receives the coalesced dirty ids/ranges and the
 * current state doc. Selection-only and meta-only transactions (e.g. setSignals) add nothing.
 * The coalescer lives with the plugin view: destroy() disposes it, so no request follows. The
 * request runs from the timer, never inside dispatch, so typing never waits; an error thrown by
 * onRequest is caught and passed to onError when given. IA-03: if onRequest returns a thenable it is
 * never awaited; its rejection is passed to onError (or swallowed), never left unhandled.
 * Retained state is bounded by the coalescer (ids plus merged ranges since the last flush).
 * Unwired by design until the app shell (AP-01/RE-10) installs it and connects onRequest to the
 * analysis service.
 * @param {{ delayMs: number,
 *   onRequest: (req: { ids: Set<string>, ranges: {from: number, to: number}[], doc: import('prosemirror-model').Node }) => void | PromiseLike<unknown>,
 *   onError?: (error: unknown) => void, now?: () => number,
 *   setTimer?: (callback: () => void, delay: number) => any, clearTimer?: (timer: any) => void }} opts
 * @returns {Plugin}
 */
export function analysisRequestPlugin({ delayMs, onRequest, onError, now, setTimer, clearTimer }) {
  /** @type {ReturnType<typeof createCoalescer> | null} */
  let coalescer = null;
  /** @type {import('prosemirror-model').Node | null} */
  let latestDoc = null;
  return new Plugin({
    key: analysisRequestKey,
    state: {
      init: () => null,
      apply(tr, value, _old, newState) {
        if (tr.docChanged && coalescer) {
          latestDoc = newState.doc;
          coalescer.add(tr);
        }
        return value;
      },
    },
    view(view) {
      latestDoc = view.state.doc;
      const own = createCoalescer({
        delayMs, now, setTimer, clearTimer,
        onFlush: ({ ids, ranges }) => {
          const report = (/** @type {unknown} */ error) => {
            if (onError) {
              try { onError(error); } catch { /* never reach the timer/dispatch path */ }
            }
          };
          try {
            const result = /** @type {any} */ (onRequest({ ids, ranges, doc: /** @type {any} */ (latestDoc) }));
            // IA-03: an async service is fire-and-forget; a rejection goes to onError (never an
            // unhandled rejection) and a pending/slow promise is never awaited, so later dispatches
            // and later requests proceed.
            if (result && typeof result.then === 'function') {
              try { result.then(undefined, report); } catch (error) { report(error); }
            }
          } catch (error) {
            report(error);
          }
        },
      });
      coalescer = own;
      return {
        destroy() {
          own.dispose();
          if (coalescer === own) coalescer = null;
        },
      };
    },
  });
}
