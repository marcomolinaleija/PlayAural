"""Human-playtest corrections, safe deadlines, and legacy save compatibility."""

import pytest

from server.game_utils.sequence_runner_mixin import SequenceBeat
from server.games.mexicopoly.board import MEXICO_BOARD as LEGACY_BOARD
from server.games.mexicopoly.game import MexicopolyGame, TURN_TIMER_CHOICES
from server.games.monopoly.game import (
    MonopolyGame, PHASE_AWAIT_ROLL, PHASE_TURN_ACTIONS, PHASE_PROPERTY,
    PHASE_AUCTION, PHASE_RENT, PHASE_DEBT, PHASE_JAIL,
)
from server.messages.localization import Localization
from .test_mexicopoly import drain, fast_audio, force_actor, make_game


def timed_game(seconds="20"):
    game = make_game(start=False)
    game.options.turn_timer = seconds
    game.on_start()
    drain(game, "monopoly_intro")
    force_actor(game)
    game._start_turn(announce=False)
    return game


@pytest.mark.parametrize("locale", ["en", "vi", "es"])
def test_options_and_compact_colors_are_clear(locale):
    game = make_game(locale=locale, start=False)
    metas = game.options.get_option_metas()
    assert game.options.automatic_rent is True and game.options.turn_timer == "0"
    assert TURN_TIMER_CHOICES == ("0", "20", "30", "40", "60", "120")
    assert metas["turn_timer"].get_localized_choice("0", locale) in metas["turn_timer"].get_label(locale, "0")
    assert all(metas["turn_timer"].get_localized_choice(x, locale) != f"mexicopoly-timer-{x}" for x in TURN_TIMER_CHOICES)
    assert len(game.board.spaces) == 50
    assert len([g for g in game.board.property_groups if game.board.group_spaces(g.id)[0].kind == "street"]) == 8
    assert all(len(game.board.group_spaces(color)) == 3 for color in ("brown", "light_blue", "pink", "orange", "red", "yellow", "green", "dark_blue"))
    assert Localization.get(locale, game.board.space("electricity").name_key) == "CFE"
    assert Localization.get(locale, game.board.space("water").name_key) == "CONAGUA"
    assert "SAT" in Localization.get(locale, game.board.space("income_tax").name_key)
    game.options.turn_timer = "15"
    assert "mexicopoly-error-turn-timer" in game.validate_start()


def test_automatic_rent_is_one_payment_and_advances_only_after_resolution():
    game = make_game()
    tenant = force_actor(game)
    owner = game.players[1]
    space = game.board.space("tijuana")
    game.property_states[space.id].owner_id = owner.id
    tenant.position = game.board.space_index(space.id)
    game._resolve_landing(tenant)
    assert (tenant.cash, owner.cash) == (2985, 3015)
    assert game.rent_state is None and game.debt_state is None
    assert game.current_player.id == owner.id
    game._action_claim_rent(owner, "claim_rent")
    assert (tenant.cash, owner.cash) == (2985, 3015)


@pytest.mark.parametrize("both", [False, True])
def test_automatic_utility_rent_waits_for_a_fresh_roll(monkeypatch, both):
    game = make_game()
    tenant = force_actor(game)
    owner = game.players[1]
    game.property_states["electricity"].owner_id = owner.id
    if both:
        game.property_states["water"].owner_id = owner.id
    tenant.position = game.board.space_index("electricity")
    monkeypatch.setattr(game, "_roll_pair", lambda: (3, 4))
    game._resolve_landing(tenant)
    drain(game, "monopoly_utility_rent")
    rent = 168 if both else 70
    assert tenant.cash == 3000 - rent and owner.cash == 3000 + rent
    assert game.rent_state is None and game.current_player.id == owner.id


@pytest.mark.parametrize("waive", [False, True])
def test_manual_collection_remains_optional(waive):
    game = make_game()
    game.options.automatic_rent = False
    tenant = force_actor(game)
    owner = game.players[1]
    game.property_states["tijuana"].owner_id = owner.id
    tenant.position = game.board.space_index("tijuana")
    game._resolve_landing(tenant)
    assert game.phase == PHASE_RENT and tenant.cash == 3000
    if waive:
        game._action_waive_rent(owner, "waive_rent")
    else:
        game._action_claim_rent(owner, "claim_rent")
    assert tenant.cash == (3000 if waive else 2985)
    assert game.current_player.id == owner.id


def test_insolvent_rent_keeps_the_tenant_decision_open():
    # When the tenant has no cash but owns a mortgageable property, PHASE_DEBT stays open:
    game = make_game()
    tenant = force_actor(game)
    tenant.cash = 0
    owner = game.players[1]
    game.property_states["tijuana"].owner_id = owner.id
    game.property_states["mexicali"].owner_id = tenant.id
    tenant.position = game.board.space_index("tijuana")
    game._resolve_landing(tenant)
    assert game.phase == PHASE_DEBT
    assert game.decision_player_id == tenant.id
    assert game.current_player.id == tenant.id and owner.cash == 3000

    # When the tenant has neither cash nor sufficient liquid assets, bankruptcy is automatic:
    auto_game = make_game()
    broke_tenant = force_actor(auto_game)
    broke_tenant.cash = 0
    creditor = auto_game.players[1]
    auto_game.property_states["tijuana"].owner_id = creditor.id
    broke_tenant.position = auto_game.board.space_index("tijuana")
    auto_game._resolve_landing(broke_tenant)
    assert broke_tenant.bankrupt is True
    assert auto_game.status == "finished"
    assert auto_game.winner_id == creditor.id


