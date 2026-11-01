"""Probe service-user ownership and fsync support before production startup."""
import os
import tempfile
from pathlib import Path

root = Path('/home/marco/apps/playaural')
if os.geteuid() != 1000:
    raise SystemExit('Run as the deployment service user (uid 1000)')
for name in ('PlayAural.db', 'PlayAural.db-wal', 'PlayAural.db-shm', 'PlayAural.db-journal', 'errors.log'):
    path = root / 'data' / name
    if path.exists():
        os.chown(path, 1000, 1000)
        path.chmod(0o600)
for directory in (root / 'data', root / 'backups'):
    directory.chmod(0o700)
    with tempfile.NamedTemporaryFile(prefix='.playaural-fsync-', dir=directory) as probe:
        probe.write(b'PlayAural storage preflight\n')
        probe.flush()
        os.fsync(probe.fileno())
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
print('Service ownership and live/backup filesystem fsync probes passed')
