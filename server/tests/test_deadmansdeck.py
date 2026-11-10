"""Tests for Dead Man's Deck."""

from pathlib import Path
import random

from server.games.deadmansdeck.game import (
    AUDIO_DURATIONS_TICKS,
    COCK_TO_OUTCOME_DELAY_TICKS,
    LATEST_REVOLVER_PREPARATION_START_TICKS,
    MAX_CLAIM_CARDS,
    PHASE_CHALLENGE,
    PHASE_CLAIM,
    PHASE_PLAYING,
    PHASE_ROULETTE,
    PHASE_ROUND_START,
    PREPARATION_INTRO_TICKS,
    REVOLVER_PREPARATION_DELAY_TICKS,
    SOUND_BODY_FALLS,
    SOUND_BULLET_HIT,
    SOUND_CHALLENGE,
    SOUND_CHALLENGE_SUCCESS,
    SOUND_COCK,
    SOUND_EMPTY_CASINGS,
    SOUND_EMPTY_CLICK,
    SOUND_GAME_OVER,
    SOUND_GUNSHOT,
    SOUND_INTRO,
    SOUND_MUSIC,
    SOUND_PLAYS,
    SOUND_REVEAL,
    SOUND_REVOLVER_SPIN,
    SOUND_ROUND_START,
    SOUND_VOICE_BLUFF_CAUGHT,
    SOUND_VOICE_CHALLENGE,
    SOUND_VOICE_CHALLENGE_FORCED,
    SOUND_VOICE_GAME_OVER,
    SOUND_VOICE_INTRO,
    SOUND_VOICE_ROULETTE_COCK,
    SOUND_VOICE_ROULETTE_DEATH,
    SOUND_VOICE_ROULETTE_SURVIVE,
    SOUND_VOICE_TARGETS,
    SOUND_VOICE_TRUTH_REVEALED,
    DeadMansDeckCard,
    DeadMansDeckClaim,
    DeadMansDeckGame,
)
from server.games.deadmansdeck.bot import bot_think as deadmansdeck_bot_think
from server.games.registry import GameRegistry
from server.ui.keybinds import KeybindState
from server.users.bot import Bot
from server.users.test_user import MockUser


def make_game(player_count: int = 2) -> DeadMansDeckGame:
    game = DeadMansDeckGame()
    game.setup_keybinds()
    for index in range(player_count):
        name = f"Player{index + 1}"
        game.add_player(name, MockUser(name, uuid=f"p{index + 1}"))
    game.host = "Player1"
    return game


def advance_until(game: DeadMansDeckGame, condition, max_ticks: int = 2000) -> bool:
    for _ in range(max_ticks):
        if condition():
            return True
        game.on_tick()
    return condition()


def sound_names(user: MockUser) -> list[str]:
    return [message.data["name"] for message in user.messages if message.type == "play_sound"]


def speech_texts(user: MockUser) -> list[str]:
    return [message.data["text"] for message in user.messages if message.type == "speak"]


def message_markers(user: MockUser) -> list[tuple[str, str]]:
    markers = []
    for message in user.messages:
        if message.type == "play_sound":
            markers.append((message.type, message.data["name"]))
        elif message.type == "speak":
            markers.append((message.type, message.data["text"]))
        else:
            markers.append((message.type, ""))
    return markers


def marker_index(markers: list[tuple[str, str]], message_type: str, text: str) -> int:
    for index, (current_type, marker_text) in enumerate(markers):
        if current_type == message_type and text in marker_text:
            return index
    raise AssertionError(f"Could not find {message_type} containing {text!r} in {markers!r}")


def assert_subsequence(sequence: list[str], expected: list[str]) -> None:
    index = 0
    for item in sequence:
        if item == expected[index]:
            index += 1
            if index == len(expected):
                return
    raise AssertionError(f"Did not find {expected!r} in order within {sequence!r}")


def preparation_sequence_events(game: DeadMansDeckGame):
    sequence = next(
        sequence
        for sequence in game.active_sequences
        if sequence.sequence_id == "deadmansdeck_preparation"
    )
    tick = 0
    events = []
    for beat in sequence.beats:
        for operation in beat.ops:
            events.append((tick, operation))
        tick += beat.delay_after_ticks
    return events


def visible_action_ids(game: DeadMansDeckGame, player) -> list[str]:
    return [entry.action.id for entry in game.get_all_visible_actions(player)]


def status_texts(user: MockUser) -> list[str]:
    return [getattr(item, "text", item) for item in user.menus["status_box"]["items"]]


def status_ids(user: MockUser) -> list[str | None]:
    return [getattr(item, "id", None) for item in user.menus["status_box"]["items"]]


