"""Verified standalone forum archives accompanying central SQLite snapshots."""

from datetime import datetime, timezone
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import zipfile

from ..persistence.database import Database
from .storage import validate_key

CHUNK_SIZE = 256 * 1024


def _digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class ForumObjectBackups:
    def __init__(self, storage):
        self.storage = storage

    @staticmethod
    def required(database: Path) -> bool:
        """Inspect on the maintenance worker after the live connection closes."""
        with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)) as connection:
            exists = connection.execute("SELECT 1 FROM sqlite_master WHERE name = 'forum_attachments'").fetchone()
            return bool(exists and connection.execute('SELECT 1 FROM forum_attachments WHERE published = 1 LIMIT 1').fetchone())

    def capture(self, snapshot: Path) -> Path:
        """Read only the verified snapshot, never the live SQLite connection.

        Published objects are immutable and retained independently of live post
        deletion. A backup therefore remains consistent while preparation of
        unpublished uploads continues in other workers.
        """
        snapshot = Path(snapshot).resolve()
        with closing(sqlite3.connect(snapshot.as_uri() + '?mode=ro', uri=True)) as connection:
            connection.row_factory = sqlite3.Row
            exists = connection.execute("SELECT 1 FROM sqlite_master WHERE name = 'forum_attachments'").fetchone()
            rows = connection.execute(
                'SELECT id, object_key, size, sha256, thumbnail_key, captions_key FROM forum_attachments WHERE published = 1 ORDER BY id',
            ).fetchall() if exists else []
        required = snapshot.stat().st_size + sum(row['size'] + 2 * 1024 * 1024 * (bool(row['thumbnail_key']) + bool(row['captions_key'])) for row in rows)
        if shutil.disk_usage(snapshot.parent).free < required + Database.MINIMUM_MAINTENANCE_FREE_BYTES:
            raise OSError('Insufficient free space for the forum object archive')
        final = snapshot.with_suffix('.forum.zip')
        if final.exists():
            # Never overwrite an existing archive on a retry. Verify its
            # snapshot binding before accepting the previous publication.
            self.verify(final, snapshot)
            return final
        fd, temporary_name = tempfile.mkstemp(prefix=f'.{final.name}.', suffix='.partial', dir=snapshot.parent)
        temporary = Path(temporary_name)
        os.close(fd)
        published = False
        try:
            manifest = {'format': 'playaural-forum-backup-v1', 'created_at': datetime.now(timezone.utc).isoformat(),
                        'database': {'name': snapshot.name, 'size': snapshot.stat().st_size, 'sha256': _digest(snapshot)}, 'objects': []}
            with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
                archive.write(snapshot, 'database.sqlite3')
                for row in rows:
                    manifest['objects'].append(self._copy(archive, row['object_key'], row['size'], row['sha256']))
                    if row['thumbnail_key']:
                        manifest['objects'].append(self._copy(archive, row['thumbnail_key'], 2 * 1024 * 1024))
                    if row['captions_key']:
                        manifest['objects'].append(self._copy(archive, row['captions_key'], 2 * 1024 * 1024))
                archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, sort_keys=True))
            self.verify(temporary, snapshot)
            with temporary.open('r+b') as stream:
                os.fsync(stream.fileno())
            os.link(temporary, final)
            published = True
            Database._flush_directory_to_disk(snapshot.parent)
            return final
        except BaseException:
            if published:
                final.unlink(missing_ok=True)
            raise
        finally:
            temporary.unlink(missing_ok=True)

    def _copy(self, archive, key: str, expected_size: int, expected_sha: str | None = None) -> dict:
        validate_key(key)
        checksum, total = hashlib.sha256(), 0
        with self.storage.open(key) as source, archive.open('objects/' + key, 'w', force_zip64=True) as target:
            while chunk := source.read(CHUNK_SIZE):
                total += len(chunk)
                if total > expected_size:
                    raise ValueError('Stored forum object exceeds its declared size')
                checksum.update(chunk)
                target.write(chunk)
        if expected_sha is not None and (total != expected_size or checksum.hexdigest() != expected_sha):
            raise ValueError('Stored forum object does not match its published checksum')
        return {'key': key, 'size': total, 'sha256': checksum.hexdigest()}

    @staticmethod
    def verify(path: Path, snapshot: Path | None = None) -> dict:
        """Verify every member and checksum without extracting untrusted paths."""
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            if manifest.get('format') != 'playaural-forum-backup-v1':
                raise ValueError('Unknown forum backup format')
            expected = {'database.sqlite3', 'manifest.json'} | {'objects/' + validate_key(row['key']) for row in manifest['objects']}
            if set(archive.namelist()) != expected or len(archive.namelist()) != len(expected):
                raise ValueError('Unexpected or duplicate forum backup members')
            entries = [('database.sqlite3', manifest['database'])] + [('objects/' + row['key'], row) for row in manifest['objects']]
            for name, entry in entries:
                checksum, total = hashlib.sha256(), 0
                with archive.open(name) as stream:
                    while chunk := stream.read(CHUNK_SIZE):
                        checksum.update(chunk)
                        total += len(chunk)
                if total != entry['size'] or checksum.hexdigest() != entry['sha256']:
                    raise ValueError('Forum backup checksum mismatch')
            if snapshot and (manifest['database']['sha256'] != _digest(snapshot) or manifest['database']['size'] != snapshot.stat().st_size):
                raise ValueError('Forum archive belongs to a different database snapshot')
            return manifest
