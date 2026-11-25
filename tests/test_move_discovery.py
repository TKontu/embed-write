"""MV-02: move-discovery cluster report. LLM-built synthetic fixtures; offline.

Fake embedders and fake model callables only; no corpus text, no network.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import socket
import tempfile
import unittest
import urllib.request
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from experiments import move_discovery as md
from service.embedder import HashEmbedder
from service.genre import load_genre
from service.vectors import LevelVector

GENRE_PATH = os.path.join(os.path.dirname(__file__), 'fixtures', 'genre_synthetic_sections.json')
GENRE = load_genre(GENRE_PATH)


def sentence_doc(*, preamble='', findings=(), odd=(), conclusions=()):
    """A Markdown document whose headings map to the fixture genre's section types."""
    parts = []
    if preamble:
        parts.append(preamble)
    if findings:
        parts.extend(('## Findings', ' '.join(findings)))
    if odd:
        parts.extend(('## Odd heading', ' '.join(odd)))
    if conclusions:
        parts.extend(('## Conclusions', ' '.join(conclusions)))
    return '\n\n'.join(parts) + '\n'


class MarkerEmbedder:
    """Two clearly separable directions plus a deterministic tiny per-text offset."""

    model_id = 'marker-fake'
    model_version = '2'
    dims = 2

    def __init__(self):
        self.calls = []

    def embed(self, texts, level):
        self.calls.append(list(texts))
        out = []
        for text in texts:
            digest = int.from_bytes(hashlib.sha256(text.encode('utf-8')).digest()[:4], 'big')
            noise = 0.02 * (2 * digest / 2**32 - 1)
            low = text.lower()
            if 'alpha' in low:
                values = (1.0, noise)
            elif 'beta' in low:
                values = (noise, 1.0)
            else:
                values = (noise, -1.0)
            out.append(LevelVector(level, values))
        return out


class HashVectorEmbedder:
    """Deterministic pseudo-random unit-ish vectors, for seed-behaviour checks."""

    model_id = 'hash-vectors-fake'
    model_version = '1'
    dims = 8

    def embed(self, texts, level):
        out = []
        for text in texts:
            digest = hashlib.sha256(text.encode('utf-8')).digest()
            values = tuple(
                int.from_bytes(digest[i * 4:(i + 1) * 4], 'big') / 2**31 - 1
                for i in range(8)
            )
            out.append(LevelVector(level, values))
        return out


class AngleEmbedder:
    """Maps each known sentence to a fixed angle on the unit circle."""

    model_id = 'angle-fake'
    model_version = '1'
    dims = 2

    def __init__(self, angles):
        self.angles = angles

    def embed(self, texts, level):
        return [LevelVector(level, (math.cos(self.angles[t]), math.sin(self.angles[t])))
                for t in texts]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.corpus = self.root / 'corpus'
        self.corpus.mkdir()

    def write(self, rel, text):
        path = self.corpus / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def report(self, **kw):
        kw.setdefault('embedder', MarkerEmbedder())
        return md.build_report(self.corpus, GENRE, **kw)


SEPARABLE = ('Alpha finding one.', 'Alpha finding two.', 'Alpha finding three.',
             'Beta finding one.', 'Beta finding two.', 'Beta finding three.')