def test_game_registration_and_metadata() -> None:
    game_cls = GameRegistry.get("deadmansdeck")
    assert game_cls is DeadMansDeckGame
    assert DeadMansDeckGame.get_name() == "Dead Man's Deck"
    assert DeadMansDeckGame.get_category() == "cards"
    assert DeadMansDeckGame.get_min_players() == 2
    assert DeadMansDeckGame.get_max_players() == 4
    assert DeadMansDeckGame.get_supported_leaderboards() == ["wins", "rating", "games_played"]


def test_game_delegates_bot_logic_to_bot_module() -> None:
    game = make_game(2)
    player = game.players[0]

    assert game.bot_think(player) == deadmansdeck_bot_think(game, player)


def test_bot_challenges_instead_of_forced_false_final_claim() -> None:
    game = make_game(2)
    bot = game.players[0]
    opponent = game.players[1]
    bot.is_bot = True
    game.status = "playing"
    game.game_active = True
    game.phase = PHASE_PLAYING
    game.target_rank = "king"
    game.set_turn_players([bot, opponent])
    bot.hand = [DeadMansDeckCard(id=1, rank="queen")]
    opponent.hand = [
        DeadMansDeckCard(id=2, rank="ace"),
        DeadMansDeckCard(id=3, rank="king"),
    ]
    game.last_claim = DeadMansDeckClaim(
        player_id=opponent.id,
        player_name=opponent.name,
        cards=[DeadMansDeckCard(id=4, rank="ace")],
        target_rank="king",
    )

    assert deadmansdeck_bot_think(game, bot) == "call_liar"
    assert bot.selected_card_ids == []


def test_bot_preserves_truthful_exit_card_in_two_player_endgame() -> None:
    random.seed(101)
    game = make_game(2)
    bot = game.players[0]
    opponent = game.players[1]
    bot.is_bot = True
    game.status = "playing"
    game.game_active = True
    game.phase = PHASE_PLAYING
    game.target_rank = "king"
    game.set_turn_players([bot, opponent])
    bot.hand = [
        DeadMansDeckCard(id=1, rank="queen"),
        DeadMansDeckCard(id=2, rank="king"),
    ]
    opponent.hand = [DeadMansDeckCard(id=3, rank="ace")]

    assert deadmansdeck_bot_think(game, bot) == "play_selected"

    selected = [card for card in bot.hand if card.id in bot.selected_card_ids]
    assert [card.rank for card in selected] == ["queen"]


def test_bot_finishes_truthfully_when_forced_challenge_is_good() -> None:
    random.seed(102)
    game = make_game(2)
    bot = game.players[0]
    opponent = game.players[1]
    bot.is_bot = True
    game.status = "playing"
    game.game_active = True
    game.phase = PHASE_PLAYING
    game.target_rank = "king"
    game.set_turn_players([bot, opponent])
    bot.hand = [
        DeadMansDeckCard(id=1, rank="king"),
        DeadMansDeckCard(id=2, rank="joker"),
    ]
    opponent.hand = [DeadMansDeckCard(id=3, rank="ace")]

    assert deadmansdeck_bot_think(game, bot) == "play_selected"

    selected = [card for card in bot.hand if card.id in bot.selected_card_ids]
    assert [card.rank for card in selected] == ["king", "joker"]


def test_bot_calls_overwhelmingly_unlikely_large_claim() -> None:
    random.seed(1)
    game = make_game(2)
    bot = game.players[0]
    opponent = game.players[1]
    bot.is_bot = True
    game.status = "playing"
    game.game_active = True
    game.phase = PHASE_PLAYING
    game.target_rank = "king"
    game.set_turn_players([bot, opponent])
    bot.hand = [
        DeadMansDeckCard(id=1, rank="king"),
        DeadMansDeckCard(id=2, rank="king"),
        DeadMansDeckCard(id=3, rank="king"),
        DeadMansDeckCard(id=4, rank="joker"),
        DeadMansDeckCard(id=5, rank="joker"),
    ]
    opponent.hand = [DeadMansDeckCard(id=6, rank="ace")]
    game.last_claim = DeadMansDeckClaim(
        player_id=opponent.id,
        player_name=opponent.name,
        cards=[
            DeadMansDeckCard(id=7, rank="ace"),
            DeadMansDeckCard(id=8, rank="queen"),
            DeadMansDeckCard(id=9, rank="queen"),
        ],
        target_rank="king",
    )

    assert deadmansdeck_bot_think(game, bot) == "call_liar"


