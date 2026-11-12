"""Discover attachments and activate their real content from a thread row."""

import asyncio
import json

from aiohttp import ClientSession
from PIL import Image
import pytest
from websockets.asyncio.client import connect

from ..auth.auth import AuthManager
from ..core.server import Server, VERSION
from ..forum import navigation as nav
from ..forum.media_http import ForumMediaHTTP
from ..forum.media_processing import MediaProcessor, ProcessedMedia
from ..forum.models import ForumError
from ..forum.polls import PollConfig
from .test_forum_thread_polls import forum, menu


@pytest.fixture
def resources(forum, tmp_path):
    server, service, users, _ = forum
    server._stopping = False
    server.forum_manager.media = ForumMediaHTTP(server, base_url='http://127.0.0.1:8001', directory=tmp_path / 'media')
    return server, service, users


def attachment(service, owner, tmp_path, kind='image', *, topic=0, description='Descripción de la imagen'):
    suffix, mime = {'image':('.png', 'image/png'), 'audio':('.mp3', 'audio/mpeg'),
                    'video':('.mp4', 'video/mp4'), 'file':('.txt', 'text/plain')}[kind]
    row = service.attachments.reserve(owner, kind + suffix, 10, description, topic_id=topic)
    service.attachments.processing(owner, row['id'])
    service.attachments.complete(owner, row['id'], ProcessedMedia(tmp_path / 'unused', mime, kind, suffix, 10, '0' * 64))
    return row['id']


def make_post(resources, tmp_path, kinds=(), *, poll=False, private=False):
    server, service, users = resources
    owner, viewer = users['Alice'].uuid, users['Bob'].uuid
    if private:
        topic, _ = service.conversations.create(owner, 'Private', 'Private invitation', (viewer,))
        service.conversations.respond(viewer, service.conversations.invitations(viewer)[0]['id'], accept=True)
    else:
        topic, _ = service.create_topic(owner, 'general', 'Resources', 'Introduction')
    ids = tuple(attachment(service, owner, tmp_path, kind, topic=topic) for kind in kinds)
    post = service.reply(owner, topic, 'Resource body', attachment_ids=ids,
                         poll=PollConfig('Post question', ('Yes', 'No')) if poll else None)
    user = users['Bob']
    server._nav_push(user, server.forum_manager.views.thread, topic)
    user.get_queued_messages()
    return topic, post, ids


async def key(server, user, post, name='enter', shift=False):
    await server._handle_keybind(user._connection, {'type':'keybind', 'key':name, 'shift':shift,
        'menu_id':nav.THREAD, 'menu_item_id':f'post:{post}',
        'menu_index':server._menu_item_position(user, nav.THREAD, f'post:{post}')})
    return user.get_queued_messages()


@pytest.mark.parametrize('kind', ['image', 'audio', 'video', 'file', 'poll', 'text'])
@pytest.mark.parametrize('activation', ['key', 'menu'])
async def test_enter_opens_the_only_resource_and_keeps_plain_text_reading(resources, tmp_path, kind, activation):
    server, service, users = resources
    topic, post, ids = make_post(resources, tmp_path, (kind,) if kind in {'image', 'audio', 'video', 'file'} else (), poll=kind == 'poll')
    user = users['Bob']
    if activation == 'key':
        packets = await key(server, user, post)
    else:
        await server._handle_menu(user._connection, {'type':'menu', 'menu_id':nav.THREAD, 'selection_id':f'post:{post}'})
        packets = user.get_queued_messages()
    if ids:
        opened = next(p for p in packets if p.get('type') == 'forum_open_media')
        assert opened['attachment']['id'] == ids[0] and opened['attachment']['kind'] == kind
        assert opened['attachment']['description'] == 'Descripción de la imagen'
        assert server._user_states[user.username]['menu'] == nav.THREAD
    elif kind == 'poll':
        assert server._user_states[user.username]['menu'] == nav.POLL
        assert any(row['id'].startswith('choice:') for row in next(p for p in packets if p.get('menu_id') == nav.POLL)['items'])
        await server._handle_menu(user._connection, {'type':'menu', 'menu_id':nav.POLL, 'selection_id':'back'})
        assert server._user_states[user.username]['menu'] == nav.THREAD
        assert any(p.get('selection_id') == f'post:{post}' for p in user.get_queued_messages())
    else:
        assert any(p.get('type') == 'speak' and p.get('text') == 'Resource body' for p in packets)
    assert not any(p.get('type') == 'request_input' or p.get('menu_id') == nav.POST for p in packets)
    # Opening a resource is independent of reading the post's body.
    assert service.topic(user.uuid, topic).unread_count == (0 if kind == 'text' else 2)


