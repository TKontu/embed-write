"""AN-07 annotation store tests. Synthetic LLM-built data only (no corpus, no
expert annotations)."""

import builtins
import copy
import json
import os
import tempfile
import unittest
from unittest import mock

from service import annotation_store as st
from service import genre as g

FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'genre_synthetic.json')


def genre_v1():
    return g.load_genre(FIXTURE)


def genre_v2_version():
    obj = copy.deepcopy(genre_v1())
    obj['version'] = 2
    return obj


def genre_v2_content():
    obj = copy.deepcopy(genre_v1())
    obj['moves'][0]['definition'] = 'Changed invented definition.'
    return obj  # same version number, different hash


def rec(sid, label='alpha', annotator='ann-x', ts='2026-01-01T00:00:00Z'):
    return {'sentence_id': sid, 'label': label, 'annotator': annotator,
            'timestamp': ts}


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, 'labels.jsonl')
        self.store = st.AnnotationStore(self.path)

    def tearDown(self):
        self.tmp.cleanup()


class VersionIsolationTests(StoreCase):
    def test_v1_labels_not_returned_under_v2_version(self):
        self.store.append(genre_v1(), rec('s1'))
        self.store.append(genre_v1(), rec('s2', 'beta'))
        v2 = genre_v2_version()
        self.assertEqual(self.store.read(v2), [])
        self.assertEqual(self.store.stale_count(v2), 2)

    def test_v1_labels_not_returned_under_changed_hash(self):
        self.store.append(genre_v1(), rec('s1'))
        v2 = genre_v2_content()
        self.assertEqual(self.store.read(v2), [])
        self.assertEqual(self.store.stale_count(v2), 1)

    def test_current_and_stale_separated(self):
        self.store.append(genre_v1(), rec('s1'))
        self.store.append(genre_v2_version(), rec('s2', 'other'))
        out = self.store.read(genre_v2_version())
        self.assertEqual([r['sentence_id'] for r in out], ['s2'])
        self.assertEqual(self.store.stale_count(genre_v1()), 1)

    def test_records_carry_version_key(self):
        self.store.append(genre_v1(), rec('s1'))
        out = self.store.read(genre_v1())
        self.assertTrue(g.labels_valid_for(genre_v1(), out[0]))
        self.assertEqual(out[0]['genre'], 'synthetic-test-genre')

    def test_other_genre_not_counted_or_returned(self):
        other = copy.deepcopy(genre_v1())
        other['genre'] = 'another-genre'
        self.store.append(other, rec('s1'))
        self.assertEqual(self.store.read(genre_v1()), [])
        self.assertEqual(self.store.read(genre_v1(), include_stale=True), [])
        self.assertEqual(self.store.stale_count(genre_v1()), 0)


class IncludeStaleTests(StoreCase):
    def test_stale_exposed_only_when_asked_and_marked(self):
        self.store.append(genre_v1(), rec('s1'))
        self.store.append(genre_v2_version(), rec('s2'))
        v2 = genre_v2_version()
        self.assertTrue(all('stale' not in r or r['stale'] is False
                            for r in self.store.read(v2)))
        out = self.store.read(v2, include_stale=True)
        by = {r['sentence_id']: r for r in out}
        self.assertIs(by['s1']['stale'], True)
        self.assertIs(by['s2']['stale'], False)

    def test_stale_and_current_for_same_sentence_both_listed(self):
        self.store.append(genre_v1(), rec('s1', 'alpha'))
        self.store.append(genre_v2_version(), rec('s1', 'beta'))
        out = self.store.read(genre_v2_version(), include_stale=True)
        self.assertEqual(sorted((r['label'], r['stale']) for r in out),
                         [('alpha', True), ('beta', False)])
        self.assertEqual([r['label'] for r in self.store.read(genre_v2_version())],
                         ['beta'])


class ValidationTests(StoreCase):
    def test_unknown_label_rejected(self):
        with self.assertRaises(st.AnnotationStoreError):
            self.store.append(genre_v1(), rec('s1', 'gamma'))
        self.assertFalse(os.path.exists(self.path) and os.path.getsize(self.path))

    def test_other_accepted(self):
        self.store.append(genre_v1(), rec('s1', 'other'))
        self.assertEqual(self.store.read(genre_v1())[0]['label'], 'other')

    def test_missing_or_bad_fields_rejected(self):
        for bad in ({'label': 'alpha', 'annotator': 'a', 'timestamp': 't'},
                    rec(''), rec('s1', annotator=''), rec('s1', ts=5),
                    dict(rec('s1'), genre_version=9)):
            with self.subTest(bad=bad), self.assertRaises(st.AnnotationStoreError):
                self.store.append(genre_v1(), bad)

    def test_append_does_not_mutate_input(self):
        r = rec('s1')
        self.store.append(genre_v1(), r)
        self.assertEqual(r, rec('s1'))


