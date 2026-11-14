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


async def enter_thread(server, user, topic):
    server._nav_push(user, server.forum_manager.views.thread, topic)
    user.get_queued_messages()


async def command(server, user, post, key='right', shift=False, **extra):
    packet = {'type':'keybind', 'key':key, 'shift':shift, 'control':False, 'alt':False, 'meta':False,
              'menu_id':nav.THREAD, 'menu_item_id':f'post:{post}',
              'menu_index':server._menu_item_position(user, nav.THREAD, f'post:{post}')}
    await server._handle_keybind(user._connection, {**packet, **extra})
    return user.get_queued_messages()


async def close_reader(server, user, **extra):
    await server._handle_editbox(user._connection, {'type':'editbox','input_id':nav.BODY_READER, 'cancelled':True, **extra})
    return user.get_queued_messages()


@pytest.mark.parametrize('activation', ['right', 'enter', 'menu'])
async def test_complete_speech_preserves_list_focus_stack_and_does_not_open_a_box(forum, activation):
    server, users, topic, post, body = forum
    user = users['Reader']
    await enter_thread(server, user, topic)
    before = server._user_states[user.username]
    stack = list(before['_stack'])
    if activation == 'menu':
        await server._handle_menu(user._connection, {'type':'menu','menu_id':nav.THREAD,'selection_id':f'post:{post}'})
        packets = user.get_queued_messages()
    else:
        packets = await command(server, user, post, activation)
    assert server._user_states[user.username] is before
    assert before['menu'] == nav.THREAD and before['_stack'] == stack
    assert before['_last_selection_id'] == f'post:{post}'
    assert len(packets) == 1 and packets[0]['type'] == 'speak'
    assert packets[0]['text'] == body and packets[0]['history'] is False
    assert server.forum_manager.service.topic(user.uuid, topic).unread_count == 0


async def test_shift_enter_opens_only_readonly_box_and_escape_returns_to_exact_post(forum):
    server, users, topic, post, body = forum
    user = users['Reader']
    await enter_thread(server, user, topic)
    stack = list(server._user_states[user.username]['_stack'])
    packets = await command(server, user, post, 'enter', True)
    assert not any(p.get('menu_id') == nav.POST for p in packets)
    prompt = next(p for p in packets if p.get('type') == 'request_input')
    assert prompt['read_only'] and prompt['multiline'] and prompt['default_value'] == body
    assert prompt['max_length'] == 64000
    state = server._user_states[user.username]
    assert state['_parent_frame']['menu'] == nav.THREAD and state['_stack'] == stack
    closed = await close_reader(server, user, text='Forged edit')
    assert server._user_states[user.username]['menu'] == nav.THREAD
    assert server._user_states[user.username]['_stack'] == stack
    assert any(p.get('selection_id') == f'post:{post}' for p in closed)
    assert not any(p.get('type') == 'request_input' or p.get('menu_id') == nav.POST for p in closed)
    assert server.forum_manager.service.post(user.uuid, post).body == body


@pytest.mark.parametrize('key,shift', [('applications', False), ('f10', True)])
async def test_context_menu_only_contains_actions_and_restores_list(forum, key, shift):
    server, users, topic, post, body = forum
    user = users['Reader']
    await enter_thread(server, user, topic)
    packets = await command(server, user, post, key, shift)
    menu = next(p for p in packets if p.get('menu_id') == nav.POST)
    ids = [row['id'] for row in menu['items']]
    assert ids[:2] == ['speak_body', 'read_body'] and 'reply' in ids and 'report_post' in ids
    assert not any(body[:100] in row['text'] for row in menu['items'])
    assert not any(p.get('type') == 'request_input' for p in packets)
    assert server.forum_manager.service.topic(user.uuid, topic).unread_count == 1
    await server._handle_menu(user._connection, {'type':'menu','menu_id':nav.POST,'selection_id':'back'})
    assert server._user_states[user.username]['menu'] == nav.THREAD
    assert any(p.get('selection_id') == f'post:{post}' for p in user.get_queued_messages())


async def test_context_text_action_returns_to_list_when_reader_closes(forum):
    server, users, topic, post, _ = forum
    user = users['Reader']
    await enter_thread(server, user, topic)
    await command(server, user, post, 'applications')
    await server._handle_menu(user._connection, {'type':'menu','menu_id':nav.POST,'selection_id':'read_body'})
    assert server._user_states[user.username]['menu'] == nav.BODY_READER
    assert server._user_states[user.username]['_parent_frame']['menu'] == nav.THREAD
    await close_reader(server, user)
    assert server._user_states[user.username]['menu'] == nav.THREAD


@pytest.mark.parametrize('extra', [{'menu_id':'main_menu'}, {'menu_item_id':'post:999999'}, {'menu_index':99},
    {'control':True}, {'alt':True}, {'meta':True}, {'shift':True}])
async def test_stale_or_modified_read_requests_cannot_read_hidden_targets(forum, extra):
    server, users, topic, post, _ = forum
    user = users['Reader']
    await enter_thread(server, user, topic)
    assert not await command(server, user, post, **extra)
    assert server._user_states[user.username]['menu'] == nav.THREAD
    assert server.forum_manager.service.topic(user.uuid, topic).unread_count == 1


