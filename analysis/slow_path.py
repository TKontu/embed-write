"""LY-02 wires LY-04/05/06; unwired by design until LY-01/analysis service.

Optional DS-01 label_store receives one candidate per accepted fresh Signal.

Only the injected review runs outside the state lock. No LLM or corpus is loaded.
The owner must call note_edit on every relevant edit, including context changes.
Context is JSON data (string-keyed objects, finite numbers); its canonical UTF-8
JSON SHA-256 includes section identity, preventing cross-section Signal reuse.
Callers must include all review dependencies, e.g. model/prompt version, in context.

At most max_pending jobs (running plus queued), max_workers reviews and
cache_entries cached batches are retained. Per-section guard/reconciler state
lasts for this instance's lifetime. Text/context/signal byte sizes and signals per
review are not bounded; large-document latency is untested. submit hashes and
copies inputs synchronously but never waits for review or available capacity.
"""
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from threading import Lock
import time

from analysis.reconcile_layers import LayerReconciler
from analysis.signals import Signal
from analysis.slow_cache import SlowLayerCache
from analysis.staleness import StalenessGuard


def _json(value):
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError('context object keys must be strings')
        for item in value.values():
            _json(item)
    elif isinstance(value, list):
        for item in value:
            _json(item)
    elif value is not None and not isinstance(value, (str, int, float, bool)):
        raise TypeError('context must contain only JSON data')
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False)


def _inputs(section_id, text, context):
    if not isinstance(section_id, str) or not section_id:
        raise ValueError('section_id must be a nonempty string')
    if not isinstance(text, str):
        raise TypeError('text must be a string')
    encoded = _json(context)
    content_hash = sha256(text.encode('utf-8')).hexdigest()
    context_hash = sha256(_json([section_id, json.loads(encoded)]).encode('utf-8')).hexdigest()
    return content_hash, context_hash, json.loads(encoded)


def _ready(status):
    future = Future()
    future.set_result(status)
    return future


class SlowPath:
    """Own serialized state and background reviews.

    submit returns Future[str]: accepted, stale, cached or busy. Review/validation
    exceptions are reported by Future.result()/exception(); they never escape
    submit. A busy submission still records the edit; the caller may retry later.
    Input/lifecycle errors raise synchronously. Futures cannot cancel admitted
    jobs, so tickets and capacity are always released. shutdown waits by default;
    wait=False cannot stop an already running injected review. An optional
    reconciler transfers exclusive access to this instance; callers must not
    access it concurrently. shutdown must be called from the owning thread,
    not a review or Future callback.
    """

    def __init__(self, review, *, max_workers=2, max_pending=8, cache_entries=128,
                 reconciler=None, label_store=None, model_version=None, clock=time.time):
        for name, value in [('max_workers', max_workers), ('max_pending', max_pending)]:
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f'{name} must be an int >= 1')
        if not callable(review):
            raise TypeError('review must be callable')
        if label_store is not None and (not isinstance(model_version, str) or not model_version):
            raise ValueError('model_version must be a non-empty str when label_store is given')
        self._review = review
        self._label_store = label_store
        self._model_version = model_version
        self._clock = clock
        self._cache = SlowLayerCache(cache_entries)
        self._guard = StalenessGuard()
        self._reconciler = reconciler if reconciler is not None else LayerReconciler()
        self._lock = Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._max_pending = max_pending
        self._pending = 0
        self._closed = False

    def note_edit(self, section_id, text, context):
        """Invalidate in-flight work for changed content or context, without review."""
        content, context_hash, _ = _inputs(section_id, text, context)
        with self._lock:
            self._guard.note_edit(section_id, content + context_hash)

    def submit(self, section_id, text, context):
        """Admit a review without waiting for its completion or free capacity."""
        content, context_hash, snapshot = _inputs(section_id, text, context)
        with self._lock:
            if self._closed:
                raise RuntimeError('SlowPath is shut down')
            revision = content + context_hash
            self._guard.note_edit(section_id, revision)
            cached = self._cache.get(content, context_hash)
            if cached is not None:
                self._publish(cached, content)
                return _ready('cached')
            if self._pending >= self._max_pending:
                return _ready('busy')
            ticket = self._guard.start(section_id, revision)
            self._pending += 1
            result = Future()
            result.set_running_or_notify_cancel()
            try:
                self._executor.submit(self._run, text, snapshot, content,
                                      context_hash, ticket, result)
            except Exception:
                self._pending -= 1
                self._guard.accept(ticket)
                raise
            return result

    def _publish(self, signals, content):
        for signal in signals:
            self._reconciler.offer(deepcopy(signal), content)

    def _store(self, signals):
        # DS-01: accepted fresh verdicts only; cached replays never reach here.
        if self._label_store is None:
            return
        for signal in signals:
            label = json.dumps([signal.level, signal.kind, signal.value], sort_keys=True,
                               separators=(',', ':'), ensure_ascii=False, allow_nan=False)
            self._label_store.append(signal.node_id, label, self._model_version, self._clock())

    def _run(self, text, context, content, context_hash, ticket, result):
        error = None
        try:
            signals = tuple(self._review(text, context))
            if any(not isinstance(signal, Signal) for signal in signals):
                raise TypeError('review must return Signals')
            signals = tuple(deepcopy(replace(signal, layer='confirmed')) for signal in signals)
        except Exception as exc:
            error = exc
        with self._lock:
            accepted = self._guard.accept(ticket)
            try:
                if error is None and accepted:
                    self._publish(signals, content)
                    self._store(signals)
                    self._cache.put(content, context_hash, signals)
            except Exception as exc:
                error = exc
            finally:
                self._pending -= 1
        # Callbacks may call submit/current: never invoke under the lock.
        if error is not None:
            result.set_exception(error)
        else:
            result.set_result('accepted' if accepted else 'stale')

    def current(self, node_id, level, kind):
        """Read a detached signal under the same lock used by completions."""
        with self._lock:
            return deepcopy(self._reconciler.current(node_id, level, kind))

    @property
    def discard_count(self):
        """Snapshot the guard's rejected completion count."""
        with self._lock:
            return self._guard.discard_count

    def shutdown(self, wait=True):
        """Stop accepting work; optionally wait for all admitted jobs to finish."""
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=wait)