class ClusterTests(Base):
    def test_separable_groups_land_in_two_clusters(self):
        self.write('r.md', sentence_doc(findings=SEPARABLE))
        report = self.report(k=2)
        clusters = report['clusters']['findings']
        self.assertEqual(len(clusters), 2)
        self.assertEqual(sorted(c['size'] for c in clusters), [3, 3])
        groups = sorted(sorted('alpha' if 'alpha' in e.lower() else 'beta'
                               for e in c['examples'])
                        for c in clusters)
        self.assertEqual(groups, [['alpha', 'alpha', 'alpha'],
                                  ['beta', 'beta', 'beta']])

    def test_same_seed_gives_identical_report(self):
        self.write('r.md', sentence_doc(findings=SEPARABLE,
                                        conclusions=('Beta conclusion one.',
                                                     'Alpha conclusion one.')))
        self.assertEqual(self.report(k=2, seed=7), self.report(k=2, seed=7))

    def test_different_seed_can_change_clustering(self):
        self.write('r.md', sentence_doc(
            findings=[f'Vector sentence {i}.' for i in range(12)]))
        blobs = {json.dumps(md.build_report(self.corpus, GENRE, embedder=HashVectorEmbedder(),
                                            k=3, seed=seed)['clusters'], sort_keys=True)
                 for seed in range(6)}
        self.assertGreater(len(blobs), 1)

    def test_examples_are_nearest_centroid_in_order(self):
        names = ['Zero angle.', 'Twenty angle.', 'Forty-five angle.', 'Ninety angle.',
                 'One-fifty angle.']
        angles = {name: math.radians(deg)
                  for name, deg in zip(names, (0, 20, 45, 90, 150))}
        self.write('r.md', sentence_doc(findings=names))
        report = md.build_report(self.corpus, GENRE, embedder=AngleEmbedder(angles),
                                 k=1, examples=2)
        cluster = report['clusters']['findings'][0]
        self.assertEqual(cluster['size'], 5)
        vectors = {name: (math.cos(angle), math.sin(angle)) for name, angle in angles.items()}
        mean = [sum(v[i] for v in vectors.values()) / len(vectors) for i in (0, 1)]
        norm = math.hypot(*mean)
        unit = (mean[0] / norm, mean[1] / norm)
        similarity = {name: vectors[name][0] * unit[0] + vectors[name][1] * unit[1]
                      for name in names}
        expected = sorted(names, key=lambda name: -similarity[name])[:2]
        self.assertEqual(cluster['examples'], expected)

    def test_k_larger_than_sample_is_clipped(self):
        self.write('r.md', sentence_doc(findings=SEPARABLE[:3]))
        report = self.report(k=10)
        self.assertEqual(report['sections']['findings']['k'], 3)
        clusters = report['clusters']['findings']
        self.assertEqual(len(clusters), 3)
        self.assertEqual(sum(c['size'] for c in clusters), 3)

    def test_unknown_section_type_kept_apart(self):
        self.write('r.md', '# Report\n\nPreamble alpha sentence.\n\n## Odd heading\n\n'
                           'Alpha aside sentence.\n\n## Findings\n\nAlpha finding.\n')
        report = self.report(k=1)
        self.assertEqual(set(report['sections']), {'unknown', 'findings'})
        self.assertEqual(report['sections']['unknown']['seen'], 2)
        self.assertEqual(report['sections']['findings']['seen'], 1)

    def test_invalid_arguments_rejected(self):
        self.write('r.md', sentence_doc(findings=SEPARABLE))
        for kw in ({'k': 0}, {'max_per_type': 0}, {'examples': -1}):
            with self.subTest(**kw), self.assertRaises(ValueError):
                self.report(**kw)


class SamplingTests(Base):
    def test_cap_holds_sample_and_header_reports_seen(self):
        self.write('r.md', sentence_doc(
            findings=[f'Alpha finding number {i}.' for i in range(10)]))
        backend = MarkerEmbedder()
        report = md.build_report(self.corpus, GENRE, embedder=backend,
                                 k=2, max_per_type=4)
        self.assertEqual(report['sections']['findings'],
                         {'seen': 10, 'sampled': 4, 'k': 2})
        self.assertEqual(report['sentences'], {'seen': 10, 'sampled': 4})
        self.assertEqual(sum(c['size'] for c in report['clusters']['findings']), 4)
        # Sampling happens before embedding, so only the retained texts are embedded.
        self.assertEqual(sum(len(call) for call in backend.calls), 4)

    def test_sample_is_seeded(self):
        self.write('r.md', sentence_doc(
            findings=[f'Alpha finding number {i}.' for i in range(10)]))
        blobs = {json.dumps(md.build_report(self.corpus, GENRE, embedder=MarkerEmbedder(),
                                            k=1, max_per_type=4, seed=seed)['clusters'],
                            sort_keys=True)
                 for seed in range(6)}
        self.assertGreater(len(blobs), 1)


