import contextlib
import io
import json
import os
import tempfile
import unittest

from service import palette as p

# Sharma, Wu & Dalal 2005, Table 1 (selected pairs).
SHARMA = [
    ((50, 2.6772, -79.7751), (50, 0, -82.7485), 2.0425),
    ((50, 3.1571, -77.2803), (50, 0, -82.7485), 2.8615),
    ((50, 2.8361, -74.0200), (50, 0, -82.7485), 3.4412),
    ((50, 0, 0), (50, -1, 2), 2.3669),
    ((50, 2.5, 0), (73, 25, -18), 27.1492),
    ((50, 2.5, 0), (61, -5, 29), 22.8977),
    ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
    ((63.0109, -31.0961, -5.8663), (62.8187, -29.7946, -4.0864), 1.2630),
    ((2.0776, 0.0795, -1.1350), (0.9033, -0.0636, -0.5514), 0.9082),
]

SPREAD = {'a': '#000000', 'b': '#ffffff', 'c': '#0072b2', 'd': '#e69f00'}


class PaletteTest(unittest.TestCase):
    def test_parse_hex(self):
        self.assertEqual(p.parse_hex('#ff8000'), (255, 128, 0))
        self.assertEqual(p.parse_hex('#ABCDEF'), (171, 205, 239))
        for bad in ('ff8000', '#ff80', '#gg0000', '#ff80000', '', None, ' #ff8000'):
            with self.assertRaises(ValueError):
                p.parse_hex(bad)

    def test_sharma_pairs(self):
        for l1, l2, want in SHARMA:
            self.assertAlmostEqual(p.delta_e_2000(l1, l2), want, delta=1e-4)
            self.assertAlmostEqual(p.delta_e_2000(l2, l1), want, delta=1e-4)

    def test_lab_white_black(self):
        for got, want in zip(p.srgb_to_lab((255, 255, 255)), (100, 0, 0)):
            self.assertAlmostEqual(got, want, delta=0.01)
        for got in p.srgb_to_lab((0, 0, 0)):
            self.assertAlmostEqual(got, 0, delta=1e-9)

    def test_simulate(self):
        for kind in ('protan', 'deutan', 'tritan'):
            for c in p.simulate((128, 128, 128), kind):
                self.assertAlmostEqual(c, 128 / 255, delta=1e-4)
            self.assertTrue(all(0 <= c <= 1 for c in p.simulate((255, 0, 0), kind)))
        red = p.simulate((255, 0, 0), 'protan')
        self.assertGreater(abs(red[0] - 1.0), 0.1)
        with self.assertRaises(ValueError):
            p.simulate((1, 2, 3), 'achroma')

    def test_validate_near_identical(self):
        v = p.validate({'x': '#336699', 'y': '#336698'})
        self.assertEqual({x.vision for x in v}, set(p.VISIONS))
        self.assertEqual(v[0].vision, 'normal')
        self.assertEqual((v[0].move_a, v[0].move_b), ('x', 'y'))

    def test_validate_red_green(self):
        v = p.validate({'r': '#e00000', 'g': '#008000'})
        self.assertEqual({x.vision for x in v}, {'protan', 'deutan'})

    def test_validate_spread_and_deterministic(self):
        self.assertEqual(p.validate(SPREAD), ())
        a = p.validate({'b': '#336699', 'a': '#336698', 'c': '#336697'})
        b = p.validate({'c': '#336697', 'a': '#336698', 'b': '#336699'})
        self.assertEqual(a, b)

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            good = os.path.join(d, 'good.json')
            bad = os.path.join(d, 'bad.json')
            with open(good, 'w') as f:
                json.dump(SPREAD, f)
            with open(bad, 'w') as f:
                json.dump({'x': '#336699', 'y': '#336698'}, f)
            self.assertEqual(p.main([good]), 0)
            self.assertEqual(p.main([bad]), 1)
            self.assertEqual(p.main([good, '--min-delta-e', '1000']), 1)


def genre_obj(colors, other='#808080'):
    """Synthetic LLM-built genre file with placeholder colours."""
    ids = [k for k in colors if not k.startswith('_')]
    return {
        'genre': 'synthetic', 'version': 1,
        'moves': [{'id': i, 'name': i, 'definition': 'd', 'near_miss': 'n',
                   'positive_examples': ['e1', 'e2']} for i in ids],
        'legend': {'colors': dict(colors), 'other': other},
    }


class GenrePaletteTest(unittest.TestCase):
    def write(self, d, obj, name='genre.json'):
        path = os.path.join(d, name)
        with open(path, 'w') as f:
            json.dump(obj, f)
        return path

    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = p.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_genre_palette(self):
        obj = genre_obj({'_note': 'x', 'b': '#000000', 'a': '#ffffff'}, '#0072b2')
        got = p.genre_palette(obj)
        self.assertEqual(got, {'b': '#000000', 'a': '#ffffff', 'other': '#0072b2'})
        self.assertEqual(list(got), ['b', 'a', 'other'])

    def test_cli_genre_pass_and_fail(self):
        with tempfile.TemporaryDirectory() as d:
            good = self.write(d, genre_obj(
                {'a': '#000000', 'b': '#ffffff', 'c': '#0072b2'}, '#e69f00'), 'g.json')
            bad = self.write(d, genre_obj(
                {'x': '#336699', 'y': '#336698'}, '#e69f00'), 'b.json')
            self.assertEqual(self.run_main(['--genre', good])[0], 0)
            code, out, _ = self.run_main(['--genre', bad])
            self.assertEqual(code, 1)
            self.assertIn('normal: x vs y', out)

    def test_cli_genre_other_checked(self):
        with tempfile.TemporaryDirectory() as d:
            path = self.write(d, genre_obj({'a': '#336699'}, '#336698'))
            code, out, _ = self.run_main(['--genre', path])
            self.assertEqual(code, 1)
            self.assertIn('a vs other', out)

    def test_cli_genre_invalid(self):
        with tempfile.TemporaryDirectory() as d:
            obj = genre_obj({'a': '#000000'}); obj['legend']['other'] = 'grey'
            code, _, err = self.run_main(['--genre', self.write(d, obj)])
            self.assertEqual(code, 2)
            self.assertIn('legend.other', err)

    def test_cli_both_modes_error(self):
        with tempfile.TemporaryDirectory() as d:
            path = self.write(d, genre_obj({'a': '#000000'}))
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    p.main([path, '--genre', path])
                self.assertEqual(cm.exception.code, 2)
                with self.assertRaises(SystemExit):
                    p.main([])


if __name__ == '__main__':
    unittest.main()
