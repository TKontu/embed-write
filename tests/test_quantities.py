import unittest

from service.quantities import Quantity, extract_quantities


def one(text):
    qs = extract_quantities(text)
    assert len(qs) == 1, qs
    return qs[0]


class DecimalTests(unittest.TestCase):
    def test_dot_decimal(self):
        q = one("weighs 3.5 kg")
        self.assertEqual((q.value, q.low, q.high, q.unit, q.kind), (3.5, 3.5, 3.5, "kg", "value"))

    def test_comma_decimal(self):
        self.assertEqual(one("weighs 3,5 kg").value, 3.5)

    def test_negative(self):
        q = one("at -4.2 °C overnight")
        self.assertEqual((q.value, q.unit), (-4.2, "°C"))
        self.assertEqual(one("at −4.2 °C").value, -4.2)

    def test_plus_sign(self):
        self.assertEqual(one("+3 kg").value, 3.0)


class ThousandsTests(unittest.TestCase):
    def test_space_and_comma_groups(self):
        for t in ("12 000 m", "12,000 m", "12 000 m"):
            q = one(t)
            self.assertEqual((q.value, q.unit), (12000.0, "m"), t)

    def test_ambiguous_comma_three_digits_is_thousands(self):
        self.assertEqual(one("1,234").value, 1234.0)

    def test_grouped_with_decimal(self):
        self.assertEqual(one("12,000.5 kg").value, 12000.5)


class RangeTests(unittest.TestCase):
    def test_range_variants(self):
        for t in ("5–10 mm", "5-10 mm", "5 to 10 mm", "from 5 to 10 mm", "5 mm to 10 mm", "5 — 10 mm"):
            q = one(t)
            self.assertEqual((q.kind, q.low, q.high, q.unit), ("range", 5.0, 10.0, "mm"), t)

    def test_range_without_unit(self):
        q = one("between 5-10 items")
        self.assertEqual((q.kind, q.unit), ("range", None))

    def test_mismatched_units_not_merged(self):
        qs = extract_quantities("5 mm to 10 kg")
        self.assertEqual([(q.kind, q.unit) for q in qs], [("value", "mm"), ("value", "kg")])


class ToleranceTests(unittest.TestCase):
    def test_absolute(self):
        for t in ("12 ± 0.5 kg", "12 +/- 0.5 kg", "12 kg ± 0.5 kg", "12±0.5 kg"):
            q = one(t)
            self.assertEqual((q.kind, q.value, q.unit), ("tolerance", 12.0, "kg"), t)
            self.assertAlmostEqual(q.low, 11.5)
            self.assertAlmostEqual(q.high, 12.5)

    def test_percent_relative(self):
        q = one("12 kg ± 4 %")
        self.assertEqual((q.kind, q.unit), ("tolerance", "kg"))
        self.assertAlmostEqual(q.low, 11.52)
        self.assertAlmostEqual(q.high, 12.48)

    def test_percent_of_percent_is_absolute(self):
        q = one("50 % ± 4 %")
        self.assertEqual((q.unit, q.low, q.high), ("%", 46.0, 54.0))


class UnitTests(unittest.TestCase):
    def test_aliases(self):
        groups = {
            "mm": ["3 mm", "3 millimetre", "3 millimeters"],
            "°C": ["3 °C", "3 degC", "3 deg C", "3°C"],
            "%": ["3 %", "3%", "3 percent"],
            "kg": ["3 kg", "3 kilograms"],
            "h": ["3 h", "3 hr", "3 hours"],
        }
        for canon, texts in groups.items():
            for t in texts:
                self.assertEqual(one(t).unit, canon, t)

    def test_bare_number(self):
        q = one("we saw 42 cases")
        self.assertIsNone(q.unit)
        self.assertEqual((q.low, q.high, q.value), (42.0, 42.0, 42.0))

    def test_unit_needs_boundary(self):
        self.assertIsNone(one("3 mmx").unit)


class SpanTests(unittest.TestCase):
    def test_spans_reconstruct(self):
        text = "Values: 3,5 kg, from 5 to 10 mm and 12 ± 0.5 kg; also -4.2 °C and 12 000 m."
        qs = extract_quantities(text)
        self.assertEqual(len(qs), 5)
        for q in qs:
            self.assertEqual(text[q.span[0]:q.span[1]], q.text)
        self.assertEqual([q.span for q in qs], sorted(q.span for q in qs))

    def test_urls_and_link_targets_skipped(self):
        text = "See https://ex.com/a/12/b?x=5 and [doc 3 kg](https://ex.com/v2/9) or [x](files/7.md)."
        qs = extract_quantities(text)
        self.assertEqual([(q.value, q.unit) for q in qs], [(3.0, "kg")])

    def test_dates_and_times_skipped(self):
        self.assertEqual(extract_quantities("on 2024-05-10 at 14:30"), ())

    def test_empty(self):
        self.assertEqual(extract_quantities(""), ())

    def test_frozen(self):
        q = one("3 kg")
        self.assertIsInstance(q, Quantity)
        with self.assertRaises(Exception):
            q.value = 4


if __name__ == "__main__":
    unittest.main()
