"""Contract tests for SV-03: the client sends dirty node sets, never whole documents."""

import json
import unittest
import urllib.error
import urllib.request

from service.client import AnalysisClient
from service.contract import (
    ContractError,
    build_request,
    dirty_nodes,
    node_hash,
    validate_items,
)
from service.network_guard import NetworkGuardError
from service.server import AnalysisService


class RecordingHandler:
    def __init__(self):
        self.calls = []

    def __call__(self, items):
        self.calls.append(list(items))
        return [item["text"].upper() for item in items]


def _item(node_id, text):
    return {"id": node_id, "hash": node_hash(text), "text": text}


def _post(service, payload):
    host, port = service.address
    req = urllib.request.Request(
        f"http://{host}:{port}/v1/batch", data=json.dumps(payload).encode(), method="POST"
    )
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as err:
        return err.code, json.loads(err.read())


class ContractUnitTest(unittest.TestCase):
    def test_node_hash_is_sha256_hex(self):
        self.assertEqual(
            node_hash("abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        )

    def test_dirty_nodes_only_changed_or_new_in_current_order(self):
        current = {"n3": "new", "n1": "same", "n2": "edited"}
        known = {"n1": node_hash("same"), "n2": node_hash("old"), "gone": node_hash("x")}
        self.assertEqual(dirty_nodes(current, known), [_item("n3", "new"), _item("n2", "edited")])
        self.assertEqual(dirty_nodes({"n1": "same"}, known), [])

    def test_build_request(self):
        self.assertEqual(build_request({"a": "t"}, {}), {"items": [_item("a", "t")]})

    def test_validate_items_rejects(self):
        cases = {
            "missing hash": [{"id": "a", "text": "t"}],
            "mismatch": [{"id": "a", "hash": node_hash("other"), "text": "t"}],
            "duplicate": [_item("a", "t"), _item("a", "u")],
            "too long": [_item("a", "x" * 11)],
        }
        for name, items in cases.items():
            with self.subTest(name), self.assertRaises(ContractError):
                validate_items(items, max_node_chars=10)
        validate_items([_item("a", "x" * 10), _item("b", "y")], max_node_chars=10)


class ClientServiceTest(unittest.TestCase):
    def test_only_dirty_nodes_sent(self):
        handler = RecordingHandler()
        current = {"p1": "unchanged", "p2": "changed now", "p3": "brand new"}
        known = {"p1": node_hash("unchanged"), "p2": node_hash("changed before")}
        with AnalysisService(handler) as svc:
            host, port = svc.address
            results = AnalysisClient(f"http://{host}:{port}").analyze(current, known)
        self.assertEqual(results, {"p2": "CHANGED NOW", "p3": "BRAND NEW"})
        self.assertEqual(len(handler.calls), 1)
        self.assertEqual([it["id"] for it in handler.calls[0]], ["p2", "p3"])
        self.assertNotIn("unchanged", json.dumps(handler.calls))

    def test_empty_dirty_set_sends_no_request(self):
        handler = RecordingHandler()
        with AnalysisService(handler) as svc:
            host, port = svc.address
            client = AnalysisClient(f"http://{host}:{port}")
            self.assertEqual(client.analyze({"a": "t"}, {"a": node_hash("t")}), {})
            self.assertEqual(client.analyze({}, {}), {})
        self.assertEqual(handler.calls, [])

    def test_server_rejects_contract_violations_400(self):
        handler = RecordingHandler()
        with AnalysisService(handler, max_node_chars=10) as svc:
            cases = [
                {"items": [{"id": "a", "text": "t"}]},
                {"items": [{"id": "a", "hash": node_hash("x"), "text": "t"}]},
                {"items": [_item("a", "t"), _item("a", "t")]},
                {"items": [_item("a", "x" * 11)]},
                {"items": [{"id": "a", "hash": 5, "text": "t"}]},
            ]
            for case in cases:
                with self.subTest(case=case):
                    status, body = _post(svc, case)
                    self.assertEqual(status, 400)
                    self.assertIn("error", body)
            self.assertEqual(_post(svc, {"items": [_item("a", "x" * 10)]})[0], 200)
        self.assertEqual(len(handler.calls), 1)

    def test_client_error_raised_on_rejection(self):
        with AnalysisService(RecordingHandler(), max_node_chars=3) as svc:
            host, port = svc.address
            with self.assertRaises(ContractError):
                AnalysisClient(f"http://{host}:{port}").analyze({"a": "long text"}, {})

    def test_client_refuses_non_loopback(self):
        with self.assertRaises(NetworkGuardError):
            AnalysisClient("http://192.0.2.1:8080")


if __name__ == "__main__":
    unittest.main()
