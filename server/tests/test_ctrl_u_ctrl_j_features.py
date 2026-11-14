import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from ..core.server import Server
from ..games.pig.game import PigGame
from ..messages.localization import Localization
from ..users.network_user import NetworkUser
from ..users.test_user import MockUser
from ..tables.manager import TableManager


class DummyClient:
    def __init__(self, username: str):
        self.username = username
        self.sent_packets = []

    async def send(self, packet):
        self.sent_packets.append(packet)


def _create_test_table(server, host_user, is_private=False):
    table = server._tables.create_table("pig", host_user.username, host_user)
    table.is_private = is_private
    game = PigGame()
    table.game = game
    game._table = table
    game.initialize_lobby(host_user.username, host_user)
    return table


@pytest.fixture
def test_server(tmp_path):
    Localization.init(Path(__file__).resolve().parents[1] / "locales")
    server = Server(
        db_path=str(tmp_path / "ctrl_features.db"),
        locales_dir=Path(__file__).resolve().parents[1] / "locales",
    )
    server._db.connect()

    users = {}
    for name in ("Host", "Player", "Friend", "Stranger", "Admin"):
        trust = 100 if name == "Admin" else 1
        record = server._db.create_user(name, "hash", approved=True, trust_level=trust)
        u = MockUser(name, locale="es", uuid=record.uuid)
        u._trust_level = trust
        server._users[name] = u
        users[name] = u

    # Make Host and Friend actual friends
    server._db.send_friend_request(users["Host"].uuid, users["Friend"].uuid)
    server._db.accept_friend_request(users["Host"].uuid, users["Friend"].uuid)

    try:
        yield server, users
    finally:
        server._db.close()


@pytest.mark.asyncio
async def test_ctrl_u_opens_online_users_menu(test_server):
    server, users = test_server
    player = users["Player"]
    client = DummyClient(player.username)

    # Send keybind Ctrl+U
    await server._handle_keybind(client, {"key": "u", "control": True, "alt": False})

    state = server._user_states.get(player.username, {})
    assert state.get("menu") == "online_users"
    assert "online_users" in player.menus


@pytest.mark.asyncio
async def test_ctrl_j_joins_public_table_of_non_friend(test_server):
    server, users = test_server
    host = users["Host"]
    stranger = users["Stranger"]
    client = DummyClient(stranger.username)

    # Host creates a public table with game
    table = _create_test_table(server, host, is_private=False)

    # Stranger opens online_users menu and focuses host
    server._show_online_users_menu(stranger)
    items = stranger.menus["online_users"]["items"]
    host_item_idx = next(i for i, item in enumerate(items) if f"online_{host.username}" in item.id)

    # Press Ctrl+J on Host item
    await server._handle_keybind(
        client,
        {
            "key": "j",
            "control": True,
            "alt": False,
            "menu_id": "online_users",
            "menu_index": host_item_idx + 1,
            "menu_item_id": items[host_item_idx].id,
        },
    )

    # Stranger should now be in the table!
    assert server._tables.find_user_table(stranger.username) == table


@pytest.mark.asyncio
async def test_ctrl_j_joins_from_friends_list(test_server):
    server, users = test_server
    host = users["Host"]
    friend = users["Friend"]
    client = DummyClient(friend.username)

    table = _create_test_table(server, host, is_private=False)

    server._show_friends_list_menu(friend)
    items = friend.menus["friends_list_menu"]["items"]
    host_item_idx = next(i for i, item in enumerate(items) if f"friend_{host.username}" in item.id)

    await server._handle_keybind(
        client,
        {
            "key": "j",
            "control": True,
            "alt": False,
            "menu_id": "friends_list_menu",
            "menu_index": host_item_idx + 1,
            "menu_item_id": items[host_item_idx].id,
        },
    )

    assert server._tables.find_user_table(friend.username) == table


@pytest.mark.asyncio
async def test_ctrl_j_private_table_blocked(test_server):
    server, users = test_server
    host = users["Host"]
    stranger = users["Stranger"]
    client = DummyClient(stranger.username)

    # Host creates a private table
    table = _create_test_table(server, host, is_private=True)

    server._show_online_users_menu(stranger)
    items = stranger.menus["online_users"]["items"]
    host_item_idx = next(i for i, item in enumerate(items) if f"online_{host.username}" in item.id)

    stranger.clear_messages()
    await server._handle_keybind(
        client,
        {
            "key": "j",
            "control": True,
            "alt": False,
            "menu_id": "online_users",
            "menu_index": host_item_idx + 1,
            "menu_item_id": items[host_item_idx].id,
        },
    )

    # Should NOT be in table
    assert server._tables.find_user_table(stranger.username) is None
    # Spoke private message
    spoken_texts = [m.data.get("text", "") for m in stranger.messages if m.type == "speak"]
    assert any("privada" in t for t in spoken_texts)


@pytest.mark.asyncio
async def test_ctrl_j_target_not_in_table(test_server):
    server, users = test_server
    host = users["Host"]
    stranger = users["Stranger"]
    client = DummyClient(stranger.username)

    # Host is not in any table
    server._show_online_users_menu(stranger)
    items = stranger.menus["online_users"]["items"]
    host_item_idx = next(i for i, item in enumerate(items) if f"online_{host.username}" in item.id)

    stranger.clear_messages()
    await server._handle_keybind(
        client,
        {
            "key": "j",
            "control": True,
            "alt": False,
            "menu_id": "online_users",
            "menu_index": host_item_idx + 1,
            "menu_item_id": items[host_item_idx].id,
        },
    )

    spoken_texts = [m.data.get("text", "") for m in stranger.messages if m.type == "speak"]
    assert any("no está en ninguna mesa" in t for t in spoken_texts)


@pytest.mark.asyncio
async def test_inviting_non_friend_to_table(test_server):
    server, users = test_server
    host = users["Host"]
    stranger = users["Stranger"]

    table = _create_test_table(server, host, is_private=False)

    # Check that stranger is in invitable users list for host
    invitable = server._get_invitable_friends(host, table)
    assert stranger.username in invitable

    # Host sends table invite to stranger
    sent = await server._send_table_invite(host, table, stranger)
    assert sent is True
    assert stranger.username in server._pending_invites


@pytest.mark.asyncio
async def test_profile_privacy_configuration_and_permissions(test_server):
    server, users = test_server
    host = users["Host"]
    friend = users["Friend"]
    stranger = users["Stranger"]
    admin = users["Admin"]

    # 1. Host changes profile privacy to friends
    host.preferences.profile_privacy = "friends"
    server._save_user_preferences(host)

    # Friend checks profile -> allowed
    can_view, _ = server._can_view_profile(friend, server._db.get_user(host.username))
    assert can_view is True

    # Stranger checks profile -> denied with profile-view-friends-only
    can_view, err = server._can_view_profile(stranger, server._db.get_user(host.username))
    assert can_view is False
    assert err == "profile-view-friends-only"

    # Admin checks profile -> allowed
    can_view, _ = server._can_view_profile(admin, server._db.get_user(host.username))
    assert can_view is True

    # 2. Host changes profile privacy to private
    host.preferences.profile_privacy = "private"
    server._save_user_preferences(host)

    # Friend checks profile -> denied with profile-view-private
    can_view, err = server._can_view_profile(friend, server._db.get_user(host.username))
    assert can_view is False
    assert err == "profile-view-private"

    # Host checks own profile -> allowed
    can_view, _ = server._can_view_profile(host, server._db.get_user(host.username))
    assert can_view is True

    # Admin checks profile -> allowed
    can_view, _ = server._can_view_profile(admin, server._db.get_user(host.username))
    assert can_view is True