def test_bot_uses_mixed_strategy_for_opening_three_card_claim() -> None:
    challenges = 0
    passes = 0

    for seed in range(80):
        random.seed(seed)
        game = make_game(2)
        bot = game.players[0]
        opponent = game.players[1]
        bot.is_bot = True
        game.status = "playing"
        game.game_active = True
        game.phase = PHASE_PLAYING
        game.target_rank = "king"
        game.set_turn_players([bot, opponent])
        bot.hand = [
            DeadMansDeckCard(id=1, rank="king"),
            DeadMansDeckCard(id=2, rank="queen"),
            DeadMansDeckCard(id=3, rank="queen"),
            DeadMansDeckCard(id=4, rank="ace"),
            DeadMansDeckCard(id=5, rank="ace"),
        ]
        opponent.hand = [
            DeadMansDeckCard(id=6, rank="ace"),
            DeadMansDeckCard(id=7, rank="queen"),
        ]
        game.last_claim = DeadMansDeckClaim(
            player_id=opponent.id,
            player_name=opponent.name,
            cards=[
                DeadMansDeckCard(id=8, rank="ace"),
                DeadMansDeckCard(id=9, rank="queen"),
                DeadMansDeckCard(id=10, rank="queen"),
            ],
            target_rank="king",
        )

        action = deadmansdeck_bot_think(game, bot)
        if action == "call_liar":
            challenges += 1
        elif action == "play_selected":
            passes += 1

    assert 20 <= challenges <= 60
    assert passes > 0


def test_card_count_action_and_keybind_are_available() -> None:
    game = make_game(3)
    game.status = "playing"
    game.phase = PHASE_PLAYING
    game.players[0].hand = [
        DeadMansDeckCard(id=1, rank="king"),
        DeadMansDeckCard(id=2, rank="ace"),
    ]
    game.players[1].hand = [DeadMansDeckCard(id=3, rank="queen")]
    game.players[2].eliminated = True
    game.players[2].hand = []

    player = game.players[0]
    user = game.get_user(player)
    user.clear_messages()
    game.execute_action(player, "read_card_counts")

    texts = status_texts(user)
    assert "Player1: 2 cards left." in texts
    assert "Player2: 1 card left." in texts
    assert "Player3: eliminated." in texts
    assert status_ids(user) == ["cards:p1", "cards:p2", "cards:p3"]
    assert user.menus["status_box"]["selection_id"] == "cards:p1"

    game.players[1].hand.append(DeadMansDeckCard(id=4, rank="ace"))
    game.refresh_menus()
    game.flush_menus()

    assert "Player2: 2 cards left." in status_texts(user)

    card_count_keybinds = game._keybinds["e"]
    assert any(
        keybind.actions == ["read_card_counts"]
        and keybind.state == KeybindState.ACTIVE
        and keybind.include_spectators
        for keybind in card_count_keybinds
    )


def test_touch_info_actions_keep_card_counts_in_logical_order() -> None:
    game = make_game(2)
    player = game.players[0]
    user = game.get_user(player)
    user.client_type = "web"

    action_set = game.create_standard_action_set(player)
    target = [
        "read_hand",
        "read_table",
        "read_card_counts",
        "read_revolvers",
        "whose_turn",
        "whos_at_table",
    ]
    ordered_target = [action_id for action_id in action_set._order if action_id in target]

    assert ordered_target == target


def test_challenge_loser_starts_next_round_when_alive() -> None:
    game = make_game(3)
    game.status = "playing"
    game.game_active = True
    game.round_order_ids = [player.id for player in game.players]
    game.next_round_starter_id = game.players[1].id

    game._start_round()

    assert game.round_order_ids[0] == game.players[1].id


def test_eliminated_challenge_loser_hands_start_to_next_alive_player() -> None:
    game = make_game(3)
    game.status = "playing"
    game.game_active = True
    game.round_order_ids = [player.id for player in game.players]
    game.players[1].eliminated = True
    game.next_round_starter_id = game.players[1].id

    game._start_round()

    assert game.round_order_ids[0] == game.players[2].id
    assert game.players[1].id not in game.round_order_ids


def test_hand_is_sorted_king_to_ace_with_jokers_last() -> None:
    game = make_game(2)
    game.status = "playing"
    game.phase = PHASE_PLAYING
    game.set_turn_players(game.players)
    player = game.current_player
    player.hand = [
        DeadMansDeckCard(id=4, rank="ace"),
        DeadMansDeckCard(id=1, rank="joker"),
        DeadMansDeckCard(id=3, rank="queen"),
        DeadMansDeckCard(id=2, rank="king"),
        DeadMansDeckCard(id=5, rank="king"),
    ]

    game.refresh_menus(player)
    game.flush_menus()
    turn_set = game.get_action_set(player, "turn")
    assert turn_set is not None

    assert [card.rank for card in player.hand] == [
        "king",
        "king",
        "queen",
        "ace",
        "joker",
    ]
    assert [
        action_id for action_id in turn_set._order if action_id.startswith("select_card_")
    ] == [
        "select_card_2",
        "select_card_5",
        "select_card_3",
        "select_card_4",
        "select_card_1",
    ]


