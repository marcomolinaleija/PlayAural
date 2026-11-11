"""Integration and extended-board regressions for Mexican Monopoly."""

import asyncio
import json
import random
import secrets
from collections import Counter
from dataclasses import replace

import pytest
import websockets

from server.core.server import Server, VERSION
from server.documentation.manager import DocumentationManager
from server.game_utils.sequence_runner_mixin import SequenceBeat
from server.games.mexicopoly.compact_board import AIRPORTS, METRO_STATIONS, MEXICO_BOARD, REGIONS
from server.games.mexicopoly.game import MexicopolyGame, MexicopolyOptions
from server.games.monopoly import audio as game_audio
from server.games.monopoly.boards import get_board, get_board_ids, validate_board
from server.games.monopoly.game import MonopolyGame, PHASE_AWAIT_ROLL, PHASE_PROPERTY
from server.games.monopoly.models import PropertyState
from server.games.monopoly.rules import calculate_rent, can_build, unmortgage_cost
from server.games.registry import GameRegistry
from server.messages.localization import Localization
from server.tables.table import Table
from server.users.bot import Bot
from server.users.test_user import MockUser


@pytest.fixture(autouse=True)
def fast_audio(monkeypatch):
    """Skip only presentation delays; exercise the actual sequences and bots."""
    monkeypatch.setattr(game_audio, "sound_ticks", lambda sound: 0)
    for name in (
        "ROLL_TO_LANDING_PAUSE_TICKS", "LANDING_TO_EVENT_PAUSE_TICKS",
        "OPENING_ROLL_GAP_TICKS",
    ):
        monkeypatch.setattr(game_audio, name, 0)
    monkeypatch.setattr(game_audio, "BOT_ACTION_DELAY_MIN_TICKS", 1)
    monkeypatch.setattr(game_audio, "BOT_ACTION_DELAY_MAX_TICKS", 1)
    state = random.getstate()
    random.seed(20261101)
    yield
    random.setstate(state)


def drain(game, tag):
    for _ in range(2000):
        if not game.has_active_sequence(tag=tag):
            game.flush_menus()
            return
        game.on_tick()
    raise AssertionError(f"Sequence did not finish: {tag}")


def make_game(*, locale="en", client_type="python", start=True, bots=False, count=2):
    game = MexicopolyGame()
    game.setup_keybinds()
    for index in range(count):
        name = f"User{index}"
        user = Bot(name, uuid=f"mex-{index}") if bots else MockUser(
            name, locale=locale, uuid=f"mex-{index}"
        )
        user.client_type = client_type
        game.add_player(name, user)
    game.host = game.players[0].name
    if start:
        game.on_start()
        drain(game, "monopoly_intro")
    return game


def force_actor(game):
    player = game.players[0]
    game.current_player = player
    game.phase = PHASE_AWAIT_ROLL
    game.decision_player_id = player.id
    return player


def test_independent_registration_options_and_classic_compatibility():
    assert GameRegistry.get("mexicopoly") is MexicopolyGame
    assert GameRegistry.get("monopoly") is MonopolyGame
    assert MexicopolyGame.get_category() == "board"
    assert (MexicopolyGame.get_min_players(), MexicopolyGame.get_max_players()) == (2, 8)
    assert MexicopolyGame.get_supported_leaderboards() == ["wins", "rating", "games_played"]
    assert MexicopolyGame().supports_score_actions() is False
    assert "mexico80" not in get_board_ids()
    assert len(get_board("mexico").spaces) == len(get_board("standard").spaces) == 40
    options = MexicopolyOptions()
    assert options.board_id == "mexico50"
    assert "board_id" not in options.get_option_metas()
    assert len(options.get_option_metas()) == 10
    assert options.economic_mode == "normal"
    assert options.automatic_rent is True
    assert options.auctions_enabled is True
    assert options.auction_timer == "5"
    assert options.turn_timer == "0"
    assert all(getattr(options, key) is False for key in ("free_parking_cash", "double_salary_on_go", "no_rent_in_jail", "buy_after_passing_go", "snake_eyes_bonus"))
    game = make_game(start=False)
    assert game.find_action(game.players[0], "set_board_id") is None
    game.options.board_id = "standard"
    assert ("monopoly-error-unsupported-board", {"board": "standard"}) in game.validate_start()