class SupersedeTests(StoreCase):
    def test_last_write_wins_history_kept(self):
        self.store.append(genre_v1(), rec('s1', 'alpha', ts='t1'))
        self.store.append(genre_v1(), rec('s2', 'beta', ts='t1'))
        self.store.append(genre_v1(), rec('s1', 'beta', ts='t2'))
        out = self.store.read(genre_v1())
        self.assertEqual([(r['sentence_id'], r['label']) for r in out],
                         [('s1', 'beta'), ('s2', 'beta')])
        hist = self.store.history('s1')
        self.assertEqual([r['label'] for r in hist], ['alpha', 'beta'])
        with open(self.path, encoding='utf-8') as fh:
            self.assertEqual(len(fh.readlines()), 3)


class DurabilityTests(StoreCase):
    def test_reopen_returns_same_records(self):
        self.store.append(genre_v1(), rec('s1'))
        self.store.append(genre_v1(), rec('s2', 'other'))
        before = self.store.read(genre_v1())
        again = st.AnnotationStore(self.path)
        self.assertEqual(again.read(genre_v1()), before)

    def test_one_line_per_append_and_fsync(self):
        with mock.patch.object(st.os, 'fsync', wraps=os.fsync) as fs:
            self.store.append(genre_v1(), rec('s1'))
            self.store.append(genre_v1(), rec('s2'))
        self.assertEqual(fs.call_count, 2)
        with open(self.path, encoding='utf-8') as fh:
            lines = fh.read().split('\n')
        self.assertEqual(lines[-1], '')
        self.assertEqual(len(lines), 3)
        for line in lines[:2]:
            json.loads(line)

    def test_truncated_last_line_reported_on_read(self):
        self.store.append(genre_v1(), rec('s1'))
        with open(self.path, 'a', encoding='utf-8') as fh:
            fh.write('{"sentence_id": "s2", "lab')
        again = st.AnnotationStore(self.path)  # opening does not crash
        with self.assertRaises(st.TruncatedRecordError) as cm:
            again.read(genre_v1())
        self.assertIn('line 2', str(cm.exception))
        with self.assertRaises(st.TruncatedRecordError):
            again.stale_count(genre_v1())

    def test_append_refuses_after_truncated_tail(self):
        self.store.append(genre_v1(), rec('s1'))
        with open(self.path, 'a', encoding='utf-8') as fh:
            fh.write('{"partial')
        with self.assertRaises(st.TruncatedRecordError):
            self.store.append(genre_v1(), rec('s2'))

    def test_corrupt_middle_line_reported(self):
        with open(self.path, 'w', encoding='utf-8') as fh:
            fh.write('not json\n')
        with self.assertRaises(st.AnnotationStoreError) as cm:
            self.store.read(genre_v1())
        self.assertIn('line 1', str(cm.exception))

    def test_missing_file_reads_empty(self):
        self.assertEqual(self.store.read(genre_v1()), [])
        self.assertEqual(self.store.stale_count(genre_v1()), 0)


class StreamingTests(StoreCase):
    def test_read_never_loads_whole_file(self):
        for i in range(5):
            self.store.append(genre_v1(), rec(f's{i}'))
        real_open = builtins.open

        class Guard:
            def __init__(self, fh):
                self.fh = fh

            def __enter__(self):
                return self

            def __exit__(self, *a):
                self.fh.close()

            def __iter__(self):
                return iter(self.fh)

            def read(self, *a):
                raise AssertionError('whole-file read')

            def readlines(self, *a):
                raise AssertionError('whole-file readlines')

        def guarded(*a, **k):
            return Guard(real_open(*a, **k))

        with mock.patch.object(st, 'open', guarded, create=True):
            self.assertEqual(len(self.store.read(genre_v1())), 5)
            self.assertEqual(self.store.stale_count(genre_v1()), 0)


if __name__ == '__main__':
    unittest.main()