@pytest.mark.parametrize('revocation', ['hidden', 'blocked', 'membership', 'disabled'])
async def test_all_read_and_context_paths_recheck_current_access(forum, revocation):
    server, users, topic, post, body = forum
    user, owner = users['Reader'], users['Staff']
    service = server.forum_manager.service
    if revocation == 'membership':
        body = 'Privado\n' + body[len('Privado\n'):]
        topic, post = service.conversations.create(owner.uuid, 'Private', body, (user.uuid,))
        service.conversations.respond(user.uuid, service.conversations.invitations(user.uuid)[0]['id'], accept=True)
    await enter_thread(server, user, topic)
    if revocation == 'hidden':
        service.moderate(owner.uuid, topic, 'hidden', True, post)
    elif revocation == 'blocked':
        server.db.block_user(user.uuid, owner.uuid)
    elif revocation == 'membership':
        service.conversations.remove(owner.uuid, topic, user.uuid)
    else:
        server.set_forum_enabled(False)
    for key, shift in [('right', False), ('enter', True), ('applications', False)]:
        packets = await command(server, user, post, key, shift)
        assert not any(body in p.get('text', '') or p.get('type') == 'request_input' for p in packets)
        assert server._user_states[user.username]['menu'] != nav.BODY_READER


async def test_reader_close_after_disable_keeps_drafts_and_returns_to_valid_parent(forum):
    server, users, topic, post, _ = forum
    user = users['Reader']
    manager = server.forum_manager
    server._nav_push(user, manager.composer.show, Draft('topic', category_id='general', title='Kept', body='Kept draft'))
    await enter_thread(server, user, topic)
    await command(server, user, post, 'enter', True)
    server.set_forum_enabled(False)
    packets = await close_reader(server, user)
    assert server._user_states[user.username]['menu'] == nav.COMPOSER
    assert server._user_states[user.username]['forum_draft']['body'] == 'Kept draft'
    assert any(p.get('key') == 'forum-unavailable' for p in packets)


async def test_continue_reads_and_focuses_exact_unread_post_without_a_detail_page(forum):
    server, users, topic, first, body = forum
    user, owner = users['Reader'], users['Staff']
    second = server.forum_manager.service.reply(owner.uuid, topic, 'Second message')
    await enter_thread(server, user, topic)
    await server._handle_menu(user._connection, {'type':'menu','menu_id':nav.THREAD,'selection_id':'continue'})
    packets = user.get_queued_messages()
    assert any(p.get('type') == 'speak' and p.get('text') == body for p in packets)
    assert any(p.get('selection_id') == f'post:{first}' for p in packets)
    assert server._user_states[user.username]['menu'] == nav.THREAD
    assert not any(p.get('type') == 'request_input' for p in packets)
    packets = await command(server, user, second)
    assert any(p.get('text') == 'Second message' for p in packets)


@pytest.mark.parametrize('client_type', ['python', 'web'])
async def test_speech_context_and_optional_reader_over_real_socket(tmp_path, client_type):
    server = Server(host='127.0.0.1', port=0, db_path=str(tmp_path / 'socket.db'))
    await server.start()
    try:
        auth = AuthManager(server.db)
        for name in ('Staff', 'Reader'):
            assert auth.register(name, 'TestPassword123', locale='es', email=f'{name}@example.test') == 'ok'
            server.db.approve_user(name)
        body = 'First line\n' + 'x' * 63989
        topic, post = server.forum_manager.service.create_topic(server.db.get_user('Staff').uuid, 'general', 'Full message', body)
        port = server._ws_server._server.sockets[0].getsockname()[1]
        async def receive(ws, predicate):
            async with asyncio.timeout(15):
                while True:
                    packet = json.loads(await ws.recv())
                    if predicate(packet):
                        return packet
        async def choose(ws, surface, item, target):
            await ws.send(json.dumps({'type':'menu','menu_id':surface,'selection_id':item}))
            return await receive(ws, lambda p:p.get('menu_id') == target)
        async with connect(f'ws://127.0.0.1:{port}') as ws:
            await ws.send(json.dumps({'type':'authorize','client':client_type,'version':VERSION,'username':'Reader','password':'TestPassword123'}))
            await receive(ws, lambda p:p.get('menu_id') == 'main_menu')
            await choose(ws, 'main_menu', 'forum', nav.HOME)
            await choose(ws, nav.HOME, 'category:general', nav.TOPICS)
            await choose(ws, nav.TOPICS, f'topic:{topic}', nav.THREAD)
            await ws.send(json.dumps({'type':'menu','menu_id':nav.THREAD,'selection_id':f'post:{post}'}))
            spoken = await receive(ws, lambda p:p.get('type') == 'speak' and p.get('text') == body)
            assert spoken['history'] is False
            assert server._user_states['Reader']['menu'] == nav.THREAD
            packet = {'type':'keybind','menu_id':nav.THREAD,'menu_item_id':f'post:{post}','key':'enter','shift':True}
            await ws.send(json.dumps(packet))
            prompt = await receive(ws, lambda p:p.get('type') == 'request_input')
            assert prompt['read_only'] and prompt['multiline'] and prompt['default_value'] == body
            await ws.send(json.dumps({'type':'editbox','input_id':nav.BODY_READER,'cancelled':True}))
            await receive(ws, lambda p:p.get('menu_id') == nav.THREAD)
            await ws.send(json.dumps({**packet,'key':'f10','shift':True}))
            context = await receive(ws, lambda p:p.get('menu_id') == nav.POST)
            assert [row['id'] for row in context['items'][:2]] == ['speak_body', 'read_body']
            await choose(ws, nav.POST, 'back', nav.THREAD)
    finally:
        await server.stop()