def test_complete_private_board_and_geographic_membership():
    validate_board(MEXICO_BOARD)
    assert len(MEXICO_BOARD.spaces) == len({s.id for s in MEXICO_BOARD.spaces}) == 50
    assert Counter(s.kind for s in MEXICO_BOARD.spaces) == {
        "street": 24, "transit": 8, "utility": 3, "chance": 5,
        "community": 4, "tax": 2, "go": 1, "jail": 1,
        "go_to_jail": 1, "free_parking": 1,
    }
    assert [MEXICO_BOARD.spaces[i].id for i in (0, 13, 25, 38)] == [
        "go", "jail", "free_parking", "go_to_jail"
    ]
    assert len(REGIONS) == 8
    for group_id, cities in REGIONS:
        assert tuple(s.id for s in MEXICO_BOARD.group_spaces(group_id)) == cities
    assert MEXICO_BOARD.space("aguascalientes").group_id == "orange"
    assert MEXICO_BOARD.space("toluca").group_id == "yellow"
    assert MEXICO_BOARD.space("tijuana").group_id == "brown"
    assert MEXICO_BOARD.space("juzgado").group_id == "juzgado"
    for position, identifier in {**METRO_STATIONS, **AIRPORTS}.items():
        assert MEXICO_BOARD.spaces[position].id == identifier
    assert len(MEXICO_BOARD.chance_cards) == 26 and len(MEXICO_BOARD.community_cards) == 40


def test_cards_keep_effects_but_own_their_text_and_destinations():
    classic = get_board("standard")
    for private_deck, classic_deck in (
        (MEXICO_BOARD.chance_cards, classic.chance_cards),
        (MEXICO_BOARD.community_cards, classic.community_cards),
    ):
        for card, original in zip(private_deck[:16], classic_deck, strict=True):
            if card.action in ("collect", "collect_each"):
                assert card.amount >= original.amount
            else:
                assert replace(
                    card, text_key=original.text_key,
                    destination_id=original.destination_id,
                ) == original
        for card in private_deck:
            assert card.text_key.startswith("mexicopoly-card-")
            if card.destination_id:
                assert MEXICO_BOARD.space(card.destination_id)


@pytest.mark.parametrize("locale", ["en", "vi", "es"])
def test_all_content_is_localized_and_manual_is_available(locale):
    keys = {
        "game-name-mexicopoly", MEXICO_BOARD.name_key,
        MEXICO_BOARD.description_key, MEXICO_BOARD.currency_key,
        *vars(MEXICO_BOARD.terminology).values(),
        *(s.name_key for s in MEXICO_BOARD.spaces),
        *(g.name_key for g in MEXICO_BOARD.property_groups),
        *(c.text_key for c in (*MEXICO_BOARD.chance_cards, *MEXICO_BOARD.community_cards)),
    }
    assert all(Localization.has_message(locale, key) for key in keys)
    names = " ".join(Localization.get(locale, s.name_key) for s in MEXICO_BOARD.spaces)
    assert "aifa" not in names.casefold() and "felipe" not in names.casefold()
    assert "Apodaca" in names and "Guadalajara" in names
    manual = DocumentationManager().get_document("games/mexicopoly", locale)
    assert manual and "50" in manual and "24" in manual


@pytest.mark.parametrize("locale", ["en", "vi", "es"])
@pytest.mark.parametrize("client_type", ["python", "web", "mobile"])
def test_shared_lobby_touch_information_and_bonus_help(locale, client_type):
    game = make_game(locale=locale, client_type=client_type, start=False)
    player = game.players[0]
    assert game.validate_start() == []
    description = game._option_description_text(player, "toggle_snake_eyes_bonus")
    assert "500" in description
    assert "peso" in description.casefold() or "MX$" in description
    game.on_start()
    drain(game, "monopoly_intro")
    game.before_menu_build(player)
    assert len(game.property_states) == 35
    assert player.cash == 3000
    assert (game.bank_houses, game.bank_hotels) == (64, 24)
    for action in ("read_board", "read_property_groups", "read_cash", "read_status"):
        assert game.find_action(player, action) is not None
    for card in (*MEXICO_BOARD.chance_cards, *MEXICO_BOARD.community_cards):
        text = game._card_text(locale, card)
        assert text != card.text_key and "{" not in text
    game._action_read_board(player, "read_board")
    user = game.get_user(player)
    rows = user.get_current_menu_items("status_box")
    assert len([row for row in rows if row.id and row.id.startswith("space:")]) == 50


def test_human_start_validation_and_forged_classic_board_action():
    game = make_game(start=False, bots=True)
    assert "action-start-needs-human-player" in game.validate_start()
    human_game = make_game(start=False)
    player = human_game.players[0]
    human_game.execute_action(player, "set_board_id", "standard")
    assert human_game.options.board_id == "mexico50"


def test_move_wraps_at_fifty_and_collects_only_at_go():
    game = make_game()
    player = force_actor(game)
    player.position = 39
    game._move_by(player, 4, collect_go=True, resolve_landing=False)
    assert player.position == 43 and player.cash == 3000
    player.position = 49
    game._move_by(player, 4, collect_go=True, resolve_landing=False)
    assert player.position == 3 and player.cash == 3400
    assert game._nearest_space_id(49, "transit") == "cuauhtemoc_metrorrey"
    assert game._nearest_space_id(36, "utility") == "water"


