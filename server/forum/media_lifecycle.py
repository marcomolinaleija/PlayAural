"""Recover interrupted uploads and collect expired unpublished objects only."""

import asyncio
import logging
from pathlib import Path
import shutil
from uuid import UUID

logger = logging.getLogger(__name__)


class MediaLifecycle:
    def __init__(self, transport):
        self.transport = transport
        self._stop = asyncio.Event()
        self._task = None

    async def recover(self) -> None:
        worker = self.transport.worker
        with worker.database_work():
            with worker.service.repository.atomic():
                worker.service.repository.connection.execute(
                    "UPDATE forum_attachments SET state = 'failed' WHERE published = 0 AND state IN ('uploading', 'processing')",
                )
        staging = self.transport.staging.resolve()
        for path in staging.iterdir():
            resolved = path.resolve()
            # This is a private application-owned staging directory. Never
            # follow a symlink or remove an unknown path alongside our jobs.
            if path.name.startswith('upload-') and path.is_dir() and not path.is_symlink() and resolved.parent == staging:
                await asyncio.to_thread(shutil.rmtree, resolved)
        await self.collect()

    async def collect(self) -> int:
        worker, service = self.transport.worker, self.transport.service
        with worker.database_work():
            rows = service.attachments.expired()
        removed = 0
        for row in rows:
            if row['id'] in worker.active_ids or row['id'] in self.transport._upload_ids:
                continue
            prefix = UUID(row['id']).hex
            # Published objects are never selected. Historical snapshots can
            # continue to reference them after posts/accounts are deleted.
            await asyncio.to_thread(self.transport.storage.delete, prefix + '/content')
            await asyncio.to_thread(self.transport.storage.delete, prefix + '/thumbnail')
            await asyncio.to_thread(self.transport.storage.delete, prefix + '/captions')
            if not await worker.server.maintenance_manager.begin_tracked_work_when_available():
                return removed
            try:
                with service.repository.atomic():
                    service.repository.connection.execute(
                        "DELETE FROM forum_attachments WHERE id = ? AND published = 0 AND (expires_at <= ? OR state = 'retired')",
                        (row['id'], int(service.clock())),
                    )
                removed += 1
            finally:
                worker.server.maintenance_manager.end_tracked_work()
        return removed

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=60)
            except TimeoutError:
                try:
                    await self.collect()
                except Exception:
                    logger.exception('Forum upload expiry collection failed')

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task
            self._task = None
