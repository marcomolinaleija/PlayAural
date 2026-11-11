"""Global forum navigation preserves modals, return context and pinned views."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ..core.server import Server
from ..forum import navigation as nav
from ..forum.languages import FORUM_LANGUAGES
from ..forum.models import Draft
from ..games.pig.game import PigGame
from ..users.network_user import NetworkUser

CHORD = {'type':'keybind','key':'f','control':True,'shift':True,'alt':False,'meta':False}


@pytest.fixture
def forum(tmp_path):
    server = Server(db_path=str(tmp_path / 'shortcut.db'))
    server.db.connect()
    users = {}
    for name in ('Player', 'Guest'):
        account = server.db.create_user(name, 'hash', locale='es')
        server.db.approve_user(name)
        client = SimpleNamespace(username=name, retired=False, authenticated=True)
        user = NetworkUser(name, 'es', client, uuid=account.uuid, approved=True)
        server._users[name] = users[name] = user
        server._show_main_menu(user)
        user.get_queued_messages()
    yield server, users
    server.db.close()


async def test_shortcut_opens_home_and_repeated_chord_does_not_duplicate_stack(forum):
    server, users = forum
    user = users['Player']
    await server._handle_keybind(user._connection, CHORD)
    state = server._user_states[user.username]
    assert state['menu'] == nav.HOME
    stack = list(state['_stack'])
    await server._handle_keybind(user._connection, CHORD)
    assert server._user_states[user.username]['_stack'] == stack
    server._nav_back(user)
    assert server._user_states[user.username]['menu'] == 'main_menu'


def test_pinned_views_always_precede_language_subforums(forum):
    server, users = forum
    user = users['Player']
    for language in FORUM_LANGUAGES:
        server.forum_manager.views.home(user, language)
        packet = next(p for p in user.get_queued_messages() if p.get('menu_id') == nav.HOME)
        ids = [row['id'] for row in packet['items']]
        assert ids[:2] == ['private', 'recent']
        assert all(key.startswith('category:') for key in ids[2:5])
        assert ids[5:8] == ['unread', 'saved', 'search']
        assert ids.count('private') == ids.count('recent') == 1
        assert ids[-2:] == ['language', 'back']


async def test_disabled_forum_shortcut_only_announces(forum):
    server, users = forum
    user = users['Player']
    before = dict(server._user_states[user.username])
    server.set_forum_enabled(False)
    await server._handle_keybind(user._connection, CHORD)
    assert server._user_states[user.username] == before
    packets = user.get_queued_messages()
    assert any(p.get('key') == 'forum-unavailable' for p in packets)
    assert not any(p.get('menu_id') == nav.HOME for p in packets)


async def test_shortcut_never_discards_open_input_or_existing_composer(forum):
    server, users = forum
    user = users['Player']
    manager = server.forum_manager
    server._nav_push(user, manager.composer.show, Draft('topic', category_id='general', title='Kept', body='Draft'))
    manager.handle_menu(user, 'edit_body', server._user_states[user.username])
    state = server._user_states[user.username]
    await server._handle_keybind(user._connection, CHORD)
    assert server._user_states[user.username] is state and state['menu'] == nav.BODY_INPUT
    await server._handle_editbox(user._connection, {'type':'editbox','input_id':nav.BODY_INPUT,'cancelled':True})
    await server._handle_keybind(user._connection, CHORD)
    assert server._user_states[user.username]['menu'] == nav.HOME
    server._nav_back(user)
    assert server._user_states[user.username]['menu'] == nav.COMPOSER
    assert server._user_states[user.username]['forum_draft']['body'] == 'Draft'


@pytest.mark.parametrize('menu', ['motd_menu', 'mandatory_email_menu', 'banned_menu'])
async def test_shortcut_respects_required_system_screens(forum, menu):
    server, users = forum
    user = users['Player']
    server._user_states[user.username] = {'menu':menu}
    await server._handle_keybind(user._connection, CHORD)
    assert server._user_states[user.username]['menu'] == menu


async def test_game_shortcut_keeps_table_and_does_not_dispatch_game_action(forum):
    server, users = forum
    user, guest = users['Player'], users['Guest']
    table = server._tables.create_table('pig', user.username, user)
    game = PigGame()
    table.game = game
    game._table = table
    game.initialize_lobby(user.username, user)
    table.add_member(guest.username, guest, as_spectator=False)
    game.add_player(guest.username, guest)
    game.on_start()
    server._user_states[user.username] = {'menu':'in_game','table_id':table.table_id}
    game.handle_event = Mock()
    await server._handle_keybind(user._connection, CHORD)
    assert server._user_states[user.username]['menu'] == nav.HOME
    assert server._tables.find_user_table(user.username) is table
    game.handle_event.assert_not_called()
    server._nav_back(user)
    assert server._user_states[user.username]['menu'] == 'in_game'


@pytest.mark.parametrize('change', [{'shift':False}, {'control':False}, {'alt':True}, {'meta':True}])
async def test_only_exact_chord_opens_forum(forum, change):
    server, users = forum
    user = users['Player']
    await server._handle_keybind(user._connection, {**CHORD, **change})
    assert server._user_states[user.username]['menu'] == 'main_menu'
