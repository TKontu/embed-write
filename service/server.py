"""Local analysis service (SV-01): loopback HTTP, batched requests, stdlib only.

Endpoints: ``GET /v1/health`` and ``POST /v1/batch`` with ``{"items": [{"id", "text"}, ...]}``.
The handler is called once per request with the whole item list and returns one result per item.

Wires SV-05: the bind host is checked with ``check_host`` (fail closed) and the service runs inside
``guard_sockets`` for its lifetime, so outbound connects made by handlers are guarded.
SV-03: ``/v1/batch`` enforces the dirty-node contract (``service.contract.validate_items``) unless
constructed with ``contract=False``. Production client: ``service.client.AnalysisClient``.
"""

from __future__ import annotations

import contextlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Sequence

from service.contract import DEFAULT_MAX_NODE_CHARS, ContractError, validate_items
from service.network_guard import NetworkGuardError, NetworkPolicy, check_host, guard_sockets

Handler = Callable[[Sequence[dict]], Sequence[Any]]


def echo_handler(items: Sequence[dict]) -> list:
    """Test handler: returns each item's text."""
    return [item["text"] for item in items]


class _BadRequest(Exception):
    pass


def _parse_items(raw: bytes, max_batch: int, max_node_chars: int | None = None) -> list:
    """Parse a batch; when ``max_node_chars`` is set, enforce the SV-03 dirty-node contract."""
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise _BadRequest(f"malformed JSON: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise _BadRequest("body must be an object with an 'items' list")
    items = payload["items"]
    if len(items) > max_batch:
        raise _BadRequest(f"batch of {len(items)} exceeds max_batch {max_batch}")
    for i, item in enumerate(items):
        if not (
            isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and isinstance(item.get("text"), str)
        ):
            raise _BadRequest(f"items[{i}] must have string 'id' and 'text'")
    if max_node_chars is not None:
        try:
            validate_items(items, max_node_chars)
        except ContractError as exc:
            raise _BadRequest(f"contract: {exc}") from exc
    return [{"id": item["id"], "text": item["text"]} for item in items]


class AnalysisService:
    """Loopback-only HTTP analysis service dispatching batches to a pluggable handler."""

    def __init__(
        self,
        handler: Handler,
        host: str = "127.0.0.1",
        port: int = 0,
        policy: NetworkPolicy = NetworkPolicy(),
        max_batch: int = 256,
        max_body_bytes: int = 1 << 20,
        contract: bool = True,
        max_node_chars: int = DEFAULT_MAX_NODE_CHARS,
    ):
        check_host(host, port, policy)  # fail closed before binding
        self._handler = handler
        self._policy = policy
        self._max_batch = max_batch
        self._max_body = max_body_bytes
        self._max_node_chars = max_node_chars if contract else None
        self._server = ThreadingHTTPServer((host, port), self._make_request_handler())
        self._server.daemon_threads = True
        self._thread: threading.Thread | None = None
        self._guard: contextlib.ExitStack | None = None

    @property
    def address(self) -> tuple:
        return self._server.server_address[:2]

    def start(self) -> "AnalysisService":
        if self._thread is not None:
            return self
        guard = contextlib.ExitStack()
        guard.enter_context(guard_sockets(self._policy))
        self._guard = guard
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._thread is not None:
            self._server.shutdown()
            self._thread.join()
            self._thread = None
        self._server.server_close()
        if self._guard is not None:
            self._guard.close()
            self._guard = None

    def __enter__(self) -> "AnalysisService":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    def _make_request_handler(self):
        service = self

        class _RequestHandler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # keep test output quiet
                pass

            def _send(self, status: int, body: dict) -> None:
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                if self.path == "/v1/health":
                    self._send(200, {"status": "ok"})
                else:
                    self._send(404, {"error": f"unknown path {self.path}"})

            def do_POST(self):
                if self.path != "/v1/batch":
                    self.close_connection = True
                    self._send(404, {"error": f"unknown path {self.path}"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", ""))
                except ValueError:
                    self.close_connection = True
                    self._send(400, {"error": "Content-Length required"})
                    return
                if length < 0 or length > service._max_body:
                    self.close_connection = True
                    self._send(413, {"error": f"body exceeds {service._max_body} bytes"})
                    return
                try:
                    items = _parse_items(
                        self.rfile.read(length), service._max_batch, service._max_node_chars
                    )
                except _BadRequest as exc:
                    self._send(400, {"error": str(exc)})
                    return
                try:
                    outputs = list(service._handler(items))
                    if len(outputs) != len(items):
                        raise ValueError(
                            f"handler returned {len(outputs)} results for {len(items)} items"
                        )
                    results = [{"id": it["id"], "result": out} for it, out in zip(items, outputs)]
                    data = {"results": results}
                    json.dumps(data)
                except NetworkGuardError as exc:
                    self._send(500, {"error": f"network guard: {exc}"})
                    return
                except Exception as exc:  # handler failure must not take the server down
                    self._send(500, {"error": f"handler failed: {type(exc).__name__}: {exc}"})
                    return
                self._send(200, data)

        return _RequestHandler
