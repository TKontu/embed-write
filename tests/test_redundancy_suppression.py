import json
import os
import tempfile
import unittest

from analysis.redundancy import RedundantPair
from analysis.redundancy_suppression import SuppressionStore, filter_suppressed


def _pair(a, b):
    return RedundantPair(first=a, second=b, first_section='s1', second_section='s2', score=0.95)


class SuppressionStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, 'suppressions.jsonl')

    def tearDown(self):
        self.tmp.cleanup()

    def test_mark_is_per_document(self):
        store = SuppressionStore(self.path)
        store.mark('doc-a', 'n1', 'n2')
        self.assertEqual(store.suppressed('doc-a'), frozenset({frozenset({'n1', 'n2'})}))
        self.assertEqual(store.suppressed('doc-b'), frozenset())

    def test_record_shape(self):
        SuppressionStore(self.path).mark('doc-a', 'n1', 'n2')
        with open(self.path, encoding='utf-8') as fh:
            lines = fh.readlines()
        self.assertEqual([json.loads(l) for l in lines],
                         [{'document': 'doc-a', 'first': 'n1', 'second': 'n2'}])

    def test_duplicate_and_reversed_marks_idempotent(self):
        store = SuppressionStore(self.path)
        store.mark('doc-a', 'n1', 'n2')
        store.mark('doc-a', 'n1', 'n2')
        store.mark('doc-a', 'n2', 'n1')
        self.assertEqual(store.suppressed('doc-a'), frozenset({frozenset({'n1', 'n2'})}))

    def test_malformed_input_raises_and_writes_nothing(self):
        store = SuppressionStore(self.path)
        bad = [('', 'n1', 'n2'), ('d', '', 'n2'), ('d', 'n1', ''), (None, 'n1', 'n2'),
               ('d', 1, 'n2'), ('d', 'n1', ['n2']), ('d', 'n1', 'n1')]
        for args in bad:
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    store.mark(*args)
        self.assertFalse(os.path.exists(self.path))

    def test_missing_file_is_empty(self):
        self.assertEqual(SuppressionStore(self.path).suppressed('doc-a'), frozenset())

    def test_corrupt_line_names_line_number(self):
        store = SuppressionStore(self.path)
        store.mark('doc-a', 'n1', 'n2')
        with open(self.path, 'a', encoding='utf-8') as fh:
            fh.write('{not json\n')
        with self.assertRaisesRegex(ValueError, 'line 2'):
            store.suppressed('doc-a')

    def test_invalid_record_fields_rejected(self):
        with open(self.path, 'w', encoding='utf-8') as fh:
            fh.write(json.dumps({'document': 'doc-a', 'first': 'n1', 'second': 'n1'}) + '\n')
        with self.assertRaisesRegex(ValueError, 'line 1'):
            SuppressionStore(self.path).suppressed('doc-a')

    def test_truncated_line_rejected(self):
        with open(self.path, 'w', encoding='utf-8') as fh:
            fh.write(json.dumps({'document': 'doc-a', 'first': 'n1', 'second': 'n2'}))
        with self.assertRaisesRegex(ValueError, 'line 1'):
            SuppressionStore(self.path).suppressed('doc-a')

    def test_new_instance_reads_earlier_marks(self):
        SuppressionStore(self.path).mark('doc-a', 'n1', 'n2')
        self.assertEqual(SuppressionStore(self.path).suppressed('doc-a'),
                         frozenset({frozenset({'n1', 'n2'})}))


class FilterSuppressedTests(unittest.TestCase):
    def test_drops_reversed_pair_and_keeps_order(self):
        pairs = (_pair('a', 'b'), _pair('c', 'd'), _pair('e', 'f'), _pair('g', 'h'))
        result = filter_suppressed(pairs, frozenset({frozenset({'b', 'a'}), frozenset({'f', 'e'})}))
        self.assertIsInstance(result, tuple)
        self.assertEqual(result, (_pair('c', 'd'), _pair('g', 'h')))

    def test_empty_suppression_keeps_all(self):
        pairs = [_pair('a', 'b'), _pair('c', 'd')]
        self.assertEqual(filter_suppressed(pairs, frozenset()), tuple(pairs))


if __name__ == '__main__':
    unittest.main()
