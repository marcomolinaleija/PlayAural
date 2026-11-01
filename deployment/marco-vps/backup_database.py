"""Create a private, verified and durably published SQLite snapshot."""
import argparse
import fcntl
import json
import os
import runpy
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

IDENTITY_PATH = Path(__file__).resolve().parents[2] / 'server/users/identity.py'


def register_sqlite_functions(db):
    identity = runpy.run_path(str(IDENTITY_PATH))
    db.create_function('USERNAME_KEY', 1, identity['legacy_username_key_v2'], deterministic=True)
    db.create_function('USERNAME_KEY_V3', 1, identity['username_key'], deterministic=True)

def signature(db):
    schema = db.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name").fetchall()
    counts = []
    for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        quoted = '"' + name.replace('"', '""') + '"'
        counts.append((name, db.execute('SELECT COUNT(*) FROM ' + quoted).fetchone()[0]))
    return schema, counts


def flush_directory(directory):
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def backup_sqlite(source_path, destination):
    source_path, destination = Path(source_path).resolve(), Path(destination).resolve()
    if not source_path.is_file() or destination.exists():
        raise ValueError('Source must exist and destination must be new')
    partial = destination.with_name('.' + destination.name + '.partial')
    descriptor = os.open(partial, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    with sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True, timeout=30) as source:
        source.execute('BEGIN')
        expected = signature(source)
        with sqlite3.connect(partial) as target:
            source.backup(target)
            register_sqlite_functions(target)
            assert target.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
            assert not target.execute('PRAGMA foreign_key_check').fetchall()
            assert signature(target) == expected
        source.rollback()
    with partial.open('rb') as saved:
        os.fsync(saved.fileno())
    os.replace(partial, destination)
    flush_directory(destination.parent)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('/home/marco/apps/playaural'))
    root = parser.parse_args().root.resolve()
    os.umask(0o077)
    with (root / 'promotion.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        destination = root / 'backups' / ('daily-' + stamp)
        destination.mkdir(mode=0o700)
        incomplete = destination / 'INCOMPLETE'
        incomplete.write_text('Backup not yet complete; do not restore this directory.')
        backup_sqlite(root / 'data/PlayAural.db', destination / 'PlayAural.db')
        for path, name in ((root / 'current.env', 'previous.env'),
                           (root / 'config/releases.json', 'releases.json')):
            shutil.copy2(path, destination / name)
            (destination / name).chmod(0o600)
        (destination / 'metadata.json').write_text(json.dumps({
            'created_utc': stamp,
            'scope': 'SQLite durable data; active matches are checkpointed separately by the server',
            'verified': 'integrity_check, foreign_key_check, snapshot schema and row counts',
        }, indent=2))
        for path in destination.iterdir():
            if path.is_file():
                with path.open('rb') as saved:
                    os.fsync(saved.fileno())
        incomplete.unlink()
        flush_directory(destination)
        flush_directory(destination.parent)
    print('Verified private SQLite backup: ' + str(destination))


if __name__ == '__main__':
    main()
