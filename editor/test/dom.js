// Headless DOM for node --test: jsdom window globals plus the window-level event bus that
// @milkdown/ctx timers use (addEventListener/dispatchEvent on globalThis).
import { JSDOM } from 'jsdom';

export function setupDom() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', { pretendToBeVisual: true });
  const w = dom.window;
  for (const k of ['window', 'document', 'navigator', 'Node', 'HTMLElement', 'Element', 'Text',
    'MutationObserver', 'DOMParser', 'getComputedStyle', 'requestAnimationFrame', 'cancelAnimationFrame']) {
    if (globalThis[k] !== undefined) continue;
    const v = w[k];
    Object.defineProperty(globalThis, k, { configurable: true, writable: true,
      value: typeof v === 'function' && /^[a-z]/.test(k) ? v.bind(w) : v });
  }
  const bus = new EventTarget();
  for (const k of ['addEventListener', 'removeEventListener', 'dispatchEvent']) {
    if (globalThis[k] === undefined) globalThis[k] = bus[k].bind(bus);
  }
  return w;
}
