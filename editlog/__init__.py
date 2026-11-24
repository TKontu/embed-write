"""Local edit log (EL-01 schema, EL-03 SQLite store).

Unwired by design: EL-02 wires these into accept/reject/edit capture.
Stdlib only; the store opens a local file and never a network connection (I9).
"""

from editlog.schema import ACTIONS, EditLogEntry, validate_entry
from editlog.store import EditLogStore

__all__ = ['ACTIONS', 'EditLogEntry', 'EditLogStore', 'validate_entry']
