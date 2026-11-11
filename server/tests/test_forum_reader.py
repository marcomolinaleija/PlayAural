"""The full-message reader is read-only, bounded in menus and ACL-aware."""

from types import SimpleNamespace
import asyncio
import json

import pytest
from websockets.asyncio.client import connect

from ..core.server import Server, VERSION
from ..auth.auth import AuthManager
from ..forum import navigation as nav
from ..forum.models import Draft
from ..users.network_user import NetworkUser


@pytest.fixture
def forum(tmp_path):
    server = Server(db_path=str(tmp_path / 'reader.db'))
    server.db.connect()
    users = {}
    for name, level in (('Staff', 3), ('Reader', 1)):
        account = server.db.create_user(name, 'hash', locale='es', trust_level=level)
        server.db.approve_user(name)
        connection = SimpleNamespace(username=name, retired=False, authenticated=True)
        user = NetworkUser(name, 'es', connection, uuid=account.uuid, approved=True, trust_level=level)
        server._users[name] = users[name] = user
        server._show_main_menu(user)
        user.get_queued_messages()
    body = 'Primera línea\n' + 'x' * (64000 - len('Primera línea\n'))
    topic, post = server.forum_manager.service.create_topic(users['Staff'].uuid, 'general', 'Large message', body)
    yield server, users, topic, post, body
    server.db.close()


async def open_reader(server, user, topic, post):
    server._nav_push(user, server.forum_manager.views.thread, topic)
    user.get_queued_messages()
    await server._handle_menu(user._connection, {'type':'menu','menu_id':nav.THREAD,'selection_id':f'post:{post}'})
    return user.get_queued_messages()


async def close_reader(server, user, **extra):
    await server._handle_editbox(user._connection, {'type':'editbox','input_id':nav.BODY_READER, **extra})
    return user.get_queued_messages()


async def test_opening_preview_shows_complete_readonly_message_and_closing_restores_focus(forum):
    server, users, topic, post, body = forum
    actor = users['Reader']
    manager = server.forum_manager
    assert manager.service.topic(actor.uuid, topic).unread_count == 1
    server._nav_push(actor, manager.views.thread, topic)
    thread = next(p for p in actor.get_queued_messages() if p.get('menu_id') == nav.THREAD)
    assert len(thread['items'][0]['text']) < 300
    assert manager.service.topic(actor.uuid, topic).unread_count == 1
    await server._handle_menu(actor._connection, {'type':'menu','menu_id':nav.THREAD,'selection_id':f'post:{post}'})
    packets = actor.get_queued_messages()
    detail = next(p for p in packets if p.get('menu_id') == nav.POST)
    prompt = next(p for p in packets if p.get('input_id') == nav.BODY_READER)
    assert detail['items'][0]['id'] == 'read_body' and len(detail['items'][0]['text']) <= 160
    assert not any(row['id'].startswith('body:') for row in detail['items'])
    assert len(detail['items']) < 10
    assert prompt['type'] == 'request_input' and prompt['multiline'] and prompt['read_only']
    assert prompt['default_value'] == body and prompt['max_length'] == 64000
    assert not any(body in p.get('text', '') for p in packets if p.get('type') == 'speak')
    assert manager.service.topic(actor.uuid, topic).unread_count == 0
    closed = await close_reader(server, actor, text='Forged replacement')
    menu = next(p for p in closed if p.get('menu_id') == nav.POST)
    assert menu['selection_id'] == 'read_body'
    assert not any(p.get('type') == 'request_input' for p in closed)
    retained = manager.service.post(actor.uuid, post)
    assert retained.body == body and retained.revision == 0
    await server._handle_menu(actor._connection, {'type':'menu','menu_id':nav.POST,'selection_id':'back'})
    menu = next(p for p in actor.get_queued_messages() if p.get('menu_id') == nav.THREAD)
    assert menu['selection_id'] == f'post:{post}'


