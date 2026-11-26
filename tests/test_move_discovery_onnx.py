"""MV-02: --embedder onnx CLI paths with fakes; no model, offline. LLM-built fixtures."""
from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from experiments import move_discovery as md
from service.candidates import OnnxEmbedder
from tests.test_move_discovery import GENRE_PATH, SEPARABLE, Base, MarkerEmbedder, sentence_doc


class FakeOnnx(MarkerEmbedder):
    model_id, model_version = 'BAAI/bge-m3', 'hf-unpinned'


class OnnxCliTests(Base):
    def run_cli(self, *extra):
        out = self.root / 'out.json'
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = md.main(['report', str(self.corpus), GENRE_PATH, str(out), *extra])
        return code, out, stderr.getvalue()

    def model_dir(self, *files):
        d = self.root / 'model'
        d.mkdir()
        for name in files:
            (d / name).write_bytes(b'')
        return d

    def test_onnx_needs_model_dir(self):
        code, out, stderr = self.run_cli('--embedder', 'onnx')
        self.assertEqual(code, 2)
        self.assertEqual(len(stderr.strip().splitlines()), 1)
        self.assertIn('--model-dir', stderr)
        self.assertFalse(out.exists())

    def test_missing_dir_exits_2_with_one_line(self):
        code, out, stderr = self.run_cli('--embedder', 'onnx', '--model-dir',
                                         str(self.root / 'nope'))
        self.assertEqual(code, 2)
        self.assertEqual(len(stderr.strip().splitlines()), 1)
        self.assertIn('model directory not found', stderr)
        self.assertFalse(out.exists())

    def test_missing_file_exits_2(self):
        for present, missing in ((('tokenizer.json',), 'model.onnx'),
                                 (('model.onnx',), 'tokenizer.json')):
            with self.subTest(missing=missing):
                d = self.model_dir(*present)
                code, _, stderr = self.run_cli('--embedder', 'onnx', '--model-dir', str(d))
                self.assertEqual(code, 2)
                self.assertIn(missing, stderr)
                self.assertEqual(len(stderr.strip().splitlines()), 1)
                for p in d.iterdir():
                    p.unlink()
                d.rmdir()

    def test_model_dir_without_onnx_rejected(self):
        with self.assertRaises(SystemExit), redirect_stderr(io.StringIO()):
            self.run_cli('--model-dir', str(self.root))

    def test_make_embedder_builds_onnx_candidate(self):
        d = self.model_dir('model.onnx', 'tokenizer.json')
        e = md.make_embedder('onnx', str(d), 'bge-m3')
        self.assertIsInstance(e, OnnxEmbedder)
        self.assertEqual((e.model_id, e.dims), ('BAAI/bge-m3', 1024))
        self.assertIsInstance(md.make_embedder('hash'), md.HashEmbedder)
        with self.assertRaises(md.DiscoveryError):
            md.make_embedder('onnx', str(d), 'nope')

    def test_onnx_report_has_no_development_warning(self):
        self.write('r.md', sentence_doc(findings=SEPARABLE))
        d = self.model_dir('model.onnx', 'tokenizer.json')
        with mock.patch.object(md, 'make_embedder', return_value=FakeOnnx()) as make:
            code, out, stderr = self.run_cli('--embedder', 'onnx', '--model-dir', str(d),
                                             '--k', '2')
        self.assertEqual(code, 0, stderr)
        make.assert_called_once_with('onnx', str(d), 'bge-m3')
        report = json.loads(out.read_text(encoding='utf-8'))
        self.assertEqual(report['warnings'], [])
        self.assertFalse(report['embedder']['development_only'])
        self.assertEqual(report['embedder']['model_id'], 'BAAI/bge-m3')


if __name__ == '__main__':
    unittest.main()