async def test_right_and_shift_enter_keep_complete_text_and_announce_all_resources(resources, tmp_path):
    server, service, users = resources
    topic, post, _ = make_post(resources, tmp_path, ('image', 'audio'), poll=True)
    user = users['Bob']
    body = 'Line one\n' + 'x' * 63991
    service.edit(users['Alice'].uuid, post, body, 0)
    server._nav_refresh(user, server.forum_manager.views.thread, topic)
    row = next(row for row in menu(user, nav.THREAD)['items'] if row['id'] == f'post:{post}')
    assert row['text'].startswith('Contiene una encuesta. Contiene 2 archivos adjuntos.')
    assert len(row['text']) < 300
    packets = await key(server, user, post, 'right')
    spoken = next(p for p in packets if p.get('type') == 'speak')
    assert spoken['text'] == 'Contiene una encuesta. Contiene 2 archivos adjuntos.\n' + body
    assert not any(p.get('type') == 'forum_open_media' for p in packets)
    packets = await key(server, user, post, 'enter', True)
    reader = next(p for p in packets if p.get('type') == 'request_input')
    assert reader['read_only'] and reader['default_value'] == body
    assert '2 archivos adjuntos' in reader['prompt']


async def test_multiple_resources_open_a_content_only_chooser_and_restore_post_focus(resources, tmp_path):
    server, service, users = resources
    topic, post, ids = make_post(resources, tmp_path, ('image', 'audio'), poll=True)
    user = users['Bob']
    packets = await key(server, user, post)
    content = next(p for p in packets if p.get('menu_id') == nav.CONTENTS)
    assert content['items'][0]['id'] == 'poll' and content['items'][-1]['id'] == 'back'
    assert {row['id'] for row in content['items'][1:-1]} == {f'attachment:{value}' for value in ids}
    assert 'Descripción de la imagen' in content['items'][1]['text']
    await server._handle_menu(user._connection, {'type':'menu', 'menu_id':nav.CONTENTS, 'selection_id':'poll'})
    assert server._user_states[user.username]['menu'] == nav.POLL
    await server._handle_menu(user._connection, {'type':'menu', 'menu_id':nav.POLL, 'selection_id':'back'})
    user.get_queued_messages()
    await server._handle_menu(user._connection, {'type':'menu', 'menu_id':nav.CONTENTS, 'selection_id':f'attachment:{ids[0]}'})
    assert any(p.get('type') == 'forum_open_media' for p in user.get_queued_messages())
    await server._handle_menu(user._connection, {'type':'menu', 'menu_id':nav.CONTENTS, 'selection_id':'back'})
    assert server._user_states[user.username]['menu'] == nav.THREAD
    assert any(p.get('selection_id') == f'post:{post}' for p in user.get_queued_messages())
    assert service.topic(user.uuid, topic).unread_count == 2


async def test_chooser_cannot_open_an_attachment_from_another_post(resources, tmp_path):
    server, service, users = resources
    topic, post, _ = make_post(resources, tmp_path, ('image',), poll=True)
    user = users['Bob']
    await key(server, user, post)
    other = attachment(service, users['Alice'].uuid, tmp_path, 'audio', topic=topic)
    service.reply(users['Alice'].uuid, topic, 'Another post', attachment_ids=(other,))
    selection = f'attachment:{other}'
    await server._handle_menu(user._connection, {'type':'menu', 'menu_id':nav.CONTENTS, 'selection_id':selection})
    assert not any(p.get('type') == 'forum_open_media' for p in user.get_queued_messages())
    with pytest.raises(ForumError, match='forum-error-missing'):
        server.forum_manager.media_ui.handle(user, selection, server._user_states[user.username])


@pytest.mark.parametrize('change', ['hidden', 'blocked', 'membership', 'disabled'])
async def test_stale_resource_selection_rechecks_access_before_sending_media(resources, tmp_path, change):
    server, service, users = resources
    topic, post, ids = make_post(resources, tmp_path, ('image',), poll=True, private=change == 'membership')
    user = users['Bob']
    await key(server, user, post)
    if change == 'hidden':
        service.moderate(users['Staff'].uuid, topic, 'hidden', True, post)
        assert not service.post(user.uuid, post).attachment_count
    elif change == 'blocked':
        server.db.block_user(user.uuid, users['Alice'].uuid)
    elif change == 'membership':
        service.conversations.remove(users['Alice'].uuid, topic, user.uuid)
    else:
        server.set_forum_enabled(False)
    await server._handle_menu(user._connection, {'type':'menu', 'menu_id':nav.CONTENTS, 'selection_id':f'attachment:{ids[0]}'})
    assert not any(p.get('type') == 'forum_open_media' for p in user.get_queued_messages())


