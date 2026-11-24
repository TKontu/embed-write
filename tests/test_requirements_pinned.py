from pathlib import Path
import unittest


REQUIREMENTS = Path(__file__).resolve().parents[1] / 'requirements.txt'


class RequirementsPinnedTests(unittest.TestCase):
    def test_dependencies_are_present_and_exactly_pinned(self):
        self.assertTrue(REQUIREMENTS.is_file(), 'requirements.txt is missing')
        names = set()
        for line in REQUIREMENTS.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            with self.subTest(requirement=line):
                self.assertRegex(line, r'^[A-Za-z0-9][A-Za-z0-9._-]*==[0-9]+(?:\.[0-9]+)*$')
                names.add(line.split('==')[0].lower())
        self.assertTrue({'pysbd', 'lmdb'} <= names, 'pysbd and lmdb must be listed')
