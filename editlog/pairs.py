"""Training pairs (EL-04) and negatives (EL-05) read from the edit log.

Unwired by design: G-10 fine-tuning (docs/todo-01-experiments.md) consumes these.
Stdlib only; streams EditLogStore.iter_entries, never holding the log in memory.
"""

from dataclasses import dataclass
from typing import Any, Dict

_PAIR_ACTIONS = ('accept', 'edit')


@dataclass(frozen=True)
class TrainingPair:
    entry_id: int
    before: str
    after: str
    genre: str
    section_type: str
    move: str
    original_text: str
    panel_values: Dict[str, Any]
    generation_run_id: str
    action: str


@dataclass(frozen=True)
class NegativeRecord:
    entry_id: int
    rejected: str
    genre: str
    section_type: str
    move: str
    original_text: str
    panel_values: Dict[str, Any]
    generation_run_id: str


def _context(entry):
    return dict(genre=entry.genre, section_type=entry.section_type,
                move=entry.move, original_text=entry.original_text,
                panel_values=entry.panel_values,
                generation_run_id=entry.generation_run_id)


def iter_training_pairs(store):
    """Yield a TrainingPair per accept/edit entry: candidate -> final_text."""
    for entry_id, entry in store.iter_entries():
        if entry.action in _PAIR_ACTIONS:
            yield TrainingPair(entry_id=entry_id, before=entry.candidate,
                               after=entry.final_text, action=entry.action,
                               **_context(entry))


def iter_negatives(store):
    """Yield a NegativeRecord per reject entry, keeping the rejected candidate."""
    for entry_id, entry in store.iter_entries():
        if entry.action == 'reject':
            yield NegativeRecord(entry_id=entry_id, rejected=entry.candidate,
                                 **_context(entry))
