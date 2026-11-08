"""Mexican Monopoly: independent identity and content, shared rules engine."""

from dataclasses import dataclass, field
import random
from typing import Any

from ...game_utils.actions import ActionSet, MenuInput, Visibility
from ...game_utils.menu_management_mixin import StatusBoxBuild
from ...game_utils.options import BoolOption, MenuOption, option_field
from ...game_utils.player import Player
from ...game_utils.poker_timer import PokerTurnTimer
from ...game_utils.turn_timer_mixin import TurnTimerMixin
from ...messages.localization import Localization
from ...ui.keybinds import KeybindState
from ...users.base import MenuItem
from ..monopoly import audio as game_audio
from ..monopoly.bot import risk_adjusted_cash_reserve
from ..monopoly.game import (
    MonopolyGame, MonopolyOptions, MonopolyPlayer, PHASE_SETUP, PHASE_AWAIT_ROLL,
    PHASE_TURN_ACTIONS, PHASE_PROPERTY, PHASE_AUCTION, PHASE_RENT, PHASE_DEBT,
    PHASE_JAIL, PHASE_MANAGE, PHASE_TRADE_BUILD, PHASE_TRADE_RESPONSE,
    PHASE_MORTGAGE_TRANSFER, PHASE_ENTRY_ACTIONS, SELL_GROUP_OPTION_PREFIX,
)
from ..monopoly.models import (
    BoardDefinition, BoardSpaceDefinition, CardDefinition, CARD_JAIL_FREE,
    OWNABLE_SPACE_KINDS, PropertyState, SPACE_FREE_PARKING, SPACE_STREET, SPACE_TAX,
    SPACE_TRANSIT, SPACE_UTILITY,
)
from ..monopoly.rules import can_build, liquid_assets, owns_group, unmortgage_cost
from ...game_utils.sequence_runner_mixin import SequenceBeat, SequenceOperation
from ..registry import register_game
from .board import MEXICO_BOARD as LEGACY_BOARD
from .compact_board import MEXICO_BOARD

TURN_TIMER_CHOICES = ("0", "20", "30", "40", "60", "120")
AUCTION_TIMER_CHOICES = ("3", "5", "8", "10", "15")
ECONOMIC_MODE_CHOICES = ("normal", "crisis", "bonanza", "caos")
SAT_AUDIT_PERCENT = 20
SAT_JAIL_TURNS = 2
COBRO_START_CARDS = frozenset({"chance_cobro_de_piso", "community_cobro_de_piso"})
MARINA_OPERATIVO_CARDS = frozenset({"chance_marina_operativo", "community_marina_operativo"})
MIN_COBRO_DE_PISO_TURNS = 8
COBRO_COOLDOWN_TURNS = 3
RANDOM_COBRO_START_PROBABILITY = 0.15
RANDOM_MARINA_BASE_PROBABILITY = 0.05
RANDOM_MARINA_TURN_BONUS = 0.025
RANDOM_MARINA_MAX_PROBABILITY = 0.25

PHASE_VANDALISM_DECISION = "vandalism_decision"
VANDALISM_DURATION_TURNS = 3
PHASE_ENTRY_ACTIONS[PHASE_VANDALISM_DECISION] = (
    "denounce_vandal",
    "skip_vandalism_denounce",
)

