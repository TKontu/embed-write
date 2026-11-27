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


class IterRecordsTests(StoreCase):
    def test_iter_records_is_generator_equal_to_records(self):
        import types
        self.store.append(genre_v1(), rec('s1'))
        self.store.append(genre_v1(), rec('s2', label='beta'))
        it = self.store.iter_records()
        self.assertIsInstance(it, types.GeneratorType)
        self.assertEqual(list(it), list(self.store._records()))
        self.assertEqual([o['sentence_id'] for _, o in self.store.iter_records()],
                         ['s1', 's2'])


class RetractionTests(StoreCase):
    def retraction(self, sid, annotator='ann-x'):
        return {'sentence_id': sid, 'retracted': True, 'annotator': annotator,
                'timestamp': '2026-01-02T00:00:00Z'}

    def test_read_hides_retracted_sentence(self):
        self.store.append(genre_v1(), rec('s1'))
        self.store.append(genre_v1(), rec('s2'))
        self.store.append(genre_v1(), self.retraction('s1'))
        self.assertEqual([r['sentence_id'] for r in self.store.read(genre_v1())], ['s2'])
        self.assertEqual(len(self.store.history('s1')), 2)

    def test_relabel_after_retraction_is_current(self):
        self.store.append(genre_v1(), rec('s1'))
        self.store.append(genre_v1(), self.retraction('s1'))
        self.store.append(genre_v1(), rec('s1', label='beta'))
        self.assertEqual([r['label'] for r in self.store.read(genre_v1())], ['beta'])

    def test_retraction_shape_validated(self):
        for bad in (dict(self.retraction('s1'), label='alpha'),
                    dict(self.retraction('s1'), retracted='yes'),
                    {'sentence_id': 's1', 'annotator': 'a', 'timestamp': 't'}):
            with self.subTest(bad=bad), self.assertRaises(st.AnnotationStoreError):
                self.store.append(genre_v1(), bad)