def test_purchase_and_auction_finish_before_automatic_turn_end():
    game = make_game()
    actor = force_actor(game)
    actor.position = game.board.space_index("tijuana")
    game._resolve_landing(actor)
    assert game.phase == PHASE_PROPERTY and game.current_player.id == actor.id
    game._action_decline_property(actor, "decline_property")
    assert game.phase == PHASE_AUCTION and game.current_player.id == actor.id
    for _ in range(4):
        if game.phase != PHASE_AUCTION:
            break
        game._action_pass_auction(game._decision_player(), "pass_auction")
    assert game.phase == PHASE_AWAIT_ROLL
    assert game.current_player.id != actor.id


def test_doubles_keep_the_turn_but_non_doubles_finish_it():
    game = make_game()
    actor = force_actor(game)
    actor.position = game.board.space_index("free_parking") - 6
    game._start_regular_roll_sequence(actor, 3, 3)
    drain(game, "monopoly_roll")
    assert game.current_player.id == actor.id and game.extra_roll_pending
    assert game.phase == PHASE_TURN_ACTIONS
    destination = (actor.position + 5) % len(game.board.spaces)
    space = game.board.spaces[destination]
    if space.id in game.property_states:
        game.property_states[space.id].owner_id = actor.id
    game._start_regular_roll_sequence(actor, 2, 3)
    drain(game, "monopoly_roll")
    assert game.current_player.id != actor.id


def test_roll_and_jail_speech_are_concise_and_perspective_aware():
    game = make_game(locale="es")
    actor = force_actor(game)
    first, other = game.get_user(actor), game.get_user(game.players[1])
    first.clear_messages(); other.clear_messages()
    game._broadcast_actor(actor, "monopoly-you-roll", "monopoly-player-roll", die1=2, die2=3, total=5, doubles="no")
    assert first.get_last_spoken() == "Tiras 2 y 3: 5."
    assert "dados son diferentes" not in other.get_last_spoken()
    game._send_to_jail(actor)
    messages = [m.data["text"] for m in first.messages if m.type == "speak"]
    assert "Vas a la cárcel." in messages
    assert not any("no cobras" in m or "Solo de Visita" in m for m in messages)
    assert actor.in_jail
    assert Localization.get("es", game.board.space("jail").name_key) == "Cárcel"


@pytest.mark.parametrize("seconds", ["20", "30", "40", "60", "120"])
def test_timer_options_start_with_the_requested_budget(seconds):
    game = timed_game(seconds)
    assert game.timer.ticks_remaining == int(seconds) * 20


def test_unlimited_does_not_trigger_automatic_actions(monkeypatch):
    game = timed_game("0")
    actions = []
    monkeypatch.setattr(game, "_resolve_timeout", lambda *a, **kw: actions.append(True))
    for _ in range(450): game.on_tick()
    assert not actions and game.timer.ticks_remaining == 0


def test_timeout_rolls_and_audio_resolution_does_not_consume_time(monkeypatch):
    game = timed_game()
    rolled = []
    monkeypatch.setattr(game, "_action_roll_dice", lambda player, action: rolled.append(player.id))
    game.start_sequence("pause", [SequenceBeat.pause(10), SequenceBeat()], tag="pause", lock_scope=game.SEQUENCE_LOCK_GAMEPLAY, pause_bots=True, start_immediately=False)
    before = game.timer.ticks_remaining
    for _ in range(5): game.on_tick()
    assert game.timer.ticks_remaining == before
    drain(game, "pause")
    game.timer.ticks_remaining = 1
    game.on_tick()
    assert rolled == [game.current_player.id] and game.turn_time_exhausted


def test_management_does_not_reset_the_whole_turn_clock():
    game = timed_game()
    actor = game.current_player
    game.property_states["tijuana"].owner_id = actor.id
    game._action_manage_properties(actor, "manage_properties")
    game.on_tick()
    left = game.timer.ticks_remaining
    assert left == 399
    game._action_finish_management(actor, "finish_management")
    assert game.timer.ticks_remaining == left
    game.on_tick()
    assert game.timer.ticks_remaining == left - 1


def test_other_players_get_a_response_budget_without_spending_the_turn_owner_clock():
    game = timed_game()
    game.options.automatic_rent = False
    tenant = game.current_player
    owner = game.players[1]
    game._begin_rent_decision(tenant, owner, game.board.space("tijuana"), 2)
    before = game.timer.ticks_remaining
    for _ in range(10): game.on_tick()
    assert game.timer.ticks_remaining == before
    assert game.response_timer.ticks_remaining == 390
    game.response_timer.ticks_remaining = 1
    game.on_tick()
    assert tenant.cash == 2998 and owner.cash == 3002
    assert game.rent_state is None


def test_timeout_liquidates_only_needed_assets_and_pays_debt():
    game = timed_game()
    actor = game.current_player
    actor.cash = 0
    game.property_states["tijuana"].owner_id = actor.id
    game._start_debt(actor, "", 20, "monopoly-debt-tax", continuation="finish_landing")
    game.timer.ticks_remaining = 1
    game.on_tick()
    assert game.property_states["tijuana"].mortgaged
    assert actor.cash == 60 and game.debt_state is None


def test_expired_purchase_is_auctioned_not_bought_automatically():
    game = timed_game()
    actor = game.current_player
    actor.position = game.board.space_index("tijuana")
    game._resolve_landing(actor)
    game.timer.ticks_remaining = 1
    game.on_tick()
    assert game.phase == PHASE_AUCTION
    assert actor.cash == 3000
    assert game.property_states["tijuana"].owner_id == ""


