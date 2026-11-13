"""Official rules follow the forum language and return to their fixed entry."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from websockets.asyncio.client import connect

from ..auth.auth import AuthManager
from ..core.server import Server, VERSION
from ..documentation.manager import DocumentationManager
from ..forum import navigation as nav
from ..forum.languages import FORUM_LANGUAGES
from ..messages.localization import Localization
from ..users.network_user import NetworkUser


@pytest.fixture
def forum(tmp_path):
    server = Server(db_path=str(tmp_path / 'rules.db'))
    server.db.connect()
    account = server.db.create_user('Reader', 'hash', locale='es')
    server.db.approve_user('Reader')
    server.db.update_user_trust_level('Reader', 1)
    connection = SimpleNamespace(username='Reader', retired=False, authenticated=True)
    user = NetworkUser('Reader', 'es', connection, uuid=account.uuid, approved=True, trust_level=1)
    server._users[user.username] = user
    server._show_main_menu(user)
    user.get_queued_messages()
    yield server, user
    server.db.close()


async def choose(server, user, menu, selection):
    await server._handle_menu(user._connection, {
        'type': 'menu', 'menu_id': menu, 'selection_id': selection,
    })
    return user.get_queued_messages()


@pytest.mark.parametrize('language', FORUM_LANGUAGES)
async def test_rules_use_community_language_and_restore_focus_without_creating_topics(forum, language):
    server, user = forum
    manager = server.forum_manager
    manager.service.languages.select(user.uuid, language)
    server._nav_push(user, manager.home)
    home = next(p for p in user.get_queued_messages() if p.get('menu_id') == nav.HOME)
    assert home['items'][2]['id'] == 'community_rules'
    assert home['items'][2]['text'] == Localization.get(language, 'community-rules')

    packets = await choose(server, user, nav.HOME, 'community_rules')
    document = next(p for p in packets if p.get('menu_id') == 'doc_viewer')
    docs = DocumentationManager.get_instance()
    # Read the exact translation, rather than silently accepting a fallback.
    source = (docs.base_path / language / 'community_rules.md').read_text(encoding='utf-8')
    assert [row['text'] for row in document['items'][:-1]] == docs.render_markdown_lines(source)
    assert all(row['read_only'] for row in document['items'][:-1])
    assert document['items'][-1]['id'] == 'back'
    assert user.locale == 'es'
    state = server._user_states[user.username]
    assert state['doc_locale'] == language

    # Restoring a viewer must retain its language even when the interface changes.
    user.set_locale('vi')
    server._restore_frame(user, dict(state), list(state['_stack']))
    restored = next(p for p in user.get_queued_messages() if p.get('menu_id') == 'doc_viewer')
    assert restored['items'][:-1] == document['items'][:-1]
    back = await choose(server, user, 'doc_viewer', 'back')
    home = next(p for p in back if p.get('menu_id') == nav.HOME)
    assert home['selection_id'] == 'community_rules'
    assert server._user_states[user.username]['forum_language'] == language
    assert manager.service.languages.current(user.uuid) == language
    assert server.db._conn.execute('SELECT COUNT(*) FROM forum_topics').fetchone()[0] == 0
    assert server.db._conn.execute('SELECT COUNT(*) FROM forum_posts').fetchone()[0] == 0


async def test_rules_remain_available_when_the_community_has_no_subforums(forum):
    server, user = forum
    manager = server.forum_manager
    with server.db._transaction() as cursor:
        cursor.execute("DELETE FROM forum_categories WHERE language = 'es'")
    server._nav_push(user, manager.home)
    home = next(p for p in user.get_queued_messages() if p.get('menu_id') == nav.HOME)
    assert not any(row['id'].startswith('category:') for row in home['items'])
    assert home['items'][2]['id'] == 'community_rules'
    packets = await choose(server, user, nav.HOME, 'community_rules')
    assert any(p.get('menu_id') == 'doc_viewer' for p in packets)


@pytest.mark.parametrize('gate', ['disabled', 'unapproved'])
async def test_rules_entry_rechecks_forum_availability_and_account_access(forum, gate):
    server, user = forum
    server._nav_push(user, server.forum_manager.home)
    user.get_queued_messages()
    if gate == 'disabled':
        server.set_forum_enabled(False)
    else:
        with server.db._transaction() as cursor:
            cursor.execute('UPDATE users SET approved = 0 WHERE uuid = ?', (user.uuid,))
    packets = await choose(server, user, nav.HOME, 'community_rules')
    assert not any(p.get('menu_id') == 'doc_viewer' for p in packets)
    key = 'forum-unavailable' if gate == 'disabled' else 'forum-error-account'
    assert any(p.get('key') == key for p in packets)


@pytest.mark.parametrize('client_type', ['python', 'web', 'mobile'])
async def test_rules_and_language_switch_over_real_websocket(tmp_path, client_type):
    server = Server(host='127.0.0.1', port=0, db_path=str(tmp_path / 'rules-socket.db'))
    await server.start()
    try:
        server.db.create_user('Staff', 'hash', locale='es', trust_level=3, approved=True)
        auth = AuthManager(server.db)
        assert auth.register('Reader', 'RulesPassword123', locale='es', email='reader@example.test') == 'ok'
        server.db.approve_user('Reader')
        server.db.update_user_trust_level('Reader', 1)
        port = server._ws_server._server.sockets[0].getsockname()[1]

        async def receive(ws, menu):
            async with asyncio.timeout(15):
                while True:
                    packet = json.loads(await ws.recv())
                    if packet.get('menu_id') == menu:
                        return packet

        async def select(ws, menu, selection, result):
            await ws.send(json.dumps({'type': 'menu', 'menu_id': menu, 'selection_id': selection}))
            return await receive(ws, result)

        async with connect(f'ws://127.0.0.1:{port}') as ws:
            await ws.send(json.dumps({'type': 'authorize', 'client': client_type, 'version': VERSION,
                                     'username': 'Reader', 'password': 'RulesPassword123'}))
            await receive(ws, 'main_menu')
            await select(ws, 'main_menu', 'forum', nav.HOME)
            for language, heading in (('en', 'Community Rules'), ('es', 'Normas de la comunidad')):
                await select(ws, nav.HOME, 'language', nav.LANGUAGES)
                home = await select(ws, nav.LANGUAGES, 'language:' + language, nav.HOME)
                assert home['items'][2]['text'] == heading
                document = await select(ws, nav.HOME, 'community_rules', 'doc_viewer')
                assert document['items'][0]['text'] == heading
                assert all(row['read_only'] for row in document['items'][:-1])
                home = await select(ws, 'doc_viewer', 'back', nav.HOME)
                assert home['selection_id'] == 'community_rules'
            assert server.db.get_user('Reader').locale == 'es'
    finally:
        await server.stop()
