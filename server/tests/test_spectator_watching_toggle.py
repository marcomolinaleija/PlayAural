"""Unit and integration tests for spectator and eliminated player watching toggling.

Requirements:
- When entering a table with a game in progress:
  - Voice announces that a game is in progress ("table-game-in-progress").
  - User starts in non-watching mode (no dialogs, no complex menus).
  - Turn menu presents a single item to watch.
  - Game speech (buffer="game") and game sounds are muted for this user.
  - Pressing Enter starts watching ("enter te permite ver").
  - Pressing Escape exits the table ("escape solo sale").
- When watching as a spectator or an eliminated player:
  - Pressing Escape exits watching mode ("escape sale de ver").
  - In non-watching mode, pressing Enter watches again ("enter entra de nuevo").
  - In non-watching mode, pressing Escape exits the table ("escape solo sale").
"""

import pytest

from ..core.server import Server
from ..games.freetable.game import FreeTable
from ..users.test_user import MockUser


@pytest.fixture
def table_fixture():
    server = Server(db_path=":memory:")
    server._db.connect()
    host = MockUser("Host", uuid="host-id", locale="es")
    guest = MockUser("Guest", uuid="guest-id", locale="es")
    server._users = {host.username: host, guest.username: guest}

    # Host creates a table with game initialized
    table = server._tables.create_table("freetable", host.username, host)
    game = FreeTable()
    table.game = game
    game._table = table
    server._set_in_game_state(host, table.table_id)
    game.initialize_lobby(host.username, host)

    yield server, table, host, guest
    server._db.close()


def test_enter_table_with_game_in_progress_announces_and_waits_for_enter(table_fixture):
    server, table, host, guest = table_fixture
    game = table.game
    # Start game so status is "playing"
    game.status = "playing"

    # Guest joins table
    server._auto_join_table(guest, table, "freetable")

    guest_player = game.get_player_by_id(guest.uuid)
    assert guest_player is not None
    assert guest_player.is_spectator is True
    assert guest_player.is_watching is False

    # Voice announces game in progress
    spoken = guest.get_spoken_messages()
    assert any("Partida en curso" in msg for msg in spoken)

    # Menu has single item with watch_game id
    menu = guest.menus.get("turn_menu")
    assert menu is not None
    assert len(menu["items"]) == 1
    item = menu["items"][0]
    assert item.id == "watch_game"
    assert "Partida en curso" in item.text

    # Game buffer messages and sounds are muted for non-watching spectator
    guest.clear_messages()
    game.broadcast_l("game-round-start", buffer="game", round=1)
    game.broadcast("A card was played", buffer="game")
    assert guest.get_spoken_messages() == []


def test_enter_key_starts_watching(table_fixture):
    server, table, host, guest = table_fixture
    game = table.game
    game.status = "playing"

    server._auto_join_table(guest, table, "freetable")
    guest_player = game.get_player_by_id(guest.uuid)
    assert guest_player.is_watching is False

    # Guest presses enter to start watching
    guest.clear_messages()
    game.handle_event(guest_player, {"type": "keybind", "key": "enter"})

    assert guest_player.is_watching is True
    spoken = guest.get_spoken_messages()
    assert any("Viendo la partida" in msg for msg in spoken)

    # Game messages are now received
    guest.clear_messages()
    game.broadcast("Public test play", buffer="game")
    assert "Public test play" in guest.get_spoken_messages()


def test_menu_activation_starts_watching(table_fixture):
    server, table, host, guest = table_fixture
    game = table.game
    game.status = "playing"

    server._auto_join_table(guest, table, "freetable")
    guest_player = game.get_player_by_id(guest.uuid)

    guest.clear_messages()
    game.handle_event(
        guest_player,
        {"type": "menu", "menu_id": "turn_menu", "selection_id": "watch_game"},
    )

    assert guest_player.is_watching is True
    assert any("Viendo la partida" in msg for msg in guest.get_spoken_messages())


def test_escape_exits_table_when_not_watching(table_fixture):
    server, table, host, guest = table_fixture
    game = table.game
    game.status = "playing"

    server._auto_join_table(guest, table, "freetable")
    guest_player = game.get_player_by_id(guest.uuid)
    assert guest_player.is_watching is False

    # Pressing escape while not watching leaves the table immediately
    game.handle_event(guest_player, {"type": "keybind", "key": "escape"})
    assert not any(m.username == guest.username for m in table.members)
    assert game.get_player_by_id(guest.uuid) is None


def test_spectator_escape_stops_watching_and_enter_resumes(table_fixture):
    server, table, host, guest = table_fixture
    game = table.game
    game.status = "playing"

    server._auto_join_table(guest, table, "freetable")
    guest_player = game.get_player_by_id(guest.uuid)

    # Start watching
    game.handle_event(guest_player, {"type": "keybind", "key": "enter"})
    assert guest_player.is_watching is True

    # Press escape to stop watching ("escape sale de ver")
    guest.clear_messages()
    game.handle_event(guest_player, {"type": "keybind", "key": "escape"})

    assert guest_player.is_watching is False
    assert any("Has dejado de ver la partida" in msg for msg in guest.get_spoken_messages())

    # Game messages are muted again
    guest.clear_messages()
    game.broadcast("Secret move", buffer="game")
    assert guest.get_spoken_messages() == []

    # Press enter to watch again ("enter entra de nuevo")
    guest.clear_messages()
    game.handle_event(guest_player, {"type": "keybind", "key": "enter"})
    assert guest_player.is_watching is True
    assert any("Viendo la partida" in msg for msg in guest.get_spoken_messages())

    # Stop watching again, then escape to exit table ("escape solo sale")
    game.handle_event(guest_player, {"type": "keybind", "key": "escape"})
    assert guest_player.is_watching is False
    game.handle_event(guest_player, {"type": "keybind", "key": "escape"})
    assert not any(m.username == guest.username for m in table.members)


def test_eliminated_player_escape_stops_watching_and_enter_resumes(table_fixture):
    server, table, host, guest = table_fixture
    game = table.game
    # Both join before match starts
    server._auto_join_table(guest, table, "freetable")
    host_player = game.get_player_by_id(host.uuid)
    guest_player = game.get_player_by_id(guest.uuid)
    assert guest_player.is_spectator is False

    # Start match
    game.status = "playing"
    assert guest_player.is_watching is True

    # Guest gets eliminated
    guest_player.eliminated = True
    assert game.is_player_eliminated(guest_player) is True

    # Guest presses escape to stop watching ("escape sale de ver")
    guest.clear_messages()
    game.handle_event(guest_player, {"type": "keybind", "key": "escape"})

    assert guest_player.is_watching is False
    assert any("Has dejado de ver la partida" in msg for msg in guest.get_spoken_messages())

    # Game messages are muted
    guest.clear_messages()
    game.broadcast("Round 2 announcement", buffer="game")
    assert guest.get_spoken_messages() == []

    # Guest presses enter to resume watching ("enter entra de nuevo")
    guest.clear_messages()
    game.handle_event(guest_player, {"type": "keybind", "key": "enter"})
    assert guest_player.is_watching is True
    assert any("Viendo la partida" in msg for msg in guest.get_spoken_messages())

    # Guest hears messages again
    guest.clear_messages()
    game.broadcast("Round 3 announcement", buffer="game")
    assert "Round 3 announcement" in guest.get_spoken_messages()
