import contextlib
import io
import json
import os
import tempfile
import unittest

from service import contrast as c

WHITE, BLACK = (255, 255, 255), (0, 0, 0)
LIGHT = {'text': '#000000', 'background': '#ffffff'}
DARK = {'text': '#ffffff', 'background': '#000000'}


class RatioTests(unittest.TestCase):
    def test_black_white_21(self):
        self.assertAlmostEqual(c.contrast_ratio(BLACK, WHITE), 21.0, delta=1e-6)

    def test_same_colour_1(self):
        self.assertAlmostEqual(c.contrast_ratio((10, 200, 30), (10, 200, 30)), 1.0)

    def test_symmetric(self):
        a, b = (12, 80, 200), (250, 240, 10)
        self.assertEqual(c.contrast_ratio(a, b), c.contrast_ratio(b, a))

    def test_known_wcag_pair(self):
        self.assertAlmostEqual(c.contrast_ratio((0x77,) * 3, WHITE), 4.48, delta=0.01)


class BlendTests(unittest.TestCase):
    def test_endpoints(self):
        t, b = (200, 10, 30), (5, 90, 250)
        self.assertEqual(c.blend(t, b, 0), b)
        self.assertEqual(c.blend(t, b, 1), t)

    def test_bad_alpha(self):
        for a in (-0.01, 1.01, float('nan')):
            with self.assertRaises(ValueError):
                c.blend(WHITE, BLACK, a)


class CheckTests(unittest.TestCase):
    def test_dark_tint_flagged_pale_passes(self):
        out = c.check({'light': LIGHT}, {'dark': '#202020', 'pale': '#fff0c0'}, 0.8)
        self.assertEqual([(s.theme, s.move) for s in out], [('light', 'dark')])
        self.assertLess(out[0].ratio, c.MIN_CONTRAST)

    def test_two_themes_ordered(self):
        out = c.check({'zlight': LIGHT, 'adark': DARK},
                      {'b': '#777777', 'a': '#7a7a7a'}, 1.0, min_ratio=5.0)
        self.assertEqual([(s.theme, s.move) for s in out],
                         [('adark', 'a'), ('adark', 'b'), ('zlight', 'a'), ('zlight', 'b')])

    def test_empty_is_pass(self):
        self.assertEqual(c.check({'light': LIGHT}, {'pale': '#fff0c0'}, 0.5), ())


class CliTests(unittest.TestCase):
    def _run(self, payload):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, 'spec.json')
            with open(path, 'w', encoding='utf-8') as fh:
                fh.write(payload if isinstance(payload, str) else json.dumps(payload))
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                return c.main([path])

    def test_exit_codes(self):
        base = {'alpha': 0.8, 'themes': {'light': LIGHT}}
        self.assertEqual(self._run({**base, 'palette': {'pale': '#fff0c0'}}), 0)
        self.assertEqual(self._run({**base, 'palette': {'dark': '#202020'}}), 1)
        self.assertEqual(self._run('not json'), 2)
        self.assertEqual(self._run({'alpha': 0.5, 'themes': {}}), 2)
        self.assertEqual(self._run({**base, 'alpha': 2, 'palette': {}}), 2)


class GenreCliTests(unittest.TestCase):
    """--genre mode; synthetic LLM-built genre fixtures, placeholder colours."""

    SPEC = {'alpha': 0.8, 'themes': {'light': LIGHT}}

    def _run(self, spec, genre):
        with tempfile.TemporaryDirectory() as d:
            sp, gp = os.path.join(d, 'spec.json'), os.path.join(d, 'genre.json')
            with open(sp, 'w', encoding='utf-8') as fh:
                json.dump(spec, fh)
            with open(gp, 'w', encoding='utf-8') as fh:
                json.dump(genre, fh)
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = c.main([sp, '--genre', gp])
            return code, out.getvalue(), err.getvalue()

    def test_pale_tints_pass(self):
        code, out, _ = self._run(self.SPEC, genre_obj({'a': '#fff0c0', 'b': '#e0f0ff'}))
        self.assertEqual((code, out), (0, ''))

    def test_dark_move_tint_fails(self):
        code, out, _ = self._run(self.SPEC, genre_obj({'a': '#fff0c0', 'b': '#202020'}))
        self.assertEqual(code, 1)
        self.assertIn('light: b ratio=', out)
        self.assertNotIn(': a ', out)

    def test_dark_other_tint_fails(self):
        code, out, _ = self._run(self.SPEC, genre_obj({'a': '#fff0c0'}, other='#202020'))
        self.assertEqual(code, 1)
        self.assertIn('light: other ratio=', out)

    def test_invalid_genre_exits_2_naming_field(self):
        g = genre_obj({'a': '#fff0c0'})
        g['legend']['other'] = 'grey'
        code, _, err = self._run(self.SPEC, g)
        self.assertEqual(code, 2)
        self.assertIn('legend.other', err)

    def test_palette_in_spec_with_genre_exits_2(self):
        code, _, err = self._run({**self.SPEC, 'palette': {'a': '#fff0c0'}},
                                 genre_obj({'a': '#fff0c0'}))
        self.assertEqual(code, 2)
        self.assertIn('palette', err)

    def test_spec_still_needs_themes_and_alpha(self):
        self.assertEqual(self._run({'alpha': 0.8}, genre_obj({'a': '#fff0c0'}))[0], 2)
        self.assertEqual(self._run({'themes': {'light': LIGHT}},
                                   genre_obj({'a': '#fff0c0'}))[0], 2)


def genre_obj(colors, other='#f0f0f0'):
    ids = list(colors)
    return {
        'genre': 'synthetic', 'version': 1,
        'moves': [{'id': i, 'name': i, 'definition': 'd', 'near_miss': 'n',
                   'positive_examples': ['e1', 'e2']} for i in ids],
        'legend': {'colors': dict(colors), 'other': other},
    }


if __name__ == '__main__':
    unittest.main()
