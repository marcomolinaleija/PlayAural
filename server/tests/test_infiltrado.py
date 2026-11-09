"""Tests for Infiltrado (Undercover) game."""

from pathlib import Path

from ..game_utils.actions import Visibility
from ..games.infiltrado.game import (
    CLUE_MODE_TEXT_AND_VOICE,
    CLUE_MODE_VOICE,
    PHASE_CLUES,
    PHASE_MR_WHITE_GUESS,
    PHASE_VOTING,
    ROLE_CIVILIAN,
    ROLE_MR_WHITE,
    ROLE_UNDERCOVER,
    InfiltradoGame,
    InfiltradoOptions,
    InfiltradoPlayer,
)
from ..games.infiltrado.words import InfiltradoWordManager, WordPair, normalize_word
from ..games.registry import GameRegistry
from ..messages.localization import Localization
from ..users.bot import Bot
from ..users.test_user import MockUser

_locales_dir = Path(__file__).parent.parent / "locales"
Localization.init(_locales_dir)


def make_infiltrado_game(
    *,
    player_count: int = 3,
    start: bool = False,
    bot_all: bool = False,
    bot_indices: set[int] | None = None,
    locale: str = "es",
    **option_overrides,
) -> InfiltradoGame:
    game = InfiltradoGame(options=InfiltradoOptions(**option_overrides))
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


def test_infiltrado_metadata():
    assert GameRegistry.get("infiltrado") is InfiltradoGame
    game = make_infiltrado_game()
    assert game.get_type() == "infiltrado"
    assert game.get_name() == "El Infiltrado"
    assert game.get_category() == "misc"
    assert game.get_min_players() == 3
    assert game.get_max_players() == 12
    assert game.get_supported_leaderboards() == ["wins", "games_played"]


def test_word_manager():
    # Initial pairs should be at least 50
    pairs = InfiltradoWordManager.get_all_pairs()
    assert len(pairs) >= 50

    # Normalization helper
    assert normalize_word("  Café  ") == "cafe"
    assert normalize_word("MÚSICA") == "musica"
    assert normalize_word("Té") == "te"

    # Add a pair
    new_p = InfiltradoWordManager.add_pair("Prueba1", "Prueba2", ["C1"], ["C2"])
    assert new_p.word1 == "Prueba1"
    assert new_p.word2 == "Prueba2"
    assert InfiltradoWordManager.get_pair_by_id(new_p.id) is not None

    # Update pair
    updated = InfiltradoWordManager.update_pair(new_p.id, word1="Modificada")
    assert updated is not None
    assert updated.word1 == "Modificada"
    assert updated.word2 == "Prueba2"

    # Delete pair
    assert InfiltradoWordManager.delete_pair(new_p.id) is True
    assert InfiltradoWordManager.get_pair_by_id(new_p.id) is None


def test_game_start_and_role_distribution():
    game = make_infiltrado_game(player_count=3, start=True, include_mr_white="no")
    assert game.phase == PHASE_CLUES
    assert game.round_number == 1
    assert game.civilian_word != ""
    assert game.undercover_word != ""
    assert game.civilian_word != game.undercover_word

    players = [p for p in game.players if isinstance(p, InfiltradoPlayer)]
    undercovers = [p for p in players if p.role == ROLE_UNDERCOVER]
    civilians = [p for p in players if p.role == ROLE_CIVILIAN]

    assert len(undercovers) == 1
    assert len(civilians) == 2
    assert undercovers[0].secret_word == game.undercover_word
    for c in civilians:
        assert c.secret_word == game.civilian_word


def test_game_start_with_mr_white():
    game = make_infiltrado_game(player_count=4, start=True, include_mr_white="yes")
    players = [p for p in game.players if isinstance(p, InfiltradoPlayer)]
    undercovers = [p for p in players if p.role == ROLE_UNDERCOVER]
    civilians = [p for p in players if p.role == ROLE_CIVILIAN]
    mr_whites = [p for p in players if p.role == ROLE_MR_WHITE]

    assert len(undercovers) == 1
    assert len(mr_whites) == 1
    assert len(civilians) == 2
    assert mr_whites[0].secret_word == ""


def test_check_secret_word_action():
    game = make_infiltrado_game(player_count=3, start=True)
    p1 = game.players[0]
    u1 = game.get_user(p1)

    game._action_check_secret_word(p1, "check_secret_word")
    last_spoken = u1.get_last_spoken()
    assert last_spoken is not None
    if p1.role == ROLE_CIVILIAN:
        assert game.civilian_word in last_spoken
    elif p1.role == ROLE_UNDERCOVER:
        assert game.undercover_word in last_spoken


def test_clue_giving_voice_mode():
    game = make_infiltrado_game(player_count=3, start=True, clue_mode=CLUE_MODE_VOICE)
    cur = game.current_player
    assert cur is not None

    # First player says word
    game._action_word_said(cur, "word_said")
    assert len(game.clue_history) == 1
    assert game.clue_history[0].player_name == cur.name
    assert game.clue_history[0].is_voice is True

    # Next player
    cur2 = game.current_player
    assert cur2.id != cur.id
    game._action_word_said(cur2, "word_said")

    # Third player
    cur3 = game.current_player
    game._action_word_said(cur3, "word_said")

    # When all 3 gave clue, transitions to voting
    assert game.phase == PHASE_VOTING


