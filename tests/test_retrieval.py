import unittest

from analysis.retrieval import Candidate, EvidenceItem, retrieve_candidates, to_support_links
from analysis.support_signals import SupportLink
from service.vectors import CrossLevelError, Level, LevelVector


def v(*values, level=Level.SENTENCE):
    return LevelVector(level, values)


def ev(node_id, *values, source='document', level=Level.SENTENCE):
    return EvidenceItem(node_id, v(*values, level=level), source)


class RetrievalTests(unittest.TestCase):
    def test_top_k_ordering_by_cosine(self):
        result = retrieve_candidates(
            {'c': v(1, 0)},
            [ev('far', 0, 1), ev('near', 1, 0.1), ev('mid', 1, 1)], k=2)
        self.assertEqual([x.evidence_id for x in result['c']], ['near', 'mid'])
        self.assertEqual([x.rank for x in result['c']], [1, 2])
        self.assertGreater(result['c'][0].score, result['c'][1].score)

    def test_k_larger_than_evidence(self):
        result = retrieve_candidates({'c': v(1, 0)}, [ev('a', 1, 0), ev('b', 0, 1)], k=10)
        self.assertEqual([x.evidence_id for x in result['c']], ['a', 'b'])

    def test_self_exclusion(self):
        result = retrieve_candidates({'s1': v(1, 0)}, [ev('s1', 1, 0), ev('s2', 1, 1)])
        self.assertEqual([x.evidence_id for x in result['s1']], ['s2'])

    def test_negative_cosine_clipped(self):
        result = retrieve_candidates({'c': v(1, 0)}, [ev('neg', -1, 0)])
        self.assertEqual(result['c'][0].score, 0.0)

    def test_tie_broken_by_input_order(self):
        evidence = [ev('first', 1, 1), ev('second', 2, 2), ev('third', 3, 3)]
        result = retrieve_candidates({'c': v(1, 1)}, evidence, k=2)
        self.assertEqual([x.evidence_id for x in result['c']], ['first', 'second'])

    def test_generator_consumed_once(self):
        calls = []

        def gen():
            calls.append(1)
            yield ev('a', 1, 0)
            yield ev('b', 0, 1)

        result = retrieve_candidates({'c1': v(1, 0), 'c2': v(0, 1)}, gen())
        self.assertEqual(len(calls), 1)
        self.assertEqual(result['c1'][0].evidence_id, 'a')
        self.assertEqual(result['c2'][0].evidence_id, 'b')

    def test_claims_without_evidence(self):
        self.assertEqual(retrieve_candidates({'c': v(1, 0)}, []), {'c': []})
        self.assertEqual(retrieve_candidates({}, [ev('a', 1)]), {})

    def test_mixed_level_raises(self):
        with self.assertRaises(CrossLevelError):
            retrieve_candidates({'c': v(1, 0)}, [ev('a', 1, 0, level=Level.BLOCK)])
        with self.assertRaises(CrossLevelError):
            retrieve_candidates({'c': v(1, 0), 'd': v(1, 0, level=Level.BLOCK)}, [])
        with self.assertRaises(CrossLevelError):
            retrieve_candidates({}, [ev('a', 1), ev('b', 1, level=Level.SECTION)])

    def test_duplicate_evidence_id(self):
        with self.assertRaises(ValueError):
            retrieve_candidates({'c': v(1, 0)}, [ev('a', 1, 0), ev('a', 0, 1, source='src')])

    def test_bad_k(self):
        for k in (0, -1, True, 2.5):
            with self.subTest(k=k), self.assertRaises(ValueError):
                retrieve_candidates({'c': v(1)}, [], k=k)

    def test_bad_evidence_item(self):
        for args in (('', v(1), 'document'), ('a', v(1), ''), (None, v(1), 'document')):
            with self.subTest(args=args), self.assertRaises(ValueError):
                EvidenceItem(*args)
        with self.assertRaises((TypeError, ValueError)):
            EvidenceItem('a', (1.0,), 'document')
        with self.assertRaises(TypeError):
            retrieve_candidates({'c': v(1)}, [('a', v(1), 'document')])

    def test_to_support_links_order(self):
        result = retrieve_candidates(
            {'c2': v(0, 1), 'c1': v(1, 0)}, [ev('a', 1, 0), ev('b', 0, 1)])
        links = to_support_links(result)
        self.assertTrue(all(isinstance(x, SupportLink) for x in links))
        self.assertEqual([(x.claim_id, x.evidence_id) for x in links],
                         [('c2', 'b'), ('c2', 'a'), ('c1', 'a'), ('c1', 'b')])
        self.assertEqual(links[0].score, result['c2'][0].score)

    def test_document_and_linked_source_retrievable(self):
        result = retrieve_candidates(
            {'c': v(1, 0)},
            [ev('s2', 1, 0.2), ev('src1#3', 1, 0.1, source='src1')], k=2)
        self.assertEqual([(x.evidence_id, x.source) for x in result['c']],
                         [('src1#3', 'src1'), ('s2', 'document')])
        self.assertIsInstance(result['c'][0], Candidate)


if __name__ == '__main__':
    unittest.main()
