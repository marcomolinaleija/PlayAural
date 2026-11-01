"""Exercise deployment backups against the application's expression indexes."""
import importlib.util
import sqlite3
from pathlib import Path

import pytest

pytest.importorskip('fcntl')
spec = importlib.util.spec_from_file_location(
    'deployment_backup', Path(__file__).resolve().parents[2] / 'deployment/marco-vps/backup_database.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


def test_verified_wal_snapshot_retains_expression_index_and_private_mode(tmp_path):
    source, saved = tmp_path / 'source.db', tmp_path / 'saved.db'
    with sqlite3.connect(source) as db:
        backup.register_sqlite_functions(db)
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE users(username TEXT)')
        db.execute('CREATE INDEX names ON users(USERNAME_KEY_V3(username))')
        db.execute('INSERT INTO users VALUES(?)', ('Ｍarco',))
    backup.backup_sqlite(source, saved)
    with sqlite3.connect(saved) as db:
        backup.register_sqlite_functions(db)
        assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        assert db.execute('SELECT USERNAME_KEY_V3(username) FROM users').fetchone() == ('marco',)
    assert saved.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        backup.backup_sqlite(source, saved)


def test_invalid_foreign_keys_never_publish_a_backup(tmp_path):
    source, saved = tmp_path / 'source.db', tmp_path / 'saved.db'
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE parent(id INTEGER PRIMARY KEY)')
        db.execute('CREATE TABLE child(id INTEGER REFERENCES parent(id))')
        db.execute('INSERT INTO child VALUES(999)')
    with pytest.raises(AssertionError):
        backup.backup_sqlite(source, saved)
    assert not saved.exists()
    assert (tmp_path / '.saved.db.partial').exists()
