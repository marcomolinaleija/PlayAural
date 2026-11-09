"""Tests for Mexican Loteria (Lotería Mexicana)."""

import random
from pathlib import Path

from ..core.server import Server
from ..game_utils.actions import Visibility
from ..game_utils.grid_mixin import GridCursor, grid_cell_id
from ..game_utils.sequence_runner_mixin import SequenceBeat
from ..games.loteria import audio as loteria_audio
from ..games.loteria.cards import LOTERIA_CARDS, TOTAL_CARDS
from ..games.loteria.game import (
    CALL_DRAW_DELAY_TICKS,
    CALL_INTERVAL_CHOICES,
    CALL_SEQUENCE_TAG,
    CARD_COLS,
    CARD_ROWS,
    CLAIM_RESULT_SOUND_DELAY_TICKS,
    CLAIM_SEQUENCE_TAG,
    CLAIM_SUSPENSE_TICKS,
    DEFAULT_CALL_INTERVAL_SECONDS,
    PATTERN_CENTRO,
    PATTERN_CHOICES,
    PATTERN_CHORRO,
    PATTERN_CUADRO_CHICO,
    PATTERN_CUATRO_ESQUINAS,
    PATTERN_LLENO,
    SOUND_CYMBAL,
    SOUND_DRAW,
    SOUND_ERROR,
    SOUND_PLACE_BEAN,
    SOUND_REMOVE_BEAN,
    SOUND_SUSPENSE,
    SOUND_WIN,
    TABLA_SIZE,
    TICKS_PER_SECOND,
    VERSES_NAMES_ONLY,
    VERSES_WITH_VERSES,
    LoteriaGame,
    LoteriaOptions,
    LoteriaPlayer,
)
from ..games.registry import GameRegistry
from ..messages.localization import Localization
from ..persistence.database import (
    ACTIVITY_BONUS_COINS,
    INITIAL_WALLET_COINS,
    MAX_BONUS_ELIGIBLE_COINS,
    Database,
)
from ..ui.keybinds import KeybindState
from ..users.bot import Bot
from ..users.test_user import MockUser

_locales_dir = Path(__file__).parent.parent / "locales"
Localization.init(_locales_dir)


def make_game(
    *,
    player_count: int = 2,
    start: bool = False,
    bot_all: bool = False,
    bot_indices: set[int] | None = None,
    locale: str = "es",
    **option_overrides,
) -> LoteriaGame:
    game = LoteriaGame(options=LoteriaOptions(**option_overrides))
    game.setup_keybinds()
    for index in range(player_count):
        name = f"Player{index + 1}"
        is_bot = bot_all or (bot_indices is not None and index in bot_indices)
        user = Bot(name, uuid=f"p{index + 1}") if is_bot else MockUser(name, locale=locale, uuid=f"p{index + 1}")
        game.add_player(name, user)
    game.host = "Player1"
    if start:
        game.on_start()
    return game


def test_loteria_metadata_and_registration():
    assert GameRegistry.get("loteria") is LoteriaGame
    game = make_game()
    assert game.get_type() == "loteria"
    assert game.get_name() == "Lotería Mexicana"
    assert game.get_category() == "misc"
    assert game.get_min_players() == 2
    assert game.get_max_players() == 12
    assert game.get_supported_leaderboards() == ["wins", "games_played"]


def test_loteria_cards_definitions():
    assert len(LOTERIA_CARDS) == 54
    assert TOTAL_CARDS == 54
    for card_id in range(1, 55):
        assert card_id in LOTERIA_CARDS
        card = LOTERIA_CARDS[card_id]
        assert card.id == card_id
        assert len(card.name_es) > 0
        assert len(card.rhyme_es) > 0
        assert len(card.name_en) > 0
        assert len(card.rhyme_en) > 0

        # Check localization in ES and EN
        name_es = Localization.get("es", f"loteria-card-{card_id}")
        assert name_es == card.name_es
        rhyme_es = Localization.get("es", f"loteria-rhyme-{card_id}")
        assert rhyme_es == card.rhyme_es

        name_en = Localization.get("en", f"loteria-card-{card_id}")
        assert name_en == card.name_en
        rhyme_en = Localization.get("en", f"loteria-rhyme-{card_id}")
        assert rhyme_en == card.rhyme_en


