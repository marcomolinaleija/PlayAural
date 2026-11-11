"""Persistent staff control and a visible, unavailable forum entry point."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from websockets.asyncio.client import connect

from ..auth.auth import AuthManager
from ..core.server import Server, VERSION
from ..administration.manager import ADMIN_MODERATION_MENU, ADMIN_SANCTIONS_MENU
from ..forum import navigation as nav
from ..users.network_user import NetworkUser


@pytest.fixture
def forum_server(tmp_path):
    server = Server(db_path=str(tmp_path / 'availability.db'))
    server.db.connect()
    users = {}
    for name, level in (('Developer', 3), ('Administrator', 2), ('Reader', 1)):
        account = server.db.create_user(name, 'hash', locale='es')
        server.db.approve_user(name)
        server.db.update_user_trust_level(name, level)
        connection = SimpleNamespace(username=name, retired=False, authenticated=True)
        user = NetworkUser(name, 'es', connection, uuid=account.uuid, approved=True, trust_level=level)
        users[name] = user
        server._users[name] = user
        server._show_main_menu(user)
        user.get_queued_messages()
    yield server, users
    server.db.close()


@pytest.mark.parametrize('name', ['Developer', 'Administrator'])
async def test_staff_can_toggle_forum_and_setting_survives_restart(forum_server, name):
    server, users = forum_server
    actor = users[name]
    server.admin_manager._show_moderation_menu(actor)
    menu = next(packet for packet in actor.get_queued_messages() if packet.get('menu_id') == ADMIN_MODERATION_MENU)
    item = next(row for row in menu['items'] if row['id'] == 'toggle_forum')
    assert not item.get('read_only', False)
    await server.admin_manager._handle_moderation_selection(actor, 'toggle_forum')
    assert not server.forum_enabled
    assert server.db.get_boolean_server_setting('forum_enabled', default=True) is False
    menu = next(packet for packet in actor.get_queued_messages() if packet.get('menu_id') == ADMIN_MODERATION_MENU)
    assert 'Desactivado' in next(row['text'] for row in menu['items'] if row['id'] == 'toggle_forum')
    restarted = Server(db_path=server.db.db_path)
    restarted.db.connect()
    try:
        restarted._load_persistent_server_settings()
        assert not restarted.forum_enabled
    finally:
        restarted.db.close()
    await server.admin_manager._handle_moderation_selection(actor, 'toggle_forum')
    assert server.forum_enabled


@pytest.mark.parametrize('revoked', [False, True])
async def test_unprivileged_or_stale_staff_cannot_change_availability(forum_server, revoked):
    server, users = forum_server
    actor = users['Administrator'] if revoked else users['Reader']
    if revoked:
        server.db.update_user_trust_level(actor.username, 1)
        assert actor.trust_level == 2
    await server.admin_manager._handle_moderation_selection(actor, 'toggle_forum')
    assert server.forum_enabled
    assert any(packet.get('key') == 'not-admin-anymore' for packet in actor.get_queued_messages())


async def test_disabled_forum_stays_visible_and_only_speaks_without_navigation(forum_server):
    server, users = forum_server
    user = users['Reader']
    server.set_forum_enabled(False)
    state = dict(server.user_states[user.username])
    await server._handle_main_menu_selection(user, 'forum')
    assert server.user_states[user.username] == state
    packets = user.get_queued_messages()
    assert [packet['type'] for packet in packets] == ['speak']
    assert packets[0]['key'] == 'forum-unavailable'
    assert 'administradores' in packets[0]['text']


async def test_setting_write_failure_does_not_change_live_availability(forum_server, monkeypatch):
    server, users = forum_server
    def fail_write(*args):
        raise RuntimeError('injected setting write failure')
    monkeypatch.setattr(server.db, 'set_boolean_server_setting', fail_write)
    await server.admin_manager._handle_moderation_selection(users['Administrator'], 'toggle_forum')
    assert server.forum_enabled
    assert any(packet.get('key') == 'forum-availability-update-failed'
               for packet in users['Administrator'].get_queued_messages())


def test_missing_setting_defaults_on_and_invalid_setting_fails_closed(forum_server):
    server, _ = forum_server
    server._load_persistent_server_settings()
    assert server.forum_enabled
    server.db.set_json_server_setting('forum_enabled', 'invalid')
    server._load_persistent_server_settings()
    assert not server.forum_enabled
    with pytest.raises(TypeError):
        server.set_forum_enabled(1)


async def test_closed_forum_keeps_local_draft_but_rejects_publication(forum_server):
    server, users = forum_server
    user = users['Reader']
    manager = server.forum_manager
    await server._handle_main_menu_selection(user, 'forum')
    manager.handle_menu(user, 'category:general', server.user_states[user.username])
    manager.handle_menu(user, 'new_topic', server.user_states[user.username])
    server.set_forum_enabled(False)
    manager.handle_menu(user, 'edit_body', server.user_states[user.username])
    await server._handle_editbox(user._connection, {'type': 'editbox', 'input_id': nav.BODY_INPUT, 'text': 'My retained draft'})
    state = server.user_states[user.username]
    manager.handle_menu(user, 'publish', state)
    assert server.db._conn.execute('SELECT COUNT(*) FROM forum_posts').fetchone()[0] == 0
    assert state['forum_draft']['body'] == 'My retained draft'
    manager.handle_menu(user, 'back', state)
    assert server.user_states[user.username]['menu'] == nav.DISCARD
    manager.handle_menu(user, 'no', server.user_states[user.username])
    assert server.user_states[user.username]['forum_draft']['body'] == 'My retained draft'


@pytest.mark.parametrize('client_type', ['python', 'web'])
async def test_live_control_blocks_stale_actions_and_resumes_after_reenable(tmp_path, client_type):
    server = Server(host='127.0.0.1', port=0, db_path=str(tmp_path / 'socket.db'))
    await server.start()
    try:
        auth = AuthManager(server.db)
        for name in ('Developer', 'Administrator', 'Reader', 'Idle'):
            assert auth.register(name, 'ForumPassword123', locale='es', email=f'{name}@example.test') == 'ok'
            server.db.approve_user(name)
        for name, level in (('Administrator', 2), ('Reader', 1), ('Idle', 1)):
            server.db.update_user_trust_level(name, level)
        port = server._ws_server._server.sockets[0].getsockname()[1]

        async def receive(ws, predicate):
            async with asyncio.timeout(15):
                while True:
                    packet = json.loads(await ws.recv())
                    if predicate(packet):
                        return packet

        async def choose(ws, menu, action, result):
            await ws.send(json.dumps({'type': 'menu', 'menu_id': menu, 'selection_id': action}))
            return await receive(ws, lambda p: p.get('menu_id') == result)

        async with connect(f'ws://127.0.0.1:{port}') as staff, connect(f'ws://127.0.0.1:{port}') as reader, connect(f'ws://127.0.0.1:{port}') as idle:
            for ws, name in ((staff, 'Administrator'), (reader, 'Reader'), (idle, 'Idle')):
                await ws.send(json.dumps({'type': 'authorize', 'username': name, 'password': 'ForumPassword123', 'version': VERSION, 'client': client_type}))
                main = await receive(ws, lambda p: p.get('menu_id') == 'main_menu')
                assert any(row['id'] == 'forum' for row in main['items'])
            await choose(reader, 'main_menu', 'forum', nav.HOME)
            await choose(reader, nav.HOME, 'category:general', nav.TOPICS)
            await choose(reader, nav.TOPICS, 'new_topic', nav.COMPOSER)
            for input_id, action, text in ((nav.TITLE_INPUT, 'edit_title', 'Retained title'), (nav.BODY_INPUT, 'edit_body', 'Retained body')):
                await reader.send(json.dumps({'type': 'menu', 'menu_id': nav.COMPOSER, 'selection_id': action}))
                await receive(reader, lambda p: p.get('input_id') == input_id)
                await reader.send(json.dumps({'type': 'editbox', 'input_id': input_id, 'text': text}))
                await receive(reader, lambda p: p.get('menu_id') == nav.COMPOSER)
            await choose(staff, 'main_menu', 'administration', 'admin_menu')
            await choose(staff, 'admin_menu', 'admin_moderation', ADMIN_SANCTIONS_MENU)
            await choose(staff, ADMIN_SANCTIONS_MENU, 'moderation', ADMIN_MODERATION_MENU)
            await choose(staff, ADMIN_MODERATION_MENU, 'toggle_forum', ADMIN_MODERATION_MENU)
            for ws in (reader, idle):
                await receive(ws, lambda p: p.get('key') == 'forum-unavailable')
            await reader.send(json.dumps({'type': 'menu', 'menu_id': nav.COMPOSER, 'selection_id': 'publish'}))
            await receive(reader, lambda p: p.get('key') == 'forum-unavailable')
            assert server.db._conn.execute('SELECT COUNT(*) FROM forum_posts').fetchone()[0] == 0
            await idle.send(json.dumps({'type': 'menu', 'menu_id': 'main_menu', 'selection_id': 'forum'}))
            await receive(idle, lambda p: p.get('key') == 'forum-unavailable')
            assert server.user_states['Idle']['menu'] == 'main_menu'
            await choose(staff, ADMIN_MODERATION_MENU, 'toggle_forum', ADMIN_MODERATION_MENU)
            published = await choose(reader, nav.COMPOSER, 'publish', nav.POST)
            assert 'Retained body' in str(published)
            await choose(idle, 'main_menu', 'forum', nav.HOME)
    finally:
        await server.stop()