def test_foreign_auction_response_timeout_passes_without_spending_turn_budget():
    game = timed_game()
    actor = game.current_player
    other = game.players[1]
    game._start_auction("tijuana", resume_kind="landing", first_bidder_id=other.id)
    before = game.timer.ticks_remaining
    for expected_stage in (1, 2):
        game.auction_gavel_timer.ticks_remaining = 1
        game.on_tick()
        assert game.auction_gavel_stage == expected_stage
        assert game.phase == PHASE_AUCTION
    game.auction_gavel_timer.ticks_remaining = 1
    game.on_tick()
    assert game.auction_state is None
    assert game.property_states["tijuana"].owner_id == ""
    assert game.timer.ticks_remaining == 400
    assert game.current_player.id == other.id


def test_response_deadline_survives_save_restore_without_a_fresh_budget():
    game = timed_game()
    game.options.automatic_rent = False
    game._begin_rent_decision(game.current_player, game.players[1], game.board.space("tijuana"), 2)
    game.on_tick()
    game.response_timer.ticks_remaining = 161
    restored = MexicopolyGame.from_json(game.to_json())
    restored.rebuild_runtime_state()
    before = restored.timer.ticks_remaining
    restored.on_tick()
    assert restored.response_timer.ticks_remaining == 160
    assert restored.timer.ticks_remaining == before


def test_expired_trade_response_is_rejected_not_accepted():
    game = timed_game()
    actor, other = game.current_player, game.players[1]
    game._action_propose_trade(actor, other.id, "propose_trade")
    game.trade_state.offered_cash = 100
    game._action_trade_submit(actor, "trade_submit")
    game.on_tick()
    game.response_timer.ticks_remaining = 1
    game.on_tick()
    assert game.trade_state is None and actor.cash == other.cash == 3000


def test_automatic_rent_respects_mortgages_and_the_jailed_owner_rule():
    for mortgaged in (False, True):
        game = make_game()
        tenant = force_actor(game)
        owner = game.players[1]
        state = game.property_states["tijuana"]
        state.owner_id = owner.id
        state.mortgaged = mortgaged
        if not mortgaged:
            game.options.no_rent_in_jail = True
            owner.in_jail = True
        tenant.position = game.board.space_index("tijuana")
        game._resolve_landing(tenant)
        assert tenant.cash == owner.cash == 3000


def test_timeout_does_not_cancel_pending_debts_or_fabricate_solvency():
    game = timed_game()
    actor = game.current_player
    actor.cash = 0
    game._start_debt(actor, "", 20, "monopoly-debt-tax", continuation="finish_landing")
    game.timer.ticks_remaining = 1
    game.on_tick()
    assert actor.bankrupt and game.status == "finished"


def test_timeout_closes_an_editbox_and_cancels_trade_without_transferring_assets():
    game = timed_game()
    actor = game.current_player
    other = game.players[1]
    game._action_propose_trade(actor, other.id, "propose_trade")
    game.execute_action(actor, "trade_offer_cash")
    assert actor.id in game._pending_actions
    game.timer.ticks_remaining = 1
    game.on_tick()
    assert actor.id not in game._pending_actions
    assert game.trade_state is None and game.phase == PHASE_AWAIT_ROLL
    assert actor.cash == other.cash == 3000


def test_timer_and_original_80_space_saves_round_trip_without_converting_positions():
    game = timed_game()
    game.timer.ticks_remaining = 231
    restored = MexicopolyGame.from_json(game.to_json())
    restored.rebuild_runtime_state()
    assert restored.timer.ticks_remaining == 231
    assert restored.board.id == "mexico50"
    legacy = make_game(start=False)
    legacy.options.board_id = "mexico80"
    legacy.on_start()
    drain(legacy, "monopoly_intro")
    legacy.players[0].position = 79
    legacy.property_states["torreon"].owner_id = legacy.players[0].id
    data = legacy.to_dict()
    for key in ("automatic_rent", "turn_timer"): data["options"].pop(key)
    for key in ("timer", "response_timer", "turn_time_exhausted", "response_timer_context", "response_warning_played"): data.pop(key)
    restored = MexicopolyGame.from_dict(data)
    restored.rebuild_runtime_state()
    assert restored.board is LEGACY_BOARD and restored.players[0].position == 79
    assert restored.property_states["torreon"].owner_id == legacy.players[0].id
    assert restored.options.automatic_rent is True and restored.options.turn_timer == "0"
    classic = MonopolyGame()
    assert len(classic.board.spaces) == 40
    assert "automatic_rent" not in classic.options.get_option_metas()


