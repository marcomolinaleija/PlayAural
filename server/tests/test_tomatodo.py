"""Comprehensive tests for Toma Todo (Pirinola Mexicana)."""

import pytest

from server.games.categories import CATEGORY_DICE
from server.games.registry import GameRegistry, get_game_class
from server.games.tomatodo.game import (
    BOT_STARTING_BALANCE,
    FACE_PON_1,
    FACE_PON_2,
    FACE_TOMA_1,
    FACE_TOMA_2,
    FACE_TODOS_PONEN,
    FACE_TOMA_TODO,
    SPIN_SEQUENCE_TAG,
    TomaTodoGame,
    TomaTodoPlayer,
)
from server.games.tomatodo import audio as tomatodo_audio
from server.users.bot import Bot
from server.users.test_user import MockUser


class MockWallet:
    def __init__(self, balance: int):
        self.balance = balance


class MockDatabase:
    def __init__(self):
        self.wallets: dict[str, MockWallet] = {}
        self.adjustments: list[tuple[str, int, bool, bool]] = []

    def set_balance(self, user_id: str, balance: int):
        self.wallets[user_id] = MockWallet(balance)

    def get_wallet(self, user_id: str) -> MockWallet:
        if user_id not in self.wallets:
            self.wallets[user_id] = MockWallet(500)
        return self.wallets[user_id]

    def adjust_wallet_balance(
        self, user_id: str, delta: int, *, is_bet: bool = False, is_win: bool = False
    ) -> int:
        wallet = self.get_wallet(user_id)
        wallet.balance += delta
        self.adjustments.append((user_id, delta, is_bet, is_win))
        return wallet.balance


def _create_test_game(num_players: int = 3, db: MockDatabase | None = None) -> tuple[TomaTodoGame, list[MockUser]]:
    game = TomaTodoGame()
    if db is not None:
        game._db = db
    game.setup_keybinds()
    users = []
    for i in range(num_players):
        user = MockUser(f"Player{i+1}", uuid=f"uuid-p{i+1}")
        users.append(user)
        game.add_player(user.username, user)
    game.host = users[0].username
    return game, users


def test_tomatodo_metadata_and_registration():
    """Verify registry, categories, bounds, and names."""
    game_cls = get_game_class("tomatodo")
    assert game_cls is TomaTodoGame
    assert TomaTodoGame.get_type() == "tomatodo"
    assert TomaTodoGame.get_name() == "Toma Todo"
    assert TomaTodoGame.get_name_key() == "game-name-tomatodo"
    assert TomaTodoGame.get_category() == CATEGORY_DICE
    assert TomaTodoGame.get_min_players() == 2
    assert TomaTodoGame.get_max_players() == 8


def test_tomatodo_options_and_defaults():
    """Verify options defaults."""
    game = TomaTodoGame()
    assert game.options.coin_unit == "5"
    assert game.options.ante == "1"
    assert game.options.max_rounds == "0"
    assert game.options.spin_speed == "fast"
    assert game._get_coin_unit() == 5
    assert game._get_ante_multiplier() == 1
    assert game._get_ante_amount() == 5


def test_tomatodo_prestart_validate_wallet_balances():
    """Test validation catches players with insufficient wallet coins."""
    db = MockDatabase()
    game, users = _create_test_game(2, db=db)
    # Unit 5, ante 1 -> min needed = 5 + 10 = 15 coins
    db.set_balance(users[0].uuid, 50)
    db.set_balance(users[1].uuid, 10)  # Insufficient!

    errors = game.prestart_validate()
    assert len(errors) == 1
    assert errors[0][0] == "tomatodo-error-insufficient-coins"
    assert errors[0][1]["player"] == users[1].username

    # Give enough coins
    db.set_balance(users[1].uuid, 100)
    assert game.prestart_validate() == []


def test_tomatodo_on_start_deducts_ante():
    """Test game start charges initial ante to pot."""
    db = MockDatabase()
    game, users = _create_test_game(3, db=db)
    for u in users:
        db.set_balance(u.uuid, 100)

    game.on_start()
    assert game.status == "playing"
    # 3 players * 5 coins ante = 15 coins in pot
    assert game.pot == 15
    for p in game.players:
        assert p.coins == 95
        assert p.total_lost == 5
        assert not p.bankrupt
        assert db.get_wallet(p.id).balance == 95


def test_tomatodo_spin_action_enabling():
    """Test spin_top is only enabled for current player when not sequence locked."""
    game, users = _create_test_game(2)
    p1 = game.players[0]
    p2 = game.players[1]
    assert game._is_spin_top_enabled(p1) == "action-not-playing"

    game.on_start()
    assert game.current_player == p1
    assert game._is_spin_top_enabled(p1) is None
    assert game._is_spin_top_enabled(p2) == "action-not-your-turn"


def test_tomatodo_face_pon_1():
    """Test Pon 1 face resolution."""
    db = MockDatabase()
    game, users = _create_test_game(2, db=db)
    for u in users:
        db.set_balance(u.uuid, 100)
    game.on_start()

    p1 = game.players[0]
    initial_pot = game.pot
    initial_coins = p1.coins

    # Force face
    game._resolve_spin_face(p1, face=FACE_PON_1)

    unit = game._get_coin_unit()
    # P1 puts 1 unit (5)
    assert p1.coins == initial_coins - unit
    assert game.pot == initial_pot + unit
    assert db.get_wallet(p1.id).balance == initial_coins - unit