class NamingTests(Base):
    def model_with_replies(self, replies):
        calls = []

        def model(prompt):
            calls.append(prompt)
            return replies[len(calls) - 1]

        model.calls = calls
        model.model_id = 'fake-llm'
        return model

    def test_model_fills_name_definition_and_proposed_by(self):
        self.write('r.md', sentence_doc(findings=SEPARABLE))
        model = self.model_with_replies([json.dumps({'name': f'Move {i}',
                                                     'definition': 'Invented definition.'})
                                         for i in range(1, 3)])
        report = self.report(k=2, model=model)
        clusters = report['clusters']['findings']
        self.assertEqual(len(model.calls), 2)
        for cluster in clusters:
            self.assertEqual(cluster['proposed_by'], 'LLM')
            self.assertIsNone(cluster['error'])
            self.assertTrue(cluster['name'])
            self.assertTrue(cluster['definition'])
        self.assertEqual(report['naming'], {'model': 'fake-llm', 'proposed_by': 'LLM'})
        self.assertTrue(all('findings' in prompt for prompt in model.calls))
        self.assertTrue(all('JSON' in prompt for prompt in model.calls))
        self.assertTrue(any('Alpha' in prompt for prompt in model.calls))

    def test_invalid_reply_is_reported_not_raised(self):
        self.write('r.md', sentence_doc(findings=SEPARABLE))
        model = self.model_with_replies([json.dumps({'name': 'Move',
                                                     'definition': 'Definition.'}),
                                         'Sorry, I cannot help with that.'])
        report = self.report(k=2, model=model)
        clusters = report['clusters']['findings']
        self.assertEqual(sum(c['proposed_by'] == 'LLM' for c in clusters), 1)
        bad = [c for c in clusters if c['proposed_by'] is None]
        self.assertEqual(len(bad), 1)
        self.assertIsNone(bad[0]['name'])
        self.assertIsNone(bad[0]['definition'])
        self.assertTrue(bad[0]['error'])

    def test_reply_rejected_when_name_missing(self):
        self.write('r.md', sentence_doc(findings=SEPARABLE))
        model = self.model_with_replies(['{"definition": "No name here."}'])
        report = self.report(k=2, model=model)
        for cluster in report['clusters']['findings']:
            self.assertIsNone(cluster['name'])
            self.assertTrue(cluster['error'])

    def test_without_model_names_are_null(self):
        self.write('r.md', sentence_doc(findings=SEPARABLE))
        report = self.report(k=2)
        for cluster in report['clusters']['findings']:
            self.assertIsNone(cluster['name'])
            self.assertIsNone(cluster['definition'])
            self.assertIsNone(cluster['proposed_by'])
            self.assertIsNone(cluster['error'])
        self.assertEqual(report['naming'], {'model': None, 'proposed_by': None})

    def test_model_without_id_still_marked_llm(self):
        self.write('r.md', sentence_doc(findings=SEPARABLE))

        def model(prompt):
            return json.dumps({'name': 'Move', 'definition': 'Definition.'})

        report = self.report(k=2, model=model)
        self.assertEqual(report['naming'], {'model': None, 'proposed_by': 'LLM'})
        for cluster in report['clusters']['findings']:
            self.assertEqual(cluster['proposed_by'], 'LLM')


class ParseNamingTests(unittest.TestCase):
    def test_accepts_exact_object(self):
        self.assertEqual(md.parse_naming('{"name": "N", "definition": "D"}'), ('N', 'D'))

    def test_rejects_anything_but_a_strict_object(self):
        replies = (
            '```json\n{"name": "N", "definition": "D"}\n```',
            'Here you go: {"name": "N", "definition": "D"}',
            '["N", "D"]',
            '{"name": "N"}',
            '{"name": "N", "definition": "D", "extra": 1}',
            '{"name": 3, "definition": "D"}',
            '{"name": "  ", "definition": "D"}',
            '{"name": "N", "definition": "D"} trailing',
            '',
            42,
        )
        for reply in replies:
            with self.subTest(reply=reply), self.assertRaises(ValueError):
                md.parse_naming(reply)