def test_five_houses_and_up_to_two_hotels_on_major_hubs():
    game = make_game(locale="es")
    owner = force_actor(game)
    owner.cash = 10000
    for city in ("tijuana", "mexicali", "la_paz"):
        game.property_states[city].owner_id = owner.id
    for level in range(1, 6):
        for city in ("tijuana", "mexicali", "la_paz"):
            game._apply_build(owner, city, announce=False)
            assert game.property_states[city].buildings == level
            if level == 5 and city == "tijuana":
                assert game._build_property_error(owner, city) == "mexicopoly-error-hotels-require-five-each"
    assert game.bank_houses == 64 - 15 and game.bank_hotels == 24
    for city in ("tijuana", "mexicali", "la_paz"):
        game._apply_build(owner, city, announce=False)
        assert game.property_states[city].buildings == 6
    assert game.bank_houses == 64 and game.bank_hotels == 21
    assert game._build_property_error(owner, "mexicali") == "monopoly-error-already-hotel"
    assert game._build_property_error(owner, "tijuana") is None
    game._apply_build(owner, "tijuana", announce=False)
    assert game.property_states["tijuana"].buildings == 7
    assert game.bank_houses == 64 and game.bank_hotels == 20
    assert game._build_property_error(owner, "tijuana") == "monopoly-error-already-hotel"
    assert "2 hoteles" in game._building_text("es", 7)
    schedule_text = game._rent_schedule_text("es", game.board.space("tijuana"))
    assert "una casa MX$60" in schedule_text
    assert "2 hoteles MX$1.650" in schedule_text or "2 hoteles MX$1,650" in schedule_text or "2 hoteles MX$1650" in schedule_text
    game.bank_houses = 4
    game._apply_sell_building(owner, "tijuana", announce=False)
    assert game.property_states["tijuana"].buildings == 6 and game.bank_hotels == 21
    assert game._sell_property_error(owner, "tijuana") == "mexicopoly-error-bank-needs-five-houses"
    game.bank_houses = 5
    game._apply_sell_building(owner, "tijuana", announce=False)
    assert game.property_states["tijuana"].buildings == 5 and game.bank_houses == 0


def test_escalating_jail_fine_and_concise_jail_actions(monkeypatch):
    game = make_game(locale="es")
    actor = force_actor(game)
    user = game.get_user(actor)
    for action_id in ("roll_dice", "roll_shortcut", "jail_roll"):
        action = game.find_action(actor, action_id)
        assert action.description is None and action.get_description is None
    assert game.find_action(actor, "jail_roll").is_hidden == "_is_jail_roll_hidden"
    for expected_fine in (100, 200, 400):
        game._send_to_jail(actor)
        game.current_player = actor
        game.phase = PHASE_JAIL
        game.decision_player_id = actor.id
        turn_set = game.get_action_set(actor, "turn")
        visible_ids = [item.action.id for item in turn_set.get_visible_actions(game, actor)]
        assert "roll_dice" in visible_ids and "jail_roll" not in visible_ids
        assert game._is_roll_enabled(actor) is None
        assert game._jail_fine(actor) == expected_fine
        assert f"MX${expected_fine}" in game._get_jail_pay_label(actor, "jail_pay")
        user.clear_messages()
        game._action_jail_pay(actor, "jail_pay")
        assert user.get_last_spoken() == f"Pagas MX${expected_fine} y sales de la cárcel."
    # Verify normal roll_dice button executes the jail roll when in PHASE_JAIL:
    game._send_to_jail(actor)
    game.current_player = actor
    game.phase = PHASE_JAIL
    game.decision_player_id = actor.id
    monkeypatch.setattr(game, "_roll_pair", lambda: (3, 3))
    game._action_roll_dice(actor, "roll_dice")
    drain(game, "monopoly_roll")
    assert not actor.in_jail
    # Verify jail fine escalation is strictly per player / per user, never general:
    p2 = game.players[1]
    assert game._jail_fine(p2) == 100
    game._send_to_jail(p2)
    assert game._jail_fine(p2) == 100
    assert game._jail_fine(actor) == 800
    game._send_to_jail(p2)
    assert game._jail_fine(p2) == 200
    assert game._jail_fine(actor) == 800
    restored = MexicopolyGame.from_json(game.to_json())
    restored.rebuild_runtime_state()
    assert restored.jail_counts[actor.id] == 4
    assert restored.jail_counts[p2.id] == 2
    for action_id in ("roll_dice", "roll_shortcut", "jail_roll"):
        action = restored.find_action(restored.players[0], action_id)
        assert action.description is None and action.get_description is None
    assert restored.find_action(restored.players[0], "jail_roll").is_hidden == "_is_jail_roll_hidden"
    restored.on_start()
    drain(restored, "monopoly_intro")
    assert restored.jail_counts == {}


def test_optional_auctions_disabled_skips_auction_and_passes_turn():
    game = make_game(locale="es")
    game.options.auctions_enabled = False
    actor = force_actor(game)
    other = game.players[1]
    user = game.get_user(actor)
    actor.position = game.board.space_index("tijuana")
    user.clear_messages()
    game._resolve_landing(actor)
    assert game.phase == PHASE_PROPERTY
    assert "Cómprala o pasa." in user.get_last_spoken()
    assert game._get_decline_property_label(actor, "decline_property") == "Pasar sin comprar"
    game._action_decline_property(actor, "decline_property")
    assert game.auction_state is None
    assert game.property_states["tijuana"].owner_id == ""
    assert game.phase == PHASE_AWAIT_ROLL
    assert game.current_player.id == other.id


