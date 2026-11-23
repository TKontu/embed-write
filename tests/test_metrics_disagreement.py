"""LLM-built synthetic pairs with hand-computed disagreement arithmetic."""

import unittest

from experiments.metrics.disagreement import layer_disagreement


class LayerDisagreementTests(unittest.TestCase):
    metric = staticmethod(layer_disagreement)

    def test_overall_and_slow_reference_move_rates(self):
        # Claim: 1/3 differs; evidence: 2/2 differ; conclusion: 0/1 differ.
        # Overall: (1+2+0)/(3+2+1) = 3/6, not the unweighted move mean.
        pairs = [('claim', 'claim'), ('evidence', 'claim'), ('claim', 'claim'),
                 ('claim', 'evidence'), ('fast-only', 'evidence'),
                 ('conclusion', 'conclusion')]
        self.assertEqual(self.metric(pairs), {
            'rate': 3 / 6, 'n': 6, 'disagreements': 3,
            'per_move': {
                'claim': {'rate': 1 / 3, 'n': 3, 'disagreements': 1},
                'evidence': {'rate': 2 / 2, 'n': 2, 'disagreements': 2},
                'conclusion': {'rate': 0 / 1, 'n': 1, 'disagreements': 0},
            },
        })

    def test_generator_and_single_pair_endpoints(self):
        for fast, expected in [('claim', 0), ('evidence', 1)]:
            with self.subTest(fast=fast):
                # One pair: either 0/1 or 1/1 disagrees.
                pairs = ((fast, 'claim') for _ in range(1))
                self.assertEqual(self.metric(pairs), {
                    'rate': expected, 'n': 1, 'disagreements': expected,
                    'per_move': {'claim': {
                        'rate': expected, 'n': 1, 'disagreements': expected}},
                })

    def test_iterable_is_streamed_once(self):
        class Once:
            used = False

            def __iter__(self):
                if self.used:
                    raise AssertionError('Input traversed twice')
                self.used = True
                return (('evidence' if i % 2 else 'claim', 'claim')
                        for i in range(10000))

        # Alternating agreement: 5000/10000 disagree, all reference claim.
        self.assertEqual(self.metric(Once()), {
            'rate': .5, 'n': 10000, 'disagreements': 5000,
            'per_move': {'claim': {'rate': .5, 'n': 10000, 'disagreements': 5000}},
        })

    def test_empty_inputs_raise_value_error(self):
        for pairs in ([], iter(())):
            with self.subTest(pairs=pairs):
                with self.assertRaises(ValueError):
                    self.metric(pairs)


if __name__ == '__main__':
    unittest.main()
