"""Persistent upload policy and developer-only storage configuration.

SQLite remains on the owner loop. Storage probes receive only an adapter and
run off-loop; changing providers is deferred to startup and freezes new uploads.
"""

import asyncio
from dataclasses import asdict, dataclass, replace
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from ..users.roles import DEVELOPER_TRUST_LEVEL
from .config import configured_storage
from .models import ForumError
from .storage import LocalObjectStorage

SETTINGS_KEY = 'forum_file_settings'
MIB = 1024 * 1024


@dataclass(frozen=True)
class FilePolicy:
    uploads_enabled: bool = True
    require_approval: bool = False
    max_file_mib: int = 128
    pending_mib: int = 256
    backend: str = 'local'

    def validate(self):
        if (type(self.uploads_enabled) is not bool or type(self.require_approval) is not bool
                or type(self.max_file_mib) is not int or not 1 <= self.max_file_mib <= 128
                or type(self.pending_mib) is not int or not self.max_file_mib <= self.pending_mib <= 256
                or type(self.backend) is not str or self.backend not in {'local', 's3'}):
            raise ForumError('admin-archivos-configuracion-invalida')
        return self


class FileSettings:
    def __init__(self, forum):
        self.forum = forum
        self.active_backend = os.environ.get('PLAYAURAL_FORUM_STORAGE', 'local')
        self.default_approval = False

    def policy(self) -> FilePolicy:
        row = self.forum.repository.connection.execute(
            'SELECT value_json FROM server_settings WHERE setting_key = ?', (SETTINGS_KEY,),
        ).fetchone()
        try:
            saved = json.loads(row['value_json']) if row is not None else {}
        except (TypeError, ValueError):
            raise ForumError('admin-archivos-configuracion-invalida') from None
        if not isinstance(saved, dict) or saved.keys() - FilePolicy.__dataclass_fields__.keys():
            raise ForumError('admin-archivos-configuracion-invalida')
        return FilePolicy(**{'backend': self.active_backend, 'require_approval': self.default_approval, **saved}).validate()

    def require_uploads(self) -> FilePolicy:
        policy = self.policy()
        if not policy.uploads_enabled or policy.backend != self.active_backend:
            raise ForumError('forum-error-cargas-desactivadas')
        return policy

    def require_developer(self, viewer: str) -> None:
        if self.forum.account(viewer).trust_level < DEVELOPER_TRUST_LEVEL:
            raise ForumError('dev-only-action')

    def update(self, viewer: str, *, expected: FilePolicy, **changes) -> FilePolicy:
        self.require_developer(viewer)
        with self.forum.repository.atomic():
            current = self.policy()
            if current != expected:
                raise ForumError('admin-archivos-configuracion-cambiada')
            if changes.keys() - {'uploads_enabled', 'require_approval', 'max_file_mib', 'pending_mib'}:
                raise ValueError('Unsupported upload policy field')
            policy = replace(current, **changes).validate()
            self.forum.repository.database.set_json_server_setting(SETTINGS_KEY, asdict(policy))
        return policy

    def select_backend(self, viewer: str, backend: str, *, expected: FilePolicy) -> None:
        self.require_developer(viewer)
        if backend not in {'local', 's3'}:
            raise ForumError('admin-archivos-configuracion-invalida')
        with self.forum.repository.atomic():
            if self.policy() != expected:
                raise ForumError('admin-archivos-configuracion-cambiada')
            if backend != expected.backend:
                # Include unpublished/processing objects: reservations and provider
                # selection serialize on the same SQLite owner and transaction.
                if self.forum.repository.connection.execute('SELECT 1 FROM forum_attachments LIMIT 1').fetchone():
                    raise ForumError('admin-archivos-cambio-bloqueado')
                policy = replace(expected, backend=backend, uploads_enabled=False)
                self.forum.repository.database.set_json_server_setting(SETTINGS_KEY, asdict(policy))

    def check_backend_change(self, viewer: str, backend: str, *, expected: FilePolicy) -> None:
        self.require_developer(viewer)
        if self.policy() != expected:
            raise ForumError('admin-archivos-configuracion-cambiada')
        if backend != expected.backend and self.forum.repository.connection.execute(
                'SELECT 1 FROM forum_attachments LIMIT 1').fetchone():
            raise ForumError('admin-archivos-cambio-bloqueado')


def probe_storage(directory: Path, backend: str) -> None:
    """Write/read/delete one fresh opaque object, never touch an attachment."""
    storage = configured_storage(directory / 'objects', backend=backend)
    key = uuid4().hex + '/content'
    content = b'PlayAural private storage check\n'
    with tempfile.TemporaryDirectory(prefix='playaural-storage-check-') as temporary:
        source = Path(temporary) / 'probe'
        source.write_bytes(content)
        try:
            storage.put(key, source, 'application/octet-stream')
            with storage.open(key) as stream:
                if stream.read(len(content) + 1) != content:
                    raise OSError('Storage probe content mismatch')
        finally:
            storage.delete(key)
            if isinstance(storage, LocalObjectStorage) and storage.path(key).parent.is_dir():
                storage.path(key).parent.rmdir()


async def check_storage(directory: Path, backend: str) -> None:
    # Cancellation cannot stop an SDK call in a thread. Retain the maintenance
    # work lease until the probe and its cleanup have actually finished.
    task = asyncio.create_task(asyncio.to_thread(probe_storage, directory, backend))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        task.result()
        raise