def test_live_gavel_auction_counts_one_two_three_resets_on_bid_and_awards_winner():
    game = make_game(locale="es", count=3)
    game.options.auction_timer = "3"
    p0, p1, p2 = game.players
    u0, u1, u2 = (game.get_user(p) for p in (p0, p1, p2))
    force_actor(game)
    p0.position = game.board.space_index("tijuana")
    game._resolve_landing(p0)
    game._action_decline_property(p0, "decline_property")
    assert game.phase == PHASE_AUCTION
    assert game.auction_gavel_timer.seconds_remaining() == 3
    # Any active bidder can bid out of turn order or leave:
    game._action_pass_auction(p0, "pass_auction")
    assert p0.id not in game.auction_state.active_bidder_ids
    game._place_bid(p2, 50)
    assert game.auction_state.highest_bid == 50 and game.auction_state.highest_bidder_id == p2.id
    assert game.auction_gavel_stage == 0
    # Tick to "¡a la 1!":
    u1.clear_messages()
    game.auction_gavel_timer.ticks_remaining = 1
    game.on_tick()
    assert game.auction_gavel_stage == 1
    assert "a la 1" in u1.get_last_spoken()
    # A new bid from p1 resets the gavel count back to 0:
    game._place_bid(p1, 80)
    assert game.auction_gavel_stage == 0
    assert game.auction_state.highest_bidder_id == p1.id
    # Now let the gavel count 1, 2, 3 without further bids:
    for expected_stage, phrase in ((1, "a la 1"), (2, "a las 2")):
        u2.clear_messages()
        game.auction_gavel_timer.ticks_remaining = 1
        game.on_tick()
        assert game.auction_gavel_stage == expected_stage
        assert phrase in u2.get_last_spoken()
    u2.clear_messages()
    game.auction_gavel_timer.ticks_remaining = 1
    game.on_tick()
    spoken = [m.data["text"] for m in u2.messages if m.type == "speak"]
    assert any("a las 3" in text for text in spoken)
    assert game.auction_state is None
    assert game.property_states["tijuana"].owner_id == p1.id
    assert p1.cash == 3000 - 80


def test_mexican_folklore_cards_sat_audit_false_accusation_and_sat_refund():
    game = make_game(locale="es")
    actor, other = game.players
    actor_user = game.get_user(actor)
    other_user = game.get_user(other)
    force_actor(game)

    # False harassment accusation (Suerte) and neighborhood complaint (Comunidad)
    false_acc = game.board.card("chance", "chance_false_accusation")
    game._resolve_card(actor, false_acc)
    assert actor.cash == 3000 - 350

    force_actor(game)
    vecinal = game.board.card("community", "community_falsa_denuncia_vecinal")
    game._resolve_card(actor, vecinal)
    assert actor.cash == 2650 - 300

    # Higher-than-expected SAT tax refund
    force_actor(game)
    sat_refund = game.board.card("community", "community_sat_refund")
    game._resolve_card(actor, sat_refund)
    assert actor.cash == 2350 + 450 == 2800

    # SAT tax audit: 20% of 2800 = 560, then 2 mandatory turns in SAT jail
    force_actor(game)
    actor.jail_card_ids.append("chance:chance_jail_free")
    game.property_states["tijuana"].owner_id = actor.id
    sat_audit = game.board.card("chance", "chance_sat_audit")
    game._resolve_card(actor, sat_audit)
    assert actor.cash == 2800 - 560 == 2240
    assert actor.in_jail and actor.position == game.board.space_index("jail")
    assert game.sat_jail_turns.get(actor.id) == 2

    # While actor is in SAT jail, other player lands on actor's property and pays NO rent
    # even though no_rent_in_jail is False by default.
    game.current_player = other
    game.phase = PHASE_AWAIT_ROLL
    game.decision_player_id = other.id
    other.position = game.board.space_index("tijuana")
    other_user.clear_messages()
    game._resolve_landing(other)
    assert other.cash == 3000 and actor.cash == 2240
    assert any("SAT" in m.data["text"] for m in other_user.messages if m.type == "speak")

    # Actor's turn 1 in SAT jail: bail and jail card are disabled; bot chooses roll_dice
    game.current_player = actor
    game.phase = PHASE_JAIL
    game.decision_player_id = actor.id
    assert game._is_jail_pay_enabled(actor) == ("mexicopoly-error-sat-no-bail", {"turns": 2})
    assert game._is_jail_card_enabled(actor) == ("mexicopoly-error-sat-no-bail", {"turns": 2})
    assert game.bot_think(actor) == "roll_dice"

    # Even rolling doubles on turn 1 of SAT jail does NOT release actor!
    game._start_jail_roll_sequence(actor, 4, 4)
    drain(game, "monopoly_roll")
    assert actor.in_jail
    assert game.sat_jail_turns.get(actor.id) == 1

    # Turn 2 in SAT jail: rolling non-doubles completes the 2-turn SAT lock
    game.current_player = actor
    game.phase = PHASE_JAIL
    game.decision_player_id = actor.id
    actor_user.clear_messages()
    game._start_jail_roll_sequence(actor, 2, 5)
    drain(game, "monopoly_roll")
    assert actor.id not in game.sat_jail_turns


