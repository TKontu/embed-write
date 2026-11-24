"""Edit-log entry schema and validation (EL-01)."""

import json
from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import datetime, timedelta

ACTIONS = frozenset({'accept', 'reject', 'edit'})
TEXT_FIELDS = ('genre', 'section_type', 'move', 'original_text', 'candidate',
               'final_text', 'generation_run_id')


@dataclass(frozen=True)
class EditLogEntry:
    genre: str
    section_type: str
    move: str
    original_text: str
    candidate: str
    final_text: str
    action: str
    panel_values: Mapping
    generation_run_id: str
    timestamp: str  # UTC ISO-8601 with explicit zero offset

    @classmethod
    def field_names(cls):
        return tuple(f.name for f in fields(cls))


def _check_json_keys(value, path='panel_values'):
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError('%s: keys must be strings' % path)
            _check_json_keys(item, path)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _check_json_keys(item, path)


def validate_entry(entry):
    """Raise ValueError naming the first bad field; return the entry if valid."""
    for name in EditLogEntry.field_names():
        if getattr(entry, name, None) is None:
            raise ValueError('%s: missing' % name)
    for name in TEXT_FIELDS:
        if not isinstance(getattr(entry, name), str):
            raise ValueError('%s: must be a string' % name)
    if entry.action not in ACTIONS:
        raise ValueError('action: must be one of %s' % sorted(ACTIONS))
    if not isinstance(entry.panel_values, Mapping):
        raise ValueError('panel_values: must be a mapping')
    _check_json_keys(entry.panel_values)
    try:
        json.dumps(entry.panel_values, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError('panel_values: not JSON-serializable (%s)' % exc) from None
    if not isinstance(entry.timestamp, str):
        raise ValueError('timestamp: must be an ISO-8601 string')
    try:
        parsed = datetime.fromisoformat(entry.timestamp.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('timestamp: unparseable ISO-8601') from None
    if parsed.utcoffset() is None:
        raise ValueError('timestamp: naive, needs UTC offset')
    if parsed.utcoffset() != timedelta(0):
        raise ValueError('timestamp: must be UTC')
    return entry
