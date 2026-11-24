"""Permanent whole-log deletion (D-004), called by python3 -m editlog.delete."""

import argparse
import os
import sqlite3
import sys

from editlog.export import export_jsonl
from editlog.store import EditLogStore

_SIDECARS = ('-wal', '-shm', '-journal')


def _local_path(db_path):
    path = os.fsdecode(db_path)
    if (path == ':memory:' or path.startswith(('file:', '//', '\\\\'))
            or '://' in path):
        raise ValueError('path: local database file only')
    return path


def delete_log(db_path):
    """Unlink the whole DB and SQLite sidecars in O(1) file operations.

    Stop writers and close all connections first. Missing DB raises before any
    sidecars are removed. Filesystem failures can leave a partial deletion;
    unlinking is not secure erasure of backups or underlying storage blocks.
    """
    path = _local_path(db_path)
    os.unlink(path)
    for suffix in _SIDECARS:
        try:
            os.unlink(path + suffix)
        except FileNotFoundError:
            pass


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='python3 -m editlog.delete', description=__doc__,
        epilog='Stop writers and close all edit-log connections before running.')
    parser.add_argument('db_path')
    parser.add_argument('--export', metavar='OUT_PATH',
                        help='export JSON Lines before deleting; never overwrite')
    parser.add_argument('--yes', action='store_true',
                        help='skip typed DELETE confirmation')
    args = parser.parse_args(argv)
    try:
        path = _local_path(args.db_path)
        if not os.path.isfile(path):
            raise FileNotFoundError('no edit log at %s' % path)
        if args.export:
            targets = [os.path.realpath(path + suffix)
                       for suffix in ('',) + _SIDECARS]
            if os.path.realpath(args.export) in targets:
                raise ValueError('export must not be the DB or a SQLite sidecar')
            with EditLogStore(path) as store:
                rows = export_jsonl(store, args.export)
            print('exported %d entries to %s' % (rows, args.export))
        else:
            print('Export is available with --export OUT_PATH before deletion.')
        if not args.yes:
            print('Permanently delete the whole edit log? Type DELETE to confirm: ',
                  end='', flush=True)
            if sys.stdin.readline().rstrip('\r\n') != 'DELETE':
                print('Deletion cancelled.')
                return 0
        delete_log(path)
    except (OSError, ValueError, sqlite3.Error) as exc:
        print('error: %s' % exc, file=sys.stderr)
        return 1
    print('Deleted the whole edit log.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
