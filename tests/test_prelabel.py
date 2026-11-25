"""G-01.4 pre-label runner. LLM-built synthetic fixtures and a fake model callable only."""
import json
import os
import random
import tempfile
import unittest

from experiments import prelabel
from experiments.gates import g01
from service.genre import load_genre, version_key
from service.network_guard import NetworkGuardError

GENRE_PATH = os.path.join(os.path.dirname(__file__), 'fixtures', 'genre_synthetic.json')
GENRE = load_genre(GENRE_PATH)
MOVE_IDS = [m['id'] for m in GENRE['moves']]


def items(n=6):
    return [{'sentence_id': f's{i}', 'doc_id': f'd{i % 2}', 'section_type': 'intro',
             'text': f'Synthetic sentence number {i}.', 'context': f'Context for {i}.'}
            for i in range(n)]


class FakeModel:
    """Answers each prompt from a script keyed by sentence text; records calls."""
    model_id = 'fake-1'

    def __init__(self, replies):
        self.replies = replies  # sentence index -> list of replies (consumed in order)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        for i, queue in self.replies.items():
            if f'Synthetic sentence number {i}.' in prompt and queue:
                return queue.pop(0)
        return MOVE_IDS[0]


def read(path):
    with open(path, encoding='utf-8') as fh:
        return [json.loads(line) for line in fh if line.strip()]


class PrelabelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = os.path.join(self.tmp.name, 'labels.jsonl')

    def tearDown(self):
        self.tmp.cleanup()

    def test_prompt_lists_inventory_other_and_context(self):
        p = prelabel.build_prompt(items(1)[0], GENRE)
        for m in GENRE['moves']:
            self.assertIn(m['id'], p)
            self.assertIn(m['definition'], p)
        self.assertIn('other', p)
        self.assertIn('Context for 0.', p)
        self.assertIn('intro', p)

    def test_every_id_exactly_one_valid_label(self):
        model = FakeModel({1: [MOVE_IDS[-1]], 2: ['other'], 3: [f'Label: {MOVE_IDS[0]}']})
        recs = prelabel.prelabel(items(), GENRE, model, out_path=self.out)
        self.assertEqual([r['sentence_id'] for r in recs], [f's{i}' for i in range(6)])
        valid = set(MOVE_IDS) | {'other'}
        for r in read(self.out):
            self.assertIn(r['label'], valid)
            self.assertEqual(r['genre_version'], version_key(GENRE)['genre_version'])
            self.assertEqual(r['genre_hash'], version_key(GENRE)['genre_hash'])
            self.assertEqual(r['model'], 'fake-1')
            self.assertEqual(len(r['prompt_hash']), 64)
            self.assertFalse(r['invalid_reply'])
        s = prelabel.summarize(items(), read(self.out))
        self.assertTrue(s['exactly_one_label_each'])
        self.assertEqual(s['invalid_replies'], 0)
        self.assertEqual(sum(s['counts'].values()), 6)

    def test_invalid_replies_retried_then_other_flagged(self):
        both = f'{MOVE_IDS[0]} or {MOVE_IDS[1]}' if len(MOVE_IDS) > 1 else 'nonsense'
        model = FakeModel({0: ['banana', both, 'nope'],
                           1: ['banana', MOVE_IDS[0]]})
        recs = prelabel.prelabel(items(2), GENRE, model, out_path=self.out, max_retries=2)
        self.assertEqual(recs[0]['label'], 'other')
        self.assertTrue(recs[0]['invalid_reply'])
        self.assertEqual(recs[0]['attempts'], 3)
        self.assertEqual(recs[1]['label'], MOVE_IDS[0])
        self.assertFalse(recs[1]['invalid_reply'])
        self.assertEqual(recs[1]['attempts'], 2)
        s = prelabel.summarize(items(2), read(self.out))
        self.assertEqual(s['invalid_replies'], 1)

    def test_resume_skips_done_ids_no_duplicates(self):
        prelabel.prelabel(items(3), GENRE, FakeModel({}), out_path=self.out)
        model = FakeModel({})
        prelabel.prelabel(items(6), GENRE, model, out_path=self.out)
        self.assertEqual(len(model.prompts), 3)
        ids = [r['sentence_id'] for r in read(self.out)]
        self.assertEqual(sorted(ids), [f's{i}' for i in range(6)])
        self.assertTrue(prelabel.summarize(items(6), read(self.out))['exactly_one_label_each'])

    def test_resume_relabels_under_other_model(self):
        prelabel.prelabel(items(2), GENRE, FakeModel({}), out_path=self.out)
        other = FakeModel({})
        other.model_id = 'fake-2'
        prelabel.prelabel(items(2), GENRE, other, out_path=self.out)
        self.assertEqual(len(other.prompts), 2)

    def test_summary_flags_missing_and_duplicate(self):
        recs = [{'sentence_id': 's0', 'label': 'other', 'invalid_reply': False}] * 2
        s = prelabel.summarize(items(2), recs)
        self.assertFalse(s['exactly_one_label_each'])
        self.assertEqual(s['missing'], ['s1'])
        self.assertEqual(s['duplicates'], ['s0'])

    def test_output_loads_into_g01_as_llm_rater(self):
        prelabel.prelabel(items(), GENRE, FakeModel({1: ['other']}), out_path=self.out)
        llm = prelabel.llm_labels(read(self.out))
        expert = {f's{i}': MOVE_IDS[0] for i in range(6)}
        out = g01.run(random.Random(0), {'expert': expert, 'llm': llm,
                                         'labels': MOVE_IDS + ['other'], 'n_resamples': 10})
        self.assertEqual(out['pairing']['expert_llm']['paired'], 6)

    def test_prompt_contains_no_other_report_text(self):
        model = FakeModel({})
        prelabel.prelabel(items(4), GENRE, model, out_path=self.out)
        for i, p in enumerate(model.prompts):
            for j in range(4):
                if j != i:
                    self.assertNotIn(f'Synthetic sentence number {j}.', p)
                    self.assertNotIn(f'Context for {j}.', p)

    def test_local_model_refuses_non_loopback(self):
        with self.assertRaises(NetworkGuardError):
            prelabel.local_model('http://example.com:8000/v1')
        m = prelabel.local_model('http://127.0.0.1:9/v1', model='x')
        self.assertEqual(m.model_id, 'x')

    def test_parse_reply(self):
        valid = MOVE_IDS + ['other']
        self.assertEqual(prelabel.parse_reply(f' {MOVE_IDS[0]}.\n', valid), MOVE_IDS[0])
        self.assertIsNone(prelabel.parse_reply('', valid))
        self.assertIsNone(prelabel.parse_reply('banana', valid))


if __name__ == '__main__':
    unittest.main()
