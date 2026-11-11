"""Authenticated HTTP transport for binary uploads and seekable media."""

import asyncio
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import quote, urlsplit

from aiohttp import web

from .media_processing import MAX_UPLOAD_BYTES, MediaProcessor
from .media_sessions import MediaSessions
from .media_worker import MediaWorker
from .models import ForumError
from .storage import LocalObjectStorage
from .config import configured_storage
from .backups import ForumObjectBackups
from .media_lifecycle import MediaLifecycle
from ..messages.localization import Localization
from ..users.network_user import NetworkUser

COOKIE = 'playaural_forum_media'
PREFIX = '/forum-media'
CHUNK_SIZE = 256 * 1024
MEDIA_USER_KEY = web.RequestKey('forum_media_user', NetworkUser)


def byte_range(value: str | None, size: int) -> tuple[int, int, bool]:
    if value is None:
        return 0, size - 1, False
    match = re.fullmatch(r'bytes=(\d*)-(\d*)', value) if len(value) <= 100 else None
    if not match or not any(match.groups()):
        raise web.HTTPRequestRangeNotSatisfiable(headers={'Content-Range': f'bytes */{size}'})
    first, last = match.groups()
    if first:
        start, end = int(first), min(int(last), size - 1) if last else size - 1
    else:
        suffix = int(last)
        start, end = max(0, size - suffix), size - 1
        if suffix == 0:
            start = size
    if start >= size or end < start:
        raise web.HTTPRequestRangeNotSatisfiable(headers={'Content-Range': f'bytes */{size}'})
    return start, end, True


