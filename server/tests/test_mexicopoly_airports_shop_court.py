"""Comprehensive tests for Mexipoly shop, airports, airplane, car, and juzgado."""

import pytest

from server.games.mexicopoly.compact_board import MEXICO_BOARD
from server.games.mexicopoly.game import (
    MexicopolyGame, PHASE_AWAIT_ROLL, PHASE_JAIL, SPECIAL_EVENT_HOY_NO_CIRCULA,
)
from server.games.mexicopoly.shop import (
    AIRPLANE_PRICE, CAR_PRICE, FUEL_PRICE, MEXICOPOLY_SHOP_ITEMS,
)
from server.games.monopoly.game import MonopolyPlayer
from server.messages.localization import Localization
from server.tests.test_mexicopoly import make_game, force_actor


def test_money_cards_boosted_liquidity():
    """Verify money cards give substantial rewards (250 - 1200 MXN)."""
    collect_cards = [
        c for c in MEXICO_BOARD.chance_cards + MEXICO_BOARD.community_cards
        if c.action in ("collect", "collect_each")
    ]
    assert len(collect_cards) >= 15
    for card in collect_cards:
        if card.action == "collect":
            assert card.amount >= 250, f"{card.id} has amount {card.amount} < 250"
        elif card.action == "collect_each":
            assert card.amount >= 100, f"{card.id} has collect_each amount {card.amount} < 100"

    assert MEXICO_BOARD.card("community", "community_sat_refund").amount == 1200
    assert MEXICO_BOARD.card("chance", "chance_tanda_oficina").amount == 800
    assert MEXICO_BOARD.card("community", "community_remesa_tio").amount == 900
    assert MEXICO_BOARD.card("chance", "chance_cetes_buen_fin").amount == 700


def test_strategic_airports_and_juzgado_board_properties():
    """Verify 4 strategic airports with updated prices and Juzgado space at position 12."""
    assert len(MEXICO_BOARD.spaces) == 50
    airports = [s for s in MEXICO_BOARD.spaces if s.group_id == "airports"]
    assert len(airports) == 4
    for ap in airports:
        assert ap.price == 800
        assert ap.mortgage_value == 400
        assert ap.rents == (120, 250, 500, 1000)

    juzgado = MEXICO_BOARD.space("juzgado")
    assert MEXICO_BOARD.space_index("juzgado") == 12
    assert juzgado.price == 650
    assert juzgado.mortgage_value == 325
    assert juzgado.group_id == "juzgado"
    # Position 13 is Jail right after Juzgado
    assert MEXICO_BOARD.spaces[13].id == "jail"


def test_airport_traversal_and_airplane_unlock():
    """Verify airplane unlocks only after visiting all 4 airports."""
    game = make_game(start=True)
    player = force_actor(game)
    assert player.cash == 3000

    # Initially 0 airports visited, airplane locked
    assert len(game.visited_airports.get(player.id, [])) == 0
    can_buy, err = MEXICOPOLY_SHOP_ITEMS["airplane"].can_buy(game, player)
    assert can_buy is False
    assert err == "mexicopoly-error-airplane-locked"

    # Move player across the board touching each airport
    # Airports are at positions 10, 22, 35, 47
    player.position = 0
    game._move_to(player, "tijuana_airport", collect_go=False)
    assert "tijuana_airport" in game.visited_airports[player.id]
    assert len(game.visited_airports[player.id]) == 1

    game._move_to(player, "monterrey_airport", collect_go=False)
    assert "monterrey_airport" in game.visited_airports[player.id]
    assert len(game.visited_airports[player.id]) == 2

    game._move_to(player, "benito_juarez_airport", collect_go=False)
    assert "benito_juarez_airport" in game.visited_airports[player.id]
    assert len(game.visited_airports[player.id]) == 3

    # Still locked with 3/4
    can_buy, _ = MEXICOPOLY_SHOP_ITEMS["airplane"].can_buy(game, player)
    assert can_buy is False

    # Visit 4th airport: Cancún
    game._move_to(player, "cancun_airport", collect_go=False)
    assert "cancun_airport" in game.visited_airports[player.id]
    assert len(game.visited_airports[player.id]) == 4

    # Now unlocked!
    can_buy, err = MEXICOPOLY_SHOP_ITEMS["airplane"].can_buy(game, player)
    assert can_buy is True
    assert err is None


