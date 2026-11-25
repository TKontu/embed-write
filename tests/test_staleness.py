"""Synthetic review/edit sequences for the LY-05 guard."""

import unittest


class StalenessGuardTests(unittest.TestCase):
    def setUp(self):
        from analysis.staleness import StalenessGuard
        self.guard = StalenessGuard()

    def test_edit_during_review_discards_result(self):
        ticket = self.guard.start('node', 'h1')
        self.guard.note_edit('node', 'h2')
        self.assertFalse(self.guard.accept(ticket))
        self.assertEqual(self.guard.discard_count, 1)

    def test_unchanged_result_is_accepted(self):
        ticket = self.guard.start('node', 'h1')
        self.assertTrue(self.guard.accept(ticket))
        self.assertEqual(self.guard.discard_count, 0)

    def test_edit_then_revert_is_accepted(self):
        ticket = self.guard.start('node', 'h1')
        self.guard.note_edit('node', 'h2')
        self.guard.note_edit('node', 'h1')
        self.assertTrue(self.guard.accept(ticket))
        self.assertEqual(self.guard.discard_count, 0)

    def test_same_hash_edit_is_accepted(self):
        ticket = self.guard.start('node', 'h1')
        self.guard.note_edit('node', 'h1')
        self.assertTrue(self.guard.accept(ticket))

    def test_overlapping_reviews_complete_in_either_order(self):
        for newest_first in (False, True):
            with self.subTest(newest_first=newest_first):
                old = self.guard.start('node', 'h1')
                self.guard.note_edit('node', 'h2')
                new = self.guard.start('node', 'h2')
                order = [(old, False), (new, True)]
                for ticket, expected in reversed(order) if newest_first else order:
                    self.assertEqual(self.guard.accept(ticket), expected)
                self.guard.note_edit('node', 'h1')
        self.assertEqual(self.guard.discard_count, 2)

    def test_same_hash_tickets_are_independent(self):
        first = self.guard.start('node', 'h1')
        second = self.guard.start('node', 'h1')
        self.assertIsNot(first, second)
        self.assertTrue(self.guard.accept(first))
        self.assertTrue(self.guard.accept(second))

    def test_nodes_are_independent(self):
        first = self.guard.start('one', 'h1')
        second = self.guard.start('two', 'h1')
        self.guard.note_edit('one', 'h2')
        self.assertFalse(self.guard.accept(first))
        self.assertTrue(self.guard.accept(second))

    def test_start_does_not_overwrite_known_current_hash(self):
        self.guard.note_edit('node', 'h2')
        stale = self.guard.start('node', 'h1')
        current = self.guard.start('node', 'h2')
        self.assertFalse(self.guard.accept(stale))
        self.assertTrue(self.guard.accept(current))

    def test_consumed_tickets_raise_without_counting_again(self):
        for changed in (False, True):
            with self.subTest(changed=changed):
                ticket = self.guard.start('node', 'h1')
                if changed:
                    self.guard.note_edit('node', 'h2')
                self.assertEqual(self.guard.accept(ticket), not changed)
                with self.assertRaises(ValueError):
                    self.guard.accept(ticket)
        self.assertEqual(self.guard.discard_count, 1)

    def test_foreign_and_unknown_tickets_do_not_consume_valid_ticket(self):
        from analysis.staleness import StalenessGuard
        ticket = self.guard.start('node', 'h1')
        other = StalenessGuard()
        with self.assertRaises(ValueError):
            other.accept(ticket)
        with self.assertRaises(ValueError):
            self.guard.accept(object())
        for invalid in (None, [], {}, 1, 'ticket'):
            with self.subTest(invalid=invalid), self.assertRaises(TypeError):
                self.guard.accept(invalid)
        self.assertTrue(self.guard.accept(ticket))
        self.assertEqual(self.guard.discard_count, 0)
        self.assertEqual(other.discard_count, 0)

    def test_invalid_start_and_edit_leave_current_hash_unchanged(self):
        ticket = self.guard.start('node', 'h1')
        for method in (self.guard.start, self.guard.note_edit):
            for invalid, error in ((None, TypeError), (1, TypeError),
                                   ([], TypeError), ('', ValueError)):
                for args in ((invalid, 'h2'), ('node', invalid)):
                    with self.subTest(method=method.__name__, args=args):
                        with self.assertRaises(error):
                            method(*args)
        self.assertTrue(self.guard.accept(ticket))
        self.assertEqual(self.guard.discard_count, 0)

    def test_completion_releases_ticket(self):
        ticket = self.guard.start('node', 'h1')
        self.guard.accept(ticket)
        # White-box check of the packet's open-ticket storage bound.
        self.assertEqual(len(self.guard._tickets), 0)
        self.assertEqual(len(self.guard._current), 1)


if __name__ == '__main__':
    unittest.main()
