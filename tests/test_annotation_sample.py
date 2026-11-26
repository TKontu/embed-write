"""AN-02 annotation sampling. LLM-built synthetic fixtures; no corpus text."""
import json
import os
import subprocess
import sys
import tempfile
import unittest

from experiments import annotation_sample as a
from experiments.splits import DocumentSplit, SplitLeakError
from service.genre import load_genre

GENRE_PATH = os.path.join(os.path.dirname(__file__), 'fixtures', 'genre_synthetic_sections.json')
GENRE = load_genre(GENRE_PATH)


def doc(i, findings=4, conclusions=2, other=1):
    parts = [f'Preamble sentence {i} zero.']
    parts.append('## 1. Findings')
    parts.append(' '.join(f'Invented finding {i} number {k}.' for k in range(findings)))
    parts.append('## Odd heading')
    parts.append(' '.join(f'Invented aside {i} number {k}.' for k in range(other)))
    parts.append('## Conclusions:')
    parts.append(' '.join(f'Invented conclusion {i} number {k}.' for k in range(conclusions)))
    return '\n\n'.join(parts) + '\n'


DOCS = [(f'r{i}.md', doc(i, findings=3 + i, conclusions=1 + (i % 2))) for i in range(5)]
SPLIT = DocumentSplit(['train.md'], [d for d, _ in DOCS])


class ManifestTests(unittest.TestCase):
    def build(self, **kw):
        kw.setdefault('n', 10)
        return a.build_manifest(iter(DOCS), SPLIT, GENRE, **kw)

    def test_deterministic_per_seed(self):
        self.assertEqual(self.build(seed=3), self.build(seed=3))
        self.assertNotEqual(self.build(seed=3)['entries'], self.build(seed=4)['entries'])

    def test_refuses_non_test_doc(self):
        with self.assertRaises(SplitLeakError):
            a.build_manifest(iter(DOCS + [('train.md', doc(9))]), SPLIT, GENRE, n=5)
        with self.assertRaises(SplitLeakError):
            a.build_manifest(iter([('stray.md', doc(9))]), SPLIT, GENRE, n=5)

    def test_every_section_type_represented(self):
        for seed in range(10):
            m = self.build(n=3, seed=seed)
            self.assertEqual({e['section_type'] for e in m['entries']},
                             {'findings', 'conclusions', 'unknown'})

    def test_total_is_min_n_candidates(self):
        total = sum(c for c in self.build()['candidates_per_stratum'].values())
        self.assertEqual(self.build(n=17)['n_drawn'], 17)
        m = self.build(n=10_000)
        self.assertEqual(m['n_drawn'], total)
        self.assertEqual(m['n_requested'], 10_000)
        self.assertEqual(len(m['entries']), total)
        ids = [e['sentence_id'] for e in m['entries']]
        self.assertEqual(len(set(ids)), len(ids))

    def test_unknown_counted_and_strata(self):
        m = self.build(n=10_000)
        # preamble + one aside per doc are unknown
        self.assertEqual(m['unknown_sentences'], 10)
        self.assertEqual(m['candidates_per_stratum']['r0.md|findings'], 3)
        self.assertEqual(sum(m['drawn_per_stratum'].values()), m['n_drawn'])

    def test_proportional(self):
        m = self.build(n=20, seed=1)
        drawn = m['drawn_per_stratum']
        self.assertGreaterEqual(drawn['r4.md|findings'], drawn['r0.md|findings'])

    def test_repeat_subset(self):
        for n in (3, 10, 17):
            m = self.build(n=n, repeat_fraction=0.1, seed=2)
            self.assertEqual(len(m['repeat']), round(0.1 * m['n_drawn']))
            self.assertLessEqual(set(m['repeat']), {e['sentence_id'] for e in m['entries']})

    def test_no_sentence_text(self):
        blob = json.dumps(self.build(n=10_000))
        self.assertNotIn('Invented', blob)
        self.assertNotIn('Preamble', blob)

    def test_manifest_header(self):
        m = self.build()
        self.assertEqual(m['schema_version'], a.SCHEMA_VERSION)
        self.assertEqual(m['seed'], 0)
        self.assertEqual(m['genre'], {'genre_version': 1, 'genre_hash': m['genre']['genre_hash']})
        self.assertEqual(len(m['split_test_ids_sha256']), 64)
        self.assertIn('memory_bound', m)

    def test_write_manifest_canonical(self):
        m = self.build()
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, 'm.json')
            a.write_manifest(p, m)
            with open(p, encoding='utf-8') as fh:
                text = fh.read()
        self.assertEqual(json.loads(text), m)
        self.assertEqual(text, json.dumps(m, sort_keys=True, indent=2) + '\n')


class CliTests(unittest.TestCase):
    def test_cli_writes_manifest(self):
        root = os.path.join(os.path.dirname(__file__), '..')
        with tempfile.TemporaryDirectory() as tmp:
            corpus = os.path.join(tmp, 'corpus')
            os.makedirs(os.path.join(corpus, 'sub'))
            for i in range(6):
                with open(os.path.join(corpus, 'sub' if i % 2 else '', f'd{i}.md'), 'w',
                          encoding='utf-8') as fh:
                    fh.write(doc(i))
            out = os.path.join(tmp, 'out.json')
            subprocess.run([sys.executable, '-m', 'experiments.annotation_sample',
                            '--corpus', corpus, '--genre', GENRE_PATH, '--split-seed', '1',
                            '--test-fraction', '0.5', '--n', '5', '--out', out],
                           cwd=root, check=True, capture_output=True)
            with open(out, encoding='utf-8') as fh:
                m = json.load(fh)
        self.assertEqual(m['n_drawn'], 5)
        self.assertEqual(len({e['doc_id'] for e in m['entries']} - {
            'd0.md', 'sub/d1.md', 'd2.md', 'sub/d3.md', 'd4.md', 'sub/d5.md'}), 0)