@pytest.mark.parametrize('column,value', [('state', 'failed'), ('approval', 'rejected'), ('published', 0)])
def test_only_published_ready_approved_files_are_announced(resources, tmp_path, column, value):
    _, service, users = resources
    topic, post, ids = make_post(resources, tmp_path, ('image',))
    service.repository.connection.execute(f'UPDATE forum_attachments SET {column} = ? WHERE id = ?', (value, ids[0]))
    assert not service.post(users['Bob'].uuid, post).attachment_count
    assert not next(item for item in service.posts(users['Bob'].uuid, topic).items if item.id == post).attachment_count


@pytest.mark.parametrize('client_type', ['python', 'web'])
async def test_socket_content_picker_image_description_and_authenticated_http(tmp_path, client_type):
    server = Server(host='127.0.0.1', port=0, db_path=str(tmp_path / 'socket.db'),
                    forum_media_url='http://127.0.0.1:0', forum_media_port=0, forum_media_dir=tmp_path / 'media')
    await server.start()
    try:
        auth = AuthManager(server.db)
        for name in ('Alice', 'Bob'):
            assert auth.register(name, 'ForumPassword123', locale='es', email=f'{name}@example.test') == 'ok'
            server.db.approve_user(name)
        service, media = server.forum_manager.service, server.forum_manager.media
        media.base_url = f'http://127.0.0.1:{media.site._server.sockets[0].getsockname()[1]}/forum-media'
        source = tmp_path / 'image.png'
        Image.new('RGB', (4, 4), 'blue').save(source)
        owner = server.db.get_user('Alice').uuid
        reserved = service.attachments.reserve(owner, 'image.png', source.stat().st_size, 'Un cuadrado azul')
        service.attachments.processing(owner, reserved['id'])
        prepared = MediaProcessor().process(source, tmp_path / 'prepared')
        media.storage.put(reserved['object_key'], prepared.path, prepared.mime)
        if prepared.thumbnail:
            media.storage.put(reserved['object_key'].replace('/content', '/thumbnail'), prepared.thumbnail, 'image/jpeg')
        service.attachments.complete(owner, reserved['id'], prepared)
        topic, post = service.create_topic(owner, 'general', 'Content', 'Body', attachment_ids=(reserved['id'],),
                                          poll=PollConfig('Question', ('Yes', 'No')))
        async def receive(ws, predicate):
            async with asyncio.timeout(15):
                while True:
                    packet = json.loads(await ws.recv())
                    if predicate(packet):
                        return packet
        async def choose(ws, surface, action, result):
            await ws.send(json.dumps({'type':'menu', 'menu_id':surface, 'selection_id':action}))
            return await receive(ws, lambda p:p.get('menu_id') == result)
        port = server._ws_server._server.sockets[0].getsockname()[1]
        async with connect(f'ws://127.0.0.1:{port}') as ws:
            await ws.send(json.dumps({'type':'authorize', 'client':client_type, 'version':VERSION,
                                      'username':'Bob', 'password':'ForumPassword123'}))
            await receive(ws, lambda p:p.get('menu_id') == 'main_menu')
            await choose(ws, 'main_menu', 'forum', nav.HOME)
            await choose(ws, nav.HOME, 'category:general', nav.TOPICS)
            thread = await choose(ws, nav.TOPICS, f'topic:{topic}', nav.THREAD)
            assert 'Contiene un archivo adjunto.' in thread['items'][0]['text']
            await choose(ws, nav.THREAD, f'post:{post}', nav.CONTENTS)
            await ws.send(json.dumps({'type':'menu', 'menu_id':nav.CONTENTS, 'selection_id':f"attachment:{reserved['id']}"}))
            opened = await receive(ws, lambda p:p.get('type') == 'forum_open_media')
            assert opened['attachment']['description'] == 'Un cuadrado azul'
            async with ClientSession() as http:
                async with http.get(opened['url'], headers={'Authorization':'Bearer ' + opened['token']}) as response:
                    assert response.status == 200 and await response.read() == prepared.path.read_bytes()
            await choose(ws, nav.CONTENTS, 'poll', nav.POLL)
            await choose(ws, nav.POLL, 'back', nav.CONTENTS)
            restored = await choose(ws, nav.CONTENTS, 'back', nav.THREAD)
            assert restored['selection_id'] == f'post:{post}'
    finally:
        await server.stop()
