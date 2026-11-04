"""Exercise free tables through real server menus, transitions, and key events."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from websockets.asyncio.client import connect

import pytest

from ..core.server import (
    HOST_GAME_SWITCH_ACTION_PREFIX,
    HOST_GAME_SWITCH_CONFIRM_MENU,
    HOST_GAME_SWITCH_MENU,
    VERSION,
    TABLE_MEMBERS_MENU,
    Server,
)
from ..auth.auth import AuthManager
from ..games.freetable.game import FreeTable
from ..tables.manager import TableManager
from ..games.registry import GameRegistry
from ..messages.localization import Localization
from ..users.bot import Bot
from ..users.test_user import MockUser


@pytest.fixture
def room():
    server = Server(db_path=":memory:")
    server._db.connect()
    host = MockUser("Host", uuid="host-id", locale="es")
    guest = MockUser("Guest", uuid="guest-id", locale="es")
    server._users = {u.username: u for u in (host, guest)}
    yield server, host, guest
    server._db.close()


async def create_room(server, host):
    server._show_main_menu(host)
    assert "create_free_table" in [i.id for i in host.get_current_menu_items("main_menu")]
    await server._handle_main_menu_selection(host, "create_free_table")
    table = server._tables.find_user_table(host.username)
    assert isinstance(table.game, FreeTable)
    return table


async def switch(server, table, host, target):
    await server._handle_host_game_switch_selection(
        host, HOST_GAME_SWITCH_ACTION_PREFIX + target, {"table_id": table.table_id}
    )
    assert server._user_states[host.username]["menu"] == HOST_GAME_SWITCH_CONFIRM_MENU
    await server._handle_host_game_switch_confirm_selection(
        host, "yes", dict(server._user_states[host.username])
    )
    assert table.game_type == target


@pytest.mark.asyncio
@pytest.mark.parametrize("client_type", ["python", "web", "mobile"])
async def test_free_table_creation_and_conversation_menu(room, client_type):
    server, host, guest = room
    host.client_type = guest.client_type = client_type
    table = await create_room(server, host)
    game = table.game
    server._auto_join_table(guest, table, "freetable")
    game.flush_menus()
    assert len(table.members) == 2
    assert game.status == "waiting" and not game.game_active
    for user in (host, guest):
        ids = [a.action.id for a in game.get_all_visible_actions(game.get_player_by_id(user.uuid))]
        assert "whos_at_table" in ids and "read_table_presence" in ids
        assert "leave_game" in ids
        assert not set(ids) & {"start_game", "add_bot", "remove_bot", "check_scores", "save_table", "whose_turn"}
    player = game.get_player_by_id(host.uuid)
    for action in ("start_game", "add_bot", "remove_bot", "save_table"):
        assert game.find_action(player, action) is None
    before = game.to_json()
    for key in ("enter", "b", "ctrl+s"):
        game.handle_event(player, {"type": "keybind", "key": key})
    assert game.to_json() == before
    with pytest.raises(ValueError, match="only admit people"):
        game.add_player("Bot", Bot("Bot"))
    assert not game._replace_with_bot(player, allow_waiting=True)
    assert not any("waiting-for-players" in s for s in host.get_spoken_messages())


@pytest.mark.asyncio
async def test_switch_both_directions_preserves_social_and_voice_state(room):
    server, host, guest = room
    table = await create_room(server, host)
    server._auto_join_table(guest, table, "freetable")
    table_id = table.table_id
    table.is_private = True
    table.ban_user("banned-id")
    table.set_voice_host_muted(guest.uuid, True)
    table.set_personal_voice_volume(host.uuid, guest.uuid, 40)
    server._voice_presence_by_user[host.username] = {"scope": "table", "context_id": table_id}
    presence = dict(server._voice_presence_by_user)
    await switch(server, table, host, "pig")
    game = table.game
    game.add_player("Robot", Bot("Robot", uuid="bot-id"))
    game.status = "playing"
    game.game_active = True
    game._sync_table_status()
    # The target is available across paginated switch menus.
    names = [cls.get_type() for cls, _ in server._get_localized_game_list(host, include_social=True)]
    assert "freetable" in names
    server._show_host_game_switch_confirm_menu(host, table, "freetable")
    assert "Se retirarán los bots" in " ".join(host.get_spoken_messages())
    await server._handle_host_game_switch_confirm_selection(
        host, "yes", dict(server._user_states[host.username])
    )
    assert isinstance(table.game, FreeTable)
    assert table.table_id == table_id and table.is_private
    assert table.is_banned("banned-id")
    assert table.host == host.username
    assert {p.id for p in table.game.players} == {host.uuid, guest.uuid}
    assert table.is_voice_host_muted(guest.uuid)
    assert table.get_personal_voice_settings(host.uuid, guest.uuid) == (40, False)
    assert server._voice_presence_by_user == presence
    assert game._destroyed and not game._users
    assert table.game.status == "waiting"
    restored = FreeTable.from_json(table.game.to_json())
    assert [(p.id, p.name) for p in restored.players] == [(host.uuid, "Host"), (guest.uuid, "Guest")]


@pytest.mark.asyncio
async def test_only_host_can_switch_and_cancel_keeps_room(room):
    server, host, guest = room
    table = await create_room(server, host)
    server._auto_join_table(guest, table, "freetable")
    game = table.game
    await server._handle_host_game_switch_selection(
        guest, HOST_GAME_SWITCH_ACTION_PREFIX + "pig", {"table_id": table.table_id}
    )
    await server._handle_host_game_switch_confirm_selection(
        guest, "yes", {"table_id": table.table_id, "target_game_type": "pig"}
    )
    assert table.game is game
    server._show_host_game_switch_confirm_menu(host, table, "pig")
    await server._handle_host_game_switch_confirm_selection(
        host, "no", dict(server._user_states[host.username])
    )
    assert table.game is game


@pytest.mark.asyncio
@pytest.mark.parametrize("control", [False, True])
async def test_w_speaks_presence_and_ctrl_w_opens_people_menu(room, control):
    server, host, guest = room
    table = await create_room(server, host)
    server._auto_join_table(guest, table, "freetable")
    guest_player = table.game.get_player_by_id(guest.uuid)
    guest_player.is_spectator = True
    table.members[1].is_spectator = True
    guest.clear_messages()
    await server._handle_keybind(
        SimpleNamespace(username=guest.username), {"type": "keybind", "key": "w", "control": control}
    )
    if control:
        assert server._user_states[guest.username]["menu"] == TABLE_MEMBERS_MENU
    else:
        assert server._user_states[guest.username]["menu"] == "in_game"
        speech = " ".join(guest.get_spoken_messages())
        assert "2 personas" in speech and "Guest" in speech and "Host" in speech
        assert "El jefe de mesa es Host" in speech


@pytest.mark.asyncio
async def test_ctrl_u_still_opens_the_same_people_menu(room):
    server, host, _guest = room
    table = await create_room(server, host)
    await server._handle_keybind(
        SimpleNamespace(username=host.username), {"type": "keybind", "key": "u", "control": True}
    )
    assert server._user_states[host.username]["menu"] == TABLE_MEMBERS_MENU


def test_w_is_reserved_in_every_activity_and_shifted_bindings_remain_available():
    for cls in GameRegistry.get_all(include_social=True):
        game = cls()
        game.setup_keybinds()
        assert all(k.actions == ["read_table_presence"] for k in game._keybinds["w"]), cls.get_type()
        assert game._keybinds["ctrl+w"][0].actions == ["whos_at_table"]
        assert game._keybinds["ctrl+u"][0].actions == ["whos_at_table"]
    for name in ("holdem", "fivecarddraw", "dominos", "deadmanspoker", "coup", "colorgame", "breachpoint", "twentyone"):
        game = GameRegistry.get(name)()
        game.setup_keybinds()
        assert "alt+w" in game._keybinds


@pytest.mark.parametrize("locale", ["en", "es", "vi"])
def test_presence_strings_and_free_table_name_are_localized(locale):
    assert Localization.get(locale, "game-name-freetable") != "game-name-freetable"
    for count in (1, 2):
        message = Localization.get(locale, "table-presence-summary", count=count, people="Alice, Bob", host="Alice")
        assert "Alice" in message and str(count) in message and "$" not in message


@pytest.mark.asyncio
async def test_free_tables_have_separate_entry_and_no_game_preferences(room):
    server, host, _guest = room
    assert "freetable" not in [cls.get_type() for cls, _ in server._get_localized_game_list(host)]
    assert server._get_game_category_counts()["all"] == len([c for c in GameRegistry.get_all() if not c.is_social_activity])
    packets = []
    async def send(packet):
        packets.append(packet)
    await server._send_game_list(SimpleNamespace(send=send))
    assert "freetable" not in [g["type"] for g in packets[0]["games"]]


@pytest.mark.asyncio
async def test_free_table_direct_switch_action_uses_the_game_switch_menu(room):
    server, host, _guest = room
    table = await create_room(server, host)
    player = table.game.get_player_by_id(host.uuid)
    table.game.execute_action(player, "switch_game")
    assert server._user_states[host.username]["menu"] == HOST_GAME_SWITCH_MENU
    assert server._user_states[host.username]["table_id"] == table.table_id


@pytest.mark.asyncio
async def test_free_table_rejects_a_game_with_too_few_seats(room):
    server, host, guest = room
    table = await create_room(server, host)
    server._auto_join_table(guest, table, "freetable")
    third = MockUser("Third", uuid="third-id")
    server._users[third.username] = third
    server._auto_join_table(third, table, "freetable")
    old_game = table.game
    await server._handle_host_game_switch_confirm_selection(
        host, "yes", {"table_id": table.table_id, "target_game_type": "chess"}
    )
    assert table.game is old_game and len(table.members) == 3
    assert "2" in host.get_last_spoken()


@pytest.mark.asyncio
async def test_free_table_passes_host_to_a_person_who_was_spectating(room):
    server, host, guest = room
    table = await create_room(server, host)
    server._auto_join_table(guest, table, "freetable")
    player = table.game.get_player_by_id(guest.uuid)
    player.is_spectator = table.members[1].is_spectator = True
    assert server._is_host_transfer_candidate(
        host, table, next(row for row in server._table_member_rows(table) if row["name"] == guest.username)
    )
    table.game.remove_player(host.uuid)
    table.remove_member(host.username)
    assert not table._destroyed
    assert table.host == table.game.host == guest.username
    guest.clear_messages()
    table.game._action_read_table_presence(player, "read_table_presence")
    assert "1 persona" in guest.get_last_spoken()
    assert "El jefe de mesa es Guest" in guest.get_last_spoken()


@pytest.mark.asyncio
async def test_free_table_recovers_from_a_real_database_checkpoint(room):
    server, host, guest = room
    table = await create_room(server, host)
    server._auto_join_table(guest, table, "freetable")
    table.is_private = True
    table.set_voice_host_muted(guest.uuid, True)
    table.set_personal_voice_volume(host.uuid, guest.uuid, 50)
    server._save_tables(
        checkpoint_kind="planned_reboot",
        checkpoint_expires_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        checkpoint_operation_id="test-free-table-recovery",
    )
    server._tables = TableManager()
    server._tables._server = server
    server._prune_obsolete_game_data()
    server._load_tables()
    restored = server._tables.find_user_table(host.username)
    assert isinstance(restored.game, FreeTable)
    assert restored.table_id == table.table_id and restored.is_private
    assert restored.is_power_restore_grace_active()
    assert restored.is_voice_host_muted(guest.uuid)
    assert restored.get_personal_voice_settings(host.uuid, guest.uuid) == (50, False)
    assert all(not player.is_bot for player in restored.game.players)
    restored.game.attach_user(host.uuid, host)
    restored.add_member(host.username, host)
    server._set_in_game_state(host, restored.table_id)
    restored.clear_power_restore_grace()
    host.clear_messages()
    await server._handle_keybind(
        SimpleNamespace(username=host.username), {"type": "keybind", "key": "w"}
    )
    assert "El jefe de mesa es Host" in host.get_last_spoken()


async def receive(ws, predicate):
    async with asyncio.timeout(12):
        while True:
            packet = json.loads(await ws.recv())
            if predicate(packet):
                return packet


@pytest.mark.asyncio
async def test_free_table_creation_and_bidirectional_switch_over_websocket(tmp_path):
    service = Server(host="127.0.0.1", port=0, db_path=str(tmp_path / "network.db"))
    await service.start()
    try:
        auth = AuthManager(service.db)
        assert auth.register("RoomTester", "RoomPassword123", locale="es", email="room@example.com") == "ok"
        port = service._ws_server._server.sockets[0].getsockname()[1]
        async with connect(f"ws://127.0.0.1:{port}") as ws:
            async def send(packet):
                await ws.send(json.dumps(packet))
            async def menu_choice(menu_id, choice):
                await send({"type": "menu", "menu_id": menu_id, "selection_id": choice})
            await send({"type": "authorize", "client": "web", "version": VERSION,
                        "username": "RoomTester", "password": "RoomPassword123"})
            await receive(ws, lambda p: p.get("menu_id") == "main_menu")
            await menu_choice("main_menu", "create_free_table")
            menu = await receive(ws, lambda p: p.get("menu_id") == "turn_menu")
            assert "start_game" not in [i.get("id") for i in menu["items"]]
            table = service._tables.find_user_table("RoomTester")
            table_id = table.table_id
            await send({"type": "keybind", "key": "w", "menu_id": "turn_menu"})
            speech = await receive(ws, lambda p: "El jefe de mesa es RoomTester" in str(p))
            assert "1 persona" in str(speech)
            await send({"type": "keybind", "key": "w", "control": True, "menu_id": "turn_menu"})
            await receive(ws, lambda p: p.get("menu_id") == TABLE_MEMBERS_MENU)
            await menu_choice(TABLE_MEMBERS_MENU, "back")
            await receive(ws, lambda p: p.get("menu_id") == "turn_menu")
            # Select a real first-page target, then switch back through the host menu.
            await menu_choice("turn_menu", "switch_game")
            choices = await receive(ws, lambda p: p.get("menu_id") == HOST_GAME_SWITCH_MENU)
            target_id = next(i["id"] for i in choices["items"] if i.get("id", "").startswith(HOST_GAME_SWITCH_ACTION_PREFIX))
            await menu_choice(HOST_GAME_SWITCH_MENU, target_id)
            await receive(ws, lambda p: p.get("menu_id") == HOST_GAME_SWITCH_CONFIRM_MENU)
            await menu_choice(HOST_GAME_SWITCH_CONFIRM_MENU, "yes")
            await receive(ws, lambda p: p.get("menu_id") == "turn_menu")
            assert table.game_type != "freetable" and table.table_id == table_id
            await send({"type": "keybind", "key": "m", "control": True, "menu_id": "turn_menu"})
            await receive(ws, lambda p: p.get("menu_id") == "host_management_menu")
            await menu_choice("host_management_menu", "switch_game")
            choices = await receive(ws, lambda p: p.get("menu_id") == HOST_GAME_SWITCH_MENU)
            while HOST_GAME_SWITCH_ACTION_PREFIX + "freetable" not in [i.get("id") for i in choices["items"]]:
                next_page = next(i["id"] for i in choices["items"] if "next" in i.get("id", ""))
                await menu_choice(HOST_GAME_SWITCH_MENU, next_page)
                choices = await receive(ws, lambda p: p.get("menu_id") == HOST_GAME_SWITCH_MENU)
            await menu_choice(HOST_GAME_SWITCH_MENU, HOST_GAME_SWITCH_ACTION_PREFIX + "freetable")
            await receive(ws, lambda p: p.get("menu_id") == HOST_GAME_SWITCH_CONFIRM_MENU)
            await menu_choice(HOST_GAME_SWITCH_CONFIRM_MENU, "yes")
            await receive(ws, lambda p: p.get("menu_id") == "turn_menu")
            assert isinstance(table.game, FreeTable) and table.table_id == table_id
            await send({"type": "logout"})
            await receive(ws, lambda p: p.get("type") == "force_exit")
    finally:
        await service.stop()


@pytest.mark.asyncio
async def test_presence_counts_people_separately_from_bots_and_keeps_voice_context(room):
    server, host, guest = room
    table = await create_room(server, host)
    server._auto_join_table(guest, table, "freetable")
    context = server._resolve_table_voice_context(host, {"context_id": table.table_id})
    assert context.scope == "table" and context.context_id == table.table_id
    await switch(server, table, host, "pig")
    table.game.add_player("Robot", Bot("Robot", uuid="robot-id"))
    host.clear_messages()
    guest.clear_messages()
    table.game.handle_event(table.game.get_player_by_id(host.uuid), {"type": "keybind", "key": "w"})
    speech = host.get_spoken_messages()
    assert "2 personas" in speech[0]
    assert "Robot" not in speech[0]
    assert "Bots en la mesa: Robot" in speech[1]
    assert not guest.get_spoken_messages()
    changed_context = server._resolve_table_voice_context(host, {"context_id": table.table_id})
    assert changed_context.scope == context.scope and changed_context.context_id == context.context_id
