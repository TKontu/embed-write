"""CO-10 / invariant I9: every corpus path that takes an endpoint URL fails closed on a remote host.

Paths: experiments.prelabel.local_model (+ its CLI), experiments.g02_generate CLI (via local_model)
and service.client.AnalysisClient. Sockets and urlopen are patched to fail the test if touched.
Synthetic inputs only; no network access.
"""

import json
import os
import socket
import tempfile
import unittest
import urllib.request
from contextlib import ExitStack, contextmanager
from unittest import mock

from experiments import g02_generate, prelabel
from service.client import AnalysisClient
from service.network_guard import NetworkGuardError, NetworkPolicy

REMOTE = 'http://example.com/v1'
LOOPBACK = 'http://127.0.0.1:8080/v1'


def _no_net(*_a, **_k):
    raise AssertionError('network touched')


@contextmanager
def no_network():
    with ExitStack() as st:
        st.enter_context(mock.patch.object(urllib.request, 'urlopen', _no_net))
        st.enter_context(mock.patch.object(socket.socket, 'connect', _no_net))
        st.enter_context(mock.patch.object(socket.socket, 'connect_ex', _no_net))
        st.enter_context(mock.patch.object(socket, 'create_connection', _no_net))
        st.enter_context(mock.patch.object(socket, 'getaddrinfo', _no_net))
        yield


class LocalModelGuard(unittest.TestCase):
    def test_remote_denied_without_opt_in(self):
        with no_network(), self.assertRaises(NetworkGuardError):
            prelabel.local_model(REMOTE)

    def test_loopback_passes(self):
        with no_network():
            self.assertTrue(callable(prelabel.local_model(LOOPBACK)))

    def test_remote_needs_named_host(self):
        with no_network():
            prelabel.local_model(REMOTE, policy=NetworkPolicy.allow_remote(['example.com']))
            with self.assertRaises(NetworkGuardError):
                prelabel.local_model(REMOTE, policy=NetworkPolicy.allow_remote(['other.org']))


class PrelabelCliGuard(unittest.TestCase):
    def test_remote_cli_fails_closed(self):
        with tempfile.TemporaryDirectory() as d, no_network(), \
                mock.patch.object(prelabel, 'load_genre', return_value={}):
            items = os.path.join(d, 'items.jsonl')
            with open(items, 'w', encoding='utf-8') as fh:
                fh.write(json.dumps({'sentence_id': 's1', 'text': 'synthetic'}) + '\n')
            out = os.path.join(d, 'out.jsonl')
            with self.assertRaises(NetworkGuardError):
                prelabel.main(['--items', items, '--genre', 'g', '--model-url', REMOTE,
                               '--out', out])
            self.assertFalse(os.path.exists(out))


class G02CliGuard(unittest.TestCase):
    def test_remote_cli_fails_closed(self):
        with tempfile.TemporaryDirectory() as d, no_network():
            notes = os.path.join(d, 'notes.jsonl')
            pool = os.path.join(d, 'pool.jsonl')
            for p in (notes, pool):
                open(p, 'w', encoding='utf-8').close()
            out = os.path.join(d, 'out.jsonl')
            with self.assertRaises(NetworkGuardError):
                g02_generate.main(['--notes', notes, '--pool', pool, '--out', out,
                                   '--model-url', REMOTE])
            self.assertFalse(os.path.exists(out))


class AnalysisClientGuard(unittest.TestCase):
    def test_remote_denied_without_opt_in(self):
        with no_network(), self.assertRaises(NetworkGuardError):
            AnalysisClient(REMOTE)

    def test_loopback_passes(self):
        with no_network():
            AnalysisClient(LOOPBACK).close()

    def test_remote_needs_named_host(self):
        with no_network():
            AnalysisClient(REMOTE, policy=NetworkPolicy.allow_remote(['example.com'])).close()
            with self.assertRaises(NetworkGuardError):
                AnalysisClient(REMOTE, policy=NetworkPolicy.allow_remote(['other.org']))


if __name__ == '__main__':
    unittest.main()