def test_city_purchase_and_jail_use_the_extended_board():
    game = make_game()
    player = force_actor(game)
    player.position = MEXICO_BOARD.space_index("aguascalientes")
    game._resolve_landing(player)
    assert game.phase == PHASE_PROPERTY
    space = game.board.space("aguascalientes")
    game._action_buy_property(player, "buy_property")
    game.flush_menus()
    assert game.property_states[space.id].owner_id == player.id
    assert player.cash == 3000 - space.price
    force_actor(game)
    before = player.cash
    player.position = 38
    game._resolve_landing(player)
    assert player.in_jail and player.position == 13
    assert player.cash == before


def test_separate_transport_groups_and_finite_construction():
    states = {s.id: PropertyState() for s in MEXICO_BOARD.spaces if s.price}
    metro = MEXICO_BOARD.space("cuauhtemoc_metrorrey")
    airport = MEXICO_BOARD.space("tijuana_airport")
    for number, station in enumerate(MEXICO_BOARD.group_spaces("metro"), 1):
        states[station.id].owner_id = "owner"
        assert calculate_rent(MEXICO_BOARD, states, metro, 7) == metro.rents[number - 1]
    states[airport.id].owner_id = "owner"
    assert calculate_rent(MEXICO_BOARD, states, airport, 7) == 120
    assert calculate_rent(MEXICO_BOARD, states, metro, 7, rent_multiplier=2) == 960
    states[metro.id].mortgaged = True
    assert calculate_rent(MEXICO_BOARD, states, metro, 7) == 0
    for city in MEXICO_BOARD.group_spaces("brown"):
        states[city.id].owner_id = "owner"
    assert can_build(MEXICO_BOARD, states, "tijuana", "owner", 64, 24) is None
    assert can_build(MEXICO_BOARD, states, "tijuana", "owner", 0, 24) == "monopoly-error-no-houses"
    states["tijuana"].buildings = 1
    assert can_build(MEXICO_BOARD, states, "tijuana", "owner", 63, 24) == "monopoly-error-build-evenly"
    assert unmortgage_cost(100) == 110


@pytest.mark.parametrize("brief", [False, True])
def test_actor_observer_speech_and_preferences_are_independent(brief):
    game = make_game()
    actor, observer = game.players
    actor_user, observer_user = game.get_user(actor), game.get_user(observer)
    actor_user.preferences.set_game_override("brief_announcements", "monopoly", not brief)
    actor_user.preferences.set_game_override("brief_announcements", "mexicopoly", brief)
    actor_user.clear_messages()
    observer_user.clear_messages()
    position = MEXICO_BOARD.space_index("chetumal")
    game._announce_move(actor, position, 6)
    personal = actor_user.get_last_spoken()
    public = observer_user.get_last_spoken()
    assert "Chetumal" in personal and "Chetumal" in public
    assert actor.name not in personal and actor.name in public
    assert (str(position + 1) in personal) is (not brief)
    assert str(position + 1) in public


def test_serialization_results_and_classic_games_stay_separate():
    game = make_game()
    player = game.players[0]
    player.position = 49
    game.property_states["chetumal"].owner_id = player.id
    game.property_states["chetumal"].mortgaged = True
    game.start_sequence(
        "save-probe", [SequenceBeat.pause(5)],
        tag="save-probe", start_immediately=False,
    )
    table = Table(table_id="mx80", game_type=game.get_type(), host=player.name)
    table.game = game
    table.save_game_state()
    restored = GameRegistry.get(table.game_type).from_json(table.game_json)
    restored.rebuild_runtime_state()
    assert type(restored) is MexicopolyGame
    assert type(restored.options) is MexicopolyOptions
    assert restored.board is MEXICO_BOARD and restored.players[0].position == 49
    assert restored.property_states == game.property_states
    assert restored.chance_deck == game.chance_deck
    assert restored.active_sequences == game.active_sequences
    assert restored.has_active_sequence(tag="save-probe")
    result = restored.build_game_result()
    assert result.game_type == "mexicopoly"
    assert result.custom_data["board_id"] == "mexico50"
    assert result.custom_data["currency_key"] == "mexicopoly-currency-mxn"
    classic = MonopolyGame()
    classic.options.board_id = "mexico"
    classic = MonopolyGame.from_json(classic.to_json())
    assert classic.get_type() == "monopoly" and len(classic.board.spaces) == 40


