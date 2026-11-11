"""Real HTTP upload/streaming, session revocation, CORS and SQLite barriers."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace

from aiohttp import ClientSession, CookieJar
from aiohttp import web
import pytest

from ..core.server import Server
from ..forum.media_http import ForumMediaHTTP, byte_range
from ..forum.media_processing import MediaProcessor
from ..forum.models import ForumError
from ..users.network_user import NetworkUser


@pytest.fixture
async def media_server(tmp_path):
    server = Server(db_path=str(tmp_path / 'forum.db'))
    server._stopping = False
    server.db.connect()
    users = {}
    for name in ('Alice', 'Bob'):
        account = server.db.create_user(name, 'hash')
        server.db.approve_user(name)
        client = SimpleNamespace(username=name, authenticated=True, retired=False)
        users[name] = NetworkUser(name, 'es', client, uuid=account.uuid, approved=True)
        server._users[name] = users[name]
    media = ForumMediaHTTP(server, base_url='http://127.0.0.1:0', directory=tmp_path / 'media',
                           origins=('http://127.0.0.1:18766',))
    await media.start('127.0.0.1', 0)
    port = media.site._server.sockets[0].getsockname()[1]
    media.base_url = f'http://127.0.0.1:{port}/forum-media'
    yield server, media, users
    await media.stop()
    server.db.close()


async def ready_file(server, media, user, tmp_path):
    source = tmp_path / 'source.txt'
    source.write_bytes(b'0123456789abcdef')
    service = server.forum_manager.service
    row = service.attachments.reserve(user.uuid, 'notes.txt', source.stat().st_size)
    service.attachments.processing(user.uuid, row['id'])
    processed = MediaProcessor().process(source, tmp_path / 'prepared')
    media.storage.put(row['object_key'], processed.path, processed.mime)
    service.attachments.complete(user.uuid, row['id'], processed)
    return row['id']


def test_range_parser_bounds_and_suffixes():
    assert byte_range(None, 10) == (0, 9, False)
    assert byte_range('bytes=2-6', 10) == (2, 6, True)
    assert byte_range('bytes=8-', 10) == (8, 9, True)
    assert byte_range('bytes=-3', 10) == (7, 9, True)
    assert byte_range('bytes=0-100', 10) == (0, 9, True)
    for invalid in ('bytes=', 'bytes=-0', 'bytes=10-', 'bytes=7-2', 'bytes=0-1,4-5', 'bytes=' + '9' * 5000 + '-'):
        with pytest.raises(web.HTTPRequestRangeNotSatisfiable):
            byte_range(invalid, 10)


async def test_binary_access_needs_current_session_and_supports_seek_and_head(media_server, tmp_path):
    server, media, users = media_server
    attachment = await ready_file(server, media, users['Alice'], tmp_path)
    credentials = media.credentials(users['Alice'])
    url = f"{media.base_url}/files/{attachment}"
    headers = {'Authorization': 'Bearer ' + credentials['token']}
    async with ClientSession() as client:
        async with client.get(url) as response:
            assert response.status == 401
        async with client.get(url, headers={**headers, 'Range': 'bytes=3-7'}) as response:
            assert response.status == 206 and await response.read() == b'34567'
            assert response.headers['Content-Range'] == 'bytes 3-7/16'
            assert response.headers['Content-Disposition'].startswith('attachment;')
            assert response.headers['Cache-Control'] == 'private, no-store'
            assert response.headers['X-Content-Type-Options'] == 'nosniff'
        async with client.head(url, headers=headers) as response:
            assert response.status == 200 and response.content_length == 16
            assert await response.read() == b''
        async with client.get(url, headers={**headers, 'Range': 'bytes=99-'}) as response:
            assert response.status == 416 and response.headers['Content-Range'] == 'bytes */16'
        # Handover retires the old credential even though the UUID is unchanged.
        old_user = users['Alice']
        client_connection = SimpleNamespace(username='Alice', authenticated=True, retired=False)
        server._users['Alice'] = NetworkUser('Alice', 'es', client_connection, uuid=old_user.uuid, approved=True)
        async with client.get(url, headers=headers) as response:
            assert response.status == 401


async def test_cookie_bootstrap_cors_and_missing_binary_does_not_reveal_metadata(media_server, tmp_path):
    server, media, users = media_server
    attachment = await ready_file(server, media, users['Alice'], tmp_path)
    url = f'{media.base_url}/files/{attachment}'
    headers = {'Authorization': 'Bearer ' + media.credentials(users['Alice'])['token'], 'Origin': 'http://127.0.0.1:18766'}
    async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as client:
        async with client.post(media.base_url + '/session', headers=headers) as response:
            assert response.status == 200 and response.cookies['playaural_forum_media']['httponly']
            assert response.headers['Access-Control-Allow-Origin'] == headers['Origin']
        async with client.get(url, headers={'Origin': headers['Origin']}) as response:
            assert response.status == 200 and await response.read() == b'0123456789abcdef'
            assert response.headers['Access-Control-Allow-Credentials'] == 'true'
        async with client.get(url, headers={**headers, 'Origin': 'https://unrelated.example'}) as response:
            assert response.status == 403
        async with client.post(media.base_url + '/uploads', json={'name': 'forged'}) as response:
            assert response.status == 403  # Cookie mutations require a trusted origin.
    bob_headers = {'Authorization': 'Bearer ' + media.credentials(users['Bob'])['token']}
    async with ClientSession() as client:
        async with client.get(url, headers=bob_headers) as response:
            assert response.status == 404
        async with client.get(url + '?token=' + headers['Authorization'][7:]) as response:
            assert response.status == 401  # URLs alone never authorize files.


async def test_published_file_rechecks_membership_for_each_range_request(media_server, tmp_path):
    server, media, users = media_server
    service = server.forum_manager.service
    attachment = await ready_file(server, media, users['Alice'], tmp_path)
    topic, _ = service.conversations.create(users['Alice'].uuid, 'Private', 'Body', (users['Bob'].uuid,), attachment_ids=(attachment,))
    invite = service.conversations.invitations(users['Bob'].uuid)[0]['id']
    service.conversations.respond(users['Bob'].uuid, invite, accept=True)
    headers = {'Authorization': 'Bearer ' + media.credentials(users['Bob'])['token'], 'Range': 'bytes=0-3'}
    async with ClientSession() as client:
        async with client.get(f'{media.base_url}/files/{attachment}', headers=headers) as response:
            assert response.status == 206 and await response.read() == b'0123'
        service.conversations.leave(users['Bob'].uuid, topic)
        async with client.get(f'{media.base_url}/files/{attachment}', headers=headers) as response:
            assert response.status == 404


async def test_actual_upload_is_processed_outside_event_loop_and_only_then_ready(media_server):
    server, media, users = media_server
    media.on_reserve = lambda user, payload: server.forum_manager.service.attachments.reserve(user.uuid, payload['name'], payload['size'])
    headers = {'Authorization': 'Bearer ' + media.credentials(users['Alice'])['token']}
    content = b'Uploaded over authenticated HTTP.'
    completed = asyncio.Event()
    media.worker.on_complete = lambda *args: completed.set()
    async with ClientSession() as client:
        async with client.post(media.base_url + '/uploads', headers=headers, json={'name': 'test.txt', 'size': len(content)}) as response:
            assert response.status == 201
            reservation = await response.json()
        async with client.put(reservation['upload_url'], headers=headers, data=content) as response:
            assert response.status == 202
        await asyncio.wait_for(completed.wait(), timeout=10)
        assert not any(media.staging.iterdir())
        async with client.get(f"{media.base_url}/files/{reservation['id']}", headers=headers) as response:
            assert response.status == 200 and await response.read() == content
        # A finished upload cannot be replaced using its old upload URL.
        async with client.put(reservation['upload_url'], headers=headers, data=content) as response:
            assert response.status == 404


async def test_maintenance_rejects_http_before_touching_sqlite(media_server, tmp_path):
    server, media, users = media_server
    attachment = await ready_file(server, media, users['Alice'], tmp_path)
    headers = {'Authorization': 'Bearer ' + media.credentials(users['Alice'])['token']}
    server.maintenance_manager._active_operation = SimpleNamespace()
    try:
        server.db.close()
        async with ClientSession() as client:
            async with client.get(f'{media.base_url}/files/{attachment}', headers=headers) as response:
                assert response.status == 503
    finally:
        server.maintenance_manager._active_operation = None
        server.db.connect()