def test_loteria_board_generation():
    game = make_game(player_count=2, start=True)
    for player in game.players:
        assert isinstance(player, LoteriaPlayer)
        assert len(player.tabla) == CARD_ROWS
        assert all(len(row) == CARD_COLS for row in player.tabla)
        assert len(player.marked) == CARD_ROWS
        assert all(len(row) == CARD_COLS for row in player.marked)

        all_cards = [card for row in player.tabla for card in row]
        assert len(all_cards) == TABLA_SIZE
        assert len(set(all_cards)) == TABLA_SIZE  # All unique on tabla
        assert all(1 <= card <= TOTAL_CARDS for card in all_cards)
        assert all(not marked for row in player.marked for marked in row)  # Starts unmarked


def test_loteria_grid_navigation_and_cell_labels():
    game = make_game(player_count=1, start=True)
    player = game.players[0]
    p1_user: MockUser = game.get_user(player)
    p1_user._locale = "es"

    card_0_0 = player.tabla[0][0]
    card_name = game._card_name(card_0_0, "es")

    label_unmarked = game.get_cell_label(0, 0, player, "es")
    assert f"{card_name}, sin marcar." == label_unmarked

    # Select cell to place bean
    game.on_grid_select(player, 0, 0)
    assert player.marked[0][0] is True
    assert p1_user.get_sounds_played()[-1] == SOUND_PLACE_BEAN
    assert p1_user.get_last_spoken() == f"Pusiste frijolito en {card_name}."

    label_marked = game.get_cell_label(0, 0, player, "es")
    assert f"{card_name}, con frijol." == label_marked

    # Select again to remove bean
    game.on_grid_select(player, 0, 0)
    assert player.marked[0][0] is False
    assert p1_user.get_sounds_played()[-1] == SOUND_REMOVE_BEAN
    assert p1_user.get_last_spoken() == f"Quitaste frijolito de {card_name}."


def test_pattern_candidate_cells():
    game = make_game()
    # Chorro: 4 rows + 4 cols + 2 diagonals = 10
    chorro_candidates = game._pattern_candidate_cells(PATTERN_CHORRO)
    assert len(chorro_candidates) == 10

    # Cuatro esquinas: 1 shape of 4 cells
    esquinas = game._pattern_candidate_cells(PATTERN_CUATRO_ESQUINAS)
    assert len(esquinas) == 1
    assert esquinas[0] == [(0, 0), (0, 3), (3, 0), (3, 3)]

    # Centro: 1 shape of 4 cells
    centro = game._pattern_candidate_cells(PATTERN_CENTRO)
    assert len(centro) == 1
    assert centro[0] == [(1, 1), (1, 2), (2, 1), (2, 2)]

    # Cuadro chico: 9 candidate 2x2 squares
    cuadro_chico = game._pattern_candidate_cells(PATTERN_CUADRO_CHICO)
    assert len(cuadro_chico) == 9

    # Lleno: 1 shape of 16 cells
    lleno = game._pattern_candidate_cells(PATTERN_LLENO)
    assert len(lleno) == 1
    assert len(lleno[0]) == 16


def test_claim_verification_chorro_win():
    game = make_game(player_count=2, start=True, pattern=PATTERN_CHORRO)
    player = game.players[0]

    # Row 0 of player's tabla: 4 cards
    row_0_cards = player.tabla[0]
    for c in range(CARD_COLS):
        player.marked[0][c] = True

    # With none called yet, claim fails
    is_valid, bad_card, winning = game._verify_claim(player)
    assert not is_valid
    assert bad_card == row_0_cards[0]

    # Call 3 of the 4 cards: still fails
    for card in row_0_cards[:3]:
        game.called_cards.append(card)
    is_valid, bad_card, winning = game._verify_claim(player)
    assert not is_valid
    assert bad_card == row_0_cards[3]

    # Call all 4 cards: valid win!
    game.called_cards.append(row_0_cards[3])
    is_valid, bad_card, winning = game._verify_claim(player)
    assert is_valid
    assert bad_card is None
    assert winning == row_0_cards


def test_claim_verification_cuatro_esquinas():
    game = make_game(player_count=2, start=True, pattern=PATTERN_CUATRO_ESQUINAS)
    player = game.players[0]

    corners = [(0, 0), (0, 3), (3, 0), (3, 3)]
    for r, c in corners:
        player.marked[r][c] = True
        game.called_cards.append(player.tabla[r][c])

    is_valid, bad_card, winning = game._verify_claim(player)
    assert is_valid
    assert winning == [player.tabla[r][c] for r, c in corners]