def test_clue_giving_text_mode():
    game = make_infiltrado_game(player_count=3, start=True, clue_mode=CLUE_MODE_TEXT_AND_VOICE)
    cur = game.current_player

    game._action_give_clue_text(cur, "Madera", "give_clue_text")
    assert len(game.clue_history) == 1
    assert game.clue_history[0].clue == "Madera"
    assert game.clue_history[0].is_voice is False


def test_voting_tie_advances_round():
    game = make_infiltrado_game(player_count=3, start=True)
    # Fast forward clues
    for p in list(game._living_players()):
        game._record_clue(p, "Pista", is_voice=True)
    game._start_voting_phase()

    assert game.phase == PHASE_VOTING
    p1, p2, p3 = game._living_players()

    # Vote resulting in 3-way tie: p1 votes p2, p2 votes p3, p3 votes p1
    game._action_vote_suspect(p1, p2.id, "vote_suspect")
    game._action_vote_suspect(p2, p3.id, "vote_suspect")
    game._action_vote_suspect(p3, p1.id, "vote_suspect")

    # Tie should advance to round 2 without eliminating anyone
    assert game.round_number == 2
    assert game.phase == PHASE_CLUES
    assert len(game._living_players()) == 3


def test_voting_elimination_civilian():
    game = make_infiltrado_game(player_count=4, start=True, include_mr_white="no")
    p_civ = next(p for p in game._living_players() if p.role == ROLE_CIVILIAN)
    others = [p for p in game._living_players() if p.id != p_civ.id]

    game._start_voting_phase()
    # Everyone votes for p_civ
    for o in others:
        game._action_vote_suspect(o, p_civ.id, "vote_suspect")
    game._action_vote_suspect(p_civ, others[0].id, "vote_suspect")

    # p_civ is eliminated
    assert p_civ.is_alive is False
    # Game continues to round 2 because 1 undercover and 1 civilian remain
    assert game.round_number == 2


def test_voting_elimination_undercover_triggers_civilian_win():
    game = make_infiltrado_game(player_count=3, start=True, include_mr_white="no")
    p_und = next(p for p in game._living_players() if p.role == ROLE_UNDERCOVER)
    civilians = [p for p in game._living_players() if p.role == ROLE_CIVILIAN]

    game._start_voting_phase()
    for c in civilians:
        game._action_vote_suspect(c, p_und.id, "vote_suspect")
    game._action_vote_suspect(p_und, civilians[0].id, "vote_suspect")

    # Undercover eliminated -> Civilians win
    assert p_und.is_alive is False
    assert game.status != "playing"
    assert game.winning_role == ROLE_CIVILIAN


def test_undercovers_win_when_equalizing_civilians():
    game = make_infiltrado_game(player_count=3, start=True, include_mr_white="no")
    # In a 3 player game (1 undercover, 2 civilians), if 1 civilian is eliminated:
    # 1 undercover vs 1 civilian -> undercovers win immediately!
    p_civ = next(p for p in game._living_players() if p.role == ROLE_CIVILIAN)
    others = [p for p in game._living_players() if p.id != p_civ.id]

    game._start_voting_phase()
    for o in others:
        game._action_vote_suspect(o, p_civ.id, "vote_suspect")
    game._action_vote_suspect(p_civ, others[0].id, "vote_suspect")

    assert p_civ.is_alive is False
    assert game.status != "playing"
    assert game.winning_role == ROLE_UNDERCOVER


def test_mr_white_elimination_and_guess():
    game = make_infiltrado_game(player_count=4, start=True, include_mr_white="yes")
    p_white = next(p for p in game._living_players() if p.role == ROLE_MR_WHITE)
    others = [p for p in game._living_players() if p.id != p_white.id]

    game._start_voting_phase()
    for o in others:
        game._action_vote_suspect(o, p_white.id, "vote_suspect")
    game._action_vote_suspect(p_white, others[0].id, "vote_suspect")

    # Should enter PHASE_MR_WHITE_GUESS
    assert game.phase == PHASE_MR_WHITE_GUESS
    assert game.mr_white_target_id == p_white.id

    # Test correct guess:
    game._action_mr_white_guess(p_white, game.civilian_word, "mr_white_guess")
    assert game.status != "playing"
    assert game.winning_role == ROLE_MR_WHITE
    assert p_white.id in game.winning_player_ids


def test_mr_white_wrong_guess():
    game = make_infiltrado_game(player_count=4, start=True, include_mr_white="yes")
    p_white = next(p for p in game._living_players() if p.role == ROLE_MR_WHITE)
    others = [p for p in game._living_players() if p.id != p_white.id]

    game._start_voting_phase()
    for o in others:
        game._action_vote_suspect(o, p_white.id, "vote_suspect")
    game._action_vote_suspect(p_white, others[0].id, "vote_suspect")

    # Test wrong guess:
    game._action_mr_white_guess(p_white, "PalabraTotalmenteErronea123", "mr_white_guess")
    assert p_white.is_alive is False
    # If other undercovers remain, game continues
    assert game.round_number == 2


def test_clues_history_status_box():
    game = make_infiltrado_game(player_count=3, start=True)
    p1 = game.players[0]
    game._record_clue(p1, "Cuerdas", is_voice=False)

    game._action_check_clues_history(p1, "check_clues_history")
    u1 = game.get_user(p1)
    status_menu = u1.menus.get("status_box")
    assert status_menu is not None
    rendered_texts = [item.text if hasattr(item, "text") else str(item) for item in status_menu.get("items", [])]
    assert any("Cuerdas" in t for t in rendered_texts)