def test_cobro_de_piso_extortion_tiers_cards_and_marina_operativo(monkeypatch):
    game = make_game(locale="es")
    owner, tenant = game.players
    owner_user = game.get_user(owner)
    force_actor(game)

    # Activate cobro de piso via card
    cobro_card = game.board.card("chance", "chance_cobro_de_piso")
    game._resolve_card(owner, cobro_card)
    assert game.cobro_de_piso_active is True
    assert owner.cash == 3000 - 200 == 2800

    # Verify status box reports active cobro de piso
    status_items = game._build_game_status(owner, owner_user).items
    assert any(item.id == "mexicopoly:cobro_de_piso" and "ACTIVO" in item.text for item in status_items)

    # Check extortion percentage tiers across property development levels:
    tijuana = game.board.space("tijuana")
    metro = game.board.space("cuauhtemoc_metrorrey")
    for city in ("tijuana", "mexicali", "la_paz"):
        game.property_states[city].owner_id = owner.id
    game.property_states[metro.id].owner_id = owner.id

    # Normal (0 houses) and transit -> 5%
    assert game._extortion_percent(tijuana) == 5
    assert game._extortion_percent(metro) == 5
    # 1 or 2 houses -> 10%
    game.property_states["tijuana"].buildings = 1
    assert game._extortion_percent(tijuana) == 10
    game.property_states["tijuana"].buildings = 2
    assert game._extortion_percent(tijuana) == 10
    # 3 to 5 houses -> 15%
    game.property_states["tijuana"].buildings = 3
    assert game._extortion_percent(tijuana) == 15
    game.property_states["tijuana"].buildings = 5
    assert game._extortion_percent(tijuana) == 15
    # 1 hotel (buildings == 6) when max_hotels is 2 -> 30%
    game.property_states["tijuana"].buildings = 6
    assert game._extortion_percent(tijuana) == 30
    # 2 hotels (max_hotels == 2, buildings == 7) -> 50%
    game.property_states["tijuana"].buildings = 7
    assert game._extortion_percent(tijuana) == 50

    # Also check a 1-hotel-max group where all 3 cities have 1 hotel -> 50%
    for city in ("hermosillo", "chihuahua", "ciudad_juarez"):
        game.property_states[city].owner_id = owner.id
        game.property_states[city].buildings = 6
    assert game._extortion_percent(game.board.space("hermosillo")) == 50

    # Verify actual rent deduction on landing (Tijuana at 2 hotels: rent 1650, 50% cut = 825)
    game.current_player = tenant
    game.phase = PHASE_AWAIT_ROLL
    game.decision_player_id = tenant.id
    tenant.position = game.board.space_index("tijuana")
    owner_before = owner.cash
    tenant_before = tenant.cash
    game._resolve_landing(tenant)
    assert tenant.cash == tenant_before - 1650
    assert owner.cash == owner_before + (1650 - 825)

    # Marina operation card clears cobro de piso, grants reward, and starts cooldown
    force_actor(game)
    owner_before = owner.cash
    marina_card = game.board.card("chance", "chance_marina_operativo")
    game._resolve_card(owner, marina_card)
    assert game.cobro_de_piso_active is False
    assert game.cobro_cooldown_turns == 3
    assert owner.cash == owner_before + 250

    # Random event respects cooldown, then triggers and lasts at least MIN_COBRO_DE_PISO_TURNS (8)
    game.turn_number = 6
    monkeypatch.setattr("server.games.mexicopoly.game.random.random", lambda: 0.01)
    for _ in range(3):
        game._maybe_trigger_random_cobro_event()
        assert game.cobro_de_piso_active is False
    game._maybe_trigger_random_cobro_event()
    assert game.cobro_de_piso_active is True
    # Turns 2 through 7 of cobro de piso cannot randomly end even with random() == 0.01
    for expected_turns in range(2, 8):
        game._maybe_trigger_random_cobro_event()
        assert game.cobro_de_piso_active is True
        assert game.cobro_de_piso_turns == expected_turns
    # On turn 8 (>= MIN_COBRO_DE_PISO_TURNS), random Marina raid can liberate properties
    game._maybe_trigger_random_cobro_event()
    assert game.cobro_de_piso_active is False


