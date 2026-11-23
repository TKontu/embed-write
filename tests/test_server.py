"""Integration tests for the local analysis service (SV-01) with a stub urllib client."""

import json
import socket
import unittest
import urllib.error
import urllib.request

from service.network_guard import NetworkGuardError, NetworkPolicy
from service.server import AnalysisService, echo_handler


def _call(service, method, path, body=None):
    host, port = service.address
    req = urllib.request.Request(f"http://{host}:{port}{path}", data=body, method=method)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


def _post(service, payload):
    data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return _call(service, "POST", "/v1/batch", data)


class RecordingHandler:
    def __init__(self):
        self.calls = []

    def __call__(self, items):
        self.calls.append(list(items))
        return [item["text"].upper() for item in items]


class AnalysisServiceTest(unittest.TestCase):
    def test_health(self):
        with AnalysisService(echo_handler) as svc:
            self.assertEqual(_call(svc, "GET", "/v1/health"), (200, {"status": "ok"}))

    def test_batch_in_order_single_handler_call(self):
        handler = RecordingHandler()
        items = [{"id": "a", "text": "x"}, {"id": "b", "text": "y"}, {"id": "c", "text": "z"}]
        with AnalysisService(handler) as svc:
            status, body = _post(svc, {"items": items})
        self.assertEqual(status, 200)
        self.assertEqual(
            body["results"],
            [{"id": "a", "result": "X"}, {"id": "b", "result": "Y"}, {"id": "c", "result": "Z"}],
        )
        self.assertEqual(handler.calls, [items])

    def test_bad_requests_400(self):
        with AnalysisService(echo_handler, max_batch=2) as svc:
            cases = [
                b"{not json",
                {"items": "nope"},
                {"nope": []},
                {"items": [{"id": 1, "text": "x"}]},
                {"items": [{"id": "a"}]},
                {"items": ["a"]},
                [1, 2],
                {"items": [{"id": str(i), "text": "t"} for i in range(3)]},
            ]
            for case in cases:
                with self.subTest(case=case):
                    status, body = _post(svc, case)
                    self.assertEqual(status, 400)
                    self.assertIn("error", body)
            self.assertEqual(_call(svc, "GET", "/v1/health")[0], 200)

    def test_oversize_body_413(self):
        with AnalysisService(echo_handler, max_body_bytes=64) as svc:
            status, body = _post(svc, {"items": [{"id": "a", "text": "x" * 200}]})
        self.assertEqual(status, 413)
        self.assertIn("error", body)

    def test_unknown_path_404(self):
        with AnalysisService(echo_handler) as svc:
            self.assertEqual(_call(svc, "GET", "/nope")[0], 404)
            self.assertEqual(_call(svc, "POST", "/nope", b"{}")[0], 404)

    def test_non_loopback_bind_refused(self):
        with self.assertRaises(NetworkGuardError):
            AnalysisService(echo_handler, host="0.0.0.0")
        with self.assertRaises(NetworkGuardError):
            AnalysisService(echo_handler, host="192.0.2.1")

    def test_handler_outbound_connect_denied_500(self):
        seen = []

        def leaky(items):
            try:
                socket.create_connection(("192.0.2.1", 80), timeout=1)
            except NetworkGuardError as exc:
                seen.append(exc)
                raise
            return [None for _ in items]

        with AnalysisService(leaky, policy=NetworkPolicy()) as svc:
            status, body = _post(svc, {"items": [{"id": "a", "text": "x"}]})
            self.assertEqual(status, 500)
            self.assertIn("error", body)
            self.assertEqual(len(seen), 1)
            self.assertEqual(_call(svc, "GET", "/v1/health")[0], 200)

    def test_stop_releases_port(self):
        svc = AnalysisService(echo_handler)
        svc.start()
        host, port = svc.address
        svc.stop()
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind((host, port))
        finally:
            s.close()


if __name__ == "__main__":
    unittest.main()