def test_card_buttons_stay_visible_out_of_turn_and_speak_error() -> None:
    game = make_game(2)
    game.status = "playing"
    game.phase = PHASE_PLAYING
    game.set_turn_players(game.players)
    other = next(player for player in game.players if player != game.current_player)
    other.hand = [DeadMansDeckCard(id=21, rank="king")]
    game.refresh_menus(other)
    game.flush_menus()

    assert "select_card_21" in visible_action_ids(game, other)

    user = game.get_user(other)
    user.clear_messages()
    game.execute_action(other, "select_card_21")

    assert "turn" in user.get_last_spoken().lower()
    assert other.selected_card_ids == []


def test_card_buttons_stay_visible_across_non_transition_phases() -> None:
    game = make_game(2)
    game.status = "playing"
    game.game_active = True
    game.set_turn_players(game.players)
    player = game.current_player
    player.hand = [
        DeadMansDeckCard(id=22, rank="king"),
        DeadMansDeckCard(id=23, rank="queen"),
    ]

    for phase in [PHASE_PLAYING, PHASE_CLAIM, PHASE_CHALLENGE, PHASE_ROULETTE]:
        game.phase = phase
        game.refresh_menus(player)
        game.flush_menus()
        visible_ids = visible_action_ids(game, player)
        assert "select_card_22" in visible_ids
        assert "select_card_23" in visible_ids

    game.phase = PHASE_CHALLENGE
    user = game.get_user(player)
    user.clear_messages()
    game.execute_action(player, "select_card_22")

    assert player.selected_card_ids == []
    assert "sequence" in user.get_last_spoken().lower()


def test_round_transition_clears_old_cards_until_new_hand_is_dealt() -> None:
    random.seed(23)
    game = make_game(2)
    game.status = "playing"
    game.game_active = True
    for index, player in enumerate(game.players):
        player.hand = [DeadMansDeckCard(id=40 + index, rank="king")]
    game.refresh_menus()
    game.flush_menus()
    assert any(
        action_id.startswith("select_card_")
        for action_id in visible_action_ids(game, game.players[0])
    )

    game._start_round()

    assert game.phase == PHASE_ROUND_START
    assert all(not player.hand for player in game.players)
    assert not any(
        action_id.startswith("select_card_")
        for action_id in visible_action_ids(game, game.players[0])
    )

    assert advance_until(game, lambda: game.phase == PHASE_PLAYING, max_ticks=120)
    assert all(len(player.hand) == 5 for player in game.players)
    assert any(
        action_id.startswith("select_card_")
        for action_id in visible_action_ids(game, game.players[0])
    )


def test_selected_cards_stay_visible_at_limit_and_fourth_card_speaks_error() -> None:
    game = make_game(2)
    game.status = "playing"
    game.phase = PHASE_PLAYING
    game.set_turn_players(game.players)
    player = game.current_player
    player.hand = [
        DeadMansDeckCard(id=31, rank="king"),
        DeadMansDeckCard(id=32, rank="queen"),
        DeadMansDeckCard(id=33, rank="ace"),
        DeadMansDeckCard(id=34, rank="joker"),
    ]
    player.selected_card_ids = [31, 32, 33]
    game.refresh_menus(player)
    game.flush_menus()

    visible_ids = visible_action_ids(game, player)
    assert all(f"select_card_{card.id}" in visible_ids for card in player.hand)

    user = game.get_user(player)
    user.clear_messages()
    game.execute_action(player, "select_card_34")

    assert len(player.selected_card_ids) == MAX_CLAIM_CARDS
    assert "at most three" in user.get_last_spoken()


def test_required_exclusive_sound_constants_match_asset_plan() -> None:
    expected = {
        SOUND_MUSIC,
        SOUND_INTRO,
        SOUND_ROUND_START,
        SOUND_REVOLVER_SPIN,
        SOUND_COCK,
        SOUND_EMPTY_CLICK,
        *SOUND_EMPTY_CASINGS,
        SOUND_GUNSHOT,
        SOUND_BULLET_HIT,
        *SOUND_BODY_FALLS,
        SOUND_GAME_OVER,
    }
    assert all(sound.startswith("game_deadmansdeck/") for sound in expected)
    assert len(SOUND_EMPTY_CASINGS) == 3
    assert len(SOUND_BODY_FALLS) == 2