class RepairTailTests(StoreCase):
    def _torn(self, tail=b'{"sentence_id": "s9", "lab'):
        self.store.append(genre_v1(), rec('s1'))
        self.store.append(genre_v1(), rec('s2'))
        with open(self.path, 'ab') as fh:
            fh.write(tail)
        return tail

    def test_nothing_to_repair_missing_empty_clean(self):
        self.assertIsNone(self.store.repair_tail())  # missing
        self.assertFalse(os.path.exists(self.path))
        open(self.path, 'wb').close()
        self.assertIsNone(self.store.repair_tail())  # empty
        self.store.append(genre_v1(), rec('s1'))
        with open(self.path, 'rb') as fh:
            before = fh.read()
        self.assertIsNone(self.store.repair_tail())
        with open(self.path, 'rb') as fh:
            self.assertEqual(fh.read(), before)
        self.assertEqual(sorted(os.listdir(self.tmp.name)), ['labels.jsonl'])

    def test_torn_tail_moved_to_sidecar_and_append_resumes(self):
        tail = self._torn()
        with open(self.path, 'rb') as fh:
            complete = fh.read()[:-len(tail)]
        before = [json.loads(l) for l in complete.splitlines()]
        self.assertEqual(len(before), 2)
        side = self.store.repair_tail()
        self.assertTrue(os.path.basename(side).startswith('labels.jsonl.torn-'))
        with open(side, 'rb') as fh:
            self.assertEqual(fh.read(), tail)
        with open(self.path, 'rb') as fh:
            self.assertTrue(fh.read().endswith(b'\n'))
        self.assertEqual([r for _, r in self.store.iter_records()], before)
        self.store.append(genre_v1(), rec('s3'))
        self.assertEqual(len(list(self.store.iter_records())), 3)

    def test_no_newline_truncates_to_zero(self):
        with open(self.path, 'wb') as fh:
            fh.write(b'{"partial')
        side = self.store.repair_tail()
        self.assertEqual(os.path.getsize(self.path), 0)
        with open(side, 'rb') as fh:
            self.assertEqual(fh.read(), b'{"partial')

    def test_long_tail_spans_chunks(self):
        tail = b'x' * (3 * st.TAIL_CHUNK + 7)
        self._torn(tail)
        side = self.store.repair_tail()
        with open(side, 'rb') as fh:
            self.assertEqual(fh.read(), tail)
        self.assertEqual(len(list(self.store.iter_records())), 2)

    def test_sidecar_never_overwritten(self):
        self._torn(b'first')
        with mock.patch.object(st, '_utc_stamp', return_value='20260101T000000Z'):
            a = self.store.repair_tail()
            with open(self.path, 'ab') as fh:
                fh.write(b'second')
            b = self.store.repair_tail()
        self.assertNotEqual(a, b)
        with open(a, 'rb') as fh:
            self.assertEqual(fh.read(), b'first')
        with open(b, 'rb') as fh:
            self.assertEqual(fh.read(), b'second')

    def test_sidecar_failure_leaves_store_untouched(self):
        self._torn()
        with open(self.path, 'rb') as fh:
            before = fh.read()
        with mock.patch.object(st.os, 'fsync', side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                self.store.repair_tail()
        with open(self.path, 'rb') as fh:
            self.assertEqual(fh.read(), before)

    def _traced_repair(self, fail=None):
        """Run repair_tail recording fsync/open/close/truncate order."""
        events, dir_fds = [], set()
        self._last_events = events
        real_open, real_fsync, real_close = os.open, os.fsync, os.close
        real_ftrunc = os.ftruncate
        parent = os.path.realpath(self.tmp.name)

        def t_open(path, flags, *a, **k):
            is_dir = (os.path.realpath(path) == parent
                      and flags & getattr(os, 'O_DIRECTORY', 0))
            if is_dir and fail == 'open':
                raise OSError('dir open')
            fd = real_open(path, flags, *a, **k)
            if is_dir:
                dir_fds.add(fd)
                events.append('dir-open')
            return fd

        def t_fsync(fd):
            if fd in dir_fds:
                events.append('dir-fsync')
                if fail == 'fsync':
                    raise OSError('dir fsync')
            else:
                events.append('file-fsync')
            return real_fsync(fd)

        def t_close(fd):
            if fd in dir_fds:
                events.append('dir-close')
            return real_close(fd)

        def t_ftrunc(fd, n):
            events.append('truncate')
            return real_ftrunc(fd, n)

        with mock.patch.object(st.os, 'open', t_open), \
                mock.patch.object(st.os, 'fsync', t_fsync), \
                mock.patch.object(st.os, 'close', t_close), \
                mock.patch.object(st.os, 'ftruncate', t_ftrunc):
            side = self.store.repair_tail()
        return side, events

    @unittest.skipUnless(hasattr(os, 'O_DIRECTORY'), 'needs O_DIRECTORY')
    def test_dir_fsync_after_sidecar_before_truncate(self):
        self._torn()
        side, events = self._traced_repair()
        self.assertEqual(events, ['file-fsync', 'dir-open', 'dir-fsync',
                                  'dir-close', 'truncate', 'file-fsync'])
        self.assertTrue(os.path.exists(side))

    @unittest.skipUnless(hasattr(os, 'O_DIRECTORY'), 'needs O_DIRECTORY')
    def test_dir_fsync_failure_keeps_store_and_sidecar(self):
        for fail in ('open', 'fsync'):
            with self.subTest(fail=fail):
                for f in os.listdir(self.tmp.name):
                    os.unlink(os.path.join(self.tmp.name, f))
                self._torn()
                with open(self.path, 'rb') as fh:
                    before = fh.read()
                with self.assertRaises(OSError):
                    self._traced_repair(fail=fail)
                with open(self.path, 'rb') as fh:
                    self.assertEqual(fh.read(), before)
                sides = [f for f in os.listdir(self.tmp.name) if '.torn-' in f]
                self.assertEqual(len(sides), 1)
                self.assertNotIn('truncate', self._last_events)
                if fail == 'fsync':  # dir fd closed even when fsync raised
                    self.assertEqual(self._last_events[-2:],
                                     ['dir-fsync', 'dir-close'])

    def test_check_tail_message_names_cli(self):
        self._torn()
        with self.assertRaises(st.TruncatedRecordError) as cm:
            self.store.append(genre_v1(), rec('s3'))
        self.assertIn('python -m service.annotation_store repair', str(cm.exception))

    def test_docstring_names_repair(self):
        self.assertIn('repair_tail', st.__doc__)


class RepairCliTests(StoreCase):
    def _run(self, *argv):
        import io
        from contextlib import redirect_stderr, redirect_stdout
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = st.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_repair_reports_bytes_and_never_prints_tail(self):
        self.store.append(genre_v1(), rec('s1'))
        with open(self.path, 'ab') as fh:
            fh.write(b'SECRETPARTIAL')
        code, out, err = self._run('repair', self.path)
        self.assertEqual(code, 0)
        self.assertRegex(out, r'^repaired: moved 13 bytes to .*\.torn-')
        self.assertNotIn('SECRET', out + err)

    def test_nothing_to_repair(self):
        self.store.append(genre_v1(), rec('s1'))
        code, out, _ = self._run('repair', self.path)
        self.assertEqual((code, out.strip()), (0, 'nothing to repair'))

    def test_missing_path_exit_2(self):
        code, out, err = self._run('repair', self.path)
        self.assertEqual(code, 2)
        self.assertEqual(len(err.strip().splitlines()), 1)

    def test_os_error_exit_2(self):
        with open(self.path, 'ab') as fh:
            fh.write(b'SECRETPARTIAL')
        with mock.patch.object(st.os, 'fsync', side_effect=OSError('disk')):
            code, out, err = self._run('repair', self.path)
        self.assertEqual(code, 2)
        self.assertEqual(len(err.strip().splitlines()), 1)
        self.assertNotIn('SECRET', out + err)