SPECIAL_EVENT_FERIA = "feria_turistica"
SPECIAL_EVENT_HOY_NO_CIRCULA = "hoy_no_circula"
SPECIAL_EVENT_APAGON = "apagon_nacional"
SPECIAL_EVENT_DURATION_TURNS = 6
RANDOM_SPECIAL_EVENT_PROBABILITY = 0.14

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
    economic_mode: str = option_field(MenuOption(
        default="normal", choices=list(ECONOMIC_MODE_CHOICES),
        value_key="value",
        label="mexicopoly-option-economic-mode",
        change_msg="mexicopoly-option-changed-economic-mode",
        prompt="mexicopoly-option-select-economic-mode",
        description="mexicopoly-option-economic-mode-description",
        choice_labels={value: f"mexicopoly-economic-mode-{value}" for value in ECONOMIC_MODE_CHOICES},
    ))
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
    cobro_cooldown_turns: int = 0
    vandalized_turns: dict[str, int] = field(default_factory=dict)
    vandalized_this_turn: bool = False
    vandalism_pending: dict[str, Any] = field(default_factory=dict)
    vandalism_resume_phase: str = ""
    vandalism_resume_actor_id: str = ""
    unannounced_vandalisms: list[dict[str, Any]] = field(default_factory=list)
    active_special_event: str = ""
    special_event_turns: int = 0
    special_event_group_id: str = ""

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
        if self.options.economic_mode not in ECONOMIC_MODE_CHOICES:
            errors.append("mexicopoly-error-economic-mode")
        return errors

    def setup_keybinds(self) -> None:
        super().setup_keybinds()
        self.define_keybind(
            "h",
            "Comprar casa",
            ["quick_buy_house"],
            state=KeybindState.ACTIVE,
        )
        self.define_keybind(
            "shift+h",
            "Vender casa",
            ["quick_sell_house"],
            state=KeybindState.ACTIVE,
        )
        self.define_keybind(
            "k",
            "Hipotecar",
            ["quick_mortgage"],
            state=KeybindState.ACTIVE,
        )
        self.define_keybind(
            "shift+k",
            "Deshipotecar",
            ["quick_unmortgage"],
            state=KeybindState.ACTIVE,
        )
        self.define_keybind(
            "v",
            "Ver mi portafolio",
            ["read_my_portfolio"],
            state=KeybindState.ACTIVE,
        )
        self.define_keybind(
            "shift+v",
            "Ver portafolio de todos",
            ["read_portfolios"],
            state=KeybindState.ACTIVE,
            include_spectators=True,
        )
        self.define_keybind(
            "x",
            "Vandalize opponent property",
            ["vandalize_property"],
            state=KeybindState.ACTIVE,
        )

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
                        action.is_hidden = "_is_jail_roll_hidden"
            decline = self.find_action(player, "decline_property")
            if decline:
                decline.get_label = "_get_decline_property_label"
                decline.get_description = "_get_decline_property_description"
            rp = self.find_action(player, "read_portfolios")
            if rp:
                rp.input = None

    def create_standard_action_set(self, player: Player) -> ActionSet:
        action_set = super().create_standard_action_set(player)
        rp = action_set.get_action("read_portfolios")
        if rp:
            rp.input = None
        action_set.add(
            self._action(
                player,
                "quick_buy_house",
                "mexicopoly-action-quick-buy-house",
                "_action_quick_buy_house",
                "_is_quick_buy_enabled",
                "_is_quick_management_hidden",
                description_key="mexicopoly-desc-quick-buy-house",
                input_request=MenuInput(
                    prompt="mexicopoly-prompt-quick-buy-house",
                    options="_build_property_options",
                    bot_select="_first_menu_option",
                    option_label="_build_property_option_label",
                    option_description="_property_option_description",
                    initial_selection="_first_menu_option",
                ),
                show_in_actions_menu=True,
            )
        )
        action_set.add(
            self._action(
                player,
                "quick_sell_house",
                "mexicopoly-action-quick-sell-house",
                "_action_quick_sell_house",
                "_is_quick_sell_enabled",
                "_is_quick_management_hidden",
                description_key="mexicopoly-desc-quick-sell-house",
                input_request=MenuInput(
                    prompt="mexicopoly-prompt-quick-sell-house",
                    options="_sell_property_options",
                    bot_select="_first_menu_option",
                    option_label="_sell_property_option_label",
                    option_description="_sell_property_option_description",
                    initial_selection="_first_menu_option",
                ),
                show_in_actions_menu=True,
            )
        )
        action_set.add(
            self._action(
                player,
                "quick_mortgage",
                "mexicopoly-action-quick-mortgage",
                "_action_quick_mortgage",
                "_is_quick_mortgage_enabled",
                "_is_quick_management_hidden",
                description_key="mexicopoly-desc-quick-mortgage",
                input_request=MenuInput(
                    prompt="mexicopoly-prompt-quick-mortgage",
                    options="_mortgage_property_options",
                    bot_select="_first_menu_option",
                    option_label="_mortgage_property_option_label",
                    option_description="_property_option_description",
                    initial_selection="_first_menu_option",
                ),
                show_in_actions_menu=True,
            )
        )
        action_set.add(
            self._action(
                player,
                "quick_unmortgage",
                "mexicopoly-action-quick-unmortgage",
                "_action_quick_unmortgage",
                "_is_quick_unmortgage_enabled",
                "_is_quick_management_hidden",
                description_key="mexicopoly-desc-quick-unmortgage",
                input_request=MenuInput(
                    prompt="mexicopoly-prompt-quick-unmortgage",
                    options="_unmortgage_property_options",
                    bot_select="_first_menu_option",
                    option_label="_unmortgage_property_option_label",
                    option_description="_property_option_description",
                    initial_selection="_first_menu_option",
                ),
                show_in_actions_menu=True,
            )
        )
        self._apply_standard_action_order(action_set, player)
        return action_set

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
                    action.is_hidden = "_is_jail_roll_hidden"
        decline = actions.get_action("decline_property")
        if decline:
            decline.get_label = "_get_decline_property_label"
            decline.get_description = "_get_decline_property_description"
        actions.add(
            self._action(
                player,
                "vandalize_property",
                "mexicopoly-action-vandalize-property",
                "_action_vandalize_property",
                "_is_vandalize_enabled",
                "_is_vandalize_hidden",
                description_key="mexicopoly-desc-vandalize-property",
                input_request=MenuInput(
                    prompt="mexicopoly-prompt-vandalize-property",
                    options="_vandalize_property_options",
                    bot_select="_first_menu_option",
                    option_label="_vandalize_property_option_label",
                    option_description="_property_option_description",
                    initial_selection="_first_menu_option",
                ),
            )
        )
        actions.add(
            self._action(
                player,
                "denounce_vandal",
                "mexicopoly-action-denounce-vandal",
                "_action_denounce_vandal",
                "_is_vandalism_response_enabled",
                "_is_vandalism_response_hidden",
                description_key="mexicopoly-desc-denounce-vandal",
                input_request=MenuInput(
                    prompt="mexicopoly-prompt-denounce-vandal",
                    options="_vandalism_suspect_options",
                    bot_select="_bot_vandalism_suspect_input",
                    option_label="_vandalism_suspect_option_label",
                    option_description="_trade_target_description",
                    initial_selection="_first_menu_option",
                ),
            )
        )
        actions.add(
            self._action(
                player,
                "skip_vandalism_denounce",
                "mexicopoly-action-skip-vandalism-denounce",
                "_action_skip_vandalism_denounce",
                "_is_vandalism_response_enabled",
                "_is_vandalism_response_hidden",
                description_key="mexicopoly-desc-skip-vandalism-denounce",
            )
        )
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

    def _starting_cash(self) -> int:
        if self.board.id != MEXICO_BOARD.id:
            return self.board.starting_cash
        mode = self.options.economic_mode
        if mode == "crisis":
            return 2400
        if mode == "bonanza":
            return 4000
        if mode == "caos":
            return 3200
        return self.board.starting_cash

    def _go_salary(self) -> int:
        if self.board.id != MEXICO_BOARD.id:
            return self.board.go_salary
        mode = self.options.economic_mode
        if mode == "crisis":
            return 300
        if mode == "bonanza":
            return 550
        if mode == "caos":
            return 450
        return self.board.go_salary

    def on_start(self) -> None:
        self.jail_counts.clear()
        self.sat_jail_turns.clear()
        self.cobro_de_piso_active = False
        self.cobro_de_piso_turns = 0
        self.cobro_cooldown_turns = 0
        self.vandalized_turns.clear()
        self.vandalized_this_turn = False
        self.vandalism_pending.clear()
        self.vandalism_resume_phase = ""
        self.vandalism_resume_actor_id = ""
        self.unannounced_vandalisms.clear()
        self.active_special_event = ""
        self.special_event_turns = 0
        self.special_event_group_id = ""
        self.auction_gavel_stage = 0
        self.auction_gavel_timer.clear()
        super().on_start()
        starting_cash = self._starting_cash()
        for player in self.get_active_players():
            if isinstance(player, MonopolyPlayer):
                player.cash = starting_cash

    def _clear_interactions(self) -> None:
        super()._clear_interactions()
        self.vandalism_pending.clear()
        self.vandalism_resume_phase = ""
        self.vandalism_resume_actor_id = ""

    def on_sequence_callback(
        self,
        sequence_id: str,
        callback_id: str,
        payload: dict[str, Any],
    ) -> None:
        if callback_id == "announce_game_start":
            board = self.board
            starting_cash = self._starting_cash()
            self._broadcast_global(
                "monopoly-game-started",
                "monopoly-game-started-brief",
                players=len(self.alive_players),
                board=lambda locale: Localization.get(locale, board.name_key),
                cash=lambda locale: self._money(locale, starting_cash),
            )
            return
        super().on_sequence_callback(sequence_id, callback_id, payload)

    def _collect_go(
        self, player: MonopolyPlayer, *, landed_on_go: bool = False
    ) -> None:
        amount = self._go_salary()
        if landed_on_go and self.options.double_salary_on_go:
            amount *= 2
        player.cash += amount
        player.passed_go_once = True
        self._broadcast_actor(
            player,
            "monopoly-you-pass-go",
            "monopoly-player-pass-go",
            go=lambda locale: self._space_name(
                locale, self.board.space(self.board.go_space_id)
            ),
            amount=lambda locale: self._money(locale, amount),
            cash=lambda locale: self._money(locale, player.cash),
            brief_personal_key="monopoly-you-pass-go-brief",
            brief_others_key="monopoly-player-pass-go-brief",
        )
        self.play_sound(random.choice(game_audio.SOUND_CASH_RECEIVED))  # nosec B311

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

    def _is_jail_roll_hidden(self, player) -> Visibility:
        del player
        return Visibility.HIDDEN

    def _is_roll_enabled(self, player: MonopolyPlayer):
        if self.phase == PHASE_JAIL:
            turns = self.sat_jail_turns.get(player.id, 0)
            if turns > 0:
                return ("mexicopoly-error-sat-no-bail", {"turns": turns})
            return self._is_jail_roll_enabled(player)
        return super()._is_roll_enabled(player)

    def _action_roll_dice(self, player: MonopolyPlayer, action_id: str) -> None:
        if self.phase == PHASE_JAIL:
            turns = self.sat_jail_turns.get(player.id, 0)
            if turns > 0:
                self._speak(player, "mexicopoly-error-sat-no-bail", turns=turns)
                return
            self._action_jail_roll(player, "jail_roll")
            return
        super()._action_roll_dice(player, action_id)

    def _focus_after_user_transition(self, player: MonopolyPlayer) -> None:
        if (
            not player.is_bot
            and self.status == "playing"
            and self.decision_player_id == player.id
            and self.phase == PHASE_JAIL
            and self.sat_jail_turns.get(player.id, 0) <= 0
        ):
            self.request_menu_focus(player, "roll_dice")
            return
        super()._focus_after_user_transition(player)

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
        if self.sat_jail_turns.get(player.id, 0) > 0:
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
        self.unannounced_vandalisms = [
            v for v in self.unannounced_vandalisms
            if v.get("owner_id") != player.id and v.get("culprit_id") != player.id
        ]
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
        self.cobro_cooldown_turns = 0
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
        self.cobro_cooldown_turns = COBRO_COOLDOWN_TURNS
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
        mode = self.options.economic_mode
        if self.cobro_de_piso_active:
            self.cobro_de_piso_turns += 1
            min_turns = (
                10 if mode == "crisis" else MIN_COBRO_DE_PISO_TURNS
            )
            if self.cobro_de_piso_turns < min_turns:
                return
            turns_over = self.cobro_de_piso_turns - min_turns + 1
            chance = min(
                RANDOM_MARINA_MAX_PROBABILITY,
                RANDOM_MARINA_BASE_PROBABILITY
                + RANDOM_MARINA_TURN_BONUS * turns_over,
            )
            if random.random() < chance:  # nosec B311
                self._deactivate_cobro_de_piso(announce=True, play_sound=True)
            return
        if self.cobro_cooldown_turns > 0:
            self.cobro_cooldown_turns -= 1
            return
        start_prob = (
            0.22
            if mode == "caos"
            else (0.20 if mode == "crisis" else RANDOM_COBRO_START_PROBABILITY)
        )
        if random.random() < start_prob:  # nosec B311
            self._activate_cobro_de_piso(announce=True, play_sound=True)

    # ------------------------------------------------------------------
    # Special Board Events
    # ------------------------------------------------------------------

    def _special_event_name(
        self, locale: str, event_id: str, group_id: str = ""
    ) -> str:
        if event_id == SPECIAL_EVENT_FERIA:
            return Localization.get(
                locale,
                "mexicopoly-event-name-feria",
                group=self._group_name(locale, group_id) if group_id else "",
            )
        if event_id == SPECIAL_EVENT_HOY_NO_CIRCULA:
            return Localization.get(locale, "mexicopoly-event-name-hoy-no-circula")
        if event_id == SPECIAL_EVENT_APAGON:
            return Localization.get(locale, "mexicopoly-event-name-apagon")
        return event_id

    def _activate_special_event(
        self,
        event_id: str,
        *,
        group_id: str = "",
        turns: int = SPECIAL_EVENT_DURATION_TURNS,
        announce: bool = True,
    ) -> None:
        if event_id == SPECIAL_EVENT_FERIA and not group_id:
            street_groups = [
                group.id
                for group in self.board.property_groups
                if any(
                    space.kind == SPACE_STREET
                    for space in self.board.group_spaces(group.id)
                )
            ]
            owned_street_groups = [
                gid
                for gid in street_groups
                if any(
                    self.property_states[space.id].owner_id
                    for space in self.board.group_spaces(gid)
                )
            ]
            pool = owned_street_groups or street_groups
            group_id = random.choice(pool) if pool else ""  # nosec B311
        self.active_special_event = event_id
        self.special_event_turns = turns
        self.special_event_group_id = (
            group_id if event_id == SPECIAL_EVENT_FERIA else ""
        )
        if not announce:
            return
        if event_id == SPECIAL_EVENT_FERIA:
            self._broadcast_global(
                "mexicopoly-event-feria-started",
                "mexicopoly-event-feria-started-brief",
                group=lambda locale: self._group_name(
                    locale, self.special_event_group_id
                ),
                turns=turns,
            )
        elif event_id == SPECIAL_EVENT_HOY_NO_CIRCULA:
            self._broadcast_global(
                "mexicopoly-event-hoy-no-circula-started",
                "mexicopoly-event-hoy-no-circula-started-brief",
                turns=turns,
            )
        elif event_id == SPECIAL_EVENT_APAGON:
            self._broadcast_global(
                "mexicopoly-event-apagon-started",
                "mexicopoly-event-apagon-started-brief",
                turns=turns,
            )

    def _maybe_trigger_special_event(self) -> None:
        if self.status != "playing" or self.turn_number < 3:
            return
        if self.active_special_event:
            self.special_event_turns -= 1
            if self.special_event_turns <= 0:
                ended_event = self.active_special_event
                ended_group = self.special_event_group_id
                self.active_special_event = ""
                self.special_event_turns = 0
                self.special_event_group_id = ""
                self._broadcast_global(
                    "mexicopoly-event-ended",
                    "mexicopoly-event-ended-brief",
                    event=lambda locale: self._special_event_name(
                        locale, ended_event, ended_group
                    ),
                )
            return
        if not any(state.owner_id for state in self.property_states.values()):
            return
        prob = (
            0.28
            if self.options.economic_mode == "caos"
            else RANDOM_SPECIAL_EVENT_PROBABILITY
        )
        if random.random() >= prob:  # nosec B311
            return
        event_id = random.choice(  # nosec B311
            (
                SPECIAL_EVENT_FERIA,
                SPECIAL_EVENT_HOY_NO_CIRCULA,
                SPECIAL_EVENT_APAGON,
            )
        )
        self._activate_special_event(event_id, announce=True)

    # ------------------------------------------------------------------
    # Property Vandalism & Accusation System
    # ------------------------------------------------------------------

    def _vandalism_cost(
        self, space: BoardSpaceDefinition, state: PropertyState | None = None
    ) -> int:
        state = state if state is not None else self.property_states.get(space.id)
        base = max(60, (space.price * 25) // 100)
        if space.kind == SPACE_STREET and state is not None and state.buildings > 0:
            base += state.buildings * max(30, (space.building_cost * 25) // 100)
        return base

    def _vandalism_caught_penalty(
        self,
        space: BoardSpaceDefinition,
        state: PropertyState | None,
        cost: int,
    ) -> int:
        buildings = state.buildings if (space.kind == SPACE_STREET and state) else 0
        proportional = (space.price * 50) // 100 + buildings * max(
            50, (space.building_cost * 40) // 100
        )
        return max(cost * 2, proportional)

    def _vandalism_false_accusation_penalty(
        self,
        space: BoardSpaceDefinition,
        state: PropertyState | None,
        cost: int,
    ) -> int:
        buildings = state.buildings if (space.kind == SPACE_STREET and state) else 0
        proportional = (space.price * 35) // 100 + buildings * max(
            40, (space.building_cost * 25) // 100
        )
        return max((cost * 3) // 2, proportional)

    def _vandalize_property_options(self, player: MonopolyPlayer) -> list[str]:
        if not isinstance(player, MonopolyPlayer):
            return []
        options: list[str] = []
        for space in self.board.spaces:
            if space.id not in self.property_states:
                continue
            state = self.property_states[space.id]
            owner = self._alive_player_by_id(state.owner_id)
            if (
                not owner
                or owner.id == player.id
                or state.mortgaged
                or self.vandalized_turns.get(space.id, 0) > 0
                or any(v.get("property_id") == space.id for v in self.unannounced_vandalisms)
            ):
                continue
            options.append(space.id)
        return options

    def _vandalize_property_option_label(
        self, player: MonopolyPlayer, value: str
    ) -> str:
        if value not in self.property_states:
            return value
        locale = self._locale(player)
        space = self.board.space(value)
        state = self.property_states[value]
        owner = self._alive_player_by_id(state.owner_id)
        cost = self._vandalism_cost(space, state)
        return Localization.get(
            locale,
            "mexicopoly-vandalize-property-option",
            property=self._space_name(locale, space),
            owner=owner.name if owner else "",
            cost=self._money(locale, cost),
        )

    def _is_vandalize_hidden(self, player: MonopolyPlayer) -> Visibility:
        if (
            self.status != "playing"
            or getattr(player, "is_spectator", False)
            or getattr(player, "bankrupt", False)
            or self.phase not in {PHASE_AWAIT_ROLL, PHASE_TURN_ACTIONS}
            or self.decision_player_id != player.id
            or self.vandalized_this_turn
            or not self._vandalize_property_options(player)
        ):
            return Visibility.HIDDEN
        return Visibility.VISIBLE

    def _is_vandalize_enabled(self, player: MonopolyPlayer):
        if not self._is_actor(player) or self.phase not in {
            PHASE_AWAIT_ROLL,
            PHASE_TURN_ACTIONS,
        }:
            return self._waiting_reason(player)
        if self.vandalized_this_turn:
            return "mexicopoly-error-already-vandalized-turn"
        options = self._vandalize_property_options(player)
        if not options:
            return "mexicopoly-error-no-vandalizable-properties"
        cheapest = min(
            self._vandalism_cost(
                self.board.space(prop_id), self.property_states[prop_id]
            )
            for prop_id in options
        )
        if player.cash < cheapest:
            locale = self._locale(player)
            return (
                "mexicopoly-error-vandalize-needs-cash",
                {
                    "cost": self._money(locale, cheapest),
                    "cash": self._money(locale, player.cash),
                },
            )
        return None

    def _announce_vandalism_discovery(
        self,
        victim: MonopolyPlayer,
        space: BoardSpaceDefinition,
    ) -> None:
        for listener in self.players:
            user = self.get_user(listener)
            if not user:
                continue
            locale = user.locale
            is_brief = self._wants_brief(user)
            prop_name = self._space_name(locale, space)
            if listener.id == victim.id:
                key = (
                    "mexicopoly-your-property-vandalized-brief"
                    if is_brief
                    else "mexicopoly-your-property-vandalized"
                )
                user.speak_l(
                    key,
                    buffer="game",
                    property=prop_name,
                    turns=VANDALISM_DURATION_TURNS,
                )
            else:
                key = (
                    "mexicopoly-property-vandalized-brief"
                    if is_brief
                    else "mexicopoly-property-vandalized"
                )
                user.speak_l(
                    key,
                    buffer="game",
                    owner=victim.name,
                    property=prop_name,
                    turns=VANDALISM_DURATION_TURNS,
                )

    def _action_vandalize_property(
        self, player: MonopolyPlayer, input_value: str, action_id: str
    ) -> None:
        del action_id
        error = self._is_vandalize_enabled(player)
        if error:
            if isinstance(error, tuple):
                self._speak(player, error[0], **error[1])
            else:
                self._speak(player, error)
            return
        options = self._vandalize_property_options(player)
        if input_value not in options:
            self._speak(player, "mexicopoly-error-no-vandalizable-properties")
            return
        space = self.board.space(input_value)
        state = self.property_states[space.id]
        victim = self._alive_player_by_id(state.owner_id)
        if not victim or victim.id == player.id:
            return
        cost = self._vandalism_cost(space, state)
        if player.cash < cost:
            locale = self._locale(player)
            self._speak(
                player,
                "mexicopoly-error-vandalize-needs-cash",
                cost=self._money(locale, cost),
                cash=self._money(locale, player.cash),
            )
            return
        player.cash -= cost
        if self.options.free_parking_cash:
            self.free_parking_pot += cost
        self.vandalized_this_turn = True
        alibi_holds = (
            random.random() < 0.45  # nosec B311
            if len(self.alive_players) <= 2
            else False
        )
        self.unannounced_vandalisms.append(
            {
                "property_id": space.id,
                "owner_id": victim.id,
                "culprit_id": player.id,
                "cost": cost,
                "alibi_holds": alibi_holds,
            }
        )
        user = self.get_user(player)
        if user:
            locale = user.locale
            is_brief = self._wants_brief(user)
            prop_name = self._space_name(locale, space)
            key = (
                "mexicopoly-you-vandalize-property-brief"
                if is_brief
                else "mexicopoly-you-vandalize-property"
            )
            user.speak_l(
                key,
                buffer="game",
                property=prop_name,
                owner=victim.name,
                cost=self._money(locale, cost),
                cash=self._money(locale, player.cash),
                turns=VANDALISM_DURATION_TURNS,
            )
        self.refresh_menus(player)

    def _check_and_trigger_vandalism_discovery(
        self, player: MonopolyPlayer
    ) -> bool:
        matching = [
            v for v in self.unannounced_vandalisms
            if v.get("owner_id") == player.id
        ]
        if not matching:
            return False
        pending = matching[0]
        self.unannounced_vandalisms.remove(pending)
        prop_id = str(pending.get("property_id", ""))
        self.vandalized_turns[prop_id] = VANDALISM_DURATION_TURNS
        self.vandalism_pending = dict(pending)
        self.vandalism_resume_phase = self.phase
        self.vandalism_resume_actor_id = player.id
        self.phase = PHASE_VANDALISM_DECISION
        self.decision_player_id = player.id
        if prop_id in self.property_states:
            space = self.board.space(prop_id)
            self._announce_vandalism_discovery(player, space)
        self.play_sound(game_audio.SOUND_DEBT_WARNING)
        self._focus_after_user_transition(player)
        self.refresh_menus()
        return True

    def _is_vandalism_response_hidden(self, player: MonopolyPlayer) -> Visibility:
        return self._visible_for_actor(player, PHASE_VANDALISM_DECISION)

    def _is_vandalism_response_enabled(self, player: MonopolyPlayer):
        return (
            None
            if self._is_actor(player, PHASE_VANDALISM_DECISION)
            else self._waiting_reason(player)
        )

    def _vandalism_suspect_options(self, player: MonopolyPlayer) -> list[str]:
        return [
            other.id
            for other in self.alive_players
            if other.id != player.id
        ]

    def _bot_vandalism_suspect_input(
        self, player: MonopolyPlayer, options: list[str]
    ) -> str | None:
        del player
        return random.choice(options) if options else None  # nosec B311

    def _vandalism_suspect_option_label(
        self, player: MonopolyPlayer, value: str
    ) -> str:
        suspect = self._alive_player_by_id(value)
        if not suspect:
            return value
        locale = self._locale(player)
        prop_id = str(self.vandalism_pending.get("property_id", ""))
        cost = int(self.vandalism_pending.get("cost", 0))
        if prop_id in self.property_states:
            space = self.board.space(prop_id)
            state = self.property_states[prop_id]
            caught_pen = self._vandalism_caught_penalty(space, state, cost)
            false_pen = self._vandalism_false_accusation_penalty(space, state, cost)
            return Localization.get(
                locale,
                "mexicopoly-vandalism-suspect-option",
                suspect=suspect.name,
                reward=self._money(locale, caught_pen),
                risk=self._money(locale, false_pen),
            )
        return suspect.name

    def _action_denounce_vandal(
        self, player: MonopolyPlayer, input_value: str, action_id: str
    ) -> None:
        del action_id
        if not self._is_actor(player, PHASE_VANDALISM_DECISION):
            return
        suspect = self._alive_player_by_id(input_value)
        if not suspect or suspect.id == player.id:
            return
        pending = dict(self.vandalism_pending)
        prop_id = str(pending.get("property_id", ""))
        culprit_id = str(pending.get("culprit_id", ""))
        cost = int(pending.get("cost", 0))
        alibi_holds = bool(pending.get("alibi_holds", False))
        self.vandalism_resume_phase = str(
            pending.get("resume_phase", self.vandalism_resume_phase or PHASE_AWAIT_ROLL)
        )
        self.vandalism_resume_actor_id = str(
            pending.get("resume_actor_id", self.vandalism_resume_actor_id)
        )
        self.vandalism_pending.clear()
        if prop_id not in self.property_states:
            self._resume_after_vandalism()
            return
        space = self.board.space(prop_id)
        state = self.property_states[prop_id]
        caught = suspect.id == culprit_id and not alibi_holds
        if caught:
            self.vandalized_turns.pop(prop_id, None)
            penalty = self._vandalism_caught_penalty(space, state, cost)
            self._broadcast_actor_target(
                player,
                suspect,
                "mexicopoly-you-denounce-correct",
                "mexicopoly-you-were-caught-vandalizing",
                "mexicopoly-player-denounces-correct",
                brief_personal_key="mexicopoly-you-denounce-correct-brief",
                brief_target_key="mexicopoly-you-were-caught-vandalizing-brief",
                brief_others_key="mexicopoly-player-denounces-correct-brief",
                suspect=suspect.name,
                victim=player.name,
                property=lambda locale: self._space_name(locale, space),
                penalty=lambda locale: self._money(locale, penalty),
            )
            self._start_debt(
                suspect,
                player.id,
                penalty,
                "mexicopoly-debt-vandalism-caught",
                continuation="resume_after_vandalism",
            )
            self._focus_after_user_transition(player)
            return
        penalty = self._vandalism_false_accusation_penalty(space, state, cost)
        self._broadcast_actor_target(
            player,
            suspect,
            "mexicopoly-you-denounce-false",
            "mexicopoly-you-were-falsely-accused",
            "mexicopoly-player-denounces-false",
            brief_personal_key="mexicopoly-you-denounce-false-brief",
            brief_target_key="mexicopoly-you-were-falsely-accused-brief",
            brief_others_key="mexicopoly-player-denounces-false-brief",
            suspect=suspect.name,
            accuser=player.name,
            property=lambda locale: self._space_name(locale, space),
            penalty=lambda locale: self._money(locale, penalty),
        )
        self._start_debt(
            player,
            suspect.id,
            penalty,
            "mexicopoly-debt-false-accusation",
            continuation="resume_after_vandalism",
        )
        self._focus_after_user_transition(player)

    def _action_skip_vandalism_denounce(
        self, player: MonopolyPlayer, action_id: str
    ) -> None:
        del action_id
        if not self._is_actor(player, PHASE_VANDALISM_DECISION):
            return
        pending = dict(self.vandalism_pending)
        prop_id = str(pending.get("property_id", ""))
        self.vandalism_resume_phase = str(
            pending.get("resume_phase", self.vandalism_resume_phase or PHASE_AWAIT_ROLL)
        )
        self.vandalism_resume_actor_id = str(
            pending.get("resume_actor_id", self.vandalism_resume_actor_id)
        )
        self.vandalism_pending.clear()
        if prop_id in self.property_states:
            space = self.board.space(prop_id)
            self._broadcast_actor(
                player,
                "mexicopoly-you-skip-denounce",
                "mexicopoly-player-skips-denounce",
                property=lambda locale: self._space_name(locale, space),
                turns=self.vandalized_turns.get(prop_id, VANDALISM_DURATION_TURNS),
                brief_personal_key="mexicopoly-you-skip-denounce-brief",
                brief_others_key="mexicopoly-player-skips-denounce-brief",
            )
        self._resume_after_vandalism()
        self._focus_after_user_transition(player)

    def _resume_after_vandalism(self) -> None:
        resume_phase = self.vandalism_resume_phase or PHASE_AWAIT_ROLL
        resume_actor_id = self.vandalism_resume_actor_id
        self.vandalism_resume_phase = ""
        self.vandalism_resume_actor_id = ""
        self.vandalism_pending.clear()
        actor = self._alive_player_by_id(resume_actor_id)
        if not actor or actor.bankrupt:
            current = self.current_player
            if isinstance(current, MonopolyPlayer) and not current.bankrupt:
                actor = current
            else:
                self._start_turn(announce=True)
                return
        if self._check_and_trigger_vandalism_discovery(actor):
            self.vandalism_resume_phase = resume_phase
            return
        self._restore_interrupted_phase(resume_phase, actor.id)
        self._focus_after_user_transition(actor)

    def _tick_vandalized_properties(
        self, player: MonopolyPlayer | None = None
    ) -> None:
        if not self.vandalized_turns:
            return
        expired: list[str] = []
        for prop_id in list(self.vandalized_turns.keys()):
            state = self.property_states.get(prop_id)
            if player is not None:
                if state and state.owner_id and state.owner_id != player.id:
                    continue
            remaining = self.vandalized_turns[prop_id] - 1
            if remaining <= 0:
                expired.append(prop_id)
                del self.vandalized_turns[prop_id]
            else:
                self.vandalized_turns[prop_id] = remaining
        for prop_id in expired:
            if prop_id in self.property_states:
                space = self.board.space(prop_id)
                self._broadcast_global(
                    "mexicopoly-vandalism-repaired",
                    "mexicopoly-vandalism-repaired-brief",
                    property=lambda locale, s=space: self._space_name(locale, s),
                )

    def _next_building_cost(
        self, space: BoardSpaceDefinition, current_buildings: int | None = None
    ) -> int:
        if current_buildings is None:
            state = self.property_states.get(space.id)
            current_buildings = state.buildings if state else 0
        h_per_hotel = self.board.development.houses_per_hotel
        if current_buildings >= h_per_hotel:
            return max(1, (space.building_cost * 3) // 2)
        return space.building_cost

    def _street_undeveloped_group_rents(
        self, space: BoardSpaceDefinition
    ) -> tuple[int, int]:
        base = space.rents[0] if space.rents else 0
        two_of_three = max(1, (base * 150) // 100)
        full_group = max(1, (base * 2 * 125) // 100)
        return two_of_three, full_group

    def _rent_schedule_text(self, locale: str, space: BoardSpaceDefinition) -> str:
        if space.kind == SPACE_STREET and self.board.id == MEXICO_BOARD.id:
            h_per_hotel = self.board.development.houses_per_hotel
            two_of_three, full_group = self._street_undeveloped_group_rents(space)
            parts = [
                f"base {self._money(locale, space.rents[0])}",
                Localization.get(
                    locale,
                    "mexicopoly-rent-two-of-three",
                    amount=self._money(locale, two_of_three),
                ),
                Localization.get(
                    locale,
                    "mexicopoly-rent-full-group",
                    amount=self._money(locale, full_group),
                ),
            ]
            for h in range(1, h_per_hotel + 1):
                h_name = Localization.get(
                    locale, "monopoly-building-house-count", count=h
                )
                parts.append(f"{h_name} {self._money(locale, space.rents[h])}")
            parts.append(
                f"{Localization.get(locale, 'monopoly-building-one-hotel')} "
                f"{self._money(locale, space.rents[h_per_hotel + 1])}"
            )
            if space.max_hotels > 1 and len(space.rents) > h_per_hotel + 2:
                parts.append(
                    f"{Localization.get(locale, 'mexicopoly-building-two-hotels', count=2)} "
                    f"{self._money(locale, space.rents[h_per_hotel + 2])}"
                )
            schedule = "; ".join(parts)
            hotel_str = (
                Localization.get(locale, "monopoly-building-one-hotel")
                if space.max_hotels == 1
                else Localization.get(
                    locale, "mexicopoly-building-two-hotels", count=space.max_hotels
                )
            )
            spec = Localization.get(
                locale,
                "mexicopoly-building-spec",
                houses=h_per_hotel,
                hotels=hotel_str,
            )
            cost_spec = Localization.get(
                locale,
                "mexicopoly-hotel-cost-spec",
                house_cost=self._money(locale, space.building_cost),
                hotel_cost=self._money(
                    locale, self._next_building_cost(space, h_per_hotel)
                ),
            )
            return f"{schedule}. {spec} {cost_spec}"
        return super()._rent_schedule_text(locale, space)

    def _build_property_error(
        self, player: MonopolyPlayer, property_id: str
    ) -> str | tuple[str, dict] | None:
        turns = self.vandalized_turns.get(property_id, 0)
        if turns > 0:
            return ("mexicopoly-error-property-vandalized", {"turns": turns})
        state = self.property_states.get(property_id)
        if not state or state.owner_id != player.id:
            return "monopoly-error-not-your-property"
        space = self.board.space(property_id)
        error = can_build(
            self.board,
            self.property_states,
            property_id,
            player.id,
            self.bank_houses,
            self.bank_hotels,
        )
        if error:
            return self._development_error_key(error)
        cost = self._next_building_cost(space, state.buildings)
        if player.cash < cost:
            locale = self._locale(player)
            return (
                "monopoly-error-building-needs-cash",
                {
                    "cost": self._money(locale, cost),
                    "cash": self._money(locale, player.cash),
                },
            )
        return None

    def _build_selector_empty_reason(
        self, player: MonopolyPlayer
    ) -> str | tuple[str, dict]:
        reason = super()._build_selector_empty_reason(player)
        if isinstance(reason, tuple):
            eligible = [
                self.board.space(prop_id)
                for prop_id in self._manage_property_options(player)
                if self.board.space(prop_id).kind == SPACE_STREET
                and self.vandalized_turns.get(prop_id, 0) == 0
                and can_build(
                    self.board,
                    self.property_states,
                    prop_id,
                    player.id,
                    self.bank_houses,
                    self.bank_hotels,
                )
                is None
            ]
            if eligible:
                cheapest = min(
                    self._next_building_cost(
                        space, self.property_states[space.id].buildings
                    )
                    for space in eligible
                )
                locale = self._locale(player)
                return (
                    reason[0],
                    {
                        "cost": self._money(locale, cheapest),
                        "cash": self._money(locale, player.cash),
                    },
                )
        return reason

    def _get_management_action_label(self, player, action_id: str) -> str:
        if action_id == "build" and isinstance(player, MonopolyPlayer):
            context = self._management_context(player)
            if (
                context
                and context[0].kind == SPACE_STREET
                and not self._management_action_disabled_reason(player, action_id)
            ):
                space, state = context
                locale = self._locale(player)
                return Localization.get(
                    locale,
                    "monopoly-build-label",
                    building=self._development_level_text(
                        locale, state.buildings + 1
                    ),
                    cost=self._money(
                        locale, self._next_building_cost(space, state.buildings)
                    ),
                )
        return super()._get_management_action_label(player, action_id)

    def _build_property_option_label(self, player, value: str) -> str:
        if value not in self.property_states:
            return value
        locale = self._locale(player)
        space = self.board.space(value)
        state = self.property_states[value]
        return Localization.get(
            locale,
            "monopoly-build-property-option",
            property=self._space_name(locale, space),
            group=self._group_name(locale, space.group_id),
            building=self._development_level_text(locale, state.buildings + 1),
            cost=self._money(
                locale, self._next_building_cost(space, state.buildings)
            ),
            current=self._building_text(locale, state.buildings),
            cash=self._money(locale, getattr(player, "cash", 0)),
        )

    def _apply_build(
        self, player: MonopolyPlayer, property_id: str, *, announce: bool = True
    ) -> None:
        if self._build_property_error(player, property_id):
            return
        space = self.board.space(property_id)
        state = self.property_states[property_id]
        cost = self._next_building_cost(space, state.buildings)
        player.cash -= cost
        built_level = state.buildings + 1
        state.buildings = built_level
        h_per_hotel = self.board.development.houses_per_hotel
        if self.board.development.finite_supply:
            if built_level == h_per_hotel + 1:
                self.bank_hotels -= 1
                self.bank_houses += h_per_hotel
            elif built_level > h_per_hotel + 1:
                self.bank_hotels -= 1
            else:
                self.bank_houses -= 1
        if announce:
            self._broadcast_actor(
                player,
                "monopoly-you-build",
                "monopoly-player-builds",
                building=lambda locale: self._development_level_text(
                    locale, built_level
                ),
                property=lambda locale: self._space_name(locale, space),
                cost=lambda locale: self._money(locale, cost),
                cash=lambda locale: self._money(locale, player.cash),
                brief_personal_key="monopoly-you-build-brief",
                brief_others_key="monopoly-player-builds-brief",
            )
            self.play_sound(game_audio.SOUND_DEVELOPMENT_BUILT)
        self.refresh_menus()

    def _bot_management_choice(
        self,
        player: MonopolyPlayer,
        property_id: str,
    ) -> tuple[str, int] | None:
        choice = super()._bot_management_choice(player, property_id)
        if not choice:
            return None
        if choice[0] == "build":
            if self._build_property_error(player, property_id) is not None:
                return None
            space = self.board.space(property_id)
            state = self.property_states[property_id]
            cost = self._next_building_cost(space, state.buildings)
            reserve = risk_adjusted_cash_reserve(
                self.board,
                self.property_states,
                player.id,
            )
            cash_after_build = player.cash - cost
            if cash_after_build < reserve or (
                state.buildings >= 3 and cash_after_build < reserve * 2
            ):
                return None
        return choice

    def _start_debt(
        self,
        debtor: MonopolyPlayer,
        creditor_id: str,
        amount: int,
        reason_key: str,
        *,
        continuation: str,
        property_id: str = "",
    ) -> None:
        super()._start_debt(
            debtor,
            creditor_id,
            amount,
            reason_key,
            continuation=continuation,
            property_id=property_id,
        )
        if (
            self.phase == PHASE_DEBT
            and self.debt_state
            and self.debt_state.debtor_id == debtor.id
            and liquid_assets(
                self.board,
                self.property_states,
                debtor.id,
                debtor.cash,
            )
            < self.debt_state.amount
        ):
            self._action_declare_bankruptcy(debtor, "declare_bankruptcy")

    def _property_state_text(
        self,
        locale: str,
        state: PropertyState,
        space: BoardSpaceDefinition | None = None,
    ) -> str:
        base = super()._property_state_text(locale, state, space)
        if space and self.vandalized_turns.get(space.id, 0) > 0:
            suffix = Localization.get(
                locale,
                "mexicopoly-property-state-vandalized-suffix",
                turns=self.vandalized_turns[space.id],
            )
            return f"{base}{suffix}"
        return base

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

    def _draw_card(self, player: MonopolyPlayer, deck_id: str) -> None:
        deck = self.chance_deck if deck_id == "chance" else self.community_deck
        if not deck:
            raise RuntimeError(f"Monopoly {deck_id} deck is unexpectedly empty")
        card_id = deck.pop(0)
        card = self.board.card(deck_id, card_id)
        if card.action != CARD_JAIL_FREE:
            deck.append(card_id)
        draw_sound = random.choice(game_audio.SOUND_CARD_DRAWS)  # nosec B311
        beats: list[SequenceBeat] = []
        if card_id in MARINA_OPERATIVO_CARDS:
            beats.append(SequenceBeat.pause(18))
        beats.extend(
            [
                SequenceBeat.after_audio(
                    game_audio.sound_ticks(draw_sound),
                    ops=[SequenceOperation.sound_op(draw_sound)],
                ),
                SequenceBeat(
                    ops=[
                        SequenceOperation.callback_op(
                            "resolve_drawn_card",
                            {
                                "player_id": player.id,
                                "deck_id": deck_id,
                                "card_id": card_id,
                            },
                        )
                    ]
                ),
            ]
        )
        self.start_sequence(
            (
                f"monopoly_draw_card_{self.turn_number}_{deck_id}_"
                f"{card_id}_{self.sound_scheduler_tick}"
            ),
            beats,
            tag="monopoly_card",
            lock_scope=self.SEQUENCE_LOCK_GAMEPLAY,
            pause_bots=True,
        )

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
            self._deactivate_cobro_de_piso(announce=False, play_sound=True)
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
        if continuation == "resume_after_vandalism":
            self._resume_after_vandalism()
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
        if space.kind == SPACE_TAX and self.options.economic_mode == "crisis":
            tax_amount = (space.tax_amount * 125) // 100
            self._start_debt(
                player,
                "",
                tax_amount,
                "monopoly-debt-tax",
                continuation="finish_landing",
            )
            return
        if space.kind == SPACE_FREE_PARKING:
            amount = self.free_parking_pot
            self.free_parking_pot = 0
            if amount > 0:
                player.cash += amount
                self._broadcast_actor(
                    player,
                    "mexicopoly-you-collect-bote",
                    "mexicopoly-player-collects-bote",
                    amount=lambda locale: self._money(locale, amount),
                    cash=lambda locale: self._money(locale, player.cash),
                    brief_personal_key="mexicopoly-you-collect-bote-brief",
                    brief_others_key="mexicopoly-player-collects-bote-brief",
                )
                self.play_sound(game_audio.SOUND_LARGE_CASH_PAYOUT)
            else:
                self._broadcast_actor(
                    player,
                    "mexicopoly-you-bote-empty",
                    "mexicopoly-player-bote-empty",
                    suppress_brief=True,
                )
            self._finish_landing()
            return
        super()._resolve_landing(
            player,
            rent_multiplier=rent_multiplier,
            utility_override=utility_override,
        )

    def _announce_rent_payment(self, owner, tenant, space, amount):
        state = self.property_states.get(space.id)
        buildings = state.buildings if state else 0
        h_per_hotel = self.board.development.houses_per_hotel
        is_street = space.kind == SPACE_STREET
        has_buildings = is_street and buildings > 0
        is_hotel = buildings > h_per_hotel

        if self.cobro_de_piso_active and amount > 0:
            percent, cut, net = self._extortion_cut(space, amount)
            owner.cash -= cut
            self.free_parking_pot += cut
            if has_buildings:
                flavor_key = (
                    f"mexicopoly-hotel-flavor-{min(buildings - h_per_hotel, 2)}"
                    if is_hotel
                    else f"mexicopoly-house-flavor-{min(buildings, 5)}"
                )
                self._broadcast_actor_target(
                    owner,
                    tenant,
                    "mexicopoly-you-collect-rent-houses-extorted",
                    "mexicopoly-you-pay-rent-houses-extorted",
                    "mexicopoly-player-pays-rent-houses-extorted",
                    brief_personal_key="mexicopoly-you-collect-rent-extorted-brief",
                    brief_target_key="mexicopoly-you-pay-rent-extorted-brief",
                    brief_others_key="mexicopoly-player-pays-rent-extorted-brief",
                    owner=owner.name,
                    tenant=tenant.name,
                    property=lambda locale: self._space_name(locale, space),
                    buildings=lambda locale: self._building_text(locale, buildings),
                    amount=lambda locale: self._money(locale, amount),
                    cut=lambda locale: self._money(locale, cut),
                    net=lambda locale: self._money(locale, net),
                    percent=percent,
                    owner_cash=lambda locale: self._money(locale, owner.cash),
                    tenant_cash=lambda locale: self._money(locale, tenant.cash),
                    flavor=lambda locale: Localization.get(
                        locale,
                        flavor_key,
                        owner=owner.name,
                        property=self._space_name(locale, space),
                    ),
                )
                return
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
            return

        if has_buildings and amount > 0:
            flavor_key = (
                f"mexicopoly-hotel-flavor-{min(buildings - h_per_hotel, 2)}"
                if is_hotel
                else f"mexicopoly-house-flavor-{min(buildings, 5)}"
            )
            self._broadcast_actor_target(
                owner,
                tenant,
                "mexicopoly-you-collect-rent-houses",
                "mexicopoly-you-pay-rent-houses",
                "mexicopoly-player-pays-rent-houses",
                brief_personal_key="monopoly-you-collect-rent-brief",
                brief_target_key="monopoly-you-pay-rent-brief",
                brief_others_key="monopoly-player-pays-rent-brief",
                owner=owner.name,
                tenant=tenant.name,
                property=lambda locale: self._space_name(locale, space),
                buildings=lambda locale: self._building_text(locale, buildings),
                amount=lambda locale: self._money(locale, amount),
                owner_cash=lambda locale: self._money(locale, owner.cash),
                tenant_cash=lambda locale: self._money(locale, tenant.cash),
                flavor=lambda locale: Localization.get(
                    locale,
                    flavor_key,
                    owner=owner.name,
                    property=self._space_name(locale, space),
                ),
            )
            return

        super()._announce_rent_payment(owner, tenant, space, amount)

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
        if rent > 0:
            if space.kind == SPACE_STREET:
                state = self.property_states.get(space.id)
                if state and state.buildings == 0:
                    group_spaces = self.board.group_spaces(space.group_id)
                    owned_in_group = sum(
                        1
                        for member in group_spaces
                        if self.property_states[member.id].owner_id == owner.id
                    )
                    if owned_in_group == 2:
                        rent = max(1, (rent * 150) // 100)
                    elif owned_in_group == len(group_spaces) and len(group_spaces) >= 3:
                        rent = max(1, (rent * 125) // 100)
            if (
                self.active_special_event == SPECIAL_EVENT_FERIA
                and space.kind == SPACE_STREET
                and space.group_id == self.special_event_group_id
            ):
                rent = max(1, (rent * 150) // 100)
            elif (
                self.active_special_event == SPECIAL_EVENT_HOY_NO_CIRCULA
                and space.kind == SPACE_TRANSIT
            ):
                rent = max(1, (rent * 150) // 100)
            elif (
                self.active_special_event == SPECIAL_EVENT_APAGON
                and space.kind == SPACE_UTILITY
            ):
                rent = max(1, (rent * 150) // 100)
            if self.vandalized_turns.get(space.id, 0) > 0:
                rent = max(1, rent // 2)
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
        self.vandalized_this_turn = False
        current = self.current_player
        if announce:
            self._tick_vandalized_properties(
                current if isinstance(current, MonopolyPlayer) else None
            )
            self._maybe_trigger_random_cobro_event()
            self._maybe_trigger_special_event()
        super()._start_turn(announce=announce)
        self.turn_time_exhausted = False
        self.response_timer.clear()
        self.response_timer_context = ""
        self.start_turn_timer()
        if announce and self.status == "playing":
            current = self.current_player
            if isinstance(current, MonopolyPlayer) and not current.bankrupt:
                if self.sat_jail_turns.get(current.id, 0) > 0 and current.in_jail:
                    self._handle_sat_jail_turn(current)
                    return
                self._check_and_trigger_vandalism_discovery(current)

    def _handle_sat_jail_turn(self, player: MonopolyPlayer) -> None:
        turns = self.sat_jail_turns.get(player.id, 0)
        remaining = turns - 1
        player.jail_turns += 1
        if remaining > 0:
            self.sat_jail_turns[player.id] = remaining
            self._broadcast_actor(
                player,
                "mexicopoly-you-stay-sat-jail",
                "mexicopoly-player-stays-sat-jail",
                remaining=remaining,
                turns=remaining,
                brief_personal_key="mexicopoly-you-stay-sat-jail-brief",
                brief_others_key="mexicopoly-player-stays-sat-jail-brief",
            )
            self._finish_turn()
            self._focus_after_user_transition(player)
        else:
            self.sat_jail_turns.pop(player.id, None)
            player.in_jail = False
            player.jail_turns = 0
            self._broadcast_actor(
                player,
                "mexicopoly-you-leave-sat-jail",
                "mexicopoly-player-leaves-sat-jail",
                brief_personal_key="mexicopoly-you-leave-sat-jail-brief",
                brief_others_key="mexicopoly-player-leaves-sat-jail-brief",
            )
            self.play_sound(game_audio.SOUND_LEAVE_JAIL)
            self._finish_turn()
            self._focus_after_user_transition(player)

    def _can_interrupt(self, player):
        # Optional management/trades belong to the acting player's own turn.
        # Required auction/debt responders may still manage their assets.
        if self.phase == PHASE_VANDALISM_DECISION:
            return False
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
        if self.phase == PHASE_VANDALISM_DECISION:
            suspects = self._vandalism_suspect_options(player)
            if suspects and random.random() < 0.65:  # nosec B311
                return "denounce_vandal"
            return "skip_vandalism_denounce"
        if self.phase == PHASE_JAIL and self.sat_jail_turns.get(player.id, 0) > 0:
            return None
        # Management used to happen after rolling. Do it before the final roll
        # now, otherwise automatic turn completion would prevent bots building.
        if self.phase == PHASE_AWAIT_ROLL:
            if self._bot_has_management_opportunity(player):
                return "manage_properties"
            if player.bot_trade_turn != self.turn_number:
                player.bot_trade_turn = self.turn_number
                if self._bot_best_trade_plan(player):
                    return "propose_trade"
        choice = super().bot_think(player)
        return "roll_dice" if choice == "jail_roll" else choice

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
                PHASE_VANDALISM_DECISION: "skip-denounce",
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
            self._action_roll_dice(actor, "roll_dice")
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
        elif self.phase == PHASE_VANDALISM_DECISION:
            self._action_skip_vandalism_denounce(actor, "skip_vandalism_denounce")

    def _phase_name(self, locale: str) -> str:
        if self.phase != PHASE_SETUP and self.is_sequence_gameplay_locked():
            return Localization.get(locale, "monopoly-phase-resolving")
        if self.phase == PHASE_VANDALISM_DECISION:
            return Localization.get(locale, "mexicopoly-phase-vandalism-decision")
        return super()._phase_name(locale)

    def _build_game_status(self, player, user):
        result = super()._build_game_status(player, user)
        result.items.append(
            MenuItem(
                id="mexicopoly:economic_mode",
                text=Localization.get(
                    user.locale,
                    "mexicopoly-status-economic-mode",
                    mode=Localization.get(
                        user.locale,
                        f"mexicopoly-economic-mode-{self.options.economic_mode}",
                    ),
                ),
            )
        )
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
        if self.active_special_event:
            result.items.append(
                MenuItem(
                    id="mexicopoly:special_event",
                    text=Localization.get(
                        user.locale,
                        "mexicopoly-status-special-event",
                        event=self._special_event_name(
                            user.locale,
                            self.active_special_event,
                            self.special_event_group_id,
                        ),
                        turns=self.special_event_turns,
                    ),
                )
            )
        for prop_id, turns in self.vandalized_turns.items():
            if turns > 0 and prop_id in self.property_states:
                space = self.board.space(prop_id)
                result.items.append(
                    MenuItem(
                        id=f"mexicopoly:vandalized:{prop_id}",
                        text=Localization.get(
                            user.locale,
                            "mexicopoly-status-vandalized-property",
                            property=self._space_name(user.locale, space),
                            turns=turns,
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
        if self.free_parking_pot > 0 or self.cobro_de_piso_active:
            result.items.append(
                MenuItem(
                    id="mexicopoly:bote_pot",
                    text=Localization.get(
                        user.locale,
                        "mexicopoly-status-bote-pot",
                        amount=self._money(user.locale, self.free_parking_pot),
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

    def _development_level_text(self, locale: str, level: int) -> str:
        h_per_hotel = self.board.development.houses_per_hotel
        if level <= h_per_hotel:
            return Localization.get(locale, "mexicopoly-building-house-nth", count=level)
        num_hotels = level - h_per_hotel
        if num_hotels == 1:
            return Localization.get(locale, "monopoly-building-hotel")
        return Localization.get(locale, "mexicopoly-building-second-hotel")

    def _is_quick_management_enabled(self, player: MonopolyPlayer) -> str | None:
        if self.status != "playing" or not self.property_states:
            return self._waiting_reason(player)
        if not self._can_interrupt(player):
            return self._waiting_reason(player)
        return None

    def _is_quick_buy_enabled(self, player: MonopolyPlayer) -> str | tuple[str, dict] | None:
        err = self._is_quick_management_enabled(player)
        if err:
            return err
        if not self._build_property_options(player):
            return self._build_selector_empty_reason(player)
        return None

    def _is_quick_sell_enabled(self, player: MonopolyPlayer) -> str | None:
        err = self._is_quick_management_enabled(player)
        if err:
            return err
        if not self._sell_property_options(player):
            return self._development_error_key("monopoly-error-no-sellable-buildings")
        return None

    def _is_quick_mortgage_enabled(self, player: MonopolyPlayer) -> str | None:
        err = self._is_quick_management_enabled(player)
        if err:
            return err
        if not self._mortgage_property_options(player):
            return "monopoly-error-no-mortgageable-properties"
        return None

    def _is_quick_unmortgage_enabled(self, player: MonopolyPlayer) -> str | None:
        err = self._is_quick_management_enabled(player)
        if err:
            return err
        if not self._unmortgage_property_options(player):
            return "monopoly-error-no-unmortgageable-properties"
        return None

    def _is_quick_management_hidden(self, player: Player) -> Visibility:
        if self.status != "playing" or not self.property_states:
            return Visibility.HIDDEN
        if player.is_spectator or not isinstance(player, MonopolyPlayer) or player.bankrupt:
            return Visibility.HIDDEN
        return Visibility.VISIBLE

    def _action_unmortgage(self, player: MonopolyPlayer, action_id: str) -> None:
        del action_id
        if self._is_unmortgage_enabled(player):
            return
        self._apply_unmortgage(player, self.management_property_id)
        self._focus_management_task(player, "choose_unmortgage_property")

    def _apply_unmortgage(
        self, player: MonopolyPlayer, property_id: str, *, announce: bool = True
    ) -> None:
        if property_id not in self.property_states:
            return
        space = self.board.space(property_id)
        state = self.property_states[property_id]
        if not state.mortgaged:
            return
        cost = unmortgage_cost(
            space.mortgage_value, self.board.rules.mortgage_interest_percent
        )
        if player.cash < cost:
            return
        player.cash -= cost
        state.mortgaged = False
        if announce:
            self._broadcast_actor(
                player,
                "monopoly-you-unmortgage",
                "monopoly-player-unmortgages",
                property=lambda locale: self._space_name(locale, space),
                cost=lambda locale: self._money(locale, cost),
                cash=lambda locale: self._money(locale, player.cash),
                brief_personal_key="monopoly-you-unmortgage-brief",
                brief_others_key="monopoly-player-unmortgages-brief",
            )
            self.play_sound(game_audio.SOUND_PROPERTY_UNMORTGAGED)
        self.refresh_menus()

    def _action_quick_buy_house(
        self, player: MonopolyPlayer, *args, **kwargs
    ) -> None:
        if self._is_quick_buy_enabled(player):
            return
        input_value = ""
        if args:
            input_value = str(args[0])
        elif "input_value" in kwargs:
            input_value = str(kwargs["input_value"])
        if not input_value and self.management_property_id:
            input_value = self.management_property_id
        if not input_value or input_value not in self.property_states:
            return
        if self._build_property_error(player, input_value):
            return
        self._apply_build(player, input_value)

    def _action_quick_sell_house(
        self, player: MonopolyPlayer, *args, **kwargs
    ) -> None:
        if self._is_quick_sell_enabled(player):
            return
        input_value = ""
        if args:
            input_value = str(args[0])
        elif "input_value" in kwargs:
            input_value = str(kwargs["input_value"])
        if not input_value and self.management_property_id:
            input_value = self.management_property_id
        if not input_value:
            return
        if input_value.startswith(SELL_GROUP_OPTION_PREFIX):
            group_id = input_value.removeprefix(SELL_GROUP_OPTION_PREFIX)
            self._apply_sell_group_buildings(player, group_id)
        elif input_value in self.property_states:
            self._apply_sell_building(player, input_value)

    def _action_quick_mortgage(
        self, player: MonopolyPlayer, *args, **kwargs
    ) -> None:
        if self._is_quick_mortgage_enabled(player):
            return
        input_value = ""
        if args:
            input_value = str(args[0])
        elif "input_value" in kwargs:
            input_value = str(kwargs["input_value"])
        if not input_value and self.management_property_id:
            input_value = self.management_property_id
        if not input_value or input_value not in self.property_states:
            return
        self._apply_mortgage(player, input_value)

    def _action_quick_unmortgage(
        self, player: MonopolyPlayer, *args, **kwargs
    ) -> None:
        if self._is_quick_unmortgage_enabled(player):
            return
        input_value = ""
        if args:
            input_value = str(args[0])
        elif "input_value" in kwargs:
            input_value = str(kwargs["input_value"])
        if not input_value and self.management_property_id:
            input_value = self.management_property_id
        if not input_value or input_value not in self.property_states:
            return
        self._apply_unmortgage(player, input_value)

    def _all_portfolios_sorted_players(self) -> list[MonopolyPlayer]:
        players = [p for p in self.alive_players if isinstance(p, MonopolyPlayer)]
        return sorted(players, key=lambda p: (self._net_worth(p), p.cash), reverse=True)

    def _build_all_portfolios_status(self, viewer: Player, user) -> StatusBoxBuild:
        locale = user.locale
        items: list[MenuItem] = []
        ranked_players = self._all_portfolios_sorted_players()
        for rank, owner in enumerate(ranked_players, start=1):
            summary = Localization.get(
                locale,
                "mexicopoly-portfolio-ranked-summary",
                rank=rank,
                player=owner.name,
                cash=self._money(locale, owner.cash),
                net_worth=self._money(locale, self._net_worth(owner)),
            )
            items.append(
                MenuItem(
                    id=f"all:summary:{owner.id}",
                    text=summary,
                )
            )
            prop_items = self._portfolio_property_items(locale, owner, prefix=f"all:{owner.id}")
            items.extend(prop_items)
        return StatusBoxBuild(items=items)

    def _action_read_portfolios(
        self,
        player: Player,
        *args,
        **kwargs,
    ) -> None:
        if not isinstance(player, MonopolyPlayer) or player.bankrupt:
            return
        ranked = self._all_portfolios_sorted_players()
        focus_id = f"all:summary:{ranked[0].id}" if ranked else ""
        self.live_status_box(
            player,
            "monopoly_all_portfolios",
            self._build_all_portfolios_status,
            focus_id=focus_id,
        )

    def _portfolio_player_options(self, player: Player) -> list[str]:
        del player
        return [p.id for p in self._all_portfolios_sorted_players()]

    def _portfolio_player_label(self, player: Player, value: str) -> str:
        owner = self.get_player_by_id(value)
        if not isinstance(owner, MonopolyPlayer):
            return value
        ranked = self._all_portfolios_sorted_players()
        rank = (ranked.index(owner) + 1) if owner in ranked else 1
        locale = self._locale(player)
        return Localization.get(
            locale,
            "mexicopoly-portfolio-ranked-summary",
            rank=rank,
            player=owner.name,
            cash=self._money(locale, owner.cash),
            net_worth=self._money(locale, self._net_worth(owner)),
        )
