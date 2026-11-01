"""Upload complete SQLite snapshots to the private PlayAural B2 bucket."""
import argparse
import fcntl
import gzip
import hashlib
import io
import json
import os
import re
import runpy
import sqlite3
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

REMOTE = 'b2playaural:marcoml-playaural-backups/snapshots'
SNAPSHOT_NAME = re.compile(r'(?:daily-\d{8}T\d{6}Z|\d{8}T\d{6}Z-[0-9a-f]{8})')
REQUIRED = ('PlayAural.db', 'previous.env', 'releases.json')


def sha256(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def archive_snapshot(snapshot, spool, identity_path):
    if snapshot.is_symlink() or not SNAPSHOT_NAME.fullmatch(snapshot.name):
        raise ValueError('Unexpected snapshot directory')
    if (snapshot / 'INCOMPLETE').exists():
        raise ValueError('Incomplete snapshot')
    names = list(REQUIRED)
    if (snapshot / 'metadata.json').exists():
        names.append('metadata.json')
    for name in names:
        path = snapshot / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Missing or unsafe snapshot file: ' + name)
    identity = runpy.run_path(str(identity_path))
    db = sqlite3.connect((snapshot / 'PlayAural.db').resolve().as_uri() + '?mode=ro', uri=True)
    try:
        db.create_function('USERNAME_KEY', 1, identity['legacy_username_key_v2'], deterministic=True)
        db.create_function('USERNAME_KEY_V3', 1, identity['username_key'], deterministic=True)
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('SQLite integrity check failed')
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('SQLite foreign-key check failed')
    finally:
        db.close()
    release = json.loads((snapshot / 'releases.json').read_text())
    manifest = {'snapshot': snapshot.name, 'version': release['version'],
                'scope': 'SQLite durable data, matching release manifest and deployment environment',
                'sha256': {name: sha256(snapshot / name) for name in names}}
    payload = json.dumps(manifest, sort_keys=True, indent=2).encode()
    spool.mkdir(mode=0o700, parents=True, exist_ok=True)
    archive = spool / (snapshot.name + '.tar.gz')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.' + snapshot.name, suffix='.partial', dir=spool, delete=False) as output:
            temporary = Path(output.name)
            with gzip.GzipFile(filename='', mode='wb', fileobj=output, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode='w') as bundle:
                    for name in names:
                        info = bundle.gettarinfo(snapshot / name, arcname=name)
                        info.uid = info.gid = info.mtime = 0
                        info.uname = info.gname = ''
                        info.mode = 0o600
                        info.pax_headers = {}
                        with (snapshot / name).open('rb') as source:
                            bundle.addfile(info, source)
                    info = tarfile.TarInfo('MANIFEST.json')
                    info.size, info.mode = len(payload), 0o600
                    bundle.addfile(info, io.BytesIO(payload))
            output.flush()
            os.fsync(output.fileno())
        if manifest['sha256'] != {name: sha256(snapshot / name) for name in names}:
            raise ValueError('Snapshot changed while packaging')
        digest = sha256(temporary)
        if archive.exists():
            if sha256(archive) != digest:
                raise ValueError('Previously packaged snapshot has changed')
        else:
            os.replace(temporary, archive)
        return archive, digest
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def rclone(config, *arguments, **kwargs):
    command = ['/usr/bin/rclone', '--config', str(config), '--contimeout', '15s',
               '--timeout', '60s', '--retries', '3', '--low-level-retries', '3', *arguments]
    return subprocess.run(command, check=True, **kwargs)


def verify_remote(config, remote, expected):
    command = ['/usr/bin/rclone', '--config', str(config), '--contimeout', '15s',
               '--timeout', '60s', '--retries', '1', '--low-level-retries', '3', 'cat', remote]
    with subprocess.Popen(command, stdout=subprocess.PIPE) as process:
        digest = hashlib.file_digest(process.stdout, 'sha256').hexdigest()
        if process.wait() != 0 or digest != expected:
            raise ValueError('Remote archive download failed verification')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('/home/marco/apps/playaural'))
    root = parser.parse_args().root.resolve()
    os.umask(0o077)
    config = root / 'config/rclone-b2.conf'
    if not config.is_file() or config.stat().st_mode & 0o077:
        raise SystemExit('A private mode-600 B2 configuration is required')
    state_path = root / 'ops/b2-upload-state.json'
    with (root / 'ops/b2-upload.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(state_path.read_text()) if state_path.exists() else {'archives': {}}
        completed = state['archives']
        uploaded, errors = 0, []
        for snapshot in sorted((root / 'backups').iterdir()):
            if not snapshot.is_dir() or not SNAPSHOT_NAME.fullmatch(snapshot.name):
                continue
            if snapshot.name in completed or (snapshot / 'INCOMPLETE').exists():
                continue
            if not all((snapshot / name).is_file() for name in REQUIRED):
                continue
            try:
                archive, digest = archive_snapshot(snapshot, root / 'ops/b2-spool', root / 'current/server/users/identity.py')
                remote = REMOTE + '/' + archive.name
                rclone(config, 'copyto', str(archive), remote, '--immutable', '--checksum')
                verify_remote(config, remote, digest)
                completed[snapshot.name] = {'remote': remote, 'sha256': digest,
                    'bytes': archive.stat().st_size, 'verified_utc': datetime.now(timezone.utc).isoformat()}
                temporary = state_path.with_suffix('.partial')
                temporary.write_text(json.dumps(state, indent=2))
                with temporary.open('rb') as saved:
                    os.fsync(saved.fileno())
                os.replace(temporary, state_path)
                uploaded += 1
                print('Verified B2 upload and readback: ' + archive.name, flush=True)
            except Exception as error:
                errors.append(snapshot.name + ': ' + str(error))
        if errors:
            raise SystemExit('\n'.join(errors))
        print(f'B2 backup complete: {uploaded} new; {len(completed)} verified archives retained')


if __name__ == '__main__':
    main()