async def test_reader_ignores_stale_input_and_reopens_current_text(forum):
    server, users, topic, post, _ = forum
    actor, owner = users['Reader'], users['Staff']
    await open_reader(server, actor, topic, post)
    await server._handle_editbox(actor._connection, {'type':'editbox','input_id':nav.BODY_INPUT,'text':'Wrong input'})
    assert server._user_states[actor.username]['menu'] == nav.BODY_READER
    await close_reader(server, actor, cancelled=True)
    server.forum_manager.service.edit(owner.uuid, post, 'Updated\nmessage', 0)
    await server._handle_menu(actor._connection, {'type':'menu','menu_id':nav.POST,'selection_id':'read_body'})
    prompt = next(p for p in actor.get_queued_messages() if p.get('input_id') == nav.BODY_READER)
    assert prompt['default_value'] == 'Updated\nmessage'


@pytest.mark.parametrize('revocation', ['hidden', 'blocked', 'private_membership'])
async def test_reopening_checks_current_visibility_and_never_sends_revoked_text(forum, revocation):
    server, users, topic, post, _ = forum
    actor, owner = users['Reader'], users['Staff']
    service = server.forum_manager.service
    if revocation == 'private_membership':
        topic, post = service.conversations.create(owner.uuid, 'Private', 'Private message', (actor.uuid,))
        invite = service.conversations.invitations(actor.uuid)[0]['id']
        service.conversations.respond(actor.uuid, invite, accept=True)
    await open_reader(server, actor, topic, post)
    await close_reader(server, actor, cancelled=True)
    if revocation == 'hidden':
        service.moderate(owner.uuid, topic, 'hidden', True, post)
    elif revocation == 'blocked':
        server.db.block_user(actor.uuid, owner.uuid)
    else:
        service.conversations.remove(owner.uuid, topic, actor.uuid)
    await server._handle_menu(actor._connection, {'type':'menu','menu_id':nav.POST,'selection_id':'read_body'})
    assert not any(p.get('type') == 'request_input' for p in actor.get_queued_messages())
    assert server._user_states[actor.username]['menu'] != nav.BODY_READER


async def test_hidden_post_opens_only_placeholder(forum):
    server, users, topic, post, _ = forum
    server.forum_manager.service.moderate(users['Staff'].uuid, topic, 'hidden', True, post)
    packets = await open_reader(server, users['Reader'], topic, post)
    assert not any(p.get('type') == 'request_input' for p in packets)
    menu = next(p for p in packets if p.get('menu_id') == nav.POST)
    assert menu['items'][0]['id'] == 'hidden'


async def test_reader_can_close_after_forum_is_disabled_without_refreshing_content(forum):
    server, users, topic, post, _ = forum
    actor = users['Reader']
    await open_reader(server, actor, topic, post)
    server.set_forum_enabled(False)
    packets = await close_reader(server, actor, text='Ignored')
    assert server._user_states[actor.username]['menu'] == 'main_menu'
    assert any(p.get('type') == 'remove_editbox' for p in packets)
    assert not any(p.get('menu_id') == nav.POST or p.get('type') == 'request_input' for p in packets)


async def test_closing_disabled_reader_preserves_an_earlier_local_draft(forum):
    server, users, topic, post, _ = forum
    actor = users['Reader']
    server._nav_push(actor, server.forum_manager.composer.show,
                     Draft('topic', category_id='general', title='Kept title', body='Kept draft'))
    await open_reader(server, actor, topic, post)
    server.set_forum_enabled(False)
    await close_reader(server, actor, cancelled=True)
    state = server._user_states[actor.username]
    assert state['menu'] == nav.COMPOSER
    assert state['forum_draft']['body'] == 'Kept draft' and state['forum_draft']['title'] == 'Kept title'


async def test_reconnect_restores_message_actions_without_reopening_cached_reader(forum):
    server, users, topic, post, _ = forum
    actor = users['Reader']
    await open_reader(server, actor, topic, post)
    frame = server._normalize_restore_state_for_client(actor, server._user_states[actor.username])
    server._restore_menu_from_state(actor, frame)
    packets = actor.get_queued_messages()
    assert server._user_states[actor.username]['menu'] == nav.POST
    assert not any(p.get('type') == 'request_input' for p in packets)


