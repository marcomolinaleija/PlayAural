"""Bounded CPU/object work; SQLite is touched only back on its owner loop."""

import asyncio
from concurrent.futures import ProcessPoolExecutor
from contextlib import contextmanager
import logging
import multiprocessing
from pathlib import Path
import shutil
from uuid import UUID

from .models import ForumError

logger = logging.getLogger(__name__)


class MediaWorker:
    def __init__(self, server, service, storage, processor, *, concurrency: int = 2):
        self.server, self.service, self.storage, self.processor = server, service, storage, processor
        self._semaphore = asyncio.Semaphore(concurrency)
        self._concurrency = concurrency
        self._executor = None
        self._tasks: set[asyncio.Task] = set()
        self._active_ids: set[str] = set()
        self.on_complete = None

    @contextmanager
    def database_work(self):
        manager = self.server.maintenance_manager
        if not manager.begin_tracked_work():
            raise ForumError('forum-error-media-maintenance')
        try:
            yield
        finally:
            manager.end_tracked_work()

    def start(self, viewer: str, attachment_id: str, directory: Path) -> None:
        self._active_ids.add(attachment_id)
        task = asyncio.create_task(self._process(viewer, attachment_id, directory))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        task.add_done_callback(lambda _: self._active_ids.discard(attachment_id))

    @property
    def active_ids(self):
        return frozenset(self._active_ids)

    async def _process(self, viewer: str, attachment_id: str, directory: Path) -> None:
        error_key = None
        try:
            async with self._semaphore:
                if self._executor is None:
                    self._executor = ProcessPoolExecutor(max_workers=self._concurrency, mp_context=multiprocessing.get_context('spawn'))
                media = await asyncio.get_running_loop().run_in_executor(
                    self._executor, self.processor.process, directory / 'source', directory / 'prepared',
                )
                key = UUID(attachment_id).hex
                await asyncio.to_thread(self.storage.put, key + '/content', media.path, media.mime)
                if media.thumbnail:
                    await asyncio.to_thread(self.storage.put, key + '/thumbnail', media.thumbnail, 'image/jpeg')
                if media.captions:
                    await asyncio.to_thread(self.storage.put, key + '/captions', media.captions, 'text/vtt')
                if not await self.server.maintenance_manager.begin_tracked_work_when_available():
                    return
                try:
                    self.service.attachments.complete(viewer, attachment_id, media)
                finally:
                    self.server.maintenance_manager.end_tracked_work()
        except Exception as error:
            error_key = error.key if isinstance(error, ForumError) else 'forum-error-media-processing'
            if not isinstance(error, ForumError):
                logger.exception('Forum media processing failed for %s', attachment_id)
            if await self.server.maintenance_manager.begin_tracked_work_when_available():
                try:
                    self.service.attachments.fail(attachment_id)
                finally:
                    self.server.maintenance_manager.end_tracked_work()
        finally:
            await asyncio.to_thread(shutil.rmtree, directory, True)
        if self.on_complete:
            if await self.server.maintenance_manager.begin_tracked_work_when_available():
                try:
                    self.on_complete(viewer, attachment_id, error_key)
                except Exception:
                    logger.exception('Forum media completion notification failed for %s', attachment_id)
                finally:
                    self.server.maintenance_manager.end_tracked_work()

    async def stop(self) -> None:
        # A to_thread operation cannot be cancelled safely. Let bounded FFmpeg
        # subprocesses finish before closing SQLite or deleting their staging.
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
        if self._executor:
            await asyncio.to_thread(self._executor.shutdown, wait=True)
            self._executor = None