def test_audio_delays_are_locked() -> None:
    assert AUDIO_DURATIONS_TICKS["game_cards/shuffle1.ogg"] == 27
    assert AUDIO_DURATIONS_TICKS["game_cards/shuffle2.ogg"] == 28
    assert AUDIO_DURATIONS_TICKS["game_cards/shuffle3.ogg"] == 26
    assert AUDIO_DURATIONS_TICKS["game_cards/play1.ogg"] == 18
    assert AUDIO_DURATIONS_TICKS["game_cards/play2.ogg"] == 21
    assert AUDIO_DURATIONS_TICKS["game_cards/play3.ogg"] == 21
    assert AUDIO_DURATIONS_TICKS["game_cards/play4.ogg"] == 21
    assert AUDIO_DURATIONS_TICKS[SOUND_REVEAL] == 22
    assert AUDIO_DURATIONS_TICKS[SOUND_CHALLENGE] == 45
    assert AUDIO_DURATIONS_TICKS[SOUND_CHALLENGE_SUCCESS] == 42
    assert AUDIO_DURATIONS_TICKS["game_coup/challengefail.ogg"] == 15
    assert AUDIO_DURATIONS_TICKS[SOUND_INTRO] == 160
    assert PREPARATION_INTRO_TICKS == 160
    assert AUDIO_DURATIONS_TICKS[SOUND_ROUND_START] == 46
    assert AUDIO_DURATIONS_TICKS[SOUND_REVOLVER_SPIN] == 60
    assert AUDIO_DURATIONS_TICKS[SOUND_COCK] == 20
    assert COCK_TO_OUTCOME_DELAY_TICKS == 40
    assert REVOLVER_PREPARATION_DELAY_TICKS == 80
    assert LATEST_REVOLVER_PREPARATION_START_TICKS == 80
    assert AUDIO_DURATIONS_TICKS[SOUND_EMPTY_CLICK] == 13
    assert AUDIO_DURATIONS_TICKS["game_deadmansdeck/empty_casing1.ogg"] == 69
    assert AUDIO_DURATIONS_TICKS["game_deadmansdeck/empty_casing2.ogg"] == 64
    assert AUDIO_DURATIONS_TICKS["game_deadmansdeck/empty_casing3.ogg"] == 70
    assert AUDIO_DURATIONS_TICKS[SOUND_GUNSHOT] == 60
    assert AUDIO_DURATIONS_TICKS[SOUND_BULLET_HIT] == 22
    assert AUDIO_DURATIONS_TICKS["game_deadmansdeck/body_fall1.ogg"] == 14
    assert AUDIO_DURATIONS_TICKS["game_deadmansdeck/body_fall2.ogg"] == 13
    assert AUDIO_DURATIONS_TICKS[SOUND_GAME_OVER] == 87


def test_grouped_sound_pools_can_select_every_variant() -> None:
    random.seed(60)
    game = DeadMansDeckGame()

    casings = {game._random_empty_casing_sound() for _ in range(100)}
    body_falls = {game._random_body_fall_sound() for _ in range(100)}

    assert casings == set(SOUND_EMPTY_CASINGS)
    assert body_falls == set(SOUND_BODY_FALLS)


def test_preparation_pan_values_match_player_counts() -> None:
    game = DeadMansDeckGame()

    assert game._preparation_pan_values(2) == [-25, 25]
    assert game._preparation_pan_values(3) == [-50, 0, 50]
    assert game._preparation_pan_values(4) == [-50, -17, 17, 50]


def test_preparation_intro_and_revolver_loads_are_concurrent() -> None:
    random.seed(70)
    game = make_game(4)
    game.on_start()

    events = preparation_sequence_events(game)
    intro_ticks = [
        tick
        for tick, operation in events
        if operation.kind == "sound" and operation.sound == SOUND_INTRO
    ]
    spin_events = [
        (tick, operation.pan)
        for tick, operation in events
        if operation.kind == "sound" and operation.sound == SOUND_REVOLVER_SPIN
    ]
    mark_ticks = [
        tick
        for tick, operation in events
        if operation.kind == "callback"
        and operation.callback_id == "mark_revolver_prepared"
    ]
    announce_ticks = [
        tick
        for tick, operation in events
        if operation.kind == "callback"
        and operation.callback_id == "announce_prepare_revolvers"
    ]
    music_ticks = [
        tick
        for tick, operation in events
        if operation.kind == "callback"
        and operation.callback_id == "start_preparation_music"
    ]
    finish_ticks = [
        tick
        for tick, operation in events
        if operation.kind == "callback"
        and operation.callback_id == "finish_preparation"
    ]

    assert intro_ticks == [0]
    assert announce_ticks == [0]
    assert len(spin_events) == 4
    assert sorted(pan for _tick, pan in spin_events) == [-50, -17, 17, 50]
    assert len({tick for tick, _pan in spin_events}) == len(spin_events)
    assert all(
        1 <= tick <= LATEST_REVOLVER_PREPARATION_START_TICKS
        for tick, _pan in spin_events
    )
    assert sorted(mark_ticks) == sorted(
        tick + REVOLVER_PREPARATION_DELAY_TICKS
        for tick, _pan in spin_events
    )
    assert max(mark_ticks) <= PREPARATION_INTRO_TICKS
    assert music_ticks == [PREPARATION_INTRO_TICKS]
    assert finish_ticks == [PREPARATION_INTRO_TICKS]