def test_shop_purchases_and_airplane_flight_mechanics():
    """Verify purchasing airplane in shop and flying with TUA, rent, and turn delay."""
    game = make_game(locale="es", start=True)
    p1, p2 = game.players
    force_actor(game)

    # Unlock airports for p1
    game.visited_airports[p1.id] = ["tijuana_airport", "monterrey_airport", "benito_juarez_airport", "cancun_airport"]

    # Buy airplane from shop
    initial_cash = p1.cash
    game._action_open_shop(p1, "open_shop", "airplane")
    assert game.has_airplane[p1.id] is True
    assert p1.cash == initial_cash - AIRPLANE_PRICE

    # P2 owns Monterrey airport (position 22)
    game.property_states["monterrey_airport"].owner_id = p2.id
    p2_before = p2.cash

    # P1 is at space 10 (Tijuana airport). Distance to Monterrey airport (22) is 12 spaces.
    # 12 spaces -> (12 + 9) // 10 = 2 turns delay!
    p1.position = 10
    game.current_player = p1
    game.phase = PHASE_AWAIT_ROLL
    game.decision_player_id = p1.id

    p1_before = p1.cash
    game._action_fly_airplane(p1, "fly_airplane", "monterrey_airport")

    # P1 moved to Monterrey airport (position 22)
    assert p1.position == 22
    # P1 pays TUA ($150) + rent ($120) = $270 to P2
    assert p1.cash == p1_before - 270
    assert p2.cash == p2_before + 270
    # Flight delay is 2 turns
    assert game.flight_delay_turns[p1.id] == 2

    # P1's next turn: flight delay decrements to 1, turn finishes automatically
    game.current_player = p1
    game._start_turn(announce=True)
    assert game.flight_delay_turns[p1.id] == 1

    # Following turn: delay decrements to 0, arrives!
    game.current_player = p1
    game._start_turn(announce=True)
    assert p1.id not in game.flight_delay_turns


def test_airplane_flight_to_own_airport_is_free():
    """Verify flying to player's own airport charges 0 TUA and 0 rent."""
    game = make_game(start=True)
    p1 = force_actor(game)
    game.has_airplane[p1.id] = True
    game.property_states["cancun_airport"].owner_id = p1.id

    p1.position = 10
    p1_before = p1.cash
    game._action_fly_airplane(p1, "fly_airplane", "cancun_airport")
    assert p1.position == game.board.space_index("cancun_airport")
    assert p1.cash == p1_before  # No charge!


def test_car_purchase_roll_with_three_dice_and_fuel_refill():
    """Verify car purchase, 4 uses of 3 dice, fuel exhaustion, and refill."""
    game = make_game(start=True)
    p1 = force_actor(game)
    assert not game.has_car.get(p1.id)

    # Buy car for 600 MXN
    cash_before = p1.cash
    game._action_open_shop(p1, "open_shop", "car")
    assert game.has_car[p1.id] is True
    assert game.car_fuel[p1.id] == 4
    assert p1.cash == cash_before - CAR_PRICE

    # Roll with car (use 1)
    p1.position = 0
    game.phase = PHASE_AWAIT_ROLL
    game.decision_player_id = p1.id
    game._action_roll_car(p1, "roll_car")
    assert game.car_fuel[p1.id] == 3
    assert p1.position > 2  # 3 dice roll minimum is 3

    # Use remaining 3 fuel
    for remaining in (2, 1, 0):
        game.active_sequences.clear()
        game.phase = PHASE_AWAIT_ROLL
        game.decision_player_id = p1.id
        game._action_roll_car(p1, "roll_car")
        assert game.car_fuel[p1.id] == remaining

    # Out of fuel: roll_car is disabled
    game.active_sequences.clear()
    game.phase = PHASE_AWAIT_ROLL
    game.decision_player_id = p1.id
    assert game._is_roll_car_enabled(p1) == "mexicopoly-error-no-gasoline"

    # Refill fuel at shop for 200 MXN
    cash_before = p1.cash
    game._action_open_shop(p1, "open_shop", "fuel")
    assert game.car_fuel[p1.id] == 4
    assert p1.cash == cash_before - FUEL_PRICE
    assert game._is_roll_car_enabled(p1) is None


