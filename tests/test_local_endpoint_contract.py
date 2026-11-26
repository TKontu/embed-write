"""Contract test: the three local-model CLIs against a stub OpenAI-compatible server (I9).

The stub mimics the llama.cpp ``llama-server`` / Ollama OpenAI-compatible
``POST /v1/chat/completions`` shape: JSON body ``{model, temperature, messages}`` in, JSON
``{"choices": [{"message": {"role": "assistant", "content": ...}}]}`` out. It binds 127.0.0.1 on an
ephemeral port in a thread; each CLI runs as a real subprocess through ``prelabel.local_model``.
No real model is run. LLM-built synthetic fixtures only.
"""
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest

from experiments import prelabel
from service.network_guard import NetworkGuardError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GENRE = os.path.join(ROOT, 'tests', 'fixtures', 'genre_synthetic_sections.json')
BODY = ' '.join(f'word{i}' for i in range(50))


def reply_for(prompt):
    if prompt.startswith('Label the TARGET'):
        return 'alpha'
    if prompt.startswith('Score how well'):
        return '7'
    return '- a neutral fact\n- another neutral fact'


class Stub(http.server.BaseHTTPRequestHandler):
    seen = []

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get('Content-Length') or 0))
        body = json.loads(raw)
        type(self).seen.append({'path': self.path, 'content_type': self.headers.get('Content-Type'),
                                'body': body})
        if self.path != '/v1/chat/completions':
            self.send_error(404)
            return
        content = reply_for(body['messages'][-1]['content'])
        out = json.dumps({'id': 'stub', 'object': 'chat.completion', 'model': body.get('model'),
                          'choices': [{'index': 0, 'finish_reason': 'stop',
                                       'message': {'role': 'assistant', 'content': content}}]})
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(out)))
        self.end_headers()
        self.wfile.write(out.encode())

    def log_message(self, *args):
        pass


class LocalEndpointContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Stub)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_address[1]}/v1'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        Stub.seen = []
        self.tmp = tempfile.mkdtemp()

    def run_cli(self, module, *args):
        env = {k: v for k, v in os.environ.items() if not k.lower().endswith('_proxy')}
        p = subprocess.run([sys.executable, '-m', module, *args, '--model-url', self.url,
                            '--model-name', 'stub-model'], cwd=ROOT, env=env,
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(p.returncode, 0, p.stderr)
        return json.loads(p.stdout.strip().splitlines()[-1])

    def assert_request_shape(self):
        self.assertTrue(Stub.seen)
        for s in Stub.seen:
            self.assertEqual(s['path'], '/v1/chat/completions')
            self.assertEqual(s['content_type'], 'application/json')
            b = s['body']
            self.assertEqual(set(b), {'model', 'temperature', 'messages'})
            self.assertEqual(b['model'], 'stub-model')
            self.assertEqual(len(b['messages']), 1)
            self.assertEqual(b['messages'][0]['role'], 'user')
            self.assertIsInstance(b['messages'][0]['content'], str)

    def read(self, path):
        with open(path, encoding='utf-8') as fh:
            return [json.loads(l) for l in fh if l.strip()]

    def test_prelabel_cli(self):
        items = os.path.join(self.tmp, 'items.jsonl')
        with open(items, 'w', encoding='utf-8') as fh:
            for i in range(3):
                fh.write(json.dumps({'sentence_id': f's{i}', 'doc_id': 'd1',
                                     'section_type': 'findings', 'text': f'Sentence {i}.',
                                     'context': {'heading': 'Findings'}}) + '\n')
        out = os.path.join(self.tmp, 'labels.jsonl')
        summary = self.run_cli('experiments.prelabel', '--items', items, '--genre', GENRE,
                               '--out', out)
        self.assertTrue(summary['exactly_one_label_each'])
        self.assertEqual(summary['invalid_replies'], 0)
        self.assertEqual({r['label'] for r in self.read(out)}, {'alpha'})
        self.assertEqual({r['model'] for r in self.read(out)}, {'stub-model'})
        self.assert_request_shape()
        self.assertEqual(len(Stub.seen), 3)
        self.assertEqual({s['body']['temperature'] for s in Stub.seen}, {0})

    def test_g02_notes_cli(self):
        corpus = os.path.join(self.tmp, 'corpus')
        os.makedirs(corpus)
        for i in range(8):
            with open(os.path.join(corpus, f'r{i}.md'), 'w', encoding='utf-8') as fh:
                fh.write(f'# Findings\n\nr{i} findings {BODY}\n\n# Conclusions\n\nr{i} end {BODY}\n')
        out = os.path.join(self.tmp, 'notes.jsonl')
        summary = self.run_cli('experiments.g02_notes', '--corpus', corpus, '--genre', GENRE,
                               '--split-seed', '0', '--test-fraction', '0.5', '--n', '2',
                               '--out', out)
        self.assertEqual(summary['selected'], 2)
        self.assertEqual(summary['records'], 2)
        recs = self.read(out)
        self.assertTrue(all('neutral fact' in r['notes'] for r in recs))
        self.assert_request_shape()
        self.assertEqual(len(Stub.seen), 2)
        self.assertEqual({s['body']['temperature'] for s in Stub.seen}, {0})

    def test_g02_generate_cli(self):
        notes = os.path.join(self.tmp, 'notes.jsonl')
        pool = os.path.join(self.tmp, 'pool.jsonl')
        with open(notes, 'w', encoding='utf-8') as fh:
            fh.write(json.dumps({'section_id': 'r0-s0', 'report_id': 'r0',
                                 'section_type': 'findings', 'notes': 'a shared fact'}) + '\n')
        with open(pool, 'w', encoding='utf-8') as fh:
            for j in range(3):
                fh.write(json.dumps({'section_id': f'ex{j}', 'report_id': f'p{j}',
                                     'section_type': 'findings',
                                     'text': f'Exemplar {j} about a shared fact.'}) + '\n')
        out = os.path.join(self.tmp, 'gen.jsonl')
        summary = self.run_cli('experiments.g02_generate', '--notes', notes, '--pool', pool,
                               '--out', out, '--expected-sections', '1', '--n-candidates', '2')
        self.assertTrue(summary['complete'], summary)
        self.assertEqual(summary['arm_counts'], {'A': 1, 'B': 1, 'C': 1})
        self.assertFalse(summary['c_deterministic'])
        self.assert_request_shape()
        temps = [s['body']['temperature'] for s in Stub.seen]
        critic = [s for s in Stub.seen
                  if s['body']['messages'][0]['content'].startswith('Score how well')]
        self.assertEqual(len(critic), 2)
        self.assertIn(0.7, temps)  # arm C candidates sample at DEFAULT_C_TEMPERATURE
        self.assertIn(0, temps)    # arms A/B and the critic stay deterministic
        self.assertEqual(len(Stub.seen), 1 + 1 + 2 + 2)

    def test_non_loopback_url_fails_closed(self):
        for url in ('http://10.0.0.5:8080/v1', 'http://example.com/v1'):
            with self.assertRaises(NetworkGuardError):
                prelabel.local_model(url)
        self.assertEqual(Stub.seen, [])


if __name__ == '__main__':
    unittest.main()
