"""Local edit log (EL-01 schema, EL-03 SQLite store, EL-04/05 pairs and negatives).

Unwired by design: EL-02 wires these into accept/reject/edit capture.
Stdlib only; the store opens a local file and never a network connection (I9).
"""

from editlog.schema import ACTIONS, EditLogEntry, validate_entry
from editlog.pairs import (NegativeRecord, TrainingPair, iter_negatives,
                           iter_training_pairs)
from editlog.store import EditLogStore

__all__ = ['ACTIONS', 'EditLogEntry', 'EditLogStore', 'NegativeRecord',
           'TrainingPair', 'iter_negatives', 'iter_training_pairs',
           'validate_entry']
