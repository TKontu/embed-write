import copy
import json
import os
import tempfile
import unittest

from service import genre as g

FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'genre_synthetic.json')


def base():
    with open(FIXTURE, encoding='utf-8') as fh:
        return json.load(fh)


def move(i):
    return {'id': f'm{i}', 'name': f'Move {i}', 'definition': 'Invented.',
            'positive_examples': ['a.', 'b.'], 'near_miss': 'c.'}


class LoadTests(unittest.TestCase):
    def test_valid_fixture_loads(self):
        obj = g.load_genre(FIXTURE)
        self.assertEqual(obj['version'], 1)
        self.assertEqual([m['id'] for m in obj['moves']], ['alpha', 'beta'])

    def test_invalid_json_raises(self):
        with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as fh:
            fh.write('{not json')
        try:
            with self.assertRaises(g.GenreFileError):
                g.load_genre(fh.name)
        finally:
            os.unlink(fh.name)


class ValidationTests(unittest.TestCase):
    def assertFails(self, obj, field):
        with self.assertRaises(g.GenreFileError) as cm:
            g.validate_genre(obj)
        self.assertIn(field, str(cm.exception))

    def test_top_level_required(self):
        for key in ('genre', 'version', 'moves', 'legend'):
            obj = base(); del obj[key]
            self.assertFails(obj, key)

    def test_move_required(self):
        for key in ('id', 'name', 'definition', 'positive_examples', 'near_miss'):
            obj = base(); del obj['moves'][0][key]
            self.assertFails(obj, f'moves[0].{key}')

    def test_legend_required(self):
        for key in ('colors', 'other'):
            obj = base(); del obj['legend'][key]
            self.assertFails(obj, f'legend.{key}')

    def test_duplicate_move_id(self):
        obj = base(); obj['moves'][1]['id'] = 'alpha'
        self.assertFails(obj, 'moves[1].id')

    def test_legend_unknown_move(self):
        obj = base(); obj['legend']['colors']['gamma'] = '#000000'
        self.assertFails(obj, 'legend.colors.gamma')

    def test_legend_comment_key_ignored(self):
        obj = base(); obj['legend']['colors']['_note'] = 'x'
        g.validate_genre(obj)
        self.assertEqual(g.content_hash(obj), g.content_hash(base()))

    def test_move_missing_from_legend(self):
        obj = base(); del obj['legend']['colors']['beta']
        self.assertFails(obj, 'legend.colors.beta')

    def test_malformed_hex(self):
        for bad in ('1f77b4', '#1f77b', '#gggggg', 7):
            obj = base(); obj['legend']['colors']['alpha'] = bad
            self.assertFails(obj, 'legend.colors.alpha')
        obj = base(); obj['legend']['other'] = 'grey'
        self.assertFails(obj, 'legend.other')

    def test_eleven_moves(self):
        obj = base()
        obj['moves'] = [move(i) for i in range(11)]
        obj['legend']['colors'] = {f'm{i}': '#000000' for i in range(11)}
        self.assertFails(obj, 'moves')
        obj['moves'].pop(); del obj['legend']['colors']['m10']
        g.validate_genre(obj)

    def test_bad_types(self):
        obj = base(); obj['version'] = True
        self.assertFails(obj, 'version')
        obj = base(); obj['version'] = 0
        self.assertFails(obj, 'version')
        obj = base(); obj['moves'][0]['positive_examples'] = ['only one']
        self.assertFails(obj, 'moves[0].positive_examples')
        obj = base(); obj['moves'][0]['id'] = 'other'
        self.assertFails(obj, 'moves[0].id')
        obj = base(); obj['moves'] = []
        self.assertFails(obj, 'moves')


class HashTests(unittest.TestCase):
    def test_stable_under_key_reordering(self):
        obj = base()
        reordered = json.loads(json.dumps(obj, sort_keys=True))
        reordered = dict(reversed(list(reordered.items())))
        reordered['legend'] = dict(reversed(list(reordered['legend'].items())))
        self.assertEqual(g.content_hash(obj), g.content_hash(reordered))

    def test_changes_on_content_change(self):
        h = g.content_hash(base())
        edits = [
            lambda o: o['moves'][0].__setitem__('definition', 'Changed.'),
            lambda o: o['moves'][1]['positive_examples'].__setitem__(0, 'x.'),
            lambda o: o['legend']['colors'].__setitem__('alpha', '#000001'),
            lambda o: o['legend'].__setitem__('other', '#000001'),
            lambda o: o.__setitem__('genre', 'other-genre'),
            lambda o: o['moves'].reverse(),
        ]
        for edit in edits:
            obj = base(); edit(obj)
            self.assertNotEqual(g.content_hash(obj), h)

    def test_version_not_part_of_content(self):
        obj = base(); obj['version'] = 2
        self.assertEqual(g.content_hash(obj), g.content_hash(base()))


class VersionBumpTests(unittest.TestCase):
    def test_content_changed_without_bump_fails(self):
        old, new = base(), base()
        new['moves'][0]['name'] = 'Renamed'
        with self.assertRaises(g.GenreFileError) as cm:
            g.check_version_bump(old, new)
        self.assertIn('version', str(cm.exception))

    def test_content_changed_with_bump_passes(self):
        old, new = base(), base()
        new['moves'][0]['name'] = 'Renamed'; new['version'] = 2
        g.check_version_bump(old, new)

    def test_unchanged_passes(self):
        g.check_version_bump(base(), base())

    def test_version_decrease_fails(self):
        old, new = base(), base()
        old['version'] = 3; new['version'] = 2; new['genre'] = 'x'
        with self.assertRaises(g.GenreFileError):
            g.check_version_bump(old, new)


class LabelValidityTests(unittest.TestCase):
    def test_valid_then_invalid_after_change(self):
        obj = base()
        record = {'labels': [], **g.version_key(obj)}
        self.assertTrue(g.labels_valid_for(obj, record))
        changed = copy.deepcopy(obj)
        changed['legend']['colors']['beta'] = '#123456'; changed['version'] = 2
        self.assertFalse(g.labels_valid_for(changed, record))

    def test_same_version_different_hash_invalid(self):
        obj = base()
        record = g.version_key(obj)
        obj['moves'][0]['near_miss'] = 'Edited.'
        self.assertFalse(g.labels_valid_for(obj, record))

    def test_missing_key_invalid(self):
        self.assertFalse(g.labels_valid_for(base(), {}))


if __name__ == '__main__':
    unittest.main()
