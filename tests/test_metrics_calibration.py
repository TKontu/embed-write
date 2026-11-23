"""LLM-built synthetic cases with hand-computed calibration arithmetic."""

import math
import unittest

from experiments.metrics import calibration


class CalibrationTests(unittest.TestCase):
    metrics = calibration

    def test_perfect_calibration(self):
        # In each four-item bin: 1/4 = .25 and 3/4 = .75, so ECE = 0.
        self.assertEqual(self.metrics.expected_calibration_error(
            [.25] * 4 + [.75] * 4, [1, 0, 0, 0, 1, 1, 1, 0], 2), 0)

    def test_miscalibration_is_weighted_by_population(self):
        # Low bin: mean=.2, accuracy=1/2; high: mean=.8, accuracy=0.
        # ECE = (2/3)*|.5-.2| + (1/3)*|0-.8| = 7/15.
        self.assertAlmostEqual(self.metrics.expected_calibration_error(
            [.1, .3, .8], [True, False, False], 2), 7 / 15, delta=1e-9)
        self.assertEqual(self.metrics.reliability_bins([.1, .3, .8], [1, 0, 0], 2), [
            dict(lo=0, hi=.5, count=2, mean_confidence=.2, accuracy=.5),
            dict(lo=.5, hi=1, count=1, mean_confidence=.8, accuracy=0),
        ])

    def test_endpoints_and_edges(self):
        # Left-closed bins; 1 belongs to the final bin along with .75.
        bins = self.metrics.reliability_bins([0, .25, .5, .75, 1], [0, 1, 0, 1, 1], 4)
        self.assertEqual([b['count'] for b in bins], [1, 1, 1, 2])
        self.assertEqual([b['mean_confidence'] for b in bins], [0, .25, .5, .875])
        for n in (10, 22, 100):
            for i in range(1, n):
                with self.subTest(n=n, edge=i):
                    edge = i / n
                    bins = self.metrics.reliability_bins(
                        [math.nextafter(edge, 0), edge, math.nextafter(edge, 1)], [0, 1, 1], n)
                    self.assertEqual(bins[i - 1]['count'], 1)
                    self.assertEqual(bins[i]['count'], 2)

    def test_empty_bins_have_none_means(self):
        bins = self.metrics.reliability_bins([1], [True])
        self.assertEqual(len(bins), 10)
        for i, b in enumerate(bins[:-1]):
            self.assertEqual(b, dict(lo=i/10, hi=(i+1)/10, count=0,
                                     mean_confidence=None, accuracy=None))
        self.assertEqual(self.metrics.expected_calibration_error([1], [True]), 0)

    def test_one_bin(self):
        # Mean confidence=(0+1)/2=.5; accuracy=1/2, hence ECE=0.
        self.assertEqual(self.metrics.reliability_bins((0, 1), (False, True), 1),
                         [dict(lo=0, hi=1, count=2, mean_confidence=.5, accuracy=.5)])

    def test_invalid_inputs(self):
        for fn in (self.metrics.reliability_bins, self.metrics.expected_calibration_error):
            for confidences, correct, n in [([], [], 10), ([.5], [], 10),
                    ([], [1], 10), ([-.1], [0], 10), ([1.1], [1], 10),
                    ([float('nan')], [1], 10), ([float('inf')], [1], 10),
                    ([.5], [1], 0), ([.5], [1], -1), ([.5], [2], 10)]:
                with self.subTest(fn=fn.__name__, confidences=confidences, correct=correct, n=n):
                    with self.assertRaises(ValueError):
                        fn(confidences, correct, n)

    def test_input_sequences_are_traversed_once(self):
        class Once:
            def __init__(self, value):
                self.value = value
                self.used = False

            def __len__(self):
                return 10000

            def __iter__(self):
                if self.used:
                    raise AssertionError('Input traversed twice')
                self.used = True
                return (self.value for _ in range(len(self)))

        self.assertEqual(self.metrics.expected_calibration_error(Once(.5), Once(1)), .5)


if __name__ == '__main__':
    unittest.main()
