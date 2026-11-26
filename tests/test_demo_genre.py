"""DE-06: the demo's synthetic genre file validates against service/genre.py."""

import os
import unittest

from service import genre

PATH = os.path.join(os.path.dirname(__file__), '..', 'examples', 'demo', 'genre.json')


class DemoGenreFileTest(unittest.TestCase):
    def test_validates(self):
        obj = genre.load_genre(PATH)
        self.assertEqual([m['id'] for m in obj['moves']], ['context', 'gap', 'method', 'finding'])
        self.assertIn('synthetic', obj['_note'].lower())


if __name__ == '__main__':
    unittest.main()
