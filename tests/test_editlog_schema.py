import unittest

from editlog.schema import ACTIONS, EditLogEntry, validate_entry


def make(**over):
    fields = dict(genre='g', section_type='s', move='m', original_text='o',
                  candidate='c', final_text='f', action='edit',
                  panel_values={'register': 0.5, 'tags': ['a']},
                  generation_run_id='run-1',
                  timestamp='2026-11-24T10:00:00+00:00')
    fields.update(over)
    return EditLogEntry(**fields)


class SchemaTest(unittest.TestCase):
    def assertBad(self, field, entry):
        with self.assertRaises(ValueError) as cm:
            validate_entry(entry)
        self.assertIn(field, str(cm.exception))

    def test_valid_entry(self):
        validate_entry(make())
        self.assertEqual(ACTIONS, frozenset({'accept', 'reject', 'edit'}))

    def test_missing_field(self):
        self.assertBad('move', make(move=None))
        with self.assertRaises(TypeError):
            EditLogEntry(genre='g')

    def test_unknown_action(self):
        self.assertBad('action', make(action='delete'))

    def test_non_string_texts(self):
        for field in ('original_text', 'candidate', 'final_text', 'genre'):
            self.assertBad(field, make(**{field: 3}))

    def test_non_json_panel_values(self):
        self.assertBad('panel_values', make(panel_values={'x': object()}))
        self.assertBad('panel_values', make(panel_values=['not', 'mapping']))
        self.assertBad('panel_values', make(panel_values={'x': float('nan')}))
        self.assertBad('panel_values', make(panel_values={1: 'int key'}))

    def test_timestamps(self):
        self.assertBad('timestamp', make(timestamp='2026-11-24T10:00:00'))
        self.assertBad('timestamp', make(timestamp='yesterday'))
        self.assertBad('timestamp', make(timestamp='2026-11-24T10:00:00+02:00'))
        validate_entry(make(timestamp='2026-11-24T10:00:00Z'))


if __name__ == '__main__':
    unittest.main()
