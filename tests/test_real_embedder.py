"""MV-02/EM-02 real-model checks; skipped unless EMBED_WRITE_MODEL_DIR holds model.onnx.

Sentences are LLM-built synthetic. Needs onnxruntime/tokenizers (requirements.txt).
"""
from __future__ import annotations

import io
import json
import math
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from experiments import move_discovery as md
from service.candidates import CANDIDATES, OnnxEmbedder
from service.embedder import embed
from service.vectors import Level

MODEL_DIR = os.environ.get('EMBED_WRITE_MODEL_DIR', '')
HAVE_MODEL = bool(MODEL_DIR) and os.path.isfile(os.path.join(MODEL_DIR, 'model.onnx'))
ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / 'examples' / 'demo'

PARAPHRASE = ('The meeting was postponed because the chair was ill.',
              'Because the chairperson was sick, the meeting was delayed.')
UNRELATED = 'Copper conducts electricity better than most metals.'
BATCH = ('Short one.', 'A considerably longer sentence about rivers, hills and the weather.',
         'Numbers like 42 and 3.14 appear here.', 'Tämä on suomenkielinen lause.',
         'Questions? Yes, sometimes.', 'The quick brown fox jumps over the lazy dog.',
         'Another line.', 'Final sentence of the batch, with a comma.')


def cosine(a, b):
    return math.fsum(x * y for x, y in zip(a, b))


@unittest.skipUnless(HAVE_MODEL, 'EMBED_WRITE_MODEL_DIR does not point at a model.onnx directory')
class RealEmbedderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        bge = {c.model_id: c for c in CANDIDATES}['BAAI/bge-m3']
        cls.embedder = OnnxEmbedder(bge, MODEL_DIR)

    def vectors(self, texts):
        return [v.values for v in embed(self.embedder, list(texts), Level.SENTENCE)]

    def test_dims_and_unit_norm(self):
        for v in self.vectors(PARAPHRASE):
            self.assertEqual(len(v), 1024)
            self.assertAlmostEqual(math.sqrt(cosine(v, v)), 1.0, places=5)

    def test_paraphrases_closer_than_unrelated(self):
        a, b, c = self.vectors(PARAPHRASE + (UNRELATED,))
        self.assertGreater(cosine(a, b), cosine(a, c))
        self.assertGreater(cosine(a, b), cosine(b, c))

    def test_batch_of_one_matches_batch_of_eight(self):
        batch = self.vectors(BATCH)
        for index in (0, 1, 3):
            single = self.vectors([BATCH[index]])[0]
            self.assertLess(max(abs(x - y) for x, y in zip(single, batch[index])), 1e-4)

    def test_demo_report_has_no_development_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'report.json'
            stderr = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                code = md.main(['report', str(DEMO), str(DEMO / 'genre.json'), str(out),
                                '--embedder', 'onnx', '--model-dir', MODEL_DIR])
            self.assertEqual(code, 0, stderr.getvalue())
            report = json.loads(out.read_text(encoding='utf-8'))
        self.assertEqual(report['warnings'], [])
        self.assertEqual((report['embedder']['model_id'], report['embedder']['dims'],
                          report['embedder']['development_only']),
                         ('BAAI/bge-m3', 1024, False))


if __name__ == '__main__':
    unittest.main()
