"""Mexican board content, classic-rule parity, localization, and save safety."""

from dataclasses import replace

import pytest

from server.games.monopoly.boards import get_board
from server.games.monopoly.game import MonopolyGame
from server.games.monopoly.models import PropertyState
from server.games.monopoly.rules import calculate_rent, can_build
from server.messages.localization import Localization
from server.users.test_user import MockUser

BOARD = get_board("mexico")
STANDARD = get_board("standard")


def make_mexico_game(locale: str = "es", client_type: str = "python") -> MonopolyGame:
    game = MonopolyGame()
    game.options.board_id = "mexico"
    game.setup_keybinds()
    for index in range(2):
        user = MockUser(f"User{index}", locale=locale, uuid=f"mexico-{index}")
        user.client_type = client_type
        game.add_player(user.username, user)
    game.host = game.players[0].name
    return game


def test_regions_contain_neighboring_mexican_cities() -> None:
    expected = {
        "brown": ["tijuana", "mexicali"],
        "light_blue": ["hermosillo", "chihuahua", "ciudad_juarez"],
        "pink": ["saltillo", "monterrey", "tampico"],
        "orange": ["aguascalientes", "zacatecas", "san_luis_potosi"],
        "red": ["guadalajara", "leon", "morelia"],
        "yellow": ["queretaro", "toluca", "mexico_city"],
        "green": ["puebla", "veracruz", "oaxaca"],
        "dark_blue": ["merida", "cancun"],
    }
    for group_id, cities in expected.items():
        assert [space.id for space in BOARD.group_spaces(group_id)] == cities
    assert [space.id for space in BOARD.group_spaces("transit")] == [
        "cuauhtemoc_metrorrey", "juarez_siteur", "tacubaya_metro", "pantitlan_metro"
    ]
    assert [space.id for space in BOARD.group_spaces("utility")] == [
        "monterrey_airport", "benito_juarez_airport"
    ]
    for locale in ("en", "vi", "es"):
        names = " ".join(Localization.get(locale, space.name_key) for space in BOARD.spaces)
        assert "aifa" not in names.casefold()
        assert "felipe" not in names.casefold()
        assert "Apodaca" in names
        assert "Guadalajara" in names


def test_mexico_changes_presentation_but_not_classic_economy_or_rules() -> None:
    assert len(BOARD.spaces) == len(STANDARD.spaces) == 40
    for mexican, standard in zip(BOARD.spaces, STANDARD.spaces, strict=True):
        assert replace(mexican, id=standard.id, name_key=standard.name_key) == standard
    for attribute in (
        "rules", "development", "starting_cash", "go_salary", "jail_fine",
        "bank_houses", "bank_hotels", "go_space_id", "jail_space_id",
    ):
        assert getattr(BOARD, attribute) == getattr(STANDARD, attribute)
    assert BOARD.community_cards == STANDARD.community_cards
    for mexican, standard in zip(BOARD.chance_cards, STANDARD.chance_cards, strict=True):
        assert replace(mexican, destination_id=standard.destination_id) == standard
        if mexican.destination_id:
            assert BOARD.space_index(mexican.destination_id) == STANDARD.space_index(
                standard.destination_id
            )


def test_metro_airport_and_city_rents_keep_classic_calculations() -> None:
    states = {space.id: PropertyState() for space in BOARD.spaces if space.price}
    metro = BOARD.space("cuauhtemoc_metrorrey")
    for count, station in enumerate(BOARD.group_spaces("transit"), start=1):
        states[station.id].owner_id = "owner"
        assert calculate_rent(BOARD, states, metro, 7) == (25, 50, 100, 200)[count - 1]
    assert calculate_rent(BOARD, states, metro, 7, rent_multiplier=2) == 400
    airport = BOARD.space("monterrey_airport")
    states[airport.id].owner_id = "owner"
    assert calculate_rent(BOARD, states, airport, 7) == 28
    assert calculate_rent(
        BOARD, states, airport, 7, rent_multiplier=10, utility_override=True
    ) == 70
    states["benito_juarez_airport"].owner_id = "owner"
    assert calculate_rent(BOARD, states, airport, 7) == 70
    states[airport.id].mortgaged = True
    assert calculate_rent(BOARD, states, airport, 7) == 0
    for city in BOARD.group_spaces("brown"):
        states[city.id].owner_id = "owner"
    assert calculate_rent(BOARD, states, BOARD.space("tijuana"), 7) == 4
    assert can_build(BOARD, states, "tijuana", "owner", 32, 12) is None
    states["tijuana"].buildings = 1
    assert can_build(BOARD, states, "tijuana", "owner", 31, 12) == (
        "monopoly-error-build-evenly"
    )


@pytest.mark.parametrize("locale", ["en", "vi", "es"])
@pytest.mark.parametrize("client_type", ["python", "web", "mobile"])
def test_mexico_is_selectable_and_described_on_each_client(
    locale: str, client_type: str
) -> None:
    game = make_mexico_game(locale, client_type)
    player = game.players[0]
    assert "mexico" in game._board_option_ids(player)
    meta = game.options.get_option_metas()["board_id"]
    assert Localization.get(locale, BOARD.name_key) in meta.get_label(locale, "mexico")
    assert "40" in game._board_option_description(player, "mexico")
    assert game.validate_start() == []
    game.on_start()
    game.flush_menus()
    assert all(player.cash == 1500 for player in game.get_active_players())
    assert len(game.property_states) == 28
    assert game._space_kind_text(locale, BOARD.space("tijuana")) == Localization.get(
        locale, "monopoly-space-kind-mexico-city"
    )
    airport_description = game._property_description(locale, "monterrey_airport")
    assert "Apodaca" in airport_description
    assert "4" in airport_description and "10" in airport_description
    for card in BOARD.chance_cards:
        text = game._card_text(locale, card)
        assert text != card.text_key
        if card.destination_id:
            assert game._space_name(locale, BOARD.space(card.destination_id)) in text
        elif card.nearest_kind:
            kind_key = (
                BOARD.terminology.utility_kind_key
                if card.nearest_kind == "utility"
                else BOARD.terminology.transit_kind_key
            )
            assert Localization.get(locale, kind_key) in text


def test_mexico_state_and_pending_card_destinations_survive_save_restore() -> None:
    game = make_mexico_game()
    game.on_start()
    player = game.players[0]
    game.property_states["tijuana"].owner_id = player.id
    game.property_states["tijuana"].buildings = 2
    game.property_states["monterrey_airport"].mortgaged = True
    player.position = BOARD.space_index("toluca")
    restored = MonopolyGame.from_json(game.to_json())
    assert restored.board is BOARD
    assert restored.property_states == game.property_states
    assert restored.players[0].position == BOARD.space_index("toluca")
    assert restored.chance_deck == game.chance_deck
    assert restored.community_deck == game.community_deck
    for card in restored.board.chance_cards:
        if card.destination_id:
            assert restored.board.space(card.destination_id)


@pytest.mark.parametrize("locale", ["en", "vi", "es"])
def test_all_mexico_specific_keys_render_without_fallback(locale: str) -> None:
    keys = {
        BOARD.name_key, BOARD.description_key, BOARD.currency_key,
        BOARD.terminology.street_kind_key, BOARD.terminology.transit_kind_key,
        BOARD.terminology.utility_kind_key,
        *(space.name_key for space in BOARD.spaces if "mexico" in space.name_key),
        *(group.name_key for group in BOARD.property_groups),
    }
    for key in keys:
        assert Localization.has_message(locale, key)
        assert Localization.get(locale, key, amount=1500) != key