async def test_continue_and_next_unread_open_the_exact_full_message(forum):
    server, users, topic, first, body = forum
    actor, owner = users['Reader'], users['Staff']
    service = server.forum_manager.service
    second = service.reply(owner.uuid, topic, 'Second message')
    server._nav_push(actor, server.forum_manager.views.thread, topic)
    actor.get_queued_messages()
    await server._handle_menu(actor._connection, {'type':'menu','menu_id':nav.THREAD,'selection_id':'continue'})
    prompt = next(p for p in actor.get_queued_messages() if p.get('input_id') == nav.BODY_READER)
    assert prompt['default_value'] == body
    await close_reader(server, actor, cancelled=True)
    await server._handle_menu(actor._connection, {'type':'menu','menu_id':nav.POST,'selection_id':'next_unread'})
    prompt = next(p for p in actor.get_queued_messages() if p.get('input_id') == nav.BODY_READER)
    assert prompt['default_value'] == 'Second message'
    assert server._user_states[actor.username]['forum_post'] == second
    assert service.topic(actor.uuid, topic).unread_count == 0


@pytest.mark.parametrize('client_type', ['python', 'web'])
async def test_open_from_thread_and_close_readonly_over_real_socket(tmp_path, client_type):
    server = Server(host='127.0.0.1', port=0, db_path=str(tmp_path / 'socket.db'))
    await server.start()
    try:
        auth = AuthManager(server.db)
        for name in ('Staff', 'Reader'):
            assert auth.register(name, 'TestPassword123', locale='es', email=f'{name}@example.test') == 'ok'
            server.db.approve_user(name)
        body = 'First line\n' + 'x' * 63989
        topic, post = server.forum_manager.service.create_topic(server.db.get_user('Staff').uuid, 'general', 'Read only', body)
        port = server._ws_server._server.sockets[0].getsockname()[1]
        async def receive(ws, predicate):
            async with asyncio.timeout(15):
                while True:
                    packet = json.loads(await ws.recv())
                    if predicate(packet):
                        return packet
        async def choose(ws, menu, action, result):
            await ws.send(json.dumps({'type':'menu','menu_id':menu,'selection_id':action}))
            return await receive(ws, lambda p:p.get('menu_id') == result)
        async with connect(f'ws://127.0.0.1:{port}') as ws:
            await ws.send(json.dumps({'type':'authorize','client':client_type,'version':VERSION,
                                     'username':'Reader','password':'TestPassword123'}))
            await receive(ws, lambda p:p.get('menu_id') == 'main_menu')
            await choose(ws, 'main_menu', 'forum', nav.HOME)
            await choose(ws, nav.HOME, 'category:general', nav.TOPICS)
            thread = await choose(ws, nav.TOPICS, f'topic:{topic}', nav.THREAD)
            assert len(thread['items'][0]['text']) < 300
            detail = await choose(ws, nav.THREAD, f'post:{post}', nav.POST)
            assert detail['items'][0]['id'] == 'read_body'
            prompt = await receive(ws, lambda p:p.get('type') == 'request_input' and p.get('input_id') == nav.BODY_READER)
            assert prompt['read_only'] and prompt['multiline'] and prompt['default_value'] == body
            # A modified return payload cannot turn the reader into an editor.
            await ws.send(json.dumps({'type':'editbox','input_id':nav.BODY_READER,'text':'Attempted modification'}))
            detail = await receive(ws, lambda p:p.get('menu_id') == nav.POST)
            assert detail['selection_id'] == 'read_body'
            assert server.forum_manager.service.post(server.db.get_user('Reader').uuid, post).body == body
            await choose(ws, nav.POST, 'back', nav.THREAD)
    finally:
        await server.stop()
