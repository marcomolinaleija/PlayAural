"""Tests for the table-level wager/pot betting system."""

from dataclasses import dataclass, field
from pathlib import Path
import tempfile
import pytest
from unittest import mock
from unittest.mock import MagicMock

from server.core.server import Server, HOST_TABLE_BET_MENU
from server.persistence.database import Database
from server.tables.table import Table, TableMember
from server.game_utils.game_result import GameResult, PlayerResult
from server.games.loteria.game import LoteriaGame


def make_user(username: str, uuid: str, locale: str = "es"):
    user = MagicMock()
    user.username = username
    user.uuid = uuid
    user.locale = locale
    user.is_bot = False
    user.trust_level = 1
    return user


@pytest.fixture
def temp_db(tmp_path):
    db_file = tmp_path / "test_betting.db"
    db = Database(str(db_file))
    db.connect()
    yield db
    db.close()


def test_table_bet_defaults():
    table = Table(table_id="tbl1", game_type="loteria", host="host_user")
    assert table.bet == 0
    assert table.pot == 0
    assert len(table._pot_contributors) == 0


def test_table_set_bet():
    table = Table(table_id="tbl1", game_type="loteria", host="host_user")
    assert table.set_bet(50) is True
    assert table.bet == 50
    assert table.set_bet(0) is True
    assert table.bet == 0
    # Negative or non-int fails
    assert table.set_bet(-10) is False
    assert table.set_bet("abc") is False
    assert table.bet == 0

    # Cannot set bet if game is already playing
    table.status = "playing"
    assert table.set_bet(100) is False
    assert table.bet == 0


def test_table_bet_save_and_checkpoint_serialization():
    table = Table(table_id="tbl1", game_type="loteria", host="host_user")
    table.set_bet(75)
    table.pot = 150
    table._pot_contributors.add("uuid-123")

    # User manual save (include_checkpoint_state=False): bet and pot are runtime-only
    saved_json = table.serialize_saved_state(include_checkpoint_state=False)
    restored_data = Table.deserialize_saved_state(saved_json, include_checkpoint_state=False)
    assert "bet" not in restored_data
    assert "pot" not in restored_data

    # Checkpoint (include_checkpoint_state=True): bet, pot and contributors are preserved
    checkpoint_json = table.serialize_saved_state(include_checkpoint_state=True)
    cp_data = Table.deserialize_saved_state(checkpoint_json, include_checkpoint_state=True)
    assert cp_data["bet"] == 75
    assert cp_data["pot"] == 150
    assert cp_data["_pot_contributors"] == {"uuid-123"}


@pytest.mark.asyncio
async def test_host_management_set_table_bet_ui(temp_db):
    server = Server(db_path=temp_db.db_path)
    server._db = temp_db

    host_acc = temp_db.create_user("HostPlayer", "hash")
    host_user = make_user("HostPlayer", host_acc.uuid)

    table = Table(table_id="tbl10", game_type="loteria", host="HostPlayer")
    table._server = server
    table._db = temp_db
    table.add_member("HostPlayer", host_user, as_spectator=False)
    server._tables._tables["tbl10"] = table

    # Push host management then bet menu on navigation stack
    server._nav_push(host_user, server._show_host_management_menu, table)
    server._nav_push(host_user, server._show_table_bet_menu, table)

    # Show bet menu
    server._show_table_bet_menu(host_user, table)
    host_user.show_menu.assert_called()
    menu_id, items = host_user.show_menu.call_args[0][:2]
    assert menu_id == HOST_TABLE_BET_MENU
    assert any(item.id == "bet_50" for item in items)

    # Host selects bet 50 (host has 250 initial coins)
    state = server._user_states[host_user.username]
    await server._handle_table_bet_selection(host_user, "bet_50", state)
    assert table.bet == 50

    # Host tries to select bet 500 (host only has 250 coins)
    await server._handle_table_bet_selection(host_user, "bet_500", state)
    # Bet remains 50 because host cannot afford 500
    assert table.bet == 50
    host_user.speak_l.assert_called_with(
        "table-error-host-cannot-afford-bet",
        buffer="system",
        coins=250,
        required=500,
    )


