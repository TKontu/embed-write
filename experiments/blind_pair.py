"""Blind-pair primitives, unwired by design until BJ-02 session design.

Keep Presentation objects (including their opaque keys and arm mappings) on the
server; only render_html output belongs in the browser. Callers supply texts
without identifying arm labels. This module does not judge preferences or run
G-02/G-10. Synthetic tests are LLM-built, not expert judgments.
"""

import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import escape


@dataclass(frozen=True)
class Presentation:
    """Server-side pair state; never serialize this object into the page."""

    pair_id: str = field(repr=False)
    left: str
    right: str
    key: str = field(repr=False)
    _left_arm: str = field(repr=False)
    _right_arm: str = field(repr=False)


def make_pair(pair_id, text_x, arm_x, text_y, arm_y, rng):
    """Randomize position with the supplied RNG; generate an independent key.

    Arm names must be distinct nonempty strings; 'tie' is reserved for records.
    The RNG controls order only, so a seeded RNG reproduces presentation order
    without making the opaque key predictable.
    """
    if any(not isinstance(arm, str) or not arm or arm == 'tie'
           for arm in (arm_x, arm_y)) or arm_x == arm_y:
        raise ValueError('Expected distinct nonempty arm names other than tie')
    if rng.randrange(2):
        text_x, text_y = text_y, text_x
        arm_x, arm_y = arm_y, arm_x
    return Presentation(pair_id, text_x, text_y, secrets.token_urlsafe(32), arm_x, arm_y)


def render_html(presentation):
    """Render only escaped texts and neutral controls, with no pair metadata.

    BJ-02 must bind POST requests to server-side presentation state. No hidden
    inputs or scripts carry the key, pair ID, arm names, or position mapping.
    """
    return f'''<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Text comparison</title>
<style>pre {{ white-space: pre-wrap; overflow-wrap: anywhere; }}</style></head>
<body>
<h1>Compare the texts</h1>
<section><h2>Left</h2><pre>{escape(presentation.left)}</pre></section>
<section><h2>Right</h2><pre>{escape(presentation.right)}</pre></section>
<form method="post">
<fieldset><legend>Which text do you prefer?</legend>
<label><input type="radio" name="choice" value="left" required>Left</label>
<label><input type="radio" name="choice" value="right" required>Right</label>
<label><input type="radio" name="choice" value="tie" required>Tie</label>
</fieldset>
<label>Reason (optional)<textarea name="reason"></textarea></label>
<button type="submit">Record choice</button>
</form>
</body></html>'''


def record_choice(path, presentation, choice, reason=None, extra=None):
    """Resolve a position on the server and append one UTF-8 JSON line.

    Memory is bounded by one record; existing records are never read. The caller
    owns private storage and serializes concurrent writers (no session layer here).
    Texts and opaque keys are not persisted in the record. Optional extra fields
    (e.g. BJ-02 session item_id) are added but may not override core fields.
    """
    if choice not in ('left', 'right', 'tie'):
        raise ValueError('Expected left, right, or tie')
    winner = ('tie' if choice == 'tie' else
              presentation._left_arm if choice == 'left' else presentation._right_arm)
    record = dict(pair_id=presentation.pair_id, choice=choice, winner=winner,
                  reason=reason, recorded_at=datetime.now(timezone.utc).isoformat())
    if extra:
        clash = set(extra) & set(record)
        if clash:
            raise ValueError(f'extra fields would override: {sorted(clash)}')
        record.update(extra)
    line = json.dumps(record, ensure_ascii=False) + '\n'
    with open(path, 'a', encoding='utf-8') as output:
        output.write(line)


def to_preference_choices(records, arm_a):
    """Yield a/b/tie from JSON lines or decoded records, one record at a time.

    Supply records for a single two-arm comparison; any non-tie winner other
    than arm_a counts as b. Materialize the result with list() at the win_rate
    boundary, since that consumer requires a sequence supporting count/len.
    """
    for record in records:
        if isinstance(record, (str, bytes, bytearray)):
            record = json.loads(record)
        winner = record['winner']
        yield 'tie' if winner == 'tie' else 'a' if winner == arm_a else 'b'