def test_preparation_music_and_round_start_are_public() -> None:
    random.seed(10)
    game = make_game(3)
    game.on_start()

    assert all(
        not any(
            message.type == "play_music" and message.data["name"] == SOUND_MUSIC
            for message in game.get_user(p).messages
        )
        for p in game.players
    )
    for player in game.players:
        spoken = speech_texts(game.get_user(player))
        assert spoken.count("The revolvers are being prepared.") == 1

    reached = advance_until(game, lambda: game.phase == PHASE_PLAYING and game.round == 1)
    assert reached
    assert all(player.revolver_prepared for player in game.players)

    for player in game.players:
        user = game.get_user(player)
        sounds = sound_names(user)
        assert SOUND_INTRO in sounds
        assert sounds.count(SOUND_REVOLVER_SPIN) == 3
        assert SOUND_ROUND_START in sounds
        assert any(
            message.type == "play_music" and message.data["name"] == SOUND_MUSIC
            for message in user.messages
        )
        assert any(sound in sounds for sound in ("game_cards/shuffle1.ogg", "game_cards/shuffle2.ogg", "game_cards/shuffle3.ogg"))


def test_preparation_sequence_resumes_after_restore() -> None:
    random.seed(11)
    game = make_game(2)
    game.on_start()
    for _ in range(30):
        game.on_tick()

    payload = game.to_json()
    restored = DeadMansDeckGame.from_json(payload)
    for index, player in enumerate(restored.players):
        restored.attach_user(player.id, MockUser(player.name, uuid=f"p{index + 1}"))

    reached = advance_until(restored, lambda: restored.phase == PHASE_PLAYING and restored.round == 1)
    assert reached
    assert all(player.revolver_prepared for player in restored.players)


def test_claim_tts_is_sent_with_play_sound() -> None:
    random.seed(18)
    game = make_game(2)
    game.on_start()
    assert advance_until(game, lambda: game.phase == PHASE_PLAYING and game.round == 1)

    player = game.current_player
    player.hand = [DeadMansDeckCard(id=201, rank=game.target_rank)]
    player.selected_card_ids = [201]
    user = game.get_user(player)
    user.clear_messages()

    game.execute_action(player, "play_selected")
    markers = message_markers(user)
    play_index = next(
        index
        for index, (message_type, marker) in enumerate(markers)
        if message_type == "play_sound" and marker in SOUND_PLAYS
    )
    claim_index = marker_index(markers, "speak", "You claim")

    assert claim_index == play_index + 1


def test_player_running_out_of_cards_is_announced_with_claim() -> None:
    random.seed(181)
    game = make_game(2)
    game.on_start()
    assert advance_until(game, lambda: game.phase == PHASE_PLAYING and game.round == 1)

    player = game.current_player
    player.hand = [DeadMansDeckCard(id=205, rank=game.target_rank)]
    player.selected_card_ids = [205]
    for table_player in game.players:
        game.get_user(table_player).clear_messages()

    game.execute_action(player, "play_selected")

    for table_player in game.players:
        text = " ".join(speech_texts(game.get_user(table_player)))
        if table_player == player:
            assert "You have no cards left" in text
        else:
            assert f"{player.name} has no cards left" in text


def test_unchallenged_claim_has_no_repetitive_tts() -> None:
    random.seed(19)
    game = make_game(3)
    game.on_start()
    assert advance_until(game, lambda: game.phase == PHASE_PLAYING and game.round == 1)

    first = game.current_player
    first.hand = [DeadMansDeckCard(id=211, rank=game.target_rank)]
    first.selected_card_ids = [211]
    game.execute_action(first, "play_selected")
    assert advance_until(game, lambda: game.phase == PHASE_PLAYING and game.current_player != first)

    second = game.current_player
    second.hand = [DeadMansDeckCard(id=212, rank=game.target_rank)]
    second.selected_card_ids = [212]
    for player in game.players:
        game.get_user(player).clear_messages()

    game.execute_action(second, "play_selected")
    assert all(
        "unchallenged" not in text and "goes unchallenged" not in text
        for player in game.players
        for text in speech_texts(game.get_user(player))
    )