def test_vandalize_property_and_denounce_correct_false_and_skip():
    game = make_game(count=3, locale="es")
    p1, p2, p3 = game.players
    u1, u2, u3 = (game.get_user(p) for p in (p1, p2, p3))

    # Give p2 all brown properties with 1 house each so we can test proportional cost & building lock
    for city in ("tijuana", "mexicali", "la_paz"):
        game.property_states[city].owner_id = p2.id
        game.property_states[city].buildings = 1

    # Scenario 1: p1 secretly vandalizes p2's Tijuana. It is NOT instantaneous:
    # It does not show in vandalized_turns yet, p1's turn is not interrupted, and p2 receives no alert.
    force_actor(game)
    tijuana = game.board.space("tijuana")
    cost = game._vandalism_cost(tijuana, game.property_states["tijuana"])
    false_penalty = game._vandalism_false_accusation_penalty(
        tijuana, game.property_states["tijuana"], cost
    )
    u2.clear_messages()
    game._action_vandalize_property(p1, "tijuana", "vandalize_property")
    assert p1.cash == 3000 - cost
    assert "tijuana" not in game.vandalized_turns
    assert game.phase == PHASE_AWAIT_ROLL
    assert game.decision_player_id == p1.id
    assert not any(m.type == "speak" for m in u2.messages)
    # Culprit p1 received private confirmation
    p1_spoken = " ".join(m.data["text"] for m in u1.messages if m.type == "speak")
    assert "secreto" in p1_spoken

    # Now p1 finishes their turn:
    game._finish_turn()
    # It becomes p2's turn. On p2's turn start, p2 discovers the vandalism!
    assert game.current_player.id == p2.id
    assert game.vandalized_turns.get("tijuana") == 3
    assert game.phase == "vandalism_decision"
    assert game.decision_player_id == p2.id
    victim_spoken = " ".join(m.data["text"] for m in u2.messages if m.type == "speak")
    assert "Han vandalizado tu propiedad" in victim_spoken
    # Victim's message does NOT reveal who did it:
    assert p1.name not in victim_spoken

    # p2 falsely accuses p3 -> p2 pays false_penalty to p3, and Tijuana remains vandalized
    p2_before = p2.cash
    p3_before = p3.cash
    game._action_denounce_vandal(p2, p3.id, "denounce_vandal")
    assert p2.cash == p2_before - false_penalty
    assert p3.cash == p3_before + false_penalty
    assert game.vandalized_turns.get("tijuana") == 3
    # After decision, p2 resumes their turn:
    assert game.phase == PHASE_AWAIT_ROLL
    assert game.decision_player_id == p2.id

    # While Tijuana is vandalized:
    # 1) Building on Tijuana is blocked
    assert game._build_property_error(p2, "tijuana") == (
        "mexicopoly-error-property-vandalized",
        {"turns": 3},
    )
    # 2) Landing on Tijuana charges only 50% rent (1 house rent on Tijuana is 60 -> 30)
    p3.position = game.board.space_index("tijuana")
    p3_before_rent = p3.cash
    p2_before_rent = p2.cash
    game._resolve_landing(p3)
    assert p3.cash == p3_before_rent - 30
    assert p2.cash == p2_before_rent + 30

    # Scenario 2: Next turn, p1 secretly vandalizes p2's Mexicali, and p2 CORRECTLY denounces p1 on p2's turn
    game.vandalized_this_turn = False
    game.current_player = p1
    game.decision_player_id = p1.id
    game.phase = PHASE_AWAIT_ROLL
    mexicali = game.board.space("mexicali")
    cost_m = game._vandalism_cost(mexicali, game.property_states["mexicali"])
    caught_penalty = game._vandalism_caught_penalty(
        mexicali, game.property_states["mexicali"], cost_m
    )
    p1_before = p1.cash
    p2_before = p2.cash
    game._action_vandalize_property(p1, "mexicali", "vandalize_property")
    assert p1.cash == p1_before - cost_m
    assert "mexicali" not in game.vandalized_turns
    # Advance to p2's turn:
    game._finish_turn()
    assert game.current_player.id == p2.id
    assert game.vandalized_turns.get("mexicali") == 3
    assert game.phase == "vandalism_decision"

    game._action_denounce_vandal(p2, p1.id, "denounce_vandal")
    assert "mexicali" not in game.vandalized_turns
    assert p1.cash == p1_before - cost_m - caught_penalty
    assert p2.cash == p2_before + caught_penalty
    assert game.phase == PHASE_AWAIT_ROLL
    assert game.decision_player_id == p2.id

    # Scenario 3: Skipping denunciation keeps La Paz vandalized for 3 turns and then repairs it
    game.vandalized_this_turn = False
    game.current_player = p1
    game.decision_player_id = p1.id
    game.phase = PHASE_AWAIT_ROLL
    game._action_vandalize_property(p1, "la_paz", "vandalize_property")
    assert "la_paz" not in game.vandalized_turns
    game._finish_turn()
    assert game.current_player.id == p2.id
    assert game.vandalized_turns.get("la_paz") == 3
    assert game.phase == "vandalism_decision"
    game._action_skip_vandalism_denounce(p2, "skip_vandalism_denounce")
    assert game.vandalized_turns.get("la_paz") == 3
    assert game.phase == PHASE_AWAIT_ROLL
    for expected_remaining in (2, 1):
        game._tick_vandalized_properties()
        assert game.vandalized_turns.get("la_paz") == expected_remaining
    game._tick_vandalized_properties()
    assert "la_paz" not in game.vandalized_turns


def test_economic_modes_and_special_board_events():
    # Test Crisis mode starting cash (2400), Go salary (300), and +25% tax
    crisis_game = make_game(locale="es", start=False)
    crisis_game.options.economic_mode = "crisis"
    crisis_game.on_start()
    drain(crisis_game, "monopoly_intro")
    p1, p2 = crisis_game.players
    assert p1.cash == 2400 and p2.cash == 2400
    crisis_game._collect_go(p1, landed_on_go=False)
    assert p1.cash == 2700
    force_actor(crisis_game)
    p1.position = crisis_game.board.space_index("income_tax")
    crisis_game._resolve_landing(p1)
    # Income tax is 450; +25% in crisis mode = 562
    assert p1.cash == 2700 - 562

    # Test Bonanza mode starting cash (4000) and Go salary (550)
    bonanza_game = make_game(locale="es", start=False)
    bonanza_game.options.economic_mode = "bonanza"
    bonanza_game.on_start()
    drain(bonanza_game, "monopoly_intro")
    b1, b2 = bonanza_game.players
    assert b1.cash == 4000
    bonanza_game._collect_go(b1, landed_on_go=False)
    assert b1.cash == 4550

    # Test Special Board Events (+50% rent on color group and transit)
    bonanza_game.property_states["tijuana"].owner_id = b2.id
    bonanza_game._activate_special_event("feria_turistica", group_id="brown", turns=2)
    force_actor(bonanza_game)
    b1.position = bonanza_game.board.space_index("tijuana")
    b1_before = b1.cash
    # Tijuana base rent is 15; +50% during Feria Turística = 22
    bonanza_game._resolve_landing(b1)
    assert b1.cash == b1_before - 22
    # Event expires after ticking its remaining turns
    bonanza_game.turn_number = 5
    bonanza_game._maybe_trigger_special_event()
    assert bonanza_game.special_event_turns == 1
    bonanza_game._maybe_trigger_special_event()
    assert bonanza_game.active_special_event == ""


