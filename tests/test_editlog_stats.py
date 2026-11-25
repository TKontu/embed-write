import contextlib
import io
import os
import tempfile
import unittest

from editlog import EditLogStore
from editlog.schema import EditLogEntry
from analysis.signals import BANNED_WORDS


def make(genre, action):
    return EditLogEntry(
        genre=genre, section_type='intro', move='gap', original_text='o',
        candidate='c', final_text='f', action=action,
        panel_values={}, generation_run_id='run',
        timestamp='2026-11-24T10:00:00+00:00')


class AcceptanceStatsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, 'log.sqlite')
        self.store = EditLogStore(self.path)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def fill(self):
        for g, a in [('paper', 'accept'), ('paper', 'accept'),
                     ('paper', 'edit'), ('grant', 'reject'),
                     ('grant', 'accept'), ('paper', 'reject')]:
            self.store.append(make(g, a))

    def test_counts_per_action_and_genre(self):
        from editlog.stats import AcceptanceStats, GenreStats, acceptance_stats
        self.fill()
        self.assertEqual(acceptance_stats(self.store), AcceptanceStats(
            total=6, accept=3, edit=1, reject=2, by_genre=(
                GenreStats('grant', 2, 1, 0, 1),
                GenreStats('paper', 4, 2, 1, 1))))

    def test_frozen(self):
        from editlog.stats import acceptance_stats
        s = acceptance_stats(self.store)
        with self.assertRaises(Exception):
            s.total = 1

    def test_empty_log(self):
        from editlog.stats import AcceptanceStats, acceptance_stats, format_stats
        s = acceptance_stats(self.store)
        self.assertEqual(s, AcceptanceStats(0, 0, 0, 0, ()))
        text = format_stats(s)
        self.assertIn('n/a', text)
        self.assertNotIn('%', text)

    def test_format_counts_and_percentages(self):
        from editlog.stats import acceptance_stats, format_stats
        self.fill()
        text = format_stats(acceptance_stats(self.store))
        self.assertIn('total 6', text)
        self.assertIn('accept 3 (50.0%)', text)
        self.assertIn('edit 1 (16.7%)', text)
        self.assertIn('reject 2 (33.3%)', text)
        self.assertIn('grant', text)
        self.assertIn('accept 2 (50.0%)', text)
        for w in BANNED_WORDS:
            self.assertNotIn(w, text.lower())

    def test_cli_missing_path(self):
        from editlog.stats import main
        missing = os.path.join(self.tmp.name, 'none.sqlite')
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(main([missing]), 2)
        self.assertFalse(os.path.exists(missing))
        self.assertIn('no edit log', err.getvalue())

    def test_cli_populated(self):
        from editlog.stats import main
        self.fill()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(main([self.path]), 0)
        self.assertIn('total 6', out.getvalue())
        self.assertIn('reject 2 (33.3%)', out.getvalue())


if __name__ == '__main__':
    unittest.main()
