"""Check immutable cloud packaging without transmitting test or account data."""
import hashlib
import importlib.util
import json
import sqlite3
import tarfile
from pathlib import Path

import pytest

pytest.importorskip('fcntl')
ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('b2_backup', ROOT / 'deployment/marco-vps/upload_backup_b2.py')
cloud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cloud)


def make_snapshot(tmp_path):
    snapshot = tmp_path / 'daily-20261101T000000Z'
    snapshot.mkdir()
    with sqlite3.connect(snapshot / 'PlayAural.db') as db:
        db.execute('CREATE TABLE sample(value TEXT)')
        db.execute("INSERT INTO sample VALUES('retained data')")
    (snapshot / 'previous.env').write_text('RELEASE_ID=example\n')
    (snapshot / 'releases.json').write_text('{"version":"1.0.5.3","targets":{}}')
    return snapshot


def test_archive_is_deterministic_and_contains_only_snapshot_allowlist(tmp_path):
    snapshot = make_snapshot(tmp_path)
    (snapshot / 'operator-secret.json').write_text('must not be uploaded')
    spool = tmp_path / 'spool'
    first, digest = cloud.archive_snapshot(snapshot, spool, ROOT / 'server/users/identity.py')
    second, repeated = cloud.archive_snapshot(snapshot, spool, ROOT / 'server/users/identity.py')
    assert first == second and digest == repeated
    with tarfile.open(first) as bundle:
        assert set(bundle.getnames()) == {*cloud.REQUIRED, 'MANIFEST.json'}
        manifest = json.load(bundle.extractfile('MANIFEST.json'))
        for name, expected in manifest['sha256'].items():
            assert hashlib.sha256(bundle.extractfile(name).read()).hexdigest() == expected


def test_existing_archive_rejects_changed_snapshot(tmp_path):
    snapshot = make_snapshot(tmp_path)
    cloud.archive_snapshot(snapshot, tmp_path / 'spool', ROOT / 'server/users/identity.py')
    with sqlite3.connect(snapshot / 'PlayAural.db') as db:
        db.execute("INSERT INTO sample VALUES('changed later')")
    with pytest.raises(ValueError, match='Previously packaged snapshot has changed'):
        cloud.archive_snapshot(snapshot, tmp_path / 'spool', ROOT / 'server/users/identity.py')


def test_incomplete_or_symlinked_snapshot_is_rejected(tmp_path):
    snapshot = make_snapshot(tmp_path)
    (snapshot / 'INCOMPLETE').touch()
    with pytest.raises(ValueError, match='Incomplete'):
        cloud.archive_snapshot(snapshot, tmp_path / 'spool', ROOT / 'server/users/identity.py')
    alias = tmp_path / 'daily-20261101T010000Z'
    alias.symlink_to(snapshot, target_is_directory=True)
    with pytest.raises(ValueError, match='Unexpected'):
        cloud.archive_snapshot(alias, tmp_path / 'spool', ROOT / 'server/users/identity.py')
