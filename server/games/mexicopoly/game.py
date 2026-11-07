"""Mexican Monopoly: independent identity and content, shared rules engine."""

from dataclasses import dataclass, field
import random
from typing import Any

from ...game_utils.actions import Visibility
from ...game_utils.options import BoolOption, MenuOption, option_field
from ...game_utils.poker_timer import PokerTurnTimer
from ...game_utils.turn_timer_mixin import TurnTimerMixin
from ...messages.localization import Localization
from ...users.base import MenuItem
from ..monopoly import audio as game_audio
from ..monopoly.game import (
    MonopolyGame, MonopolyOptions, MonopolyPlayer, PHASE_AWAIT_ROLL, PHASE_TURN_ACTIONS,
    PHASE_PROPERTY, PHASE_AUCTION, PHASE_RENT, PHASE_DEBT, PHASE_JAIL,
    PHASE_MANAGE, PHASE_TRADE_BUILD, PHASE_TRADE_RESPONSE, PHASE_MORTGAGE_TRANSFER,
)
from ..monopoly.models import (
    BoardDefinition, BoardSpaceDefinition, CardDefinition, OWNABLE_SPACE_KINDS,
    PropertyState, SPACE_STREET,
)
from ...game_utils.sequence_runner_mixin import SequenceBeat, SequenceOperation
from ..registry import register_game
from .board import MEXICO_BOARD as LEGACY_BOARD
from .compact_board import MEXICO_BOARD

TURN_TIMER_CHOICES = ("0", "20", "30", "40", "60", "120")
AUCTION_TIMER_CHOICES = ("3", "5", "8", "10", "15")
SAT_AUDIT_PERCENT = 20
SAT_JAIL_TURNS = 2
COBRO_START_CARDS = frozenset({"chance_cobro_de_piso", "community_cobro_de_piso"})
MARINA_OPERATIVO_CARDS = frozenset({"chance_marina_operativo", "community_marina_operativo"})
RANDOM_COBRO_START_PROBABILITY = 0.12
RANDOM_MARINA_BASE_PROBABILITY = 0.18
RANDOM_MARINA_TURN_BONUS = 0.05
RANDOM_MARINA_MAX_PROBABILITY = 0.45

_CONCISE_MESSAGES = {
    "monopoly-you-roll": "mexicopoly-you-roll",
    "monopoly-player-roll": "mexicopoly-player-roll",
    "monopoly-you-jail-roll": "mexicopoly-you-roll",
    "monopoly-player-jail-roll": "mexicopoly-player-roll",
    "monopoly-you-go-jail": "mexicopoly-you-go-jail",
    "monopoly-player-go-jail": "mexicopoly-player-go-jail",
    "monopoly-you-go-jail-brief": "mexicopoly-you-go-jail",
    "monopoly-player-go-jail-brief": "mexicopoly-player-go-jail",
    "monopoly-you-just-visiting": "mexicopoly-you-just-visiting",
    "monopoly-player-just-visiting": "mexicopoly-player-just-visiting",
    "monopoly-you-pay-jail": "mexicopoly-you-pay-jail",
    "monopoly-player-pays-jail": "mexicopoly-player-pays-jail",
    "monopoly-you-pay-jail-brief": "mexicopoly-you-pay-jail",
    "monopoly-player-pays-jail-brief": "mexicopoly-player-pays-jail",
}


@dataclass
class MexicopolyOptions(MonopolyOptions):
    """Independent playtest options without exposing classic board selection."""

    # No option metadata: clients cannot change this fixed, serialized board id.
    board_id: str = field(default="mexico50")
    automatic_rent: bool = option_field(BoolOption(
        default=True,
        label="mexicopoly-option-automatic-rent",
        change_msg="mexicopoly-option-changed-automatic-rent",
        description="mexicopoly-option-automatic-rent-description",
    ))
    auctions_enabled: bool = option_field(BoolOption(
        default=True,
        label="mexicopoly-option-auctions-enabled",
        change_msg="mexicopoly-option-changed-auctions-enabled",
        description="mexicopoly-option-auctions-enabled-description",
    ))
    auction_timer: str = option_field(MenuOption(
        default="5", choices=list(AUCTION_TIMER_CHOICES),
        value_key="value",
        label="mexicopoly-option-auction-timer",
        change_msg="mexicopoly-option-changed-auction-timer",
        prompt="mexicopoly-option-select-auction-timer",
        description="mexicopoly-option-auction-timer-description",
        choice_labels={value: f"mexicopoly-auction-timer-{value}" for value in AUCTION_TIMER_CHOICES},
    ))
    turn_timer: str = option_field(MenuOption(
        default="0", choices=list(TURN_TIMER_CHOICES),
        value_key="value",
        label="mexicopoly-option-turn-timer",
        change_msg="mexicopoly-option-changed-turn-timer",
        prompt="mexicopoly-option-select-turn-timer",
        description="mexicopoly-option-turn-timer-description",
        choice_labels={value: f"mexicopoly-timer-{value}" for value in TURN_TIMER_CHOICES},
    ))


