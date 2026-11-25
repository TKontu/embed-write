"""Offline GE-05 acceptance checks; no model or network required."""
import io
import json
import threading
import unittest
from unittest.mock import patch

from generation import llm_client
from generation.run_record import SamplingParams


def event(delta):
    return ('data: ' + json.dumps({'choices': [{'delta': delta}]},
                                  ensure_ascii=False) + '\n\n').encode()


DONE = b'data: [DONE]\n\n'


class GuardedResponse(io.BytesIO):
    """Reject reads beyond the currently consumable event, including read-ahead."""
    def __init__(self, raw, allowed):
        super().__init__(raw)
        self.allowed = allowed
        self.consumed = 0

    def read(self, size=-1):
        if size < 0 or self.tell() + size > self.allowed:
            raise AssertionError('read beyond consumed event')
        result = super().read(size)
        self.consumed += len(result)
        return result


class StreamingTests(unittest.TestCase):
    params = SamplingParams(17, 0.4, 0.9, 80)

    def client(self, response):
        def transport(request):
            self.request = request
            return response
        return llm_client.LLMClient('http://localhost:8000/v1/', 'm', transport=transport)

    def test_payload_matches_complete(self):
        self.client(io.BytesIO(b'{"choices":[{"message":{"content":"a"}}]}')).complete('p', self.params)
        original = self.request
        self.assertEqual(list(self.client(io.BytesIO(DONE)).stream('p', self.params)), [])
        payload = json.loads(original.data)
        payload['stream'] = True
        self.assertEqual(json.loads(self.request.data), payload)
        self.assertEqual(self.request.full_url, original.full_url)
        self.assertEqual(self.request.get_method(), 'POST')
        self.assertEqual(self.request.headers, original.headers)

    def test_chunks_and_empty_deltas(self):
        raw = event({'role': 'assistant'}) + event({}) + event({'content': ''})
        raw += event({'content': 'hé'}) + event({'content': 'llo'}) + DONE
        response = io.BytesIO(raw.replace(b'\n', b'\r\n'))
        chunks = list(self.client(response).stream('p', self.params))
        self.assertEqual(chunks, ['hé', 'llo'])
        self.assertEqual(''.join(chunks), 'héllo')
        self.assertTrue(response.closed)

    def test_incremental_and_done_no_read_ahead(self):
        first, second = event({'content': 'one'}), event({'content': 'two'})
        response = GuardedResponse(first + second + DONE + b'forbidden', len(first))
        stream = self.client(response).stream('p', self.params)
        self.assertEqual(next(stream), 'one')
        response.allowed = len(first + second)
        self.assertEqual(next(stream), 'two')
        response.allowed = len(first + second + DONE) - 1
        self.assertEqual(list(stream), [])
        self.assertTrue(response.closed)

    def test_cancel_between_chunks(self):
        first = event({'content': 'one'})
        response = GuardedResponse(first + event({'content': 'two'}), len(first))
        cancel = threading.Event()
        stream = self.client(response).stream('p', self.params, cancel=cancel)
        self.assertEqual(next(stream), 'one')
        consumed = response.consumed
        cancel.set()
        self.assertEqual(list(stream), [])
        self.assertEqual(response.consumed, consumed)
        self.assertTrue(response.closed)

    def test_cancel_before_start_sends_no_request(self):
        cancel = threading.Event()
        cancel.set()
        with patch.object(llm_client, 'build_opener') as build:
            client = llm_client.LLMClient('http://localhost', 'm')
            self.assertEqual(list(client.stream('p', self.params, cancel=cancel)), [])
            build.assert_not_called()

    def test_generator_close_closes_response(self):
        response = io.BytesIO(event({'content': 'one'}) + DONE)
        stream = self.client(response).stream('p', self.params)
        self.assertEqual(next(stream), 'one')
        stream.close()
        self.assertTrue(response.closed)

    def test_malformed_events_are_sanitized_and_closed(self):
        for raw in (b'data: private-invalid\n\n', b'data: \xff\n\n',
                    b'data: {}\n\n', b'data: null\n\n',
                    event({'content': 3}), event({'content': None}),
                    event({'content': ['private']}), event({'content': 'ok'})):
            with self.subTest(raw=raw):
                response = io.BytesIO(raw)
                with self.assertRaises(ValueError) as caught:
                    list(self.client(response).stream('p', self.params))
                self.assertNotIn('private', str(caught.exception))
                self.assertIsNone(caught.exception.__cause__)
                self.assertTrue(response.closed)

    def test_line_and_total_byte_caps(self):
        for raw in (b':' + b'x' * (1024 * 1024) + b'\n' + DONE,
                    (b':' + b'x' * 1022 + b'\n') * 4096 + DONE):
            response = io.BytesIO(raw)
            with self.assertRaisesRegex(ValueError, 'limit'):
                list(self.client(response).stream('p', self.params))
            self.assertTrue(response.closed)

    def test_default_transport_policy(self):
        with patch.object(llm_client, 'build_opener') as build:
            build.return_value.open.return_value = io.BytesIO(DONE)
            client = llm_client.LLMClient('http://localhost/v1', 'm')
            self.assertEqual(list(client.stream('p', self.params)), [])
            self.assertEqual(build.return_value.open.call_args.kwargs, {'timeout': 30})
            request = build.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, 'http://127.0.0.1/v1/chat/completions')
            handlers = build.call_args.args
            self.assertTrue(any(getattr(h, 'proxies', None) == {} for h in handlers))
            redirect = next(h for h in handlers if isinstance(h, llm_client.HTTPRedirectHandler))
            with self.assertRaises(ValueError):
                redirect.redirect_request(request, None, 302, 'Found', {}, 'http://example.com')

    def test_invalid_inputs_send_no_request(self):
        for prompt, params in ((None, self.params), ('p', None)):
            with self.subTest(prompt=prompt), patch.object(llm_client, 'build_opener') as build:
                with self.assertRaises(ValueError):
                    list(llm_client.LLMClient('http://localhost', 'm').stream(prompt, params))
                build.assert_not_called()
