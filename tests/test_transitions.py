import itertools
import unittest

from analysis.transitions import END, START, LabelledSection, TransitionStats


def S(doc, kind, *moves):
    return LabelledSection(doc, kind, tuple(moves))


class TransitionStatsTest(unittest.TestCase):
    def test_start_end_counted(self):
        st = TransitionStats.from_sections([S('d1', 'intro', 'a', 'b')])
        self.assertEqual(st.count('intro', START, 'a'), 1)
        self.assertEqual(st.count('intro', 'a', 'b'), 1)
        self.assertEqual(st.count('intro', 'b', END), 1)
        self.assertEqual(st.section_count('intro'), 1)

    def test_empty_section_start_end(self):
        st = TransitionStats.from_sections([S('d1', 'intro')])
        self.assertEqual(st.transitions('intro'), ((START, END, 1, 1),))
        self.assertEqual(st.probability('intro', START, END), 1.0)

    def test_probabilities_sum_to_one(self):
        st = TransitionStats.from_sections([
            S('d1', 'x', 'a', 'b'), S('d2', 'x', 'a', 'c'),
            S('d3', 'x', 'a', 'b'), S('d4', 'x', 'a')])
        nexts = ('a', 'b', 'c', END)
        total = sum(st.probability('x', 'a', n) for n in nexts)
        self.assertAlmostEqual(total, 1.0)
        self.assertAlmostEqual(st.probability('x', 'a', 'b'), 0.5)
        self.assertEqual(st.probability('x', 'zzz', 'a'), 0.0)

    def test_support_distinct_documents(self):
        st = TransitionStats.from_sections([
            S('d1', 'x', 'a', 'b'), S('d1', 'x', 'a', 'b'),
            S('d2', 'x', 'a', 'b')])
        self.assertEqual(st.count('x', 'a', 'b'), 3)
        self.assertEqual(st.support('x', 'a', 'b'), 2)

    def test_support_same_doc_repeated_in_section(self):
        st = TransitionStats.from_sections([S('d1', 'x', 'a', 'a', 'a')])
        self.assertEqual(st.count('x', 'a', 'a'), 2)
        self.assertEqual(st.support('x', 'a', 'a'), 1)

    def test_section_types_separate(self):
        st = TransitionStats.from_sections([
            S('d1', 'methods', 'a'), S('d1', 'intro', 'b')])
        self.assertEqual(st.section_types(), ('intro', 'methods'))
        self.assertEqual(st.count('intro', START, 'a'), 0)
        self.assertEqual(st.count('methods', START, 'a'), 1)

    def test_unknown_type_zeros(self):
        st = TransitionStats.from_sections([S('d1', 'x', 'a')])
        self.assertEqual(st.count('nope', START, 'a'), 0)
        self.assertEqual(st.probability('nope', START, 'a'), 0.0)
        self.assertEqual(st.support('nope', START, 'a'), 0)
        self.assertEqual(st.section_count('nope'), 0)
        self.assertEqual(st.transitions('nope'), ())

    def test_generator_consumed_once(self):
        pulls = []

        def gen():
            for i in range(3):
                pulls.append(i)
                yield S(f'd{i}', 'x', 'a')

        g = gen()
        st = TransitionStats.from_sections(g)
        self.assertEqual(pulls, [0, 1, 2])
        self.assertEqual(list(g), [])
        self.assertEqual(st.count('x', START, 'a'), 3)

    def test_sentinel_move_rejected(self):
        for sentinel in (START, END):
            with self.assertRaises(ValueError):
                S('d1', 'x', 'a', sentinel)

    def test_invalid_fields_rejected(self):
        for args in (('', 'x', ()), ('d', '', ()), (1, 'x', ()),
                     ('d', None, ()), ('d', 'x', ('',)), ('d', 'x', (3,)),
                     ('d', 'x', ['a'])):
            with self.assertRaises(ValueError):
                LabelledSection(*args)

    def test_non_section_type_error(self):
        with self.assertRaises(TypeError):
            TransitionStats.from_sections([('d1', 'x', ('a',))])

    def test_transitions_order_permutation_invariant(self):
        secs = [S('d1', 'x', 'a', 'b'), S('d2', 'x', 'a', 'c'),
                S('d3', 'x', 'a', 'c'), S('d1', 'x', 'b'), S('d4', 'x')]
        expected = TransitionStats.from_sections(secs).transitions('x')
        self.assertEqual(expected[0], (START, 'a', 3, 3))
        prevs = [r[0] for r in expected]
        self.assertEqual(prevs, sorted(prevs))
        a_rows = [r for r in expected if r[0] == 'a']
        self.assertEqual(a_rows, [('a', 'c', 2, 2), ('a', 'b', 1, 1)])
        for perm in itertools.permutations(secs):
            self.assertEqual(
                TransitionStats.from_sections(perm).transitions('x'), expected)


if __name__ == '__main__':
    unittest.main()
