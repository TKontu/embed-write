"""Analysis client (SV-03): posts only dirty nodes to the local AnalysisService.

Production caller of ``AnalysisService``. Unwired by design until the editor client
(todo-03/todo-05) calls it. The base URL is checked with ``check_url`` (SV-05) at construction.
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import Future, ThreadPoolExecutor
import urllib.error
import urllib.request
from typing import Mapping

from service.contract import ContractError, build_request, node_hash
from service.network_guard import NetworkPolicy, check_url


class AnalysisClient:
    def __init__(self, base_url: str, policy: NetworkPolicy = NetworkPolicy(), timeout: float = 30):
        check_url(base_url, policy)  # fail closed before any request
        self._url = base_url.rstrip("/") + "/v1/batch"
        self._timeout = timeout

        self._lock = threading.RLock()
        self._generation = 0
        self._latest = {}  # active dirty node id -> (generation, hash)
        self._pending = {}  # generation -> (sent hashes, optional executor future)
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="analysis-client")
        self._closed = False

    def _prepare(self, current, known_hashes):
        # Snapshot caller-owned mappings before queuing work.
        current = dict(current)
        payload = build_request(current, dict(known_hashes))
        if self._closed:
            raise RuntimeError("analysis client is closed")
        if len(self._pending) >= 64:
            raise RuntimeError("analysis client has 64 outstanding requests")
        self._generation += 1
        generation = self._generation
        sent = {item["id"]: item["hash"] for item in payload["items"]}
        # Even a cache hit supersedes an older request for this node. Omitted ids
        # are unaffected: current may be a subset, not a whole document.
        for node_id, text in current.items():
            if node_id in self._latest or node_id in sent:
                self._latest[node_id] = (generation, node_hash(text))
        for older, (hashes, future) in list(self._pending.items()):
            if future is not None and not any(
                self._latest.get(n) == (older, h) for n, h in hashes.items()
            ):
                future.cancel()  # queued work stops; running HTTP is filtered below
        self._pending[generation] = (sent, None)
        for node_id in current.keys() - sent.keys():
            self._latest.pop(node_id, None)
        return generation, payload

    def _forget(self, generation):
        with self._lock:
            sent, _ = self._pending.pop(generation, ({}, None))
            for node_id, h in sent.items():
                if self._latest.get(node_id) == (generation, h):
                    del self._latest[node_id]

    def analyze(self, current: Mapping[str, str], known_hashes: Mapping[str, str]) -> dict:
        """Analyze dirty nodes synchronously, discarding superseded results.

        Each call observes the supplied ids, including clean nodes; omitted ids
        are unaffected. Notify edits by calling analyze or submit again.
        """
        with self._lock:
            generation, payload = self._prepare(current, known_hashes)
        return self._run(generation, payload)

    def submit(self, current: Mapping[str, str], known_hashes: Mapping[str, str]) -> Future:
        """Return a Future of results; fully superseded queued work is cancelled.

        Running requests finish their HTTP exchange but discard superseded nodes
        at completion. A Future already completed is a delivered snapshot.
        Two workers and at most 64 outstanding calls bound local work; overload
        raises RuntimeError. Call close (or use a context manager) to join workers.
        """
        with self._lock:
            generation, payload = self._prepare(current, known_hashes)
            try:
                future = self._executor.submit(self._run, generation, payload)
            except BaseException:
                self._forget(generation)
                raise
            self._pending[generation] = (self._pending[generation][0], future)
            future.add_done_callback(lambda _: self._forget(generation))
            return future

    def _run(self, generation, payload):
        try:
            results = self._request(payload)
            with self._lock:
                sent, _ = self._pending[generation]
                return {n: result for n, result in results.items()
                        if not self._closed and n in sent
                        and self._latest.get(n) == (generation, sent[n])}
        finally:
            self._forget(generation)

    def close(self):
        """Discard outstanding results, cancel queued work, and join HTTP workers.

        Running HTTP exchanges are bounded by the configured socket timeout;
        this does not abort server-side processing.
        """
        with self._lock:
            self._closed = True
            self._latest.clear()
        self._executor.shutdown(wait=True, cancel_futures=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _request(self, payload):
        if not payload["items"]:
            return {}
        req = urllib.request.Request(
            self._url, data=json.dumps(payload).encode(), method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as err:
            detail = err.read().decode("utf-8", "replace")
            if err.code == 400:
                raise ContractError(f"service rejected request: {detail}") from err
            raise RuntimeError(f"analysis service returned {err.code}: {detail}") from err
        return {r["id"]: r["result"] for r in body["results"]}
