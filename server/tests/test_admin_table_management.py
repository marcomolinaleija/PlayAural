from __future__ import annotations

import pytest

from ..core.server import Server
from ..games.crazyeights.game import CrazyEightsGame
from ..games.freetable.game import FreeTable
from ..users.roles import ADMIN_TRUST_LEVEL, DEVELOPER_TRUST_LEVEL, USER_TRUST_LEVEL
from ..users.test_user import MockUser
from ..game_utils.actions import Visibility


def _make_test_table(game_type: str = "crazyeights"):
    server = Server(db_path=":memory:")
    server._db.connect()

    rec_alice = server._db.create_user("Alice", "hash", trust_level=USER_TRUST_LEVEL)
    server._db.approve_user("Alice")
    rec_bob = server._db.create_user("Bob", "hash", trust_level=USER_TRUST_LEVEL)
    server._db.approve_user("Bob")
    rec_charlie = server._db.create_user("Charlie", "hash", trust_level=USER_TRUST_LEVEL)
    server._db.approve_user("Charlie")

    alice = MockUser("Alice", uuid=rec_alice.uuid)
    bob = MockUser("Bob", uuid=rec_bob.uuid)
    charlie = MockUser("Charlie", uuid=rec_charlie.uuid)
    for u in (alice, bob, charlie):
        u.queue_protocol_packet = lambda packet: None
    server._users = {
        alice.username: alice,
        bob.username: bob,
        charlie.username: charlie,
    }

    table = server._tables.create_table(game_type, alice.username, alice)
    if game_type == "crazyeights":
        game = CrazyEightsGame()
    else:
        game = FreeTable()
    table.game = game
    game._table = table
    server._set_in_game_state(alice, table.table_id)
    game.initialize_lobby(alice.username, alice)

    table.add_member(bob.username, bob)
    game.add_player(bob.username, bob)
    server._set_in_game_state(bob, table.table_id)

    table.add_member(charlie.username, charlie)
    game.add_player(charlie.username, charlie)
    server._set_in_game_state(charlie, table.table_id)

    alice.clear_messages()
    bob.clear_messages()
    charlie.clear_messages()
    return server, table, game, alice, bob, charlie


@pytest.mark.asyncio
async def test_non_host_regular_user_cannot_access_host_management():
    server, table, game, alice, bob, charlie = _make_test_table()
    bob.trust_level = USER_TRUST_LEVEL

    # Regular user tries to open host management menu
    server._open_host_management_from_game(bob, table)
    assert "host_management_menu" not in bob.menus

    # Regular user tries to toggle privacy
    table.is_private = False
    await server._handle_host_management_selection(
        bob, "toggle_privacy", {"table_id": table.table_id}
    )
    assert table.is_private is False

    # Regular user tries to pass host
    assert not server._perform_host_pass(bob, table, "Bob")
    assert table.host == "Alice"

    # Regular user tries to kick player
    assert not server._perform_host_kick(bob, table, "Charlie")
    assert any(m.username == "Charlie" for m in table.members)

    # In table member actions menu, regular user does not see host management actions
    row_charlie = server._resolve_table_member_target(table, "user", "Charlie")
    assert row_charlie is not None
    items = server._get_table_member_action_items(
        bob, table, row_charlie, expected_account_id=charlie.uuid
    )
    action_ids = [item.id for item in items]
    assert "table_kick" not in action_ids
    assert "table_kick_ban" not in action_ids
    assert "table_pass_host" not in action_ids


@pytest.mark.parametrize("trust_level", [ADMIN_TRUST_LEVEL, DEVELOPER_TRUST_LEVEL])
@pytest.mark.asyncio
async def test_admin_and_dev_non_host_can_manage_table(trust_level: int):
    server, table, game, alice, bob, charlie = _make_test_table()
    bob.trust_level = trust_level

    # Admin/Dev can open host management menu
    server._open_host_management_from_game(bob, table)
    assert "host_management_menu" in bob.menus
    menu_item_ids = [item.id for item in bob.menus["host_management_menu"]["items"]]
    assert "toggle_privacy" in menu_item_ids
    assert "pass_host" in menu_item_ids
    assert "kick_player" in menu_item_ids
    assert "switch_game" in menu_item_ids

    # Admin/Dev can toggle privacy
    table.is_private = False
    await server._handle_host_management_selection(
        bob, "toggle_privacy", {"table_id": table.table_id}
    )
    assert table.is_private is True

    # Admin/Dev can pass host to Charlie
    assert server._perform_host_pass(bob, table, "Charlie")
    assert table.host == "Charlie"
    assert game.host == "Charlie"

    # Admin/Dev can kick Charlie
    assert server._perform_host_kick(bob, table, "Charlie", is_ban=False)
    assert not any(m.username == "Charlie" for m in table.members)

    # In table member actions menu, Admin/Dev sees host actions
    row_alice = server._resolve_table_member_target(table, "user", "Alice")
    assert row_alice is not None
    items = server._get_table_member_action_items(
        bob, table, row_alice, expected_account_id=alice.uuid
    )
    action_ids = [item.id for item in items]
    assert "table_kick" in action_ids
    assert "table_kick_ban" in action_ids