def test_hoy_no_circula_blocks_airplane_and_car():
    """Verify Hoy No Circula environmental event blocks both flight and car driving."""
    game = make_game(start=True)
    p1 = force_actor(game)
    game.has_airplane[p1.id] = True
    game.has_car[p1.id] = True
    game.car_fuel[p1.id] = 4

    # Normal state: both enabled
    assert game._is_fly_airplane_enabled(p1) is None
    assert game._is_roll_car_enabled(p1) is None

    # Hoy No Circula active
    game.active_special_event = SPECIAL_EVENT_HOY_NO_CIRCULA
    assert game._is_fly_airplane_enabled(p1) == "mexicopoly-error-hoy-no-circula"
    assert game._is_roll_car_enabled(p1) == "mexicopoly-error-hoy-no-circula"


def test_juzgado_court_fee_amparo_issuing_and_jail_bailout():
    """Verify Juzgado landing fee, owner issuing amparo, and jailed player buying amparo."""
    game = make_game(locale="es", start=True)
    judge_owner, defendant = game.players

    # Judge owner owns Juzgado
    game.property_states["juzgado"].owner_id = judge_owner.id

    # Defendant lands on Juzgado -> pays $150 legal fees
    defendant.position = 12
    judge_before = judge_owner.cash
    def_before = defendant.cash
    game._resolve_landing(defendant)
    assert defendant.cash == def_before - 150
    assert judge_owner.cash == judge_before + 150

    # Judge owner issues an amparo (costs $100)
    assert game.juzgado_amparos_issued.get(judge_owner.id, 0) == 0
    judge_before = judge_owner.cash
    game._action_issue_amparo(judge_owner, "issue_amparo")
    assert judge_owner.cash == judge_before - 100
    assert game.juzgado_amparos_issued[judge_owner.id] == 1
    assert any("juzgado_amparo" in cid for cid in judge_owner.jail_card_ids)

    # Restriction: cooldown in same turn
    assert game._is_issue_amparo_enabled(judge_owner) == "mexicopoly-error-amparo-cooldown"
    game.amparo_issued_this_turn = False

    # Issue 2nd amparo
    game._action_issue_amparo(judge_owner, "issue_amparo")
    assert game.juzgado_amparos_issued[judge_owner.id] == 2
    # Restriction: limit of 2 active amparos
    assert game._is_issue_amparo_enabled(judge_owner) == "mexicopoly-error-amparo-limit"

    # Defendant is sent to Jail
    defendant.in_jail = True
    defendant.position = 13
    game.phase = PHASE_JAIL
    game.decision_player_id = defendant.id
    game.current_player = defendant

    # Defendant can buy amparo from judge_owner for $200
    assert game._is_buy_juzgado_amparo_enabled(defendant) is None
    def_before = defendant.cash
    judge_before = judge_owner.cash
    game._action_buy_juzgado_amparo(defendant, "buy_juzgado_amparo")

    assert defendant.cash == def_before - 200
    assert judge_owner.cash == judge_before + 200
    assert defendant.in_jail is False  # Released immediately!
    assert game.phase == PHASE_AWAIT_ROLL
    assert game.juzgado_amparos_issued[judge_owner.id] == 1