def test_community_movement_cards_hotel_cost_premium_and_group_rent_bonuses():
    game = make_game(locale="es")
    tenant, owner = game.players

    # 1. Verify all 6 new Community Chest movement cards move to their target space:
    movement_targets = (
        ("community_guadalajara_mariachi", "guadalajara"),
        ("community_monterrey_carne_asada", "monterrey"),
        ("community_oaxaca_guelaguetza", "oaxaca"),
        ("community_cdmx_tramite", "mexico_city"),
        ("community_veracruz_carnaval", "veracruz"),
        ("community_aeropuerto_cdmx", "benito_juarez_airport"),
    )
    for card_id, expected_space_id in movement_targets:
        force_actor(game)
        tenant.position = 0
        card = game.board.card("community", card_id)
        game._resolve_card(tenant, card)
        assert tenant.position == game.board.space_index(expected_space_id)

    # 2. Verify partial (2 of 3) and full (3 of 3) undeveloped color-group rent scaling:
    # Cancún base rent is 240:
    # - 1 of 3 owned -> 240
    # - 2 of 3 owned -> 360 (+50%)
    # - 3 of 3 owned (unbuilt) -> 600 (2.5x base)
    cancun_idx = game.board.space_index("cancun")
    game.property_states["cancun"].owner_id = owner.id
    force_actor(game)
    tenant.cash = 5000
    owner.cash = 5000
    tenant.position = cancun_idx
    game._resolve_landing(tenant)
    assert tenant.cash == 5000 - 240 and owner.cash == 5000 + 240

    game.property_states["merida"].owner_id = owner.id
    force_actor(game)
    tenant.position = cancun_idx
    game._resolve_landing(tenant)
    assert tenant.cash == 4760 - 360 and owner.cash == 5240 + 360

    game.property_states["chetumal"].owner_id = owner.id
    force_actor(game)
    tenant.position = cancun_idx
    game._resolve_landing(tenant)
    assert tenant.cash == 4400 - 600 and owner.cash == 5600 + 600

    # 3. Verify houses vs hotel purchase cost premium (hotel costs 1.5x house cost):
    # In Brown group, house cost is 120, hotel cost is 180.
    for city in ("tijuana", "mexicali", "la_paz"):
        game.property_states[city].owner_id = owner.id
        game.property_states[city].buildings = 4
    tijuana_space = game.board.space("tijuana")
    assert game._next_building_cost(tijuana_space, 4) == 120
    assert game._next_building_cost(tijuana_space, 5) == 180
    assert game._next_building_cost(tijuana_space, 6) == 180

    owner.cash = 1000
    for city in ("tijuana", "mexicali", "la_paz"):
        game._apply_build(owner, city, announce=False)
        assert game.property_states[city].buildings == 5
    # 3 houses built at 120 each = 360 spent -> 640 left
    assert owner.cash == 640

    # Building 1st hotel on Tijuana costs 180 (1.5x 120), not 120:
    game._apply_build(owner, "tijuana", announce=False)
    assert game.property_states["tijuana"].buildings == 6
    assert owner.cash == 640 - 180 == 460


def test_marina_operativo_card_has_sequence_pause():
    game = make_game(locale="es")
    actor = force_actor(game)
    game.cobro_de_piso_active = True
    # Place marina operativo card at top of chance deck
    game.chance_deck.insert(0, "chance_marina_operativo")
    game._draw_card(actor, "chance")
    assert any(s.tag == "monopoly_card" for s in game.active_sequences)
    card_seq = next(s for s in game.active_sequences if s.tag == "monopoly_card")
    # Verify the sequence has the 18-tick pause beat before card audio/resolution
    # so dice roll announcements do not collide
    pause_beats = [b for b in card_seq.beats if b.delay_after_ticks >= 18 and not b.ops]
    assert len(pause_beats) >= 1
    drain(game, "monopoly_card")
    assert not game.cobro_de_piso_active


def test_multiple_vandalisms_queued_discovered_in_order():
    game = make_game(count=3, locale="es")
    p1, p2, p3 = game.players
    # Give p3 two properties
    game.property_states["tijuana"].owner_id = p3.id
    game.property_states["mexicali"].owner_id = p3.id

    # p1 secretly vandalizes Tijuana on p1's turn
    game.current_player = p1
    game.decision_player_id = p1.id
    game.phase = PHASE_AWAIT_ROLL
    game._action_vandalize_property(p1, "tijuana", "vandalize_property")

    # p2 secretly vandalizes Mexicali on p2's turn
    game.vandalized_this_turn = False
    game.current_player = p2
    game.decision_player_id = p2.id
    game.phase = PHASE_AWAIT_ROLL
    game._action_vandalize_property(p2, "mexicali", "vandalize_property")

    assert len(game.unannounced_vandalisms) == 2
    assert "tijuana" not in game.vandalized_turns
    assert "mexicali" not in game.vandalized_turns

    # Now p3's turn begins: p3 discovers the first vandalism (Tijuana)
    game._finish_turn()
    assert game.current_player.id == p3.id
    assert game.phase == "vandalism_decision"
    assert game.decision_player_id == p3.id
    assert game.vandalized_turns.get("tijuana") == 3
    assert "mexicali" not in game.vandalized_turns

    # p3 skips denouncing Tijuana -> immediately discovers second vandalism (Mexicali)
    game._action_skip_vandalism_denounce(p3, "skip_vandalism_denounce")
    assert game.phase == "vandalism_decision"
    assert game.decision_player_id == p3.id
    assert game.vandalized_turns.get("mexicali") == 3

    # p3 skips denouncing Mexicali -> now all discoveries done, resumes normal turn
    game._action_skip_vandalism_denounce(p3, "skip_vandalism_denounce")
    assert game.phase == PHASE_AWAIT_ROLL
    assert game.decision_player_id == p3.id