class HeaderTests(Base):
    def test_header_records_embedder_parameters_and_counts(self):
        self.write('r.md', sentence_doc(findings=SEPARABLE[:2],
                                        conclusions=('Beta conclusion.',)))
        report = self.report(k=3, seed=5, examples=2)
        self.assertEqual(report['schema_version'], md.SCHEMA_VERSION)
        self.assertEqual(report['k'], 3)
        self.assertEqual(report['seed'], 5)
        self.assertEqual(report['examples'], 2)
        self.assertEqual(report['embedder']['model_id'], 'marker-fake')
        self.assertEqual(report['embedder']['model_version'], '2')
        self.assertFalse(report['embedder']['development_only'])
        self.assertEqual(report['warnings'], [])
        self.assertEqual(report['sections']['conclusions']['seen'], 1)
        self.assertEqual(report['sentences'], {'seen': 3, 'sampled': 3})

    def test_hash_embedder_marked_development_only(self):
        self.write('r.md', sentence_doc(findings=SEPARABLE))
        report = md.build_report(self.corpus, GENRE, embedder=HashEmbedder(), k=2)
        self.assertTrue(report['embedder']['development_only'])
        self.assertTrue(any('development-only' in warning for warning in report['warnings']))

    def test_write_report_is_canonical_and_refuses_overwrite(self):
        self.write('r.md', sentence_doc(findings=SEPARABLE))
        report = self.report(k=1)
        out = self.root / 'out.json'
        md.write_report(report, out)
        self.assertEqual(out.read_text(encoding='utf-8'),
                         json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + '\n')
        with self.assertRaises(OSError):
            md.write_report(report, out)
        md.write_report(report, out, force=True)


@contextmanager
def no_network():
    def fail(*_args, **_kwargs):
        raise AssertionError('network touched')

    with ExitStack() as stack:
        stack.enter_context(mock.patch.object(urllib.request, 'urlopen', fail))
        stack.enter_context(mock.patch.object(socket.socket, 'connect', fail))
        stack.enter_context(mock.patch.object(socket.socket, 'connect_ex', fail))
        stack.enter_context(mock.patch.object(socket, 'create_connection', fail))
        stack.enter_context(mock.patch.object(socket, 'getaddrinfo', fail))
        yield


class CliTests(Base):
    def run_cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = md.main(list(args))
        return code, stdout.getvalue(), stderr.getvalue()

    def cli(self, out, *extra):
        return self.run_cli('report', str(self.corpus), GENRE_PATH, str(out), *extra)

    def test_cli_writes_hash_report(self):
        self.write('r.md', sentence_doc(findings=SEPARABLE))
        out = self.root / 'out.json'
        code, stdout, stderr = self.cli(out, '--k', '2')
        self.assertEqual(code, 0, stderr)
        report = json.loads(out.read_text(encoding='utf-8'))
        self.assertEqual(report['embedder']['model_id'], 'hash-stub')
        self.assertTrue(report['embedder']['development_only'])
        self.assertEqual(report['k'], 2)
        self.assertIn('wrote', stdout)

    def test_existing_out_refused_without_force(self):
        self.write('r.md', sentence_doc(findings=SEPARABLE))
        out = self.root / 'out.json'
        out.write_text('{}', encoding='utf-8')
        code, _, stderr = self.cli(out)
        self.assertEqual(code, 1)
        self.assertIn('--force', stderr)
        self.assertEqual(out.read_text(encoding='utf-8'), '{}')
        code, _, stderr = self.cli(out, '--force')
        self.assertEqual(code, 0, stderr)
        self.assertIn('clusters', json.loads(out.read_text(encoding='utf-8')))

    def test_remote_model_url_fails_closed(self):
        self.write('r.md', sentence_doc(findings=SEPARABLE))
        out = self.root / 'out.json'
        with no_network():
            code, _, stderr = self.cli(out, '--model-url', 'http://example.com/v1')
        self.assertNotEqual(code, 0)
        self.assertFalse(out.exists())
        self.assertTrue(stderr.strip())

    def test_missing_corpus_fails_without_traceback(self):
        out = self.root / 'out.json'
        code, _, stderr = self.run_cli('report', str(self.root / 'nope'), GENRE_PATH, str(out))
        self.assertEqual(code, 2)
        self.assertIn('corpus', stderr)


if __name__ == '__main__':
    unittest.main()