@pytest.mark.asyncio
async def test_admin_can_remove_bot_and_moderate_voice():
    server, table, game, alice, bob, charlie = _make_test_table()
    bob.trust_level = ADMIN_TRUST_LEVEL

    # Add a bot to the table
    bot_player = game.create_player("bot_1", "Bot1", is_bot=True)
    game.players.append(bot_player)
    assert any(p.is_bot for p in game.players)

    # Admin can remove the bot
    assert server._perform_remove_table_bot(bob, table, bot_player.id)
    assert not any(p.is_bot for p in game.players)

    # Voice moderation: Admin can host-mute Charlie
    server._voice_presence_by_user["Charlie"] = {
        "scope": "table",
        "table_id": table.table_id,
        "uuid": charlie.uuid,
        "confirmed": True,
    }
    state = {
        "table_id": table.table_id,
        "target_uuid": charlie.uuid,
        "target_name": "Charlie",
    }
    await server._handle_host_voice_target_selection(bob, "toggle_host_voice_mute", state)
    assert table.is_voice_host_muted(charlie.uuid) is True

    # And unmute
    await server._handle_host_voice_target_selection(bob, "toggle_host_voice_mute", state)
    assert table.is_voice_host_muted(charlie.uuid) is False


@pytest.mark.asyncio
async def test_free_table_admin_powers():
    server, table, game, alice, bob, charlie = _make_test_table(game_type="freetable")
    bob.trust_level = ADMIN_TRUST_LEVEL
    charlie.trust_level = USER_TRUST_LEVEL

    p_bob = game.get_player_by_name("Bob")
    p_charlie = game.get_player_by_name("Charlie")

    # FreeTable visibility and actions
    assert game._is_host_management_hidden(p_bob) == Visibility.VISIBLE
    assert game._is_host_management_enabled(p_bob) is None

    assert game._is_host_management_hidden(p_charlie) == Visibility.HIDDEN
    assert game._is_host_management_enabled(p_charlie) == "action-not-host"

    # Admin can trigger _action_switch_game
    game._action_switch_game(p_bob, "switch_game")
    assert "host_game_switch_menu" in bob.menus


def test_lobby_actions_enabled_for_admin():
    server, table, game, alice, bob, charlie = _make_test_table()
    bob.trust_level = ADMIN_TRUST_LEVEL
    charlie.trust_level = USER_TRUST_LEVEL

    p_bob = game.get_player_by_name("Bob")
    p_charlie = game.get_player_by_name("Charlie")

    assert game._is_start_game_enabled(p_bob) is None
    assert game._is_start_game_enabled(p_charlie) == "action-not-host"

    assert game._is_option_enabled(p_bob) is None
    assert game._is_option_enabled(p_charlie) == "action-not-host"

    assert game._is_save_table_enabled(p_bob) is None
    assert game._is_save_table_enabled(p_charlie) == "action-not-host"


@pytest.mark.asyncio
async def test_leave_game_keybind_q_and_ctrl_q():
    server, table, game, alice, bob, charlie = _make_test_table()

    # Alice presses 'q' to leave table
    await server._handle_keybind(alice, {"type": "keybind", "key": "q"})
    assert "leave_game_confirm" in alice.menus

    # Bob presses 'ctrl+q' to leave table (backwards compatibility)
    await server._handle_keybind(bob, {"type": "keybind", "key": "ctrl+q"})
    assert "leave_game_confirm" in bob.menus


@pytest.mark.asyncio
async def test_ctrl_p_toggles_privacy_for_host_and_admin():
    server, table, game, alice, bob, charlie = _make_test_table()
    bob.trust_level = ADMIN_TRUST_LEVEL
    charlie.trust_level = USER_TRUST_LEVEL

    assert table.is_private is False

    # Alice (host) presses 'ctrl+p' to toggle privacy
    await server._handle_keybind(alice, {"type": "keybind", "key": "ctrl+p"})
    assert table.is_private is True

    # Charlie (regular non-host) presses 'ctrl+p' -> rejected
    await server._handle_keybind(charlie, {"type": "keybind", "key": "ctrl+p"})
    assert table.is_private is True

    # Bob (Admin non-host) presses 'ctrl+p' -> toggles back to public
    await server._handle_keybind(bob, {"type": "keybind", "key": "ctrl+p"})
    assert table.is_private is False


@pytest.mark.asyncio
async def test_freetable_keybinds_q_and_ctrl_p():
    server, table, game, alice, bob, charlie = _make_test_table(game_type="freetable")
    bob.trust_level = ADMIN_TRUST_LEVEL

    # 'q' leaves table in FreeTable
    await server._handle_keybind(alice, {"type": "keybind", "key": "q"})
    assert "leave_game_confirm" in alice.menus

    # 'ctrl+p' toggles privacy in FreeTable
    assert table.is_private is False
    await server._handle_keybind(bob, {"type": "keybind", "key": "ctrl+p"})
    assert table.is_private is True

