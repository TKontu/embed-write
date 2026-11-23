"""SV-05: network guard fails closed (invariant I9)."""

import socket
import threading
import unittest

from service.network_guard import (
    NetworkGuardError,
    NetworkPolicy,
    check_host,
    check_url,
    guard_sockets,
)


class DefaultPolicyTest(unittest.TestCase):
    def test_default_denies_public_ip_and_hostname(self):
        p = NetworkPolicy()
        self.assertFalse(p.remote_enabled)
        for url in ("http://8.8.8.8/", "https://example.com/v1", "http://10.0.0.5:80/"):
            with self.assertRaises(NetworkGuardError, msg=url):
                check_url(url, p)
        with self.assertRaises(NetworkGuardError):
            check_host("example.com", 443, p)

    def test_loopback_allowed(self):
        p = NetworkPolicy()
        for url in ("http://127.0.0.1:8080/v1", "http://localhost/", "http://[::1]:9/",
                    "http://127.5.6.7/", "http://LOCALHOST./"):
            check_url(url, p)
        check_host("::1", 1, p)

    def test_opt_in_allows_only_named_host(self):
        p = NetworkPolicy.allow_remote(["api.example.com"])
        self.assertTrue(p.remote_enabled)
        check_url("https://API.example.com/v1", p)
        for url in ("https://example.com/", "https://evil.api.example.com/", "http://8.8.8.8/"):
            with self.assertRaises(NetworkGuardError, msg=url):
                check_url(url, p)

    def test_opt_in_requires_hosts(self):
        with self.assertRaises(ValueError):
            NetworkPolicy.allow_remote([])
        with self.assertRaises(ValueError):
            NetworkPolicy.allow_remote([""])

    def test_policy_frozen(self):
        with self.assertRaises(Exception):
            NetworkPolicy().allowed_hosts = frozenset({"x"})

    def test_malformed_denied(self):
        p = NetworkPolicy.allow_remote(["api.example.com"])
        for url in ("", "not a url", "http://", "http:///path", "http://[::1", "file:///etc/passwd",
                    "http://127.0.0.1:99999/", None, 42):
            with self.assertRaises(NetworkGuardError, msg=repr(url)):
                check_url(url, p)
        for host in ("", None, "  "):
            with self.assertRaises(NetworkGuardError):
                check_host(host, 80, p)


class GuardSocketsTest(unittest.TestCase):
    def setUp(self):
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(4)
        self.port = self.srv.getsockname()[1]
        self.t = threading.Thread(target=self._accept, daemon=True)
        self.t.start()

    def _accept(self):
        try:
            while True:
                c, _ = self.srv.accept()
                c.close()
        except OSError:
            pass

    def tearDown(self):
        self.srv.close()

    def test_denied_connect_raises_loopback_succeeds_and_restores(self):
        orig_connect = socket.socket.connect
        orig_cc = socket.create_connection
        with guard_sockets(NetworkPolicy()):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                with self.assertRaises(NetworkGuardError):
                    s.connect(("192.0.2.1", 80))  # TEST-NET-1, never reached
            finally:
                s.close()
            with self.assertRaises(NetworkGuardError):
                socket.create_connection(("example.com", 80), timeout=1)
            with socket.create_connection(("127.0.0.1", self.port), timeout=2):
                pass
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.connect(("127.0.0.1", self.port))
            s.close()
        self.assertIs(socket.socket.connect, orig_connect)
        self.assertIs(socket.create_connection, orig_cc)

    def test_restores_on_exception(self):
        orig_connect = socket.socket.connect
        orig_cc = socket.create_connection
        with self.assertRaises(RuntimeError):
            with guard_sockets(NetworkPolicy()):
                self.assertIsNot(socket.socket.connect, orig_connect)
                raise RuntimeError("boom")
        self.assertIs(socket.socket.connect, orig_connect)
        self.assertIs(socket.create_connection, orig_cc)


if __name__ == "__main__":
    unittest.main()