def test_bluff_challenge_uses_ordered_public_sounds() -> None:
    random.seed(20)
    game = make_game(2)
    game.on_start()
    assert advance_until(game, lambda: game.phase == PHASE_PLAYING and game.round == 1)

    alice = game.current_player
    bob = next(p for p in game.players if p != alice)
    game.target_rank = "king"
    alice.hand = [
        DeadMansDeckCard(id=101, rank="queen"),
        DeadMansDeckCard(id=103, rank="ace"),
    ]
    bob.hand = [DeadMansDeckCard(id=102, rank="king")]
    alice.selected_card_ids = [101]
    for player in game.players:
        game.get_user(player).clear_messages()

    game.execute_action(alice, "play_selected")
    assert advance_until(game, lambda: game.phase == PHASE_PLAYING and game.current_player == bob)
    game.execute_action(bob, "call_liar")
    markers = message_markers(game.get_user(bob))
    assert marker_index(markers, "speak", "You call") == marker_index(markers, "play_sound", SOUND_CHALLENGE) + 1
    assert advance_until(game, lambda: game.phase != "challenge", max_ticks=200)

    for player in game.players:
        user = game.get_user(player)
        sounds = sound_names(user)
        markers = message_markers(user)
        assert any(sound in sounds for sound in SOUND_PLAYS)
        assert_subsequence(
            sounds,
            [SOUND_CHALLENGE, SOUND_REVEAL, SOUND_CHALLENGE_SUCCESS],
        )
        assert marker_index(markers, "speak", "revealed") == marker_index(markers, "play_sound", SOUND_REVEAL) + 1
        if player == bob:
            result_text = "You caught"
        elif player == alice:
            result_text = "caught your bluff"
        else:
            result_text = "caught"
        assert marker_index(markers, "speak", result_text) == marker_index(markers, "play_sound", SOUND_CHALLENGE_SUCCESS) + 1


def test_roulette_survival_uses_empty_click_and_random_casing_publicly() -> None:
    random.seed(30)
    game = make_game(2)
    game.status = "playing"
    game.game_active = True
    game.phase = PHASE_PLAYING
    player = game.players[0]
    player.bullet_position = 5
    player.chamber_index = 0
    for table_player in game.players:
        game.get_user(table_player).clear_messages()

    game._start_roulette_sequence(player)
    for _ in range(COCK_TO_OUTCOME_DELAY_TICKS - 1):
        game.on_tick()
    assert all(SOUND_EMPTY_CLICK not in sound_names(game.get_user(p)) for p in game.players)

    game.on_tick()
    for table_player in game.players:
        markers = message_markers(game.get_user(table_player))
        assert marker_index(markers, "speak", "Empty chamber") == marker_index(markers, "play_sound", SOUND_EMPTY_CLICK) + 2

    assert advance_until(game, lambda: game.round == 1, max_ticks=120)
    assert player.chamber_index == 1

    for table_player in game.players:
        sounds = sound_names(game.get_user(table_player))
        assert_subsequence(sounds, [SOUND_COCK, SOUND_EMPTY_CLICK])
        assert any(sound in sounds for sound in SOUND_EMPTY_CASINGS)


def test_roulette_elimination_uses_gunshot_hit_and_body_fall_publicly() -> None:
    random.seed(40)
    game = make_game(2)
    game.status = "playing"
    game.game_active = True
    game.phase = PHASE_PLAYING
    player = game.players[0]
    player.bullet_position = 0
    player.chamber_index = 0
    for table_player in game.players:
        game.get_user(table_player).clear_messages()

    game._start_roulette_sequence(player)
    for _ in range(COCK_TO_OUTCOME_DELAY_TICKS - 1):
        game.on_tick()
    assert all(SOUND_GUNSHOT not in sound_names(game.get_user(p)) for p in game.players)

    game.on_tick()
    assert advance_until(game, lambda: player.eliminated, max_ticks=120)
    assert advance_until(
        game,
        lambda: any(
            sound in sound_names(game.get_user(table_player))
            for table_player in game.players
            for sound in SOUND_BODY_FALLS
        ),
        max_ticks=120,
    )

    for table_player in game.players:
        user = game.get_user(table_player)
        sounds = sound_names(user)
        markers = message_markers(user)
        assert_subsequence(sounds, [SOUND_COCK, SOUND_GUNSHOT])
        assert SOUND_BULLET_HIT in sounds
        assert marker_index(markers, "speak", "eliminated") == marker_index(markers, "play_sound", SOUND_BULLET_HIT) + 1
        assert any(sound in sounds for sound in SOUND_BODY_FALLS)


def test_read_table_and_revolvers_use_live_status_boxes() -> None:
    random.seed(45)
    game = make_game(2)
    game.on_start()
    assert advance_until(game, lambda: game.phase == PHASE_PLAYING and game.round == 1)

    player = game.players[0]
    user = game.get_user(player)
    user.clear_messages()

    game.execute_action(player, "read_table")
    table_texts = status_texts(user)
    assert any("Round" in text for text in table_texts)
    assert any("Current turn" in text for text in table_texts)
    assert user.menus["status_box"]["selection_id"] == "round"

    game.execute_action(player, "read_revolvers")
    revolver_texts = status_texts(user)
    assert revolver_texts[0] == "Revolver status"
    assert status_ids(user)[0] == "header"
    assert any(text.startswith("Player1:") for text in revolver_texts)
    assert user.menus["status_box"]["selection_id"] == "header"

    assert [message.type for message in user.messages] == ["show_menu", "show_menu"]


def test_read_table_before_round_target_is_set_uses_clear_status() -> None:
    game = make_game(2)
    game.status = "playing"
    game.game_active = True
    game.phase = "preparing"
    player = game.players[0]
    user = game.get_user(player)
    user.clear_messages()

    game.execute_action(player, "read_table")

    assert any("Target: not set yet" in text for text in status_texts(user))