def test_claim_verification_centro():
    game = make_game(player_count=2, start=True, pattern=PATTERN_CENTRO)
    player = game.players[0]

    center = [(1, 1), (1, 2), (2, 1), (2, 2)]
    for r, c in center:
        player.marked[r][c] = True
        game.called_cards.append(player.tabla[r][c])

    is_valid, bad_card, winning = game._verify_claim(player)
    assert is_valid
    assert winning == [player.tabla[r][c] for r, c in center]


def test_claim_verification_cuadro_chico():
    game = make_game(player_count=2, start=True, pattern=PATTERN_CUADRO_CHICO)
    player = game.players[0]

    square = [(2, 1), (2, 2), (3, 1), (3, 2)]
    for r, c in square:
        player.marked[r][c] = True
        game.called_cards.append(player.tabla[r][c])

    is_valid, bad_card, winning = game._verify_claim(player)
    assert is_valid
    assert winning == [player.tabla[r][c] for r, c in square]


def test_claim_verification_lleno():
    game = make_game(player_count=2, start=True, pattern=PATTERN_LLENO)
    player = game.players[0]

    for r in range(CARD_ROWS):
        for c in range(CARD_COLS):
            player.marked[r][c] = True
            game.called_cards.append(player.tabla[r][c])

    is_valid, bad_card, winning = game._verify_claim(player)
    assert is_valid
    assert len(winning) == 16


def test_claim_execution_flow_and_sequences():
    game = make_game(player_count=2, start=True, pattern=PATTERN_CHORRO)
    p1 = game.players[0]
    p1_user: MockUser = game.get_user(p1)

    # Mark row 0
    row_0 = p1.tabla[0]
    for c in range(CARD_COLS):
        p1.marked[0][c] = True
        game.called_cards.append(row_0[c])

    # Execute claim
    game.execute_action(p1, "claim_loteria")
    assert game.pending_claim_player_id == p1.id
    assert game.is_sequence_gameplay_locked()
    assert game.has_active_sequence(tag=CLAIM_SEQUENCE_TAG)

    # Finish suspense sequence
    for _ in range(CLAIM_SUSPENSE_TICKS + 5):
        game.on_tick()

    assert p1.has_loteria is True
    assert game.winner_ids == [p1.id]
    assert game.status == "finished"


def test_rejected_claim_records_signature():
    game = make_game(player_count=2, start=True, pattern=PATTERN_CHORRO)
    p1 = game.players[0]
    p1_user: MockUser = game.get_user(p1)

    # Incomplete claim
    p1.marked[0][0] = True
    game.called_cards.append(p1.tabla[0][0])

    game.execute_action(p1, "claim_loteria")
    for _ in range(CLAIM_SUSPENSE_TICKS + 5):
        game.on_tick()

    assert p1.has_loteria is False
    assert len(p1.rejected_claim_signatures) == 1
    # Claim again with unchanged board should be blocked
    assert game._is_claim_enabled(p1) == "loteria-claim-unchanged"


def test_draw_sequence_and_call_modes():
    game = make_game(player_count=2, start=True, verses=VERSES_WITH_VERSES)
    p1_user: MockUser = game.get_user(game.players[0])
    p1_user._locale = "es"

    # Fast forward through warmup ticks
    for _ in range(game.call_countdown_ticks + 1):
        game.on_tick()

    assert game.pending_call_card is not None
    assert game.has_active_sequence(tag=CALL_SEQUENCE_TAG)

    # Advance through draw sequence
    for _ in range(CALL_DRAW_DELAY_TICKS + 2):
        game.on_tick()

    assert len(game.called_cards) == 1
    called = game.called_cards[0]
    card_name = game._card_name(called, "es")
    rhyme = game._card_rhyme(called, "es")
    assert f"¡{called}: {card_name}! {rhyme}" in p1_user.get_spoken_messages()


def test_repeat_call_and_check_called_actions():
    game = make_game(player_count=1, start=True, verses=VERSES_NAMES_ONLY)
    p1 = game.players[0]
    p1_user: MockUser = game.get_user(p1)
    p1_user._locale = "es"

    game.called_cards.extend([1, 10, 25])
    game.execute_action(p1, "repeat_call")
    name_25 = game._card_name(25, "es")
    assert p1_user.get_last_spoken() == f"Última carta cantada: 25: {name_25}."

    # Status box
    items = game._called_cards_items(p1, p1_user)
    assert items[0].id == "called_count"
    assert "3 de 54 cartas cantadas" in items[0].text
    assert items[1].id == "card:25"


