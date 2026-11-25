"""LY-03 triage; public symbols unwired by design until LY-01 calls them.

One TriageSession belongs to one editor session; release it when that session
ends. There is no global session registry: only two integer counters per object
(integer storage grows logarithmically with calls). Selection uses O(sentences)
space for one section and retains no futures after returning. Corpus-scale and
large-section latency are untested; SlowPath bounds admitted background work.

Sentence and section IDs must share a globally unique node namespace. SlowPath's
section_id argument serves as the review identity for either kind of node. The
injected review must emit signals for that identity and level. The caller supplies
section context (including all model/prompt dependencies) and must call
SlowPath.note_edit for every changed node, even those triage no longer selects.
No visibility policy or gate is enabled here.
"""
from dataclasses import dataclass
import logging
from threading import Lock

from analysis.slow_path import SlowPath


_LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class Sentence:
    """A fast-layer sentence observation; IDs are stable across edits."""

    node_id: str
    text: str
    confidence: float


class TriageSession:
    """Select uncertain sentences plus the edited section once per invocation.

    call_count counts actual submit invocations, including cache hits, busy
    responses and synchronous errors; it is not a count of model executions.
    busy_count counts capacity rejections separately. Counts are logged at INFO
    after each submit, including failures, without document text or context.
    The session_id should be an opaque, non-private logging identifier.
    """

    def __init__(self, slow_path: SlowPath, *, session_id: str, cutoff: float):
        if not 0 <= cutoff <= 1:
            raise ValueError('cutoff must be in [0, 1]')
        self._slow_path = slow_path
        self._session_id = session_id
        self._cutoff = cutoff
        self._lock = Lock()
        self._calls = 0
        self._busy = 0

    @property
    def call_count(self):
        with self._lock:
            return self._calls

    @property
    def busy_count(self):
        with self._lock:
            return self._busy

    def _submit(self, node_id, text, context):
        busy = False
        try:
            future = self._slow_path.submit(node_id, text, context)
            # SlowPath returns busy as an already-completed Future. Never wait
            # for a review; errors remain available on the returned Future.
            if future.done() and future.exception() is None:
                busy = future.result() == 'busy'
            return future
        finally:
            with self._lock:
                self._calls += 1
                self._busy += int(busy)
                calls, rejected = self._calls, self._busy
            _LOG.info('triage session=%s calls=%d busy=%d',
                      self._session_id, calls, rejected)

    def submit_section(self, section_id, text, sentences, *, edited_section_id,
                       context):
        """Return node-ID -> Future for selected work, without awaiting reviews.

        Supply each section once per fast-layer update. The section matching
        edited_section_id is submitted first, then sentences strictly below the
        cutoff, including uncertain sentences within that edited section.
        Repeated invocations intentionally resubmit (SlowPath handles caching).
        Busy work is returned to the caller for its retry policy, never queued
        here. Input validation precedes submission; SlowPath input/lifecycle
        errors propagate and may leave earlier selected work already submitted.
        """
        selected = []
        ids = {section_id}
        for sentence in sentences:
            if not isinstance(sentence.node_id, str) or not sentence.node_id:
                raise ValueError('sentence node_id must be a nonempty string')
            if sentence.node_id in ids:
                raise ValueError('sentence IDs must be unique and distinct from section_id')
            ids.add(sentence.node_id)
            if not isinstance(sentence.text, str):
                raise TypeError('sentence text must be a string')
            if not 0 <= sentence.confidence <= 1:
                raise ValueError('sentence confidence must be in [0, 1]')
            if sentence.confidence < self._cutoff:
                selected.append((sentence.node_id, sentence.text))
        results = {}
        if section_id == edited_section_id:
            results[section_id] = self._submit(section_id, text, context)
        for node_id, sentence_text in selected:
            results[node_id] = self._submit(node_id, sentence_text, context)
        return results
