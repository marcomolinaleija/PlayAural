"""Optional private runtime counts used to defer unattended deployments."""
import json
import logging
import os
from pathlib import Path
import tempfile
import time


LOGGER = logging.getLogger('playaural')


class MaintenanceStatus:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.next_write = 0.0

    def publish(self, *, table_count, version):
        if self.path is None or time.monotonic() < self.next_write:
            return
        self.next_write = time.monotonic() + 10
        temporary = None
        try:
            descriptor, temporary = tempfile.mkstemp(prefix='.maintenance-status-', dir=self.path.parent)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
                json.dump({'observed_at': time.time(), 'table_count': table_count, 'version': version, 'pid': os.getpid()}, output)
            os.replace(temporary, self.path)
        except OSError:
            LOGGER.warning('Could not publish private maintenance status', exc_info=True)
        finally:
            if temporary and Path(temporary).exists():
                Path(temporary).unlink()
