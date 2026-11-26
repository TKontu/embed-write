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
 * onRequest is caught and passed to onError when given.
 * Retained state is bounded by the coalescer (ids plus merged ranges since the last flush).
 * Unwired by design until the app shell (AP-01/RE-10) installs it and connects onRequest to the
 * analysis service.
 * @param {{ delayMs: number,
 *   onRequest: (req: { ids: Set<string>, ranges: {from: number, to: number}[], doc: import('prosemirror-model').Node }) => void,
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
          try {
            onRequest({ ids, ranges, doc: /** @type {any} */ (latestDoc) });
          } catch (error) {
            if (onError) {
              try { onError(error); } catch { /* never reach the timer/dispatch path */ }
            }
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
