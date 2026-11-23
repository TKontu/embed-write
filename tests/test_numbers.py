"""Synthetic, offline examples for SP-04 quantity consistency."""
import unittest
from dataclasses import FrozenInstanceError

from analysis.numbers import Quantity, check_consistency, extract_quantities


class ExtractionTests(unittest.TestCase):
    def test_signed_numbers_and_bare_year(self):
        qs = extract_quantities('In 2024: -12, +3.5 and .25.')
        self.assertEqual([q.value for q in qs], [2024, -12, 3.5, .25])
        self.assertTrue(all(q.unit is None and q.dimension is None for q in qs))

    def test_unit_aliases_and_conversions(self):
        groups = [
            ('m', 'length', [('mm', .001), ('cm', .01), ('m', 1), ('km', 1000)]),
            ('g', 'mass', [('mg', .001), ('g', 1), ('kg', 1000), ('t', 1e6), ('tonne', 1e6)]),
            ('s', 'time', [('s', 1), ('min', 60), ('h', 3600), ('day', 86400),
                           ('days', 86400), ('year', 31536000), ('years', 31536000)]),
            ('%', 'percent', [('%', 1), ('percent', 1), ('per cent', 1)]),
            ('pp', 'percentage_points', [('pp', 1), ('percentage points', 1)]),
            ('EUR', 'currency:EUR', [('EUR', 1), ('€', 1)]),
            ('USD', 'currency:USD', [('USD', 1), ('$', 1)]),
        ]
        for unit, dimension, variants in groups:
            for alias, multiplier in variants:
                with self.subTest(alias=alias):
                    q, = extract_quantities('2 ' + alias)
                    self.assertEqual((q.value, q.unit, q.dimension), (2 * multiplier, unit, dimension))

    def test_thousands_and_decimal_comma(self):
        qs = extract_quantities('1,000; 1 000; 12,345,678.5; 12 345 678.5; 3,5 %; 1,234')
        self.assertEqual([q.value for q in qs], [1000, 1000, 12345678.5, 12345678.5, 3.5, 1234])

    def test_scale_words(self):
        for scale, factor in [('thousand', 1e3), ('million', 1e6), ('billion', 1e9),
                              ('k', 1e3), ('M', 1e6), ('bn', 1e9)]:
            with self.subTest(scale=scale):
                self.assertEqual(extract_quantities('2.5 ' + scale)[0].value, 2.5 * factor)
        self.assertEqual(extract_quantities('2M USD')[0].value, 2e6)
        self.assertEqual(extract_quantities('2 m')[0].value, 2)

    def test_currency_prefix_and_scaled_units(self):
        for text in ['€2 million', 'EUR 2 million', '2 million EUR']:
            q, = extract_quantities(text)
            self.assertEqual((q.value, q.unit), (2e6, 'EUR'))
        self.assertEqual(extract_quantities('$-5')[0].value, -5)
        self.assertEqual(extract_quantities('2 thousand kg')[0].value, 2e6)

    def test_sign_before_currency_and_no_swallowed_suffix(self):
        q, = extract_quantities('-$5')
        self.assertEqual((q.value, q.text), (-5, '-$5'))
        q, = extract_quantities('€5 USD')
        self.assertEqual(q.text, '€5')

    def test_nonfinite_quantity_rejected(self):
        with self.assertRaises(ValueError):
            extract_quantities('9' * 400)

    def test_unit_boundaries_and_horizontal_whitespace(self):
        self.assertIsNone(extract_quantities('5 percentiles')[0].unit)
        self.assertIsNone(extract_quantities('5\nkg')[0].unit)
        self.assertEqual(extract_quantities('2.5km')[0].value, 2500)
        self.assertEqual(extract_quantities('1\u00a0000')[0].value, 1000)

    def test_spans_preserve_original_text(self):
        text = 'Costs €2.5 million; length -3,5 km; growth 4 per cent.'
        qs = extract_quantities(text)
        self.assertEqual([q.text for q in qs], ['€2.5 million', '-3,5 km', '4 per cent'])
        for q in qs:
            self.assertEqual(text[slice(*q.span)], q.text)

    def test_quantity_is_frozen(self):
        q = Quantity(1, None, None, (0, 1), '1')
        with self.assertRaises(FrozenInstanceError):
            q.value = 2

    def test_no_numbers_or_numbers_inside_identifiers(self):
        self.assertEqual(extract_quantities('Nothing here; abc123; v2beta.'), [])


class ConsistencyTests(unittest.TestCase):
    def test_converted_units_match(self):
        report = check_consistency('2.5 km and 1 kg', ['2500 m and 1000 g'])
        self.assertTrue(report.ok)
        self.assertEqual(len(report.supported), 2)
        self.assertEqual(report.unsupported, [])

    def test_dimensions_and_currencies_do_not_match(self):
        for claim, source in [('5 %', '5 pp'), ('5 %', '5 kg'), ('5', '5 %'),
                              ('5 EUR', '5 USD'), ('5 m', '5 g')]:
            with self.subTest(claim=claim, source=source):
                report = check_consistency(claim, [source])
                self.assertFalse(report.ok)
                self.assertEqual(len(report.unsupported), 1)

    def test_relative_tolerance_inside_and_outside(self):
        self.assertTrue(check_consistency('100', ['99.501']).ok)
        self.assertFalse(check_consistency('100', ['99.499']).ok)
        self.assertTrue(check_consistency('100', ['100'], rel_tol=0).ok)
        self.assertFalse(check_consistency('100', ['100.001'], rel_tol=0).ok)

    def test_absolute_tolerance(self):
        self.assertTrue(check_consistency('0', ['0.01'], rel_tol=0, abs_tol=.01).ok)
        self.assertFalse(check_consistency('0', ['0.01001'], rel_tol=0, abs_tol=.01).ok)

    def test_multiple_sources_and_every_unsupported_occurrence(self):
        report = check_consistency('1 kg; 2 km; 3 %; 3 %', iter(['1000 g', '2000 m']))
        self.assertEqual([q.text for q, _ in report.supported], ['1 kg', '2 km'])
        self.assertEqual([q.text for q in report.unsupported], ['3 %', '3 %'])

    def test_no_claim_quantities_is_ok(self):
        self.assertTrue(check_consistency('No quantities', []).ok)
        self.assertFalse(check_consistency('2024', []).ok)

    def test_first_matching_evidence_is_deterministic(self):
        report = check_consistency('1 km', ['1000 m', '1 km'])
        self.assertEqual(report.supported[0][1].text, '1000 m')

    def test_invalid_tolerances_rejected_even_without_quantities(self):
        for tolerance in [-1, float('nan'), float('inf')]:
            with self.subTest(tolerance=tolerance):
                with self.assertRaises(ValueError):
                    check_consistency('', [], rel_tol=tolerance)
                with self.assertRaises(ValueError):
                    check_consistency('', [], abs_tol=tolerance)