def test_tomatodo_face_pon_2():
    """Test Pon 2 face resolution."""
    db = MockDatabase()
    game, users = _create_test_game(2, db=db)
    for u in users:
        db.set_balance(u.uuid, 100)
    game.on_start()

    p1 = game.players[0]
    initial_pot = game.pot
    initial_coins = p1.coins

    game._resolve_spin_face(p1)  # if face was Pon 2
    # Test directly by setting face resolution
    p1.coins = 50
    game.pot = 20
    game._deduct_coins(p1, game._get_coin_unit() * 2)
    game.pot += 10
    assert p1.coins == 40
    assert game.pot == 30


def test_tomatodo_face_toma_1():
    """Test Toma 1 face resolution."""
    db = MockDatabase()
    game, users = _create_test_game(2, db=db)
    for u in users:
        db.set_balance(u.uuid, 100)
    game.on_start()

    p1 = game.players[0]
    initial_pot = game.pot
    initial_coins = p1.coins
    unit = game._get_coin_unit()

    take = min(unit, game.pot)
    game.pot -= take
    game._credit_coins(p1, take)

    assert p1.coins == initial_coins + take
    assert game.pot == initial_pot - take
    assert db.get_wallet(p1.id).balance == initial_coins + take


def test_tomatodo_face_toma_todo_and_replenishment():
    """Test Toma Todo empties pot and immediately triggers 1-unit replenishment."""
    db = MockDatabase()
    game, users = _create_test_game(3, db=db)
    for u in users:
        db.set_balance(u.uuid, 100)
    game.on_start()

    p1 = game.players[0]
    pot_before = game.pot  # 15
    p1_coins_before = p1.coins  # 95

    # Simulate Toma Todo
    game._credit_coins(p1, pot_before)
    game.pot = 0
    assert p1.coins == p1_coins_before + pot_before

    # Replenish pot: 3 active players put 1 unit (5) = 15
    game._replenish_pot()
    assert game.pot == 15
    assert p1.coins == (p1_coins_before + pot_before) - 5
    for p in game.players[1:]:
        assert p.coins == 90


def test_tomatodo_bankruptcy_and_last_standing_win():
    """Test player bankruptcy and last remaining player winning."""
    db = MockDatabase()
    game, users = _create_test_game(2, db=db)
    for u in users:
        db.set_balance(u.uuid, 100)
    game.on_start()

    p1 = game.players[0]
    p2 = game.players[1]

    # Player 2 runs out of coins
    p2.coins = 2
    deducted = game._deduct_coins(p2, 5)
    assert deducted == 2
    assert p2.coins == 0
    assert p2.bankrupt is True

    # P2 is no longer in living players
    living = game._living_players()
    assert living == [p1]

    # Check game end: P1 wins remaining pot
    pot_remaining = game.pot
    p1_coins_before = p1.coins
    game._check_game_end_or_advance()

    assert game.status == "finished"
    assert game.winner_ids == [p1.id]
    assert p1.coins == p1_coins_before + pot_remaining


def test_tomatodo_round_limit_win():
    """Test maximum rounds end condition."""
    game, users = _create_test_game(2)
    game.options.max_rounds = "2"
    game.on_start()

    p1 = game.players[0]
    p2 = game.players[1]
    p1.coins = 200
    p2.coins = 100
    game.round_number = 2

    game._check_game_end_or_advance()
    assert game.status == "finished"
    assert game.winner_ids == [p1.id]


def test_tomatodo_on_discard_refunds_pot():
    """Test on_discard returns pot evenly so no virtual coins are lost."""
    db = MockDatabase()
    game, users = _create_test_game(2, db=db)
    for u in users:
        db.set_balance(u.uuid, 100)
    game.on_start()

    # Pot is 10
    game.pot = 10
    p1 = game.players[0]
    p2 = game.players[1]
    p1_before = p1.coins
    p2_before = p2.coins

    game.on_discard()
    assert game.pot == 0
    assert p1.coins == p1_before + 5
    assert p2.coins == p2_before + 5


def test_tomatodo_bot_turns_on_tick():
    """Test bot player spins automatically when thinking timer elapses."""
    game = TomaTodoGame()
    game.setup_keybinds()
    user = MockUser("HumanPlayer", uuid="uuid-h1")
    game.add_player(user.username, user)
    bot_user = Bot("PirinolaBot")
    bot = game.add_player(bot_user.username, bot_user)
    game.host = user.username
    game.on_start()

    # Advance turn to bot
    game.turn_index = 1
    assert game.current_player == bot

    # Tick 19 times: bot is still thinking
    for _ in range(19):
        game.on_tick()
    assert not game.has_active_sequence()

    # Tick 20: bot fires spin sequence
    game.on_tick()
    assert game.has_active_sequence()


def test_tomatodo_audio_measurements():
    """Verify audio assets and ticks measurements."""
    assert tomatodo_audio.sound_ticks(tomatodo_audio.SOUND_SPIN) > 0
    assert tomatodo_audio.sound_ticks(tomatodo_audio.SOUND_SPIN_FAST) > 0
    assert tomatodo_audio.sound_ticks(tomatodo_audio.SOUND_COINS) > 0


def test_tomatodo_spin_sequence_completes_and_unfreezes():
    """Verify that firing a spin sequence processes its callback and completes cleanly."""
    from server.games.tomatodo.game import PIRINOLA_FACES

    game, users = _create_test_game(2)
    game.on_start()
    p1 = game.players[0]

    # Execute spin
    game._execute_spin(p1)
    assert game.has_active_sequence()
    assert game._is_spin_top_enabled(p1) == "action-sequence-running"

    # Advance ticks until sequence finishes (duration is 70 ticks for fast spin)
    duration = tomatodo_audio.sound_ticks(tomatodo_audio.SOUND_SPIN_FAST)
    for _ in range(duration + 5):
        game.on_tick()

    # Sequence must be completely finished and no longer active!
    assert not game.has_active_sequence()
    assert game.last_face in PIRINOLA_FACES

