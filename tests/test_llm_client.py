"""Offline checks for the GE-04 endpoint boundary."""
import io
import json
import unittest
from unittest.mock import patch

from generation import llm_client
from generation.candidates import vary_sampling
from generation.run_record import SamplingParams, GenerationRunRecord, replay


class ClientTests(unittest.TestCase):
    params = SamplingParams(17, 0.4, 0.9, 80)

    def fake(self, request):
        self.request = request
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": "answer"}}]}).encode())

    def test_request_and_text(self):
        client = llm_client.LLMClient('http://localhost:8000/v1/', 'local-model', transport=self.fake)
        self.assertEqual(client.complete('rewrite', self.params), 'answer')
        self.assertEqual(self.request.full_url, 'http://127.0.0.1:8000/v1/chat/completions')
        self.assertEqual(self.request.get_method(), 'POST')
        self.assertEqual(json.loads(self.request.data), dict(
            model='local-model', messages=[dict(role='user', content='rewrite')],
            stream=False, **self.params.to_dict()))

    def test_loopback_hosts(self):
        for host in ('localhost', 'LOCALHOST', '127.0.0.1', '127.23.4.5', '[::1]'):
            with self.subTest(host=host):
                client = llm_client.LLMClient('http://' + host + '/v1', 'm', transport=self.fake)
                self.assertEqual(client.complete('p', self.params), 'answer')

    def test_remote_requires_explicit_opt_in_for_each_client(self):
        for host in ('example.com', '192.168.1.1', 'localhost.example.com', '127.0.0.1.example.com', '[::ffff:127.0.0.1]'):
            with self.subTest(host=host):
                with self.assertRaisesRegex(ValueError, 'remote'):
                    llm_client.LLMClient('http://' + host, 'm', transport=self.fake)
                client = llm_client.LLMClient('http://' + host, 'm', allow_remote=True, transport=self.fake)
                self.assertEqual(client.complete('p', self.params), 'answer')
                with self.assertRaises(ValueError):
                    llm_client.LLMClient('http://' + host, 'm')

    def test_invalid_urls(self):
        for url in ('file:///tmp/model', 'http://', 'http://localhost:bad',
                    'http://user:pass@localhost', 'http://localhost?q=x',
                    'http://localhost/#fragment', 'http://local\nhost'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                llm_client.LLMClient(url, 'm', allow_remote=True)

    def test_malformed_response(self):
        for raw in (b'bad', b'\xff', b'{}', b'null', b'[]', b'{"choices": []}',
                    b'{"choices": [{"message": {"content": null}}]}'):
            response = io.BytesIO(raw)
            client = llm_client.LLMClient('http://localhost', 'm', transport=lambda req: response)
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, 'response'):
                client.complete('p', self.params)
            self.assertTrue(response.closed)

    def test_response_read_is_bounded(self):
        class Response(io.BytesIO):
            def read(self, size=-1):
                self.size = size
                return super().read(size)
        response = Response(b'x' * (4 * 1024 * 1024 + 2))
        client = llm_client.LLMClient('http://localhost', 'm', transport=lambda req: response)
        with self.assertRaisesRegex(ValueError, 'response.*limit'):
            client.complete('p', self.params)
        self.assertEqual(response.size, 4 * 1024 * 1024 + 1)
        self.assertTrue(response.closed)

    def test_default_transport_disables_proxies_and_redirects(self):
        with patch.object(llm_client, 'build_opener') as build:
            build.return_value.open.return_value = self.fake(None)
            client = llm_client.LLMClient('http://localhost/v1', 'm')
            self.assertEqual(client.complete('p', self.params), 'answer')
            handlers = build.call_args.args
            self.assertTrue(any(getattr(h, 'proxies', None) == {} for h in handlers))
            redirect = next(h for h in handlers if isinstance(h, llm_client.HTTPRedirectHandler))
            with self.assertRaisesRegex(ValueError, 'redirect'):
                redirect.redirect_request(self.request, None, 302, 'Found', {}, 'http://example.com')
            self.assertEqual(build.return_value.open.call_args.kwargs['timeout'], 30)

    def test_varied_candidates_are_recordable_and_replayable(self):
        def generate(request):
            payload = json.loads(request.data)
            return io.BytesIO(json.dumps({'choices': [{'message': {'content': str(payload['seed'])}}]}).encode())
        client = llm_client.LLMClient('http://localhost/v1', 'm', transport=generate)
        sampling = vary_sampling(self.params, 3)
        candidates = [client.complete('p', s) for s in sampling]
        record = GenerationRunRecord.build('p', (), 'm', sampling, candidates)
        self.assertEqual(record.candidates, ('17', '18', '19'))
        self.assertTrue(replay(record, lambda p, e, m, s: client.complete(p, s)))