@pytest.mark.asyncio
async def test_real_local_websocket_can_create_and_start_mexican_game_without_voice(
    monkeypatch,
):
    """Exercise actual auth, catalog, navigation, table creation, and start packets."""
    monkeypatch.setenv("PLAYAURAL_VOICE_ENABLED", "0")
    server = Server(host="127.0.0.1", port=0, db_path=":memory:")
    await server.start()
    try:
        password = secrets.token_urlsafe(20) + "a1"
        assert server._auth.register(
            "Probe80", password, locale="es", email="probe@example.test"
        ) == "ok"
        port = server._ws_server._server.sockets[0].getsockname()[1]
        async with websockets.connect(f"ws://127.0.0.1:{port}", proxy=None) as ws:
            async def receive_until(predicate):
                async with asyncio.timeout(8):
                    while True:
                        packet = json.loads(await ws.recv())
                        if predicate(packet):
                            return packet

            async def select(menu_id, item_id):
                await ws.send(json.dumps({
                    "type": "menu", "menu_id": menu_id, "selection_id": item_id,
                }))

            await ws.send(json.dumps({
                "type": "authorize", "username": "Probe80", "password": password,
                "version": VERSION, "client": "web", "locale": "es",
            }))
            success = await receive_until(lambda p: p.get("type") == "authorize_success")
            assert success["voice"]["enabled"] is False
            catalog = await receive_until(lambda p: p.get("type") == "update_options_lists")
            assert "mexicopoly" in [g["type"] for g in catalog["games"]]
            await receive_until(lambda p: p.get("menu_id") == "main_menu")
            await select("main_menu", "play")
            menu = await receive_until(lambda p: p.get("menu_id") == "games_menu")
            assert "Mexipoly" in json.dumps(menu, ensure_ascii=False)
            await select("games_menu", "game_mexicopoly")
            await receive_until(lambda p: p.get("menu_id") == "tables_menu")
            await select("tables_menu", "create_table")
            await receive_until(lambda p: p.get("menu_id") == "turn_menu")
            table = server._tables.find_user_table("Probe80")
            assert type(table.game) is MexicopolyGame
            assert len(table.game.board.spaces) == 50
            await select("turn_menu", "add_bot")
            await receive_until(lambda p: len(table.game.get_active_players()) == 2)
            await select("turn_menu", "start_game")
            await receive_until(lambda p: table.game.status == "playing")
            assert len(table.game.property_states) == 35
            assert table.game.players[0].cash == 3000
            assert server._voice.is_ready() is False
            await ws.send(json.dumps({"type": "logout"}))
            await receive_until(lambda p: p.get("type") == "force_exit")
    finally:
        await server.stop(preserve_tables=False)


@pytest.mark.parametrize("seed", [812, 2026])
def test_bots_finish_extended_game_with_uuid_owned_winner(seed):
    random.seed(seed)
    game = make_game(bots=True, count=4)
    for _ in range(80000):
        game.on_tick()
        if game.status != "playing":
            break
    assert game.status == "finished", (seed, game.phase, game.turn_number)
    assert len(game.alive_players) == 1 and game.winner is not None
    result = game.build_game_result()
    assert result.game_type == "mexicopoly"
    assert result.custom_data["winner_ids"] == [game.winner.id]


def test_quick_action_labels_and_descriptions_in_spanish():
    game = make_game(locale="es", bots=False, count=2)
    player = game.players[0]
    game.before_menu_build(player)
    standard_set = game.get_action_set(player, "standard")
    assert standard_set is not None

    buy_house = standard_set.get_action("quick_buy_house")
    assert buy_house is not None
    resolved = game.resolve_action(player, buy_house)
    assert resolved.label == "Comprar casa"
    assert "Elige una propiedad" in resolved.description

    sell_house = standard_set.get_action("quick_sell_house")
    assert sell_house is not None
    resolved = game.resolve_action(player, sell_house)
    assert resolved.label == "Vender casa"

    mortgage = standard_set.get_action("quick_mortgage")
    assert mortgage is not None
    resolved = game.resolve_action(player, mortgage)
    assert resolved.label == "Hipotecar"

    unmortgage = standard_set.get_action("quick_unmortgage")
    assert unmortgage is not None
    resolved = game.resolve_action(player, unmortgage)
    assert resolved.label == "Deshipotecar"


def test_quick_action_localizes_even_if_created_without_user():
    game = MexicopolyGame()
    player = game.create_player("p1", "Player1")
    game.players.append(player)
    # At this point, no user is attached.
    action_set = game.create_standard_action_set(player)
    game.add_action_set(player, action_set)
    # Default without user for Mexicopoly should be Spanish now!
    buy_house = action_set.get_action("quick_buy_house")
    assert buy_house is not None
    resolved = game.resolve_action(player, buy_house)
    assert resolved.label == "Comprar casa"
    assert "Elige una propiedad" in resolved.description
