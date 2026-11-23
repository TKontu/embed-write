"""LLM-built synthetic entries with hand-computed correction arithmetic."""

import importlib.util
import unittest


class CorrectionRateTests(unittest.TestCase):
    def test_metric_exists(self):
        self.assertIsNotNone(importlib.util.find_spec(
            'experiments.metrics.correction'), 'MT-06 metric is missing')

    def test_overall_and_group_rates(self):
        from experiments.metrics.correction import correction_rate

        entries = [
            {'draft': 'a', 'move': 'claim', 'candidate': 'x', 'final': 'x'},
            {'draft': 'a', 'move': 'claim', 'candidate': 'x', 'final': 'y'},
            {'draft': 'a', 'move': 'evidence', 'candidate': 'x', 'final': 'x'},
            {'draft': 'b', 'move': 'claim', 'candidate': 'x', 'final': 'y'},
        ]
        # Overall 2/4; drafts a=1/3, b=1/1; claim=2/3, evidence=0/1.
        # Unequal group sizes rule out averaging group rates for the total.
        self.assertEqual(correction_rate(entries), {
            'rate': 2 / 4, 'n': 4,
            'per_draft': {'a': {'rate': 1 / 3, 'n': 3},
                          'b': {'rate': 1, 'n': 1}},
            'per_move': {'claim': {'rate': 2 / 3, 'n': 3},
                         'evidence': {'rate': 0, 'n': 1}},
        })

    def test_empty_population_raises_value_error(self):
        from experiments.metrics.correction import correction_rate

        for entries in ([], iter(())):
            with self.subTest(entries=entries):
                with self.assertRaises(ValueError):
                    correction_rate(entries)

    def test_each_missing_key_raises_value_error(self):
        from experiments.metrics.correction import correction_rate

        complete = {'draft': 'a', 'move': 'claim',
                    'candidate': 'x', 'final': 'x'}
        for key in complete:
            with self.subTest(key=key):
                incomplete = {k: v for k, v in complete.items() if k != key}
                with self.assertRaises(ValueError):
                    correction_rate(iter([complete, incomplete]))

    def test_exact_text_comparison_and_ignored_extra_keys(self):
        from experiments.metrics.correction import correction_rate

        # Each singleton has rate 0/1 if unchanged, otherwise 1/1.
        for candidate, final, rate in [
            ('same', 'same', 0), ('', '', 0), ('x', '', 1),
            ('x', 'x ', 1), ('x', 'X', 1), ('é', 'e\u0301', 1),
        ]:
            with self.subTest(candidate=candidate, final=final):
                result = correction_rate([{
                    'draft': 'a', 'move': 'claim', 'candidate': candidate,
                    'final': final, 'extra': ['ignored'],
                }])
                self.assertEqual(result, {
                    'rate': rate, 'n': 1,
                    'per_draft': {'a': {'rate': rate, 'n': 1}},
                    'per_move': {'claim': {'rate': rate, 'n': 1}},
                })

    def test_generator_is_consumed_without_retaining_entries(self):
        from experiments.metrics.correction import correction_rate

        def entries():
            # Reuse one mapping: retaining entries until after traversal
            # would lose the individual final values.
            entry = {'draft': 'a', 'move': 'claim', 'candidate': 'x'}
            for i in range(10000):
                entry['final'] = 'y' if i % 2 else 'x'
                yield entry
                # Consume each entry before asking the generator for another.
                entry.clear()
                entry.update(draft='a', move='claim', candidate='x')

        # Alternating changes: 5000/10000, in one draft and one move.
        self.assertEqual(correction_rate(entries()), {
            'rate': .5, 'n': 10000,
            'per_draft': {'a': {'rate': .5, 'n': 10000}},
            'per_move': {'claim': {'rate': .5, 'n': 10000}},
        })


if __name__ == '__main__':
    unittest.main()