def test_insufficient_coins_blocks_start_and_spectator_toggle(temp_db):
    p1 = temp_db.create_user("RichPlayer", "hash")
    p2 = temp_db.create_user("PoorPlayer", "hash")

    # Set PoorPlayer's balance to 10 coins
    temp_db.adjust_wallet_balance(p2.uuid, -240)

    u1 = make_user("RichPlayer", p1.uuid)
    u2 = make_user("PoorPlayer", p2.uuid)

    game = LoteriaGame()
    table = Table(table_id="tbl20", game_type="loteria", host="RichPlayer")
    table.bet = 50
    table._db = temp_db
    game._table = table

    game.add_player("RichPlayer", u1)
    game.add_player("PoorPlayer", u2)

    # validate_start should return insufficient coins error
    errors = game.validate_start()
    assert any(
        isinstance(e, tuple) and e[0] == "table-error-insufficient-coins"
        for e in errors
    )

    # Make PoorPlayer a spectator
    poor_in_game = next(p for p in game.players if p.name == "PoorPlayer")
    poor_in_game.is_spectator = True

    # PoorPlayer attempts to toggle to active player via _action_toggle_spectator
    game._users[poor_in_game.id] = u2
    game._action_toggle_spectator(poor_in_game, "toggle_spectator")

    # Still spectator because of insufficient coins!
    assert poor_in_game.is_spectator is True
    u2.speak_l.assert_called_with(
        "table-error-insufficient-coins-self",
        buffer="game",
        coins=10,
        required=50,
    )


def test_game_start_pot_deduction_and_single_winner_payout(temp_db):
    p1 = temp_db.create_user("PlayerOne", "hash")
    p2 = temp_db.create_user("PlayerTwo", "hash")

    u1 = make_user("PlayerOne", p1.uuid)
    u2 = make_user("PlayerTwo", p2.uuid)

    game = LoteriaGame()
    table = Table(table_id="tbl30", game_type="loteria", host="PlayerOne")
    table.bet = 50
    table._db = temp_db
    game._table = table

    table.add_member("PlayerOne", u1)
    table.add_member("PlayerTwo", u2)

    game.add_player("PlayerOne", u1)
    game.add_player("PlayerTwo", u2)

    # Start game from lobby
    game._start_game_from_lobby()

    # Both players had 250 coins, deducted 50 each
    w1 = temp_db.get_wallet(p1.uuid)
    w2 = temp_db.get_wallet(p2.uuid)
    assert w1.balance == 200
    assert w1.total_bet == 50
    assert w2.balance == 200
    assert w2.total_bet == 50

    assert table.pot == 100
    assert table._pot_contributors == {p1.uuid, p2.uuid}

    # Simulate game finish with PlayerOne as sole winner
    result = GameResult(
        game_type="loteria",
        timestamp="2026-11-09T00:00:00",
        duration_ticks=500,
        player_results=[
            PlayerResult(player_id=p1.uuid, player_name="PlayerOne", is_bot=False),
            PlayerResult(player_id=p2.uuid, player_name="PlayerTwo", is_bot=False),
        ],
        custom_data={"winner_ids": [p1.uuid]},
    )

    table.save_game_result(result)

    # Winner gets the entire pot (100 coins)
    w1_after = temp_db.get_wallet(p1.uuid)
    w2_after = temp_db.get_wallet(p2.uuid)
    assert w1_after.balance == 300  # 200 + 100
    assert w1_after.total_won == 100
    assert w2_after.balance == 200

    assert table.pot == 0
    assert len(table._pot_contributors) == 0


def test_game_tie_splits_pot_equally(temp_db):
    p1 = temp_db.create_user("Alice", "hash")
    p2 = temp_db.create_user("Bob", "hash")

    u1 = make_user("Alice", p1.uuid)
    u2 = make_user("Bob", p2.uuid)

    game = LoteriaGame()
    table = Table(table_id="tbl40", game_type="loteria", host="Alice")
    table.bet = 50
    table._db = temp_db
    game._table = table

    table.add_member("Alice", u1)
    table.add_member("Bob", u2)

    game.add_player("Alice", u1)
    game.add_player("Bob", u2)

    game._start_game_from_lobby()
    assert table.pot == 100

    # Game finishes in a tie
    result = GameResult(
        game_type="loteria",
        timestamp="2026-11-09T00:00:00",
        duration_ticks=400,
        player_results=[
            PlayerResult(player_id=p1.uuid, player_name="Alice", is_bot=False),
            PlayerResult(player_id=p2.uuid, player_name="Bob", is_bot=False),
        ],
        custom_data={"winner_ids": [p1.uuid, p2.uuid]},
    )

    table.save_game_result(result)

    # 100 pot split into 50 each
    w1 = temp_db.get_wallet(p1.uuid)
    w2 = temp_db.get_wallet(p2.uuid)
    assert w1.balance == 250  # 200 + 50
    assert w2.balance == 250  # 200 + 50
    assert table.pot == 0