class ForumMediaHTTP:
    def __init__(self, server, *, base_url: str, directory: str | Path, origins=(), storage=None, processor=None):
        parsed = urlsplit(base_url)
        if (parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path.rstrip('/') not in {'', PREFIX}
                or parsed.scheme == 'http' and parsed.hostname not in {'localhost', '127.0.0.1', '::1'}):
            raise ValueError('Configure an HTTPS forum media URL (HTTP allowed only on loopback)')
        self.server, self.service = server, server.forum_manager.service
        approval_policy = os.environ.get('PLAYAURAL_FORUM_MEDIA_APPROVAL', '0')
        if approval_policy not in {'0', '1'}:
            raise ValueError('PLAYAURAL_FORUM_MEDIA_APPROVAL must be 0 or 1')
        self.service.attachments.require_approval = approval_policy == '1'
        hostname = parsed.hostname.encode('idna').decode('ascii').lower()
        if ':' in hostname:
            hostname = '[' + hostname + ']'
        default_port = 443 if parsed.scheme == 'https' else 80
        authority = hostname + (f':{parsed.port}' if parsed.port is not None and parsed.port != default_port else '')
        self.base_url = f'{parsed.scheme}://{authority}{PREFIX}'
        self.secure = parsed.scheme == 'https'
        self.origins = set(origins) | {f'{parsed.scheme}://{authority}'}
        self.directory = Path(directory).resolve()
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.staging = self.directory / 'staging'
        self.staging.mkdir(mode=0o700, exist_ok=True)
        self.storage = storage or configured_storage(self.directory / 'objects')
        self.backups = ForumObjectBackups(self.storage)
        self.sessions = MediaSessions(server, self.service)
        self.worker = MediaWorker(server, self.service, self.storage, processor or MediaProcessor())
        self.runner = None
        self.site = None
        self._upload_count = 0
        self._upload_ids: set[str] = set()
        self.lifecycle = MediaLifecycle(self)
        self._closing = False
        self.on_reserve = None

    @web.middleware
    async def policy(self, request, handler):
        origin = request.headers.get('Origin')
        if self._closing:
            raise web.HTTPServiceUnavailable()
        if origin and origin not in self.origins:
            raise web.HTTPForbidden()
        if request.method == 'OPTIONS':
            response = web.Response(status=204)
        else:
            try:
                response = await handler(request)
            except FileNotFoundError:
                response = web.Response(status=404)
            except web.HTTPException as error:
                response = web.Response(status=error.status, body=error.body, headers=error.headers, reason=error.reason)
            except ForumError as error:
                status = 401 if error.key == 'forum-error-account' else 503 if error.key in {'forum-error-media-maintenance', 'forum-unavailable'} else 404
                user = request.get(MEDIA_USER_KEY)
                message = Localization.get(user.locale, error.key, **error.values) if user else ''
                response = web.json_response({'error': error.key, 'values': error.values, 'message': message}, status=status)
        response.headers.update({'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
                                 'Referrer-Policy': 'no-referrer'})
        if origin:
            response.headers.update({'Access-Control-Allow-Origin': origin, 'Access-Control-Allow-Credentials': 'true',
                                     'Access-Control-Allow-Headers': 'Authorization, Content-Type, Range',
                                     'Access-Control-Allow-Methods': 'GET, HEAD, POST, PUT, OPTIONS',
                                     'Access-Control-Expose-Headers': 'Content-Range, Accept-Ranges, Content-Disposition',
                                     'Vary': 'Origin'})
        return response

    def app(self) -> web.Application:
        app = web.Application(client_max_size=MAX_UPLOAD_BYTES, middlewares=[self.policy])
        app.router.add_post(PREFIX + '/session', self.session)
        app.router.add_post(PREFIX + '/uploads', self.reserve)
        app.router.add_put(PREFIX + '/uploads/{id}', self.upload)
        app.router.add_get(PREFIX + '/files/{id}', self.download)
        app.router.add_get(PREFIX + '/files/{id}/thumbnail', self.download)
        app.router.add_get(PREFIX + '/files/{id}/captions', self.download)
        app.router.add_route('OPTIONS', PREFIX + '/{path:.*}', self.options)
        return app

    async def options(self, request):
        return web.Response(status=204)

    async def start(self, host: str, port: int, *, ssl_context=None) -> None:
        self._closing = False
        self.lifecycle = MediaLifecycle(self)
        await self.lifecycle.recover()
        self.runner = web.AppRunner(self.app(), access_log=None)
        await self.runner.setup()
        try:
            self.site = web.TCPSite(self.runner, host, port, ssl_context=ssl_context)
            await self.site.start()
            self.lifecycle.start()
        except BaseException:
            await self.runner.cleanup()
            self.runner = None
            raise

    async def stop(self) -> None:
        self._closing = True
        if self.runner:
            await self.runner.cleanup()
            self.runner = None
        await self.lifecycle.stop()
        await self.worker.stop()
        self.sessions.clear()

    def credentials(self, user) -> dict:
        token, expiry = self.sessions.issue(user)
        return {'base_url': self.base_url, 'token': token, 'expires_at': expiry}

    def authenticate(self, request, *, bearer_only=False):
        header = request.headers.get('Authorization', '')
        token = header.removeprefix('Bearer ') if header.startswith('Bearer ') else ''
        if not token and not bearer_only:
            token = request.cookies.get(COOKIE, '')
            if request.method not in {'GET', 'HEAD'} and request.headers.get('Origin') not in self.origins:
                raise web.HTTPForbidden()
        user = self.sessions.authenticate(token)
        request[MEDIA_USER_KEY] = user
        return user

    async def session(self, request):
        with self.worker.database_work():
            self.authenticate(request, bearer_only=True)
        response = web.json_response({'ok': True})
        token = request.headers['Authorization'].removeprefix('Bearer ')
        response.set_cookie(COOKIE, token, max_age=3600, httponly=True, secure=self.secure,
                            samesite='Lax', path=PREFIX)
        return response

    async def reserve(self, request):
        if request.content_length is None or request.content_length > 4096:
            raise web.HTTPRequestEntityTooLarge(max_size=4096, actual_size=request.content_length or 0)
        try:
            payload = await request.json()
        except (ValueError, UnicodeError):
            raise web.HTTPBadRequest()
        if not isinstance(payload, dict):
            raise web.HTTPBadRequest()
        with self.worker.database_work():
            user = self.authenticate(request)
            # The picker/reservation belongs to a live draft. A callback binds
            # its opaque token before any upload can consume storage.
            if self.on_reserve is None:
                raise web.HTTPConflict()
            row = self.on_reserve(user, payload)
        return web.json_response({'id': row['id'], 'upload_url': f"{self.base_url}/uploads/{row['id']}"}, status=201)

    async def upload(self, request):
        if self._upload_count >= 4:
            raise web.HTTPTooManyRequests()
        attachment_id = request.match_info['id']
        with self.worker.database_work():
            user = self.authenticate(request)
            row = self.service.attachments.upload(user.uuid, attachment_id)
            if request.content_length != row['size']:
                raise web.HTTPBadRequest()
            self.service.attachments.processing(user.uuid, attachment_id)
        self._upload_count += 1
        self._upload_ids.add(attachment_id)
        directory = Path(tempfile.mkdtemp(prefix='upload-', dir=self.staging))
        complete = False
        try:
            total = 0
            async with asyncio.timeout(60):
                with (directory / 'source').open('xb') as target:
                    async for chunk in request.content.iter_chunked(CHUNK_SIZE):
                        if not self.server.forum_enabled:
                            raise ForumError('forum-unavailable')
                        total += len(chunk)
                        if total > row['size']:
                            raise web.HTTPRequestEntityTooLarge(max_size=row['size'], actual_size=total)
                        await asyncio.to_thread(target.write, chunk)
            if total != row['size']:
                raise web.HTTPBadRequest()
            with self.worker.database_work():
                self.authenticate(request)
            self.worker.start(user.uuid, attachment_id, directory)
            complete = True
            return web.json_response({'id': attachment_id, 'state': 'processing'}, status=202)
        finally:
            self._upload_count -= 1
            self._upload_ids.discard(attachment_id)
            if not complete:
                import shutil
                await asyncio.to_thread(shutil.rmtree, directory, True)
                if await self.server.maintenance_manager.begin_tracked_work_when_available():
                    try:
                        self.service.attachments.fail(attachment_id)
                    finally:
                        self.server.maintenance_manager.end_tracked_work()

    async def download(self, request):
        with self.worker.database_work():
            user = self.authenticate(request)
            row = self.service.attachments.get(user.uuid, request.match_info['id'])
        thumbnail = request.path.endswith('/thumbnail')
        captions = request.path.endswith('/captions')
        if thumbnail and not row['thumbnail_key'] or captions and not row['captions_key']:
            raise web.HTTPNotFound()
        key = row['thumbnail_key'] if thumbnail else row['captions_key'] if captions else row['object_key']
        stream = await asyncio.to_thread(self.storage.open, key)
        try:
            if thumbnail or captions:
                # Thumbnails are bounded, so determine their length without
                # seeking a remote S3 response body.
                content = await asyncio.to_thread(stream.read, 2 * 1024 * 1024)
                return web.Response(body=content, content_type='text/vtt' if captions else 'image/jpeg',
                                    headers={'Cache-Control': 'private, no-store'})
            start, end, partial = byte_range(request.headers.get('Range'), row['size'])
            if start:
                await asyncio.to_thread(stream.close)
                stream = await asyncio.to_thread(self.storage.open, key, start, end)
            disposition = 'attachment' if row['kind'] == 'file' else 'inline'
            headers = {'Content-Type': row['mime'], 'Content-Length': str(end - start + 1), 'Accept-Ranges': 'bytes',
                       'Content-Disposition': f"{disposition}; filename*=UTF-8''{quote(row['name'], safe='')}",
                       'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff',
                       'Referrer-Policy': 'no-referrer'}
            if partial:
                headers['Content-Range'] = f"bytes {start}-{end}/{row['size']}"
            # Set CORS before prepare(), including on streaming media.
            origin = request.headers.get('Origin')
            if origin:
                headers.update({'Access-Control-Allow-Origin': origin, 'Access-Control-Allow-Credentials': 'true',
                                'Access-Control-Expose-Headers': 'Content-Range, Accept-Ranges, Content-Disposition', 'Vary': 'Origin'})
            response = web.StreamResponse(status=206 if partial else 200, headers=headers)
            await response.prepare(request)
            if request.method != 'HEAD':
                remaining = end - start + 1
                while remaining:
                    if not self.server.forum_enabled:
                        response.force_close()
                        break
                    chunk = await asyncio.to_thread(stream.read, min(CHUNK_SIZE, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    await response.write(chunk)
            await response.write_eof()
            return response
        finally:
            await asyncio.to_thread(stream.close)