H = {'methods': 'methods', 'results': 'results'}


def types(md):
    return [(r['section_type'], r['section_index'], r['text'])
            for r in a.document_sentences('d.md', md, H)]


class SectionTypingTests(unittest.TestCase):
    def test_fenced_hash_lines_are_not_headings(self):
        for fence, close in (('```', '```'), ('~~~', '~~~~~'), ('   ```', '````')):
            md = f'# Methods\n\nAlpha one.\n\n{fence}\n# Results\n{close}\n\nBeta two.\n'
            rows = types(md)
            self.assertTrue(all(t == 'methods' and ix == 1 for t, ix, _ in rows), (fence, rows))
            self.assertIn('Beta two.', [s for *_, s in rows])

    def test_setext_headings(self):
        rows = types('Methods\n=======\n\nAlpha one.\n\nResults\n-------\n\nBeta two.\n')
        self.assertEqual([(t, ix) for t, ix, _ in rows], [('methods', 1), ('results', 2)])
        self.assertEqual([s for *_, s in rows], ['Alpha one.', 'Beta two.'])

    def test_thematic_break_after_blank_is_not_heading(self):
        rows = types('# Methods\n\nAlpha one.\n\n---\n\nBeta two.\n')
        self.assertTrue(rows and all((t, ix) == ('methods', 1) for t, ix, _ in rows), rows)

    def test_unmapped_subheading_inherits(self):
        md = ('# Methods\n\nA one.\n\n## Sample details\n\nB two.\n\n# Results\n\nC three.\n\n'
              '# Odd thing\n\nD four.\n')
        self.assertEqual([t for t, *_ in types(md)], ['methods', 'methods', 'results', 'unknown'])

    def test_same_level_mapped_replaces_and_setext_levels(self):
        md = ('## Methods\n\nA one.\n\n### Detail\n\nB two.\n\n## Results\n\nC three.\n\n'
              'Other\n-----\n\nD four.\n')
        self.assertEqual([t for t, *_ in types(md)], ['methods', 'methods', 'results', 'unknown'])

    def test_front_matter_skipped(self):
        for end in ('---', '...'):
            rows = types(f'---\ntitle: x\n{end}\n\n# Methods\n\nAlpha.')
            self.assertEqual(rows, [('methods', 1, 'Alpha.')], end)

    def test_list_item_then_rule_is_not_heading(self):
        for first in ('- item', '* item', '+ item', '1. item', '2) item', '  - item'):
            rows = types(f'# Methods\n\n{first}\n---\n\nAlpha.')
            self.assertTrue(rows and all((t, ix) == ('methods', 1) for t, ix, _ in rows), (first, rows))

    def test_fence_then_rule_is_not_heading(self):
        rows = types('# Methods\n\n```\ncode\n```\n---\n\nAlpha.')
        self.assertTrue(rows and all((t, ix) == ('methods', 1) for t, ix, _ in rows), rows)

    def test_blockquote_then_rule_is_not_heading(self):
        rows = types('# Methods\n\n> quote\n---\n\nAlpha.')
        self.assertTrue(rows and all((t, ix) == ('methods', 1) for t, ix, _ in rows), rows)

    def test_container_fenced_hash_lines_are_not_headings(self):
        cases = (('> ```', '> # Results', '> ```'),
                 ('> > ~~~', '> > # Results', '> > ~~~~'),
                 ('- ```', '  # Results', '  ```'),
                 ('* ```', '  # Results', '  ```'),
                 ('+ ```', '  # Results', '  ```'),
                 ('1. ```', '   # Results', '   ```'),
                 ('2) ```', '   # Results', '   ```'))
        for open_, inner, close in cases:
            md = f'# Methods\n\nAlpha one.\n\n{open_}\n{inner}\n{close}\n\nBeta two.\n'
            rows = types(md)
            self.assertTrue(all(t == 'methods' and ix == 1 for t, ix, _ in rows), (open_, rows))
            self.assertIn('Beta two.', [s for *_, s in rows])

    def test_list_continuation_fence(self):
        md = '# Methods\n\n- item\n\n  ```\n  # Results\n  ```\n\nBeta two.\n'
        rows = types(md)
        self.assertTrue(all(t == 'methods' and ix == 1 for t, ix, _ in rows), rows)

    def test_container_fence_closes_then_real_heading(self):
        for open_, inner, close in (('> ```', '> # Odd', '> ```'), ('- ```', '  # Odd', '  ```')):
            md = (f'# Methods\n\nA one.\n\n{open_}\n{inner}\n```\n# Odd\n{close}\n\n'
                  '# Results\n\nC three.\n')
            rows = types(md)
            self.assertEqual([(t, ix) for t, ix, _ in rows][-1], ('results', 2), (open_, rows))
            self.assertTrue(all(ix == 1 for _, ix, _ in rows[:-1]), (open_, rows))

    def test_unclosed_container_fence_runs_to_end(self):
        for open_ in ('> ```', '- ```'):
            rows = types(f'# Methods\n\nA one.\n\n{open_}\n\n# Results\n\nC three.\n')
            self.assertTrue(all((t, ix) == ('methods', 1) for t, ix, _ in rows), (open_, rows))


if __name__ == '__main__':
    unittest.main()