def test_game_over_tts_is_sent_with_sound() -> None:
    game = make_game(2)
    winner = game.players[0]
    game.status = "playing"
    game.game_active = True
    for player in game.players:
        game.get_user(player).clear_messages()

    game._start_game_over_sequence(winner)

    for player in game.players:
        markers = message_markers(game.get_user(player))
        marker = "You are the last player" if player == winner else "wins Dead Man's Deck"
        assert marker_index(markers, "speak", marker) == marker_index(markers, "play_sound", SOUND_GAME_OVER) + 1


def test_deadmansdeck_localization_parity() -> None:
    locale_dir = Path(__file__).parents[1] / "locales"
    en_keys = {
        line.split("=", 1)[0].strip()
        for line in (locale_dir / "en" / "deadmansdeck.ftl").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#") and "=" in line
    }
    vi_keys = {
        line.split("=", 1)[0].strip()
        for line in (locale_dir / "vi" / "deadmansdeck.ftl").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#") and "=" in line
    }
    assert en_keys == vi_keys


def test_bot_game_completes() -> None:
    random.seed(50)
    game = DeadMansDeckGame()
    game.setup_keybinds()
    for index in range(2):
        bot = Bot(f"Bot{index + 1}", uuid=f"b{index + 1}")
        game.add_player(bot.username, bot)
    game.host = "Bot1"
    game.on_start()

    reached = advance_until(game, lambda: game.status == "finished" or game._destroyed, max_ticks=20000)
    assert reached


def test_natural_voices_option_plays_narrator_catalog() -> None:
    random.seed(77)
    game = make_game(2)
    game.options.natural_voices = True
    game.on_start()

    assert advance_until(game, lambda: game.phase == PHASE_PLAYING and game.round == 1, max_ticks=700)
    target_voice = SOUND_VOICE_TARGETS[game.target_rank]
    for player in game.players:
        sounds = sound_names(game.get_user(player))
        assert_subsequence(sounds, [SOUND_INTRO, SOUND_VOICE_INTRO, SOUND_ROUND_START, target_voice])

    # Bluff challenge + roulette survival + next round
    alice = game.current_player
    bob = next(p for p in game.players if p != alice)
    game.target_rank = "king"
    alice.bullet_position = 5
    alice.chamber_index = 0
    alice.hand = [
        DeadMansDeckCard(id=301, rank="queen"),
        DeadMansDeckCard(id=302, rank="ace"),
    ]
    bob.hand = [DeadMansDeckCard(id=303, rank="king")]
    alice.selected_card_ids = [301]
    for player in game.players:
        game.get_user(player).clear_messages()

    game.execute_action(alice, "play_selected")
    assert advance_until(game, lambda: game.phase == PHASE_PLAYING and game.current_player == bob)
    game.execute_action(bob, "call_liar")
    assert advance_until(game, lambda: game.phase == PHASE_PLAYING and game.round == 2, max_ticks=1200)

    for player in game.players:
        sounds = sound_names(game.get_user(player))
        assert_subsequence(
            sounds,
            [
                SOUND_CHALLENGE,
                SOUND_VOICE_CHALLENGE,
                SOUND_REVEAL,
                SOUND_CHALLENGE_SUCCESS,
                SOUND_VOICE_BLUFF_CAUGHT,
                SOUND_COCK,
                SOUND_VOICE_ROULETTE_COCK,
                SOUND_EMPTY_CLICK,
                SOUND_VOICE_ROULETTE_SURVIVE,
            ],
        )

    # Forced truthful challenge + roulette elimination + game over
    starter = game.current_player
    challenger = next(p for p in game.players if p != starter)
    game.target_rank = "ace"
    challenger.bullet_position = 0
    challenger.chamber_index = 0
    starter.hand = [DeadMansDeckCard(id=401, rank="ace")]
    challenger.hand = []
    starter.selected_card_ids = [401]
    for player in game.players:
        game.get_user(player).clear_messages()

    game.execute_action(starter, "play_selected")
    assert advance_until(game, lambda: game.status == "finished" or game._destroyed, max_ticks=1500)

    for player in game.players:
        sounds = sound_names(game.get_user(player))
        assert_subsequence(
            sounds,
            [
                SOUND_CHALLENGE,
                SOUND_VOICE_CHALLENGE_FORCED,
                SOUND_REVEAL,
                SOUND_VOICE_TRUTH_REVEALED,
                SOUND_COCK,
                SOUND_VOICE_ROULETTE_COCK,
                SOUND_GUNSHOT,
                SOUND_VOICE_ROULETTE_DEATH,
                SOUND_GAME_OVER,
                SOUND_VOICE_GAME_OVER,
            ],
        )