@register_game
@dataclass
class MexicopolyGame(TurnTimerMixin, MonopolyGame):
    """A compact Mexican game, preserving the original board in existing saves."""

    options: MexicopolyOptions = field(default_factory=MexicopolyOptions)
    timer: PokerTurnTimer = field(default_factory=PokerTurnTimer)
    response_timer: PokerTurnTimer = field(default_factory=PokerTurnTimer)
    auction_gavel_timer: PokerTurnTimer = field(default_factory=PokerTurnTimer)
    turn_time_exhausted: bool = False
    response_timer_context: str = ""
    response_warning_played: bool = False
    auction_gavel_stage: int = 0
    jail_counts: dict[str, int] = field(default_factory=dict)
    sat_jail_turns: dict[str, int] = field(default_factory=dict)
    cobro_de_piso_active: bool = False
    cobro_de_piso_turns: int = 0

    @classmethod
    def get_name(cls) -> str:
        return "Mexipoly"

    @classmethod
    def get_type(cls) -> str:
        return "mexicopoly"

    @property
    def board(self) -> BoardDefinition:
        if self.options.board_id == MEXICO_BOARD.id:
            return MEXICO_BOARD
        if self.options.board_id == LEGACY_BOARD.id:
            return LEGACY_BOARD
        raise ValueError(f"Unsupported Mexican Monopoly board: {self.options.board_id}")

    def prestart_validate(self):
        errors = super().prestart_validate()
        if self.options.turn_timer not in TURN_TIMER_CHOICES:
            errors.append("mexicopoly-error-turn-timer")
        if self.options.auction_timer not in AUCTION_TIMER_CHOICES:
            errors.append("mexicopoly-error-auction-timer")
        return errors

    def rebuild_runtime_state(self):
        super().rebuild_runtime_state()
        # A restored countdown must not repeat its five-second warning.
        self._timer_warning_played = self.timer.seconds_remaining() <= 5
        for player in self.get_active_players():
            for action_id in ("roll_dice", "roll_shortcut", "jail_roll"):
                action = self.find_action(player, action_id)
                if action:
                    action.description = None
                    action.get_description = None
                    if action_id == "jail_roll":
                        action.label = "monopoly-action-roll"
            decline = self.find_action(player, "decline_property")
            if decline:
                decline.get_label = "_get_decline_property_label"
                decline.get_description = "_get_decline_property_description"

    def _broadcast_actor(self, actor, personal_key, public_key, **kwargs):
        if not self.options.auctions_enabled:
            if personal_key == "monopoly-you-land-unowned":
                personal_key = "mexicopoly-you-land-unowned-no-auction"
            if kwargs.get("brief_personal_key") == "monopoly-you-land-unowned-brief":
                kwargs["brief_personal_key"] = "mexicopoly-you-land-unowned-no-auction-brief"
        for key in ("brief_personal_key", "brief_others_key"):
            if kwargs.get(key) in _CONCISE_MESSAGES:
                kwargs[key] = _CONCISE_MESSAGES[kwargs[key]]
        super()._broadcast_actor(
            actor, _CONCISE_MESSAGES.get(personal_key, personal_key),
            _CONCISE_MESSAGES.get(public_key, public_key), **kwargs,
        )

    def create_turn_action_set(self, player):
        actions = super().create_turn_action_set(player)
        for action_id in ("roll_dice", "roll_shortcut", "jail_roll"):
            action = actions.get_action(action_id)
            if action:
                action.description = None
                action.get_description = None
                if action_id == "jail_roll":
                    action.label = "monopoly-action-roll"
        decline = actions.get_action("decline_property")
        if decline:
            decline.get_label = "_get_decline_property_label"
            decline.get_description = "_get_decline_property_description"
        return actions

    def _get_decline_property_label(self, player, action_id):
        del action_id
        locale = self._locale(player)
        key = (
            "monopoly-action-auction-property"
            if self.options.auctions_enabled
            else "mexicopoly-action-pass-property"
        )
        return Localization.get(locale, key)

    def _get_decline_property_description(self, player, action_id):
        del action_id
        locale = self._locale(player)
        key = (
            "monopoly-desc-decline-property"
            if self.options.auctions_enabled
            else "mexicopoly-desc-pass-property"
        )
        return Localization.get(locale, key)

    def _get_buy_description(self, player, action_id):
        if self.options.auctions_enabled or not self.pending_property_id:
            return super()._get_buy_description(player, action_id)
        locale = self._locale(player)
        space = self.board.space(self.pending_property_id)
        return Localization.get(
            locale,
            "mexicopoly-buy-property-description-no-auction",
            property=self._space_name(locale, space),
            group=self._group_name(locale, space.group_id),
            group_members=self._group_members_text(locale, space.group_id),
            price=self._money(locale, space.price),
            mortgage=self._money(locale, space.mortgage_value),
            rents=self._rent_schedule_text(locale, space),
            cash=self._money(locale, getattr(player, "cash", 0)),
        )

    def _is_end_turn_hidden(self, player):
        del player
        return Visibility.HIDDEN

    def on_start(self) -> None:
        self.jail_counts.clear()
        self.sat_jail_turns.clear()
        self.cobro_de_piso_active = False
        self.cobro_de_piso_turns = 0
        self.auction_gavel_stage = 0
        self.auction_gavel_timer.clear()
        super().on_start()

    def _send_to_jail(self, player: MonopolyPlayer) -> None:
        self.sat_jail_turns.pop(player.id, None)
        self.jail_counts[player.id] = self.jail_counts.get(player.id, 0) + 1
        super()._send_to_jail(player)

    def _send_to_sat_jail(
        self, player: MonopolyPlayer, *, turns: int = SAT_JAIL_TURNS
    ) -> None:
        self._broadcast_actor(
            player,
            "mexicopoly-you-sat-jail-notice",
            "mexicopoly-player-sat-jail-notice",
            turns=turns,
            brief_personal_key="mexicopoly-you-sat-jail-notice-brief",
            brief_others_key="mexicopoly-player-sat-jail-notice-brief",
        )
        self.jail_counts[player.id] = self.jail_counts.get(player.id, 0) + 1
        self.sat_jail_turns[player.id] = turns
        super()._send_to_jail(player)

    def _jail_fine(self, player: MonopolyPlayer) -> int:
        count = max(1, self.jail_counts.get(player.id, 1))
        return self.board.jail_fine * (2 ** (count - 1))

    def _is_jail_pay_enabled(self, player: MonopolyPlayer):
        if not self._is_actor(player, PHASE_JAIL):
            return self._waiting_reason(player)
        turns = self.sat_jail_turns.get(player.id, 0)
        if turns > 0:
            return ("mexicopoly-error-sat-no-bail", {"turns": turns})
        return super()._is_jail_pay_enabled(player)

    def _is_jail_card_enabled(self, player: MonopolyPlayer):
        if not self._is_actor(player, PHASE_JAIL):
            return self._waiting_reason(player)
        turns = self.sat_jail_turns.get(player.id, 0)
        if turns > 0:
            return ("mexicopoly-error-sat-no-bail", {"turns": turns})
        return super()._is_jail_card_enabled(player)

    def _action_jail_pay(self, player: MonopolyPlayer, action_id: str) -> None:
        self.sat_jail_turns.pop(player.id, None)
        super()._action_jail_pay(player, action_id)

    def _action_jail_card(self, player: MonopolyPlayer, action_id: str) -> None:
        self.sat_jail_turns.pop(player.id, None)
        super()._action_jail_card(player, action_id)

    def _start_jail_roll_sequence(
        self,
        player: MonopolyPlayer,
        die_1: int,
        die_2: int,
    ) -> None:
        if self.sat_jail_turns.get(player.id, 0) > 1:
            self.last_die_1 = die_1
            self.last_die_2 = die_2
            total = die_1 + die_2
            is_double = die_1 == die_2
            self._broadcast_actor(
                player,
                "monopoly-you-jail-roll",
                "monopoly-player-jail-roll",
                die1=die_1,
                die2=die_2,
                total=total,
                doubles="yes" if is_double else "no",
                brief_personal_key="monopoly-you-jail-roll-brief",
                brief_others_key="monopoly-player-jail-roll-brief",
            )
            beats = self._build_roll_cue_beats(player, die_1, die_2)
            beats.append(SequenceBeat.pause(game_audio.ROLL_TO_LANDING_PAUSE_TICKS))
            beats.append(
                SequenceBeat(
                    ops=[
                        SequenceOperation.callback_op(
                            "jail_roll_failed", {"player_id": player.id}
                        )
                    ]
                )
            )
            self.start_sequence(
                f"monopoly_jail_roll_{self.turn_number}",
                beats,
                tag="monopoly_roll",
                lock_scope=self.SEQUENCE_LOCK_GAMEPLAY,
                pause_bots=True,
            )
            return
        super()._start_jail_roll_sequence(player, die_1, die_2)

    def _sequence_release_from_jail(self, payload: dict[str, Any]) -> None:
        player_id = str(payload.get("player_id", ""))
        self.sat_jail_turns.pop(player_id, None)
        super()._sequence_release_from_jail(payload)

    def _sequence_failed_jail_roll(self, payload: dict[str, Any]) -> None:
        player = self.get_player_by_id(str(payload.get("player_id", "")))
        if (
            isinstance(player, MonopolyPlayer)
            and not player.bankrupt
            and self.sat_jail_turns.get(player.id, 0) > 0
        ):
            remaining = self.sat_jail_turns[player.id] - 1
            player.jail_turns += 1
            if remaining > 0:
                self.sat_jail_turns[player.id] = remaining
                self._broadcast_actor(
                    player,
                    "mexicopoly-you-stay-sat-jail",
                    "mexicopoly-player-stays-sat-jail",
                    attempt=player.jail_turns,
                    remaining=remaining,
                    turns=remaining,
                    brief_personal_key="mexicopoly-you-stay-sat-jail-brief",
                    brief_others_key="mexicopoly-player-stays-sat-jail-brief",
                )
                self._finish_turn()
                self._focus_after_user_transition(player)
                return
            self.sat_jail_turns.pop(player.id, None)
            player.in_jail = False
            player.jail_turns = 0
            fine = self._jail_fine(player)
            self._start_debt(
                player,
                "",
                fine,
                "monopoly-debt-jail",
                continuation="move_after_jail",
            )
            if self.phase == PHASE_DEBT:
                self._focus_after_user_transition(player)
            return
        super()._sequence_failed_jail_roll(payload)

    def _eliminate_player(self, player: MonopolyPlayer) -> None:
        self.sat_jail_turns.pop(player.id, None)
        super()._eliminate_player(player)

    def _extortion_percent(
        self,
        space: BoardSpaceDefinition,
        state: PropertyState | None = None,
    ) -> int:
        state = state if state is not None else self.property_states.get(space.id)
        if space.kind != SPACE_STREET or state is None or state.buildings <= 0:
            return 5
        h_per_hotel = self.board.development.houses_per_hotel
        if state.buildings <= 2:
            return 10
        if state.buildings <= h_per_hotel:
            return 15
        num_hotels = state.buildings - h_per_hotel
        if num_hotels >= 2:
            return 50
        group_spaces = self.board.group_spaces(space.group_id)
        if group_spaces and all(
            self.property_states.get(member.id, PropertyState()).buildings
            >= h_per_hotel + member.max_hotels
            for member in group_spaces
        ):
            return 50
        return 30

    def _extortion_cut(
        self, space: BoardSpaceDefinition, amount: int
    ) -> tuple[int, int, int]:
        if not self.cobro_de_piso_active or amount <= 0:
            return 0, 0, amount
        percent = self._extortion_percent(space, self.property_states.get(space.id))
        cut = max(1, (amount * percent) // 100)
        net = max(0, amount - cut)
        return percent, cut, net

    def _activate_cobro_de_piso(
        self, *, announce: bool = True, play_sound: bool = True
    ) -> bool:
        was_active = self.cobro_de_piso_active
        self.cobro_de_piso_active = True
        if self.cobro_de_piso_turns <= 0:
            self.cobro_de_piso_turns = 1
        if announce and not was_active:
            self._broadcast_global(
                "mexicopoly-cobro-de-piso-started",
                "mexicopoly-cobro-de-piso-started-brief",
            )
        if play_sound and not was_active:
            self.play_sound(game_audio.SOUND_DEBT_WARNING)
        return not was_active

    def _deactivate_cobro_de_piso(
        self, *, announce: bool = True, play_sound: bool = True
    ) -> bool:
        was_active = self.cobro_de_piso_active
        self.cobro_de_piso_active = False
        self.cobro_de_piso_turns = 0
        if announce:
            key = (
                "mexicopoly-cobro-de-piso-ended"
                if was_active
                else "mexicopoly-marina-patrol-calm"
            )
            brief_key = (
                "mexicopoly-cobro-de-piso-ended-brief"
                if was_active
                else "mexicopoly-marina-patrol-calm-brief"
            )
            self._broadcast_global(key, brief_key)
        if play_sound and was_active:
            self.play_sound(game_audio.SOUND_LEAVE_JAIL, max_instances=1)
        return was_active

    def _maybe_trigger_random_cobro_event(self) -> None:
        if self.status != "playing" or self.turn_number < 4:
            return
        if not any(state.owner_id for state in self.property_states.values()):
            return
        if self.cobro_de_piso_active:
            self.cobro_de_piso_turns += 1
            chance = min(
                RANDOM_MARINA_MAX_PROBABILITY,
                RANDOM_MARINA_BASE_PROBABILITY
                + RANDOM_MARINA_TURN_BONUS * self.cobro_de_piso_turns,
            )
            if random.random() < chance:  # nosec B311
                self._deactivate_cobro_de_piso(announce=True, play_sound=True)
        elif random.random() < RANDOM_COBRO_START_PROBABILITY:  # nosec B311
            self._activate_cobro_de_piso(announce=True, play_sound=True)

    def _card_text(self, locale: str, card: CardDefinition) -> str:
        if card.id == "chance_sat_audit":
            return Localization.get(
                locale,
                card.text_key,
                percent=SAT_AUDIT_PERCENT,
                minimum=self._money(locale, card.amount),
                amount=self._money(locale, card.amount),
                turns=SAT_JAIL_TURNS,
                jail=self._space_name(locale, self.board.space(self.board.jail_space_id)),
                go=self._space_name(locale, self.board.space(self.board.go_space_id)),
            )
        return super()._card_text(locale, card)

    def _resolve_card(self, player: MonopolyPlayer, card: CardDefinition) -> None:
        if card.id == "chance_sat_audit":
            penalty = max(card.amount, (player.cash * SAT_AUDIT_PERCENT) // 100)
            self._start_debt(
                player,
                "",
                penalty,
                "mexicopoly-debt-sat-audit",
                continuation="sat_jail",
            )
            return
        if card.id in COBRO_START_CARDS:
            self._activate_cobro_de_piso(announce=True, play_sound=True)
            self._start_debt(
                player,
                "",
                card.amount,
                "mexicopoly-debt-extortion",
                continuation="finish_landing",
            )
            return
        if card.id in MARINA_OPERATIVO_CARDS:
            self._deactivate_cobro_de_piso(announce=True, play_sound=True)
            super()._resolve_card(player, card)
            return
        super()._resolve_card(player, card)

    def _payment_funds_free_parking(self, reason_key: str) -> bool:
        if self.options.free_parking_cash and reason_key in {
            "mexicopoly-debt-sat-audit",
            "mexicopoly-debt-extortion",
        }:
            return True
        return super()._payment_funds_free_parking(reason_key)

    def _continue_after_debt(self, continuation: str) -> None:
        if continuation == "sat_jail":
            current = self.current_player
            if isinstance(current, MonopolyPlayer) and not current.bankrupt:
                self._send_to_sat_jail(current, turns=SAT_JAIL_TURNS)
            return
        super()._continue_after_debt(continuation)

    def _resolve_landing(
        self,
        player: MonopolyPlayer,
        *,
        rent_multiplier: int = 1,
        utility_override: bool = False,
    ) -> None:
        space = self.board.spaces[player.position]
        if space.kind in OWNABLE_SPACE_KINDS:
            state = self.property_states[space.id]
            owner = self._alive_player_by_id(state.owner_id)
            if (
                owner
                and owner.id != player.id
                and not state.mortgaged
                and owner.in_jail
                and self.sat_jail_turns.get(owner.id, 0) > 0
            ):
                self._broadcast_actor(
                    player,
                    "mexicopoly-you-owe-no-sat-jailed-rent",
                    "mexicopoly-player-owes-no-sat-jailed-rent",
                    owner=owner.name,
                    property=lambda locale: self._space_name(locale, space),
                    brief_personal_key="mexicopoly-you-owe-no-sat-jailed-rent-brief",
                    brief_others_key="mexicopoly-player-owes-no-sat-jailed-rent-brief",
                )
                self._finish_landing()
                return
        super()._resolve_landing(
            player,
            rent_multiplier=rent_multiplier,
            utility_override=utility_override,
        )

    def _announce_rent_payment(self, owner, tenant, space, amount):
        if not self.cobro_de_piso_active or amount <= 0:
            super()._announce_rent_payment(owner, tenant, space, amount)
            return
        percent, cut, net = self._extortion_cut(space, amount)
        owner.cash -= cut
        self._broadcast_actor_target(
            owner,
            tenant,
            "mexicopoly-you-collect-rent-extorted",
            "mexicopoly-you-pay-rent-extorted",
            "mexicopoly-player-pays-rent-extorted",
            brief_personal_key="mexicopoly-you-collect-rent-extorted-brief",
            brief_target_key="mexicopoly-you-pay-rent-extorted-brief",
            brief_others_key="mexicopoly-player-pays-rent-extorted-brief",
            owner=owner.name,
            tenant=tenant.name,
            property=lambda locale: self._space_name(locale, space),
            amount=lambda locale: self._money(locale, amount),
            cut=lambda locale: self._money(locale, cut),
            net=lambda locale: self._money(locale, net),
            percent=percent,
            owner_cash=lambda locale: self._money(locale, owner.cash),
            tenant_cash=lambda locale: self._money(locale, tenant.cash),
        )

    def _get_claim_rent_label(self, player: MonopolyPlayer, action_id: str) -> str:
        rent = self.rent_state
        if not self.cobro_de_piso_active or not rent or rent.amount <= 0:
            return super()._get_claim_rent_label(player, action_id)
        locale = self._locale(player)
        space = self.board.space(rent.property_id)
        percent, cut, net = self._extortion_cut(space, rent.amount)
        return Localization.get(
            locale,
            "mexicopoly-claim-rent-extorted-label",
            amount=self._money(locale, rent.amount),
            cut=self._money(locale, cut),
            net=self._money(locale, net),
            percent=percent,
        )

    def _action_decline_property(self, player: MonopolyPlayer, action_id: str) -> None:
        del action_id
        if not self._is_actor(player, PHASE_PROPERTY):
            return
        if not self.options.auctions_enabled:
            property_id = self.pending_property_id
            space = self.board.space(property_id)
            self._broadcast_actor(
                player,
                "mexicopoly-you-pass-property",
                "mexicopoly-player-passes-property",
                property=lambda locale: self._space_name(locale, space),
                brief_personal_key="mexicopoly-you-pass-property-brief",
                brief_others_key="mexicopoly-player-passes-property-brief",
            )
            self.pending_property_id = ""
            self._finish_landing()
            self._focus_after_user_transition(player)
            return
        super()._action_decline_property(player, "decline_property")

    def _start_auction(
        self,
        property_id: str,
        *,
        resume_kind: str,
        first_bidder_id: str = "",
    ) -> None:
        if not self.options.auctions_enabled:
            self.auction_state = None
            self.auction_gavel_stage = 0
            self.auction_gavel_timer.clear()
            self._resume_after_auction(resume_kind)
            return
        super()._start_auction(
            property_id, resume_kind=resume_kind, first_bidder_id=first_bidder_id
        )
        if self.phase == PHASE_AUCTION and self.auction_state:
            self._restart_auction_gavel()

    def _restart_auction_gavel(self) -> None:
        self.auction_gavel_stage = 0
        if self.phase == PHASE_AUCTION and self.auction_state:
            self.auction_gavel_timer.start(int(self.options.auction_timer))
        else:
            self.auction_gavel_timer.clear()

    def _is_actor(self, player, phase=None):
        if phase == PHASE_AUCTION or (phase is None and self.phase == PHASE_AUCTION):
            auction = self.auction_state
            return (
                self.status == "playing"
                and not getattr(player, "bankrupt", False)
                and not self.is_sequence_gameplay_locked()
                and self._gameplay_input_lock_owner() is None
                and self.phase == PHASE_AUCTION
                and auction is not None
                and player.id in auction.active_bidder_ids
            )
        return super()._is_actor(player, phase)

    def _is_bid_enabled(self, player: MonopolyPlayer):
        reason = super()._is_bid_enabled(player)
        if reason is not None:
            return reason
        if self.auction_state and self.auction_state.highest_bidder_id == player.id:
            return "mexicopoly-error-already-highest-bidder"
        return None

    def _place_bid(self, player: MonopolyPlayer, amount: int) -> bool:
        if self.auction_state and self.auction_state.highest_bidder_id == player.id:
            self._speak(player, "mexicopoly-error-already-highest-bidder")
            return False
        if not super()._place_bid(player, amount):
            return False
        if self.phase == PHASE_AUCTION and self.auction_state:
            self._restart_auction_gavel()
        return True

    def _advance_auction(self, previous_bidder_id: str) -> None:
        auction = self.auction_state
        if not auction:
            return
        active = [
            player_id
            for player_id in auction.active_bidder_ids
            if self._alive_player_by_id(player_id) is not None
        ]
        auction.active_bidder_ids = active
        if not active:
            self._finish_auction()
            return
        if auction.highest_bidder_id and active == [auction.highest_bidder_id]:
            self._finish_auction()
            return
        ordered = auction.bidder_ids
        try:
            start = ordered.index(previous_bidder_id)
        except ValueError:
            start = -1
        for offset in range(1, len(ordered) + 1):
            candidate = ordered[(start + offset) % len(ordered)]
            if candidate in active and candidate != auction.highest_bidder_id:
                self.decision_player_id = candidate
                next_bidder = self._alive_player_by_id(candidate)
                if next_bidder:
                    self._announce_auction_turn(next_bidder)
                self.refresh_menus()
                return
        # Single remaining active bidder who has not bid yet: keep auction open
        # so they can bid, pass, or let the gavel count down.
        self.decision_player_id = active[0]
        self.refresh_menus()

    def _finish_auction(self) -> None:
        self.auction_gavel_stage = 0
        self.auction_gavel_timer.clear()
        super()._finish_auction()

    def _tick_auction_gavel(self) -> None:
        auction = self.auction_state
        if self.phase != PHASE_AUCTION or not auction:
            self.auction_gavel_stage = 0
            self.auction_gavel_timer.clear()
            return
        if self._gameplay_input_lock_owner() is not None:
            return
        if self.auction_gavel_timer.seconds_remaining() <= 0:
            self.auction_gavel_timer.start(int(self.options.auction_timer))
        if not self.auction_gavel_timer.tick():
            return
        self.auction_gavel_stage += 1
        space = self.board.space(auction.property_id)
        leader = self._alive_player_by_id(auction.highest_bidder_id)
        if self.auction_gavel_stage in (1, 2):
            if leader and auction.highest_bid > 0:
                key = (
                    "mexicopoly-auction-going-once"
                    if self.auction_gavel_stage == 1
                    else "mexicopoly-auction-going-twice"
                )
                self._broadcast_global(
                    key,
                    key,
                    amount=lambda locale: self._money(locale, auction.highest_bid),
                    player=leader.name,
                    property=lambda locale: self._space_name(locale, space),
                )
            else:
                key = (
                    "mexicopoly-auction-no-bids-once"
                    if self.auction_gavel_stage == 1
                    else "mexicopoly-auction-no-bids-twice"
                )
                self._broadcast_global(
                    key,
                    key,
                    property=lambda locale: self._space_name(locale, space),
                    minimum=lambda locale: self._money(locale, self._auction_minimum_bid()),
                )
            self.play_sound(game_audio.SOUND_AUCTION_BID, max_instances=1)
            self.auction_gavel_timer.start(int(self.options.auction_timer))
            self.refresh_menus()
            return
        if leader and auction.highest_bid > 0:
            self._broadcast_global(
                "mexicopoly-auction-going-three",
                "mexicopoly-auction-going-three",
                amount=lambda locale: self._money(locale, auction.highest_bid),
                player=leader.name,
                property=lambda locale: self._space_name(locale, space),
            )
        else:
            self._broadcast_global(
                "mexicopoly-auction-no-bids-three",
                "mexicopoly-auction-no-bids-three",
                property=lambda locale: self._space_name(locale, space),
            )
        self._finish_auction()

    def _begin_rent_decision(self, tenant, owner, space, rent):
        if not self.options.automatic_rent:
            return super()._begin_rent_decision(tenant, owner, space, rent)
        # Use the debt/payment engine directly: no redundant collection prompt,
        # no double transfer, and insolvent tenants still get liquidation choices.
        self._start_debt(
            tenant, owner.id, rent, "monopoly-debt-rent",
            continuation="finish_landing", property_id=space.id,
        )

    def _finish_landing(self):
        super()._finish_landing()
        if (self.status == "playing" and self.phase == PHASE_TURN_ACTIONS
                and not self.extra_roll_pending):
            self._finish_turn()

    def _start_turn(self, *, announce):
        if announce:
            self._maybe_trigger_random_cobro_event()
        super()._start_turn(announce=announce)
        self.turn_time_exhausted = False
        self.response_timer.clear()
        self.response_timer_context = ""
        self.start_turn_timer()

    def _can_interrupt(self, player):
        # Optional management/trades belong to the acting player's own turn.
        # Required auction/debt responders may still manage their assets.
        current = self.current_player
        if (current and current.id != player.id
                and self.phase in {PHASE_AWAIT_ROLL, PHASE_JAIL, PHASE_TURN_ACTIONS}):
            return False
        if self.phase == PHASE_AUCTION and self.auction_state:
            if self.is_sequence_gameplay_locked():
                return False
            if self._gameplay_input_lock_owner(exclude_player_id=player.id):
                return False
            return player.id in self.auction_state.active_bidder_ids
        return super()._can_interrupt(player)

    def bot_think(self, player):
        if self.phase == PHASE_JAIL and self.sat_jail_turns.get(player.id, 0) > 0:
            return "jail_roll"
        # Management used to happen after rolling. Do it before the final roll
        # now, otherwise automatic turn completion would prevent bots building.
        if self.phase == PHASE_AWAIT_ROLL:
            if self._bot_has_management_opportunity(player):
                return "manage_properties"
            if player.bot_trade_turn != self.turn_number:
                player.bot_trade_turn = self.turn_number
                if self._bot_best_trade_plan(player):
                    return "propose_trade"
        return super().bot_think(player)

    def on_tick(self):
        super().on_tick()
        if self.status != "playing" or not self.game_active:
            self.stop_turn_timer()
            self.response_timer.clear()
            self.auction_gavel_timer.clear()
            return
        if self.is_sequence_gameplay_locked():
            return
        if self.phase == PHASE_AUCTION:
            self.response_timer_context = ""
            self.response_timer.clear()
            self._tick_auction_gavel()
            return
        if self.options.turn_timer == "0":
            return
        actor = self._gameplay_input_lock_owner() or self._decision_player()
        if not actor or actor.is_bot or actor.bankrupt:
            return
        before = (self.timer.seconds_remaining(), self.response_timer.seconds_remaining())
        if self.current_player and actor.id == self.current_player.id:
            self.response_timer_context = ""
            self.response_timer.clear()
            if self.turn_time_exhausted:
                self._resolve_timeout(actor, announce=False)
            else:
                self.on_tick_turn_timer()
        else:
            # Other required players get a separate response budget. Their
            # delay must not consume the turn owner's remaining time.
            context = f"{self.turn_number}:{actor.id}:{self.phase}"
            if self.response_timer_context != context:
                self.response_timer_context = context
                self.response_timer.start(int(self.options.turn_timer))
                self.response_warning_played = False
            if self.response_timer.tick():
                self.response_timer_context = ""
                self._resolve_timeout(actor)
            elif self.response_timer.seconds_remaining() == 5 and not self.response_warning_played:
                self.response_warning_played = True
                user = self.get_user(actor)
                if user:
                    user.play_sound(self.timer_warning_sound)
        after = (self.timer.seconds_remaining(), self.response_timer.seconds_remaining())
        if after != before:
            self.refresh_menus()

    def _on_turn_timeout(self):
        self.turn_time_exhausted = True
        actor = self._gameplay_input_lock_owner() or self._decision_player()
        if actor:
            self._resolve_timeout(actor)

    def _resolve_timeout(self, actor, *, announce=True):
        pending = self._pending_actions.get(actor.id)
        if pending:
            self._discard_pending_action_input(actor)
        if actor.id != self.decision_player_id:
            action = "cancel-input"
        else:
            action = {
                PHASE_AWAIT_ROLL: "roll", PHASE_TURN_ACTIONS: "roll" if self.extra_roll_pending else "end",
                PHASE_JAIL: "roll",
                PHASE_PROPERTY: "auction" if self.options.auctions_enabled else "pass-property",
                PHASE_AUCTION: "pass",
                PHASE_RENT: "rent", PHASE_DEBT: "debt", PHASE_MANAGE: "close-management",
                PHASE_TRADE_BUILD: "cancel-trade", PHASE_TRADE_RESPONSE: "reject-trade",
                PHASE_MORTGAGE_TRANSFER: "keep-mortgage",
            }.get(self.phase)
        if not action:
            return
        if announce:
            self._broadcast_actor(
                actor, "mexicopoly-you-timeout", "mexicopoly-player-timeout",
                action=lambda locale: Localization.get(locale, f"mexicopoly-timeout-{action}"),
            )
        if action == "cancel-input":
            self.refresh_menus()
        elif self.phase in {PHASE_AWAIT_ROLL, PHASE_TURN_ACTIONS}:
            if action == "roll":
                self._action_roll_dice(actor, "roll_dice")
            else:
                self._finish_turn()
        elif self.phase == PHASE_JAIL:
            self._action_jail_roll(actor, "jail_roll")
        elif self.phase == PHASE_PROPERTY:
            self._action_decline_property(actor, "decline_property")
        elif self.phase == PHASE_AUCTION:
            self._action_pass_auction(actor, "pass_auction")
        elif self.phase == PHASE_RENT:
            self._action_claim_rent(actor, "claim_rent")
        elif self.phase == PHASE_DEBT:
            debt = self.debt_state
            if debt and actor.cash < debt.amount:
                self._action_raise_cash(actor, "raise_cash")
            if self.debt_state and actor.cash >= self.debt_state.amount:
                self._action_pay_debt(actor, "pay_debt")
            elif self.debt_state:
                self._action_declare_bankruptcy(actor, "declare_bankruptcy")
        elif self.phase == PHASE_MANAGE:
            self._action_finish_management(actor, "finish_management")
        elif self.phase == PHASE_TRADE_BUILD:
            self._action_trade_cancel(actor, "trade_cancel")
        elif self.phase == PHASE_TRADE_RESPONSE:
            self._action_trade_reject(actor, "trade_reject")
        elif self.phase == PHASE_MORTGAGE_TRANSFER:
            self._action_keep_received_mortgaged(actor, "keep_received_mortgaged")

    def _build_game_status(self, player, user):
        result = super()._build_game_status(player, user)
        result.items.append(
            MenuItem(
                id="mexicopoly:cobro_de_piso",
                text=Localization.get(
                    user.locale,
                    (
                        "mexicopoly-status-cobro-active"
                        if self.cobro_de_piso_active
                        else "mexicopoly-status-cobro-inactive"
                    ),
                ),
            )
        )
        for active_player in self.alive_players:
            sat_turns = self.sat_jail_turns.get(active_player.id, 0)
            if active_player.in_jail and sat_turns > 0:
                result.items.append(
                    MenuItem(
                        id=f"mexicopoly:sat_jail:{active_player.id}",
                        text=Localization.get(
                            user.locale,
                            "mexicopoly-status-sat-jail",
                            player=active_player.name,
                            turns=sat_turns,
                        ),
                    )
                )
        if self.phase == PHASE_AUCTION and self.auction_state:
            result.items.append(MenuItem(
                id="mexicopoly:auction_timer",
                text=Localization.get(
                    user.locale,
                    "mexicopoly-status-auction-gavel",
                    stage=self.auction_gavel_stage,
                    seconds=self.auction_gavel_timer.seconds_remaining(),
                ),
            ))
        elif self.options.turn_timer != "0":
            actor = self._gameplay_input_lock_owner() or self._decision_player()
            countdown = self.timer if actor and self.current_player and actor.id == self.current_player.id else self.response_timer
            result.items.append(MenuItem(
                id="mexicopoly:timer",
                text=Localization.get(user.locale, "mexicopoly-status-timer", seconds=countdown.seconds_remaining()),
            ))
        return result
