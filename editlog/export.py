"""JSON Lines export of the whole edit log for the expert (EL-07a).

Production caller: the ``python3 -m editlog.export DB_PATH OUT_PATH`` CLI, the
expert's control until the TS UI exists. The output is private data (0600).
"""

import argparse
import dataclasses
import json
import os
import sys
import tempfile

from editlog.store import EditLogStore


def export_jsonl(store, out_path, force=False):
    """Stream every entry as one JSON line ({id, **fields}); return rows written.

    Writes a 0600 temp file in the destination directory, then publishes it
    atomically. Refuses an existing out_path unless force; on failure no
    partial file is left.
    """
    out_path = os.fspath(out_path)
    if not force and os.path.lexists(out_path):
        raise FileExistsError('%s exists; use --force to overwrite' % out_path)
    fd, tmp = tempfile.mkstemp(prefix='.export-', suffix='.tmp',
                               dir=os.path.dirname(os.path.abspath(out_path)))
    try:
        os.fchmod(fd, 0o600)
        rows = 0
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as fh:
            for entry_id, entry in store.iter_entries():
                row = {'id': entry_id}
                row.update(dataclasses.asdict(entry))
                fh.write(json.dumps(row, ensure_ascii=False, allow_nan=False,
                                    sort_keys=True) + '\n')
                rows += 1
            fh.flush()
            os.fsync(fh.fileno())
        if force:
            os.replace(tmp, out_path)
        else:
            os.link(tmp, out_path)  # atomic no-clobber publish
            os.unlink(tmp)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='python3 -m editlog.export',
        description='Export the edit log to a JSON Lines file (mode 0600).')
    parser.add_argument('db_path')
    parser.add_argument('out_path')
    parser.add_argument('--force', action='store_true',
                        help='overwrite an existing OUT_PATH')
    args = parser.parse_args(argv)
    if not os.path.isfile(args.db_path):
        print('error: no edit log at %s' % args.db_path, file=sys.stderr)
        return 2
    try:
        with EditLogStore(args.db_path) as store:
            rows = export_jsonl(store, args.out_path, force=args.force)
    except FileExistsError as exc:
        print('error: %s' % exc, file=sys.stderr)
        return 1
    print('exported %d entries to %s' % (rows, args.out_path))
    return 0


if __name__ == '__main__':
    sys.exit(main())