def test_game_refund_when_bot_wins_or_no_human_winner(temp_db):
    p1 = temp_db.create_user("HumanPlayer", "hash")
    u1 = make_user("HumanPlayer", p1.uuid)

    game = LoteriaGame()
    table = Table(table_id="tbl50", game_type="loteria", host="HumanPlayer")
    table.bet = 100
    table._db = temp_db
    game._table = table

    table.add_member("HumanPlayer", u1)
    game.add_player("HumanPlayer", u1)

    bot = game.create_player("bot-1", "Bot Juan", is_bot=True)
    game.players.append(bot)

    game._start_game_from_lobby()

    # Human deducted 100, pot is 100
    assert temp_db.get_wallet(p1.uuid).balance == 150
    assert table.pot == 100

    # Bot wins the game!
    result = GameResult(
        game_type="loteria",
        timestamp="2026-11-09T00:00:00",
        duration_ticks=300,
        player_results=[
            PlayerResult(player_id=p1.uuid, player_name="HumanPlayer", is_bot=False),
            PlayerResult(player_id=bot.id, player_name=bot.name, is_bot=True),
        ],
        custom_data={"winner_ids": [bot.id]},
    )

    table.save_game_result(result)

    # Human gets their 100 refunded because no human won
    w1 = temp_db.get_wallet(p1.uuid)
    assert w1.balance == 250
    assert table.pot == 0


def test_game_reset_or_destroy_refunds_pot(temp_db):
    p1 = temp_db.create_user("Canceller", "hash")
    p2 = temp_db.create_user("Canceller2", "hash")
    u1 = make_user("Canceller", p1.uuid)
    u2 = make_user("Canceller2", p2.uuid)

    game = LoteriaGame()
    table = Table(table_id="tbl60", game_type="loteria", host="Canceller")
    table.bet = 60
    table._db = temp_db
    table.game = game
    game._table = table

    table.add_member("Canceller", u1)
    table.add_member("Canceller2", u2)
    game.add_player("Canceller", u1)
    game.add_player("Canceller2", u2)

    game._start_game_from_lobby()
    assert temp_db.get_wallet(p1.uuid).balance == 190
    assert temp_db.get_wallet(p2.uuid).balance == 190
    assert table.pot == 120

    # Reset game mid-match
    table.reset_game()

    # Both players refunded!
    assert temp_db.get_wallet(p1.uuid).balance == 250
    assert temp_db.get_wallet(p2.uuid).balance == 250
    assert table.pot == 0


@pytest.mark.asyncio
async def test_custom_table_bet_ui_and_input(temp_db):
    server = Server(db_path=temp_db.db_path)
    server._db = temp_db

    host_acc = temp_db.create_user("CustomHost", "hash")
    host_user = make_user("CustomHost", host_acc.uuid)

    table = Table(table_id="tbl70", game_type="loteria", host="CustomHost")
    table._server = server
    table._db = temp_db
    table.add_member("CustomHost", host_user, as_spectator=False)
    server._tables._tables["tbl70"] = table

    server._nav_push(host_user, server._show_host_management_menu, table)
    server._nav_push(host_user, server._show_table_bet_menu, table)

    # Bet menu shows custom_bet item
    server._show_table_bet_menu(host_user, table)
    _, items = host_user.show_menu.call_args[0][:2]
    assert any(item.id == "custom_bet" for item in items)

    # Select custom_bet: editbox prompt is opened
    state = server._user_states[host_user.username]
    await server._handle_table_bet_selection(host_user, "custom_bet", state)
    host_user.show_editbox.assert_called_with(
        "custom_table_bet_input",
        mock.ANY,
        default_value="",
    )
    assert server._user_states[host_user.username]["menu"] == "custom_table_bet_input"

    server._users[host_user.username] = host_user

    # Submit valid custom bet of 120
    input_packet = {"type": "input", "input_id": "custom_table_bet_input", "text": "120"}
    await server._handle_editbox(host_user, input_packet)
    assert table.bet == 120

    # Submit excessive custom bet of 500 (balance is 250)
    server._enter_input_state(host_user, "custom_table_bet_input", table_id=table.table_id)
    input_packet = {"type": "input", "input_id": "custom_table_bet_input", "text": "500"}
    await server._handle_editbox(host_user, input_packet)
    # Bet unchanged because 500 > 250
    assert table.bet == 120
    host_user.speak_l.assert_called_with(
        "table-error-host-cannot-afford-bet",
        buffer="system",
        coins=250,
        required=500,
    )

    # Submit invalid text
    server._enter_input_state(host_user, "custom_table_bet_input", table_id=table.table_id)
    input_packet = {"type": "input", "input_id": "custom_table_bet_input", "text": "abc"}
    await server._handle_editbox(host_user, input_packet)
    assert table.bet == 120
    host_user.speak_l.assert_called_with(
        "table-error-invalid-bet-amount",
        buffer="system",
    )