def test_bot_reaction_and_marking():
    game = make_game(player_count=2, start=True, bot_indices={1})
    bot_player: LoteriaPlayer = game.players[1]
    assert bot_player.is_bot is True

    card_to_call = bot_player.tabla[0][0]
    payload = {"card_id": card_to_call}
    game._handle_announce_call(payload)

    assert bot_player.pending_mark_card == card_to_call
    assert bot_player.pending_mark_ticks > 0

    # Advance until bot marks
    for _ in range(bot_player.pending_mark_ticks + 5):
        game._process_bots()

    assert bot_player.marked[0][0] is True


def test_bot_completes_pattern_and_claims():
    game = make_game(player_count=2, start=True, bot_indices={1}, pattern=PATTERN_CHORRO)
    bot_player: LoteriaPlayer = game.players[1]

    # Pre-mark 3 of 4 in row 0
    for c in range(3):
        card = bot_player.tabla[0][c]
        bot_player.marked[0][c] = True
        game.called_cards.append(card)

    # Announce the 4th card
    last_card = bot_player.tabla[0][3]
    game._handle_announce_call({"card_id": last_card})

    # Let bot mark
    for _ in range(bot_player.pending_mark_ticks + 5):
        game._process_bots()
    assert bot_player.marked[0][3] is True

    # Bot should now queue claim
    assert bot_player.bot_pending_action == "claim_loteria"
    for _ in range(bot_player.bot_think_ticks + 5):
        game._process_bots()

    assert game.has_active_sequence(tag=CLAIM_SEQUENCE_TAG)
    for _ in range(CLAIM_SUSPENSE_TICKS + 5):
        game.on_tick()

    assert bot_player.has_loteria is True
    assert game.status == "finished"


def test_deck_exhaustion_ends_game():
    game = make_game(player_count=2, start=True)
    game.available_cards = []
    game._start_next_call()

    assert game.status == "finished"


def test_game_result_and_end_screen():
    game = make_game(player_count=2, start=True)
    p1 = game.players[0]
    p1.has_loteria = True
    game.winner_ids = [p1.id]
    game.called_cards = [1, 2, 3, 4]

    result = game.build_game_result()
    assert result.game_type == "loteria"
    assert result.custom_data["calls_made"] == 4
    assert result.custom_data["winner_names"] == [p1.name]

    lines = game.format_end_screen(result, "es")
    assert any("4 cartas" in line for line in lines)
    assert any(f"Ganador: {p1.name}" in line for line in lines)


def test_options_prestart_validate():
    game = make_game()
    assert game.prestart_validate() == []

    game.options.call_interval = "99"
    assert any("loteria-error-invalid-interval" in str(err) for err in game.prestart_validate())

    game.options.call_interval = "15"
    game.options.pattern = "unknown_pattern"
    assert any("loteria-error-invalid-pattern" in str(err) for err in game.prestart_validate())

    game.options.pattern = PATTERN_CHORRO
    game.options.verses = "unknown_verses"
    assert any("loteria-error-invalid-verses" in str(err) for err in game.prestart_validate())


def test_serialization():
    game = make_game(player_count=2, start=True)
    json_data = game.to_json()
    restored = LoteriaGame.from_json(json_data)
    assert restored.get_type() == "loteria"
    assert len(restored.players) == 2
    assert restored.options.pattern == game.options.pattern
    assert restored.options.call_interval == game.options.call_interval
    assert restored.options.verses == game.options.verses


def test_user_wallet_persistence_and_bonus():
    db = Database(":memory:")
    db.connect()
    try:
        user = db.create_user("Apostador", "hash")
        wallet = db.get_wallet(user.uuid)
        assert wallet.balance == INITIAL_WALLET_COINS  # 250
        assert wallet.total_won == 0
        assert wallet.total_bet == 0

        # Bet 50 coins
        ok, _ = db.adjust_wallet_balance(user.uuid, -50, is_bet=True)
        assert ok
        wallet = db.get_wallet(user.uuid)
        assert wallet.balance == 200
        assert wallet.total_bet == 50

        # Cannot overbet
        ok, _ = db.adjust_wallet_balance(user.uuid, -300, is_bet=True)
        assert not ok
        assert db.get_wallet(user.uuid).balance == 200

        # Win 100 coins
        ok, _ = db.adjust_wallet_balance(user.uuid, 100, is_win=True)
        assert ok
        wallet = db.get_wallet(user.uuid)
        assert wallet.balance == 300
        assert wallet.total_won == 100

        # Activity bonus cooldown check
        can_claim, reason, _ = db.can_claim_activity_bonus(user.uuid)
        assert not can_claim
        assert reason == "cooldown"

        # Simulate cooldown passed
        db._conn.execute(
            "UPDATE user_wallets SET last_activity_bonus_utc = '2000-01-01T00:00:00' WHERE user_uuid = ?",
            (user.uuid,),
        )
        db._conn.commit()

        can_claim, reason, _ = db.can_claim_activity_bonus(user.uuid)
        assert can_claim
        success, new_balance, msg = db.claim_activity_bonus(user.uuid)
        assert success
        assert new_balance == 300 + ACTIVITY_BONUS_COINS  # 450

        # Inflation cap check: set balance above MAX_BONUS_ELIGIBLE_COINS (3000)
        db._conn.execute(
            "UPDATE user_wallets SET balance = 35000, last_activity_bonus_utc = '2000-01-01T00:00:00' WHERE user_uuid = ?",
            (user.uuid,),
        )
        db._conn.commit()
        can_claim, reason, _ = db.can_claim_activity_bonus(user.uuid)
        assert not can_claim
        assert reason == "cap_reached"
    finally:
        db.close()


