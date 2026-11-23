"""Analysis client (SV-03): posts only dirty nodes to the local AnalysisService.

Production caller of ``AnalysisService``. Unwired by design until the editor client
(todo-03/todo-05) calls it. The base URL is checked with ``check_url`` (SV-05) at construction.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Mapping

from service.contract import ContractError, build_request
from service.network_guard import NetworkPolicy, check_url


class AnalysisClient:
    def __init__(self, base_url: str, policy: NetworkPolicy = NetworkPolicy(), timeout: float = 30):
        check_url(base_url, policy)  # fail closed before any request
        self._url = base_url.rstrip("/") + "/v1/batch"
        self._timeout = timeout

    def analyze(self, current: Mapping[str, str], known_hashes: Mapping[str, str]) -> dict:
        """Send the dirty nodes of ``current``; return ``{node_id: result}`` (empty, no request,
        when nothing is dirty)."""
        payload = build_request(current, known_hashes)
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
