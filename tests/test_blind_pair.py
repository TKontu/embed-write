"""Synthetic blind-pair contract checks; these are not expert judgments."""

import json
import random
import tempfile
import unittest
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from experiments.blind_pair import make_pair, render_html, record_choice, to_preference_choices
from experiments.metrics.preference import win_rate


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.data = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, data):
        self.data.append(data)


class BlindPairTests(unittest.TestCase):
    def pair(self, seed=0):
        return make_pair('PRIVATE_PAIR_ID', 'First synthetic text', 'ARM_SECRET_A',
                         'Second synthetic text', 'ARM_SECRET_B', random.Random(seed))

    def test_seeded_order_varies_without_exposing_metadata(self):
        orders = set()
        keys = set()
        for seed in range(100):
            pair = self.pair(seed)
            orders.add((pair.left, pair.right))
            self.assertEqual((pair.left, pair.right),
                             (self.pair(seed).left, self.pair(seed).right))
            self.assertTrue(pair.key)
            keys.add(pair.key)
            page = render_html(pair)
            for secret in ('ARM_SECRET_A', 'ARM_SECRET_B', pair.key, 'PRIVATE_PAIR_ID'):
                self.assertNotIn(secret, page)
            self.assertIn(pair.left, page)
            self.assertIn(pair.right, page)
        self.assertEqual(len(orders), 2)
        self.assertEqual(len(keys), 100)

    def test_text_is_escaped_and_form_has_only_blind_choices(self):
        text = '<script>alert("x")</script> & <img src=x onerror="bad()">'
        pair = make_pair('id', text, 'secret-x', "quotes ' & < >", 'secret-y', random.Random(0))
        page = render_html(pair)
        parsed = PageParser()
        parsed.feed(page)
        self.assertIn(text, parsed.data)
        self.assertNotIn('<script>', page)
        self.assertFalse(any(tag in ('script', 'img') for tag, _ in parsed.tags))
        inputs = [attrs for tag, attrs in parsed.tags if tag == 'input']
        self.assertEqual({a['value'] for a in inputs}, {'left', 'right', 'tie'})
        self.assertTrue(all(a['name'] == 'choice' for a in inputs))
        self.assertIn(('form', {'method': 'post'}), parsed.tags)
        textarea = [attrs for tag, attrs in parsed.tags if tag == 'textarea']
        self.assertEqual(len(textarea), 1)
        self.assertEqual(textarea[0]['name'], 'reason')
        self.assertNotIn('required', textarea[0])

    def test_append_resolves_both_orders_and_ties(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'choices.jsonl'
            expected = []
            before = datetime.now(timezone.utc)
            for seed in range(20):
                pair = self.pair(seed)
                for choice in ('left', 'right', 'tie'):
                    text = getattr(pair, choice) if choice != 'tie' else None
                    winner = ('tie' if text is None else
                              'ARM_SECRET_A' if text == 'First synthetic text' else 'ARM_SECRET_B')
                    record_choice(path, pair, choice, 'Synthetic reason\nwith unicode: é')
                    expected.append((choice, winner))
            after = datetime.now(timezone.utc)
            records = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual(len(records), 60)
            for record, (choice, winner) in zip(records, expected):
                self.assertEqual(set(record), {'pair_id', 'choice', 'winner', 'reason', 'recorded_at'})
                self.assertEqual(record['pair_id'], 'PRIVATE_PAIR_ID')
                self.assertEqual((record['choice'], record['winner']), (choice, winner))
                self.assertEqual(record['reason'], 'Synthetic reason\nwith unicode: é')
                stamp = datetime.fromisoformat(record['recorded_at'])
                self.assertEqual(stamp.utcoffset().total_seconds(), 0)
                self.assertLessEqual(before, stamp)
                self.assertLessEqual(stamp, after)

    def test_invalid_choice_does_not_write_and_reason_is_optional(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'choices.jsonl'
            for choice in ('a', '', None, 'LEFT'):
                with self.assertRaises(ValueError):
                    record_choice(path, self.pair(), choice)
            self.assertFalse(path.exists())
            record_choice(path, self.pair(), 'tie')
            original = path.read_bytes()
            self.assertIsNone(json.loads(original)['reason'])
            with self.assertRaises(ValueError):
                record_choice(path, self.pair(), 'invalid')
            self.assertEqual(path.read_bytes(), original)

    def test_records_stream_into_preference_metric(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'choices.jsonl'
            pair = self.pair()
            for choice in ('left', 'right', 'tie'):
                record_choice(path, pair, choice)
            with path.open() as lines:
                choices = list(to_preference_choices(lines, 'ARM_SECRET_A'))
            self.assertEqual(sorted(choices), ['a', 'b', 'tie'])
            self.assertEqual(win_rate(choices), dict(win_rate=0.5, n=3, wins=1, losses=1, ties=1))
        consumed = []

        def records():
            for winner in ('ARM_SECRET_A', 'ARM_SECRET_A', 'ARM_SECRET_B', 'tie'):
                consumed.append(winner)
                yield {'winner': winner}

        stream = to_preference_choices(records(), 'ARM_SECRET_A')
        self.assertEqual(consumed, [])
        self.assertEqual(next(stream), 'a')
        self.assertEqual(consumed, ['ARM_SECRET_A'])
        self.assertEqual(list(stream), ['a', 'b', 'tie'])

    def test_ambiguous_arm_names_are_rejected(self):
        for arms in (('same', 'same'), ('tie', 'other'), ('other', 'tie'), ('', 'other')):
            with self.assertRaises(ValueError):
                make_pair('id', 'x', arms[0], 'y', arms[1], random.Random(0))


if __name__ == '__main__':
    unittest.main()