def test_loteria_betting_validation_insufficient_coins():
    db = Database(":memory:")
    db.connect()
    try:
        u1 = db.create_user("Pobre", "hash")
        u2 = db.create_user("Rico", "hash")
        # u1 only has 25 coins
        db.adjust_wallet_balance(u1.uuid, -225)

        game = LoteriaGame(options=LoteriaOptions(bet="100"))
        game._db = db
        user1 = MockUser(u1.username, locale="es", uuid=u1.uuid)
        user2 = MockUser(u2.username, locale="es", uuid=u2.uuid)
        game.add_player(u1.username, user1)
        game.add_player(u2.username, user2)

        errors = game.prestart_validate()
        assert any(
            isinstance(e, tuple) and e[0] == "loteria-error-insufficient-coins"
            for e in errors
        )
    finally:
        db.close()


def test_loteria_betting_pot_and_winner_payout():
    db = Database(":memory:")
    db.connect()
    try:
        u1 = db.create_user("JugadorUno", "hash")
        u2 = db.create_user("JugadorDos", "hash")

        game = LoteriaGame(options=LoteriaOptions(bet="50"))
        game._db = db
        user1 = MockUser(u1.username, locale="es", uuid=u1.uuid)
        user2 = MockUser(u2.username, locale="es", uuid=u2.uuid)
        game.add_player(u1.username, user1)
        game.add_player(u2.username, user2)

        game.on_start()
        # 50 deducted from each player -> pot = 100
        assert game.pot == 100
        assert db.get_wallet(u1.uuid).balance == 200
        assert db.get_wallet(u2.uuid).balance == 200

        # Player 1 wins
        p1 = game.players[0]
        game._declare_winner(p1, winning_cards=[1, 2, 3, 4])
        assert game.pot == 0
        assert db.get_wallet(u1.uuid).balance == 300  # 200 + 100 pot
        assert db.get_wallet(u1.uuid).total_won == 100
    finally:
        db.close()


def test_loteria_betting_refund_on_exhaustion():
    db = Database(":memory:")
    db.connect()
    try:
        u1 = db.create_user("JugadorA", "hash")
        u2 = db.create_user("JugadorB", "hash")

        game = LoteriaGame(options=LoteriaOptions(bet="50"))
        game._db = db
        user1 = MockUser(u1.username, locale="es", uuid=u1.uuid)
        user2 = MockUser(u2.username, locale="es", uuid=u2.uuid)
        game.add_player(u1.username, user1)
        game.add_player(u2.username, user2)

        game.on_start()
        assert game.pot == 100
        assert db.get_wallet(u1.uuid).balance == 200
        assert db.get_wallet(u2.uuid).balance == 200

        # Deck exhaustion without winner
        game._finish_no_further_calls()
        assert game.pot == 0
        # Bets refunded
        assert db.get_wallet(u1.uuid).balance == 250
        assert db.get_wallet(u2.uuid).balance == 250
    finally:
        db.close()


def test_loteria_check_pot_action():
    game = make_game(player_count=2, bet="25")
    game.pot = 50
    p1 = game.players[0]
    actions = game.create_standard_action_set(p1)
    assert actions.get_action("check_pot") is not None

    user = game.get_user(p1)
    game._action_check_pot(p1, "check_pot")
    last_spoken = user.get_last_spoken()
    assert "50 monedas" in last_spoken or "50" in last_spoken


