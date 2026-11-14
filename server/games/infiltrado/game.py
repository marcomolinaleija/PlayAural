"""Infiltrado (Undercover) game implementation.

A social deduction word game where Civilians and Undercovers receive slightly different
secret words, and an optional Mr. White receives no word at all. Players take turns
giving clues, then debate and vote to eliminate suspects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import random
from typing import ClassVar

from mashumaro.mixins.json import DataClassJSONMixin

from ..base import Game, GameOptions, Player
from ..categories import CATEGORY_MISC
from ..registry import register_game
from ...game_utils.actions import Action, ActionSet, EditboxInput, MenuInput, Visibility
from ...game_utils.client_types import is_touch_client
from ...game_utils.game_result import GameResult, PlayerResult
from ...game_utils.options import MenuOption, option_field
from ...game_utils.poker_timer import PokerTurnTimer
from ...game_utils.turn_timer_mixin import TurnTimerMixin
from ...messages.localization import Localization
from ...ui.keybinds import KeybindState
from .words import InfiltradoWordManager, normalize_word

# --------------------------------------------------------------------- #
# Constants & Enums                                                     #
# --------------------------------------------------------------------- #

ROLE_CIVILIAN = "civilian"
ROLE_UNDERCOVER = "undercover"
ROLE_MR_WHITE = "mr_white"

PHASE_LOBBY = "lobby"
PHASE_CLUES = "clues"
PHASE_VOTING = "voting"
PHASE_MR_WHITE_GUESS = "mr_white_guess"
PHASE_GAME_OVER = "game_over"

CLUE_MODE_VOICE = "voice"
CLUE_MODE_TEXT_AND_VOICE = "text_and_voice"

CLUE_MODE_CHOICES = [CLUE_MODE_VOICE, CLUE_MODE_TEXT_AND_VOICE]
CLUE_MODE_LABELS = {
    CLUE_MODE_VOICE: "infiltrado-mode-voice",
    CLUE_MODE_TEXT_AND_VOICE: "infiltrado-mode-text-and-voice",
}

UNDERCOVER_CHOICES = ["1", "2"]
UNDERCOVER_LABELS = {
    "1": "infiltrado-undercover-1",
    "2": "infiltrado-undercover-2",
}

MR_WHITE_CHOICES = ["yes", "no"]
MR_WHITE_LABELS = {
    "yes": "infiltrado-mr-white-yes",
    "no": "infiltrado-mr-white-no",
}

TURN_TIMER_CHOICES = ["0", "30", "45", "60"]
TURN_TIMER_LABELS = {
    "0": "infiltrado-timer-0",
    "30": "infiltrado-timer-30",
    "45": "infiltrado-timer-45",
    "60": "infiltrado-timer-60",
}

VOTE_TIMER_CHOICES = ["30", "45", "60", "90"]
VOTE_TIMER_LABELS = {
    "30": "infiltrado-vote-timer-30",
    "45": "infiltrado-vote-timer-45",
    "60": "infiltrado-vote-timer-60",
    "90": "infiltrado-vote-timer-90",
}

CLUE_ROUNDS_CHOICES = ["1", "2", "3", "4", "5"]
CLUE_ROUNDS_LABELS = {
    "1": "infiltrado-clue-rounds-1",
    "2": "infiltrado-clue-rounds-2",
    "3": "infiltrado-clue-rounds-3",
    "4": "infiltrado-clue-rounds-4",
    "5": "infiltrado-clue-rounds-5",
}

WORD_CATEGORY_LABELS = {
    "all": "infiltrado-category-all",
}


def get_infiltrado_category_choices(game: "InfiltradoGame", player: Player) -> list[str]:
    cats = InfiltradoWordManager.get_categories()
    return ["all", *cats]


# --------------------------------------------------------------------- #
# Dataclasses                                                           #
# --------------------------------------------------------------------- #

@dataclass
class InfiltradoPlayer(Player):
    """Player state for Infiltrado."""

    role: str = ROLE_CIVILIAN
    secret_word: str = ""
    is_alive: bool = True
    clue_given: str = ""
    voted_for: str = ""


@dataclass
class ClueRecord(DataClassJSONMixin):
    """A record of a clue given by a player."""

    round_number: int
    player_id: str
    player_name: str
    clue: str
    is_voice: bool = False


@dataclass
class InfiltradoOptions(GameOptions):
    """Host-configurable settings for Infiltrado."""

    clue_mode: str = option_field(
        MenuOption(
            default=CLUE_MODE_VOICE,
            choices=CLUE_MODE_CHOICES,
            choice_labels=CLUE_MODE_LABELS,
            label="infiltrado-set-clue-mode",
            prompt="infiltrado-select-clue-mode",
            change_msg="infiltrado-option-changed-clue-mode",
            description="infiltrado-desc-clue-mode",
        )
    )
    undercover_count: str = option_field(
        MenuOption(
            default="1",
            choices=UNDERCOVER_CHOICES,
            choice_labels=UNDERCOVER_LABELS,
            value_key="count",
            label="infiltrado-set-undercover-count",
            prompt="infiltrado-select-undercover-count",
            change_msg="infiltrado-option-changed-undercover-count",
            description="infiltrado-desc-undercover-count",
        )
    )
    include_mr_white: str = option_field(
        MenuOption(
            default="no",
            choices=MR_WHITE_CHOICES,
            choice_labels=MR_WHITE_LABELS,
            value_key="enabled",
            label="infiltrado-set-mr-white",
            prompt="infiltrado-select-mr-white",
            change_msg="infiltrado-option-changed-mr-white",
            description="infiltrado-desc-mr-white",
        )
    )
    turn_timer: str = option_field(
        MenuOption(
            default="45",
            choices=TURN_TIMER_CHOICES,
            choice_labels=TURN_TIMER_LABELS,
            value_key="seconds",
            label="infiltrado-set-turn-timer",
            prompt="infiltrado-select-turn-timer",
            change_msg="infiltrado-option-changed-turn-timer",
            description="infiltrado-desc-turn-timer",
        )
    )
    vote_timer: str = option_field(
        MenuOption(
            default="60",
            choices=VOTE_TIMER_CHOICES,
            choice_labels=VOTE_TIMER_LABELS,
            value_key="seconds",
            label="infiltrado-set-vote-timer",
            prompt="infiltrado-select-vote-timer",
            change_msg="infiltrado-option-changed-vote-timer",
            description="infiltrado-desc-vote-timer",
        )
    )
    clue_rounds_before_vote: str = option_field(
        MenuOption(
            default="1",
            choices=CLUE_ROUNDS_CHOICES,
            choice_labels=CLUE_ROUNDS_LABELS,
            value_key="count",
            label="infiltrado-set-clue-rounds",
            prompt="infiltrado-select-clue-rounds",
            change_msg="infiltrado-option-changed-clue-rounds",
            description="infiltrado-desc-clue-rounds",
        )
    )
    word_category: str = option_field(
        MenuOption(
            default="all",
            choices=get_infiltrado_category_choices,
            choice_labels=WORD_CATEGORY_LABELS,
            value_key="category",
            label="infiltrado-set-word-category",
            prompt="infiltrado-select-word-category",
            change_msg="infiltrado-option-changed-word-category",
            description="infiltrado-desc-word-category",
        )
    )


# --------------------------------------------------------------------- #
# Game Class                                                            #
# --------------------------------------------------------------------- #

@register_game
@dataclass
class InfiltradoGame(TurnTimerMixin, Game):
    """Infiltrado social deduction game."""

    options: InfiltradoOptions = field(default_factory=InfiltradoOptions)
    timer: PokerTurnTimer = field(default_factory=PokerTurnTimer)

    phase: str = PHASE_LOBBY
    round_number: int = 0
    clue_cycle_round: int = 1
    civilian_word: str = ""
    undercover_word: str = ""
    civilian_clues: list[str] = field(default_factory=list)
    undercover_clues: list[str] = field(default_factory=list)
    clue_history: list[ClueRecord] = field(default_factory=list)
    mr_white_target_id: str = ""
    winning_role: str = ""
    winning_player_ids: list[str] = field(default_factory=list)
    vote_timer_ticks: int = 0
    bot_wait_ticks: int = field(default=0, init=False, repr=False)

    # ------------------------------------------------------------------ #
    # Metadata                                                           #
    # ------------------------------------------------------------------ #

    @classmethod
    def get_name(cls) -> str:
        return "El Infiltrado"

    @classmethod
    def get_type(cls) -> str:
        return "infiltrado"

    @classmethod
    def get_category(cls) -> str:
        return CATEGORY_MISC

    @classmethod
    def get_min_players(cls) -> int:
        return 3

    @classmethod
    def get_max_players(cls) -> int:
        return 12

    @classmethod
    def get_supported_leaderboards(cls) -> list[str]:
        return ["wins", "games_played"]

    def prestart_validate(self) -> list[str | tuple[str, dict]]:
        errors = list(super().prestart_validate())
        active_count = len(self.get_active_players())
        if self.options.undercover_count == "2" and active_count < 5:
            errors.append("infiltrado-error-need-5-for-two-undercovers")
        if self.options.include_mr_white == "yes" and active_count < 4:
            errors.append("infiltrado-error-need-4-for-mr-white")
        return errors

    def create_player(
        self, player_id: str, name: str, is_bot: bool = False
    ) -> InfiltradoPlayer:
        return InfiltradoPlayer(id=player_id, name=name, is_bot=is_bot)

    def _locale(self, player: Player) -> str:
        user = self.get_user(player)
        return user.locale if user else "es"

    # ------------------------------------------------------------------ #
    # Keybinds & Actions                                                 #
    # ------------------------------------------------------------------ #

    def setup_keybinds(self) -> None:
        super().setup_keybinds()
        self.define_keybind(
            "space",
            "Word said",
            ["word_said", "word_said_voice"],
            state=KeybindState.ACTIVE,
        )
        self.define_keybind(
            "alt+w",
            "Check secret word",
            ["check_secret_word"],
            state=KeybindState.ACTIVE,
        )
        self.define_keybind(
            "h",
            "Check clues history",
            ["check_clues_history"],
            state=KeybindState.ACTIVE,
            include_spectators=True,
        )
        self.define_keybind(
            "s",
            "Check alive players",
            ["check_alive_players"],
            state=KeybindState.ACTIVE,
            include_spectators=True,
        )

    def create_turn_action_set(self, player: Player) -> ActionSet:
        action_set = ActionSet(name="turn")
        locale = self._locale(player)
        p = self._as_infiltrado_player(player)

        if self.phase == PHASE_CLUES:
            is_voice_mode = self.options.clue_mode == CLUE_MODE_VOICE
            if is_voice_mode:
                action_set.add(
                    Action(
                        id="word_said",
                        label=Localization.get(locale, "infiltrado-action-word-said"),
                        handler="_action_word_said",
                        is_enabled="_is_clue_turn_enabled",
                        is_hidden="_is_clue_turn_hidden",
                        show_in_actions_menu=False,
                    )
                )
            else:
                action_set.add(
                    Action(
                        id="give_clue_text",
                        label=Localization.get(locale, "infiltrado-action-give-clue-text"),
                        handler="_action_give_clue_text",
                        is_enabled="_is_clue_turn_enabled",
                        is_hidden="_is_clue_turn_hidden",
                        input_request=EditboxInput(
                            prompt="infiltrado-prompt-enter-clue",
                            bot_input="_bot_input_clue",
                        ),
                        show_in_actions_menu=False,
                    )
                )
                action_set.add(
                    Action(
                        id="word_said_voice",
                        label=Localization.get(locale, "infiltrado-action-word-said-voice"),
                        handler="_action_word_said_voice",
                        is_enabled="_is_clue_turn_enabled",
                        is_hidden="_is_clue_turn_hidden",
                        show_in_actions_menu=False,
                    )
                )

        elif self.phase == PHASE_VOTING:
            action_set.add(
                Action(
                    id="vote_suspect",
                    label=Localization.get(locale, "infiltrado-action-vote-suspect"),
                    handler="_action_vote_suspect",
                    is_enabled="_is_voting_enabled",
                    is_hidden="_is_voting_hidden",
                    input_request=MenuInput(
                        prompt="infiltrado-prompt-vote-suspect",
                        options="_vote_options",
                        option_label="_vote_option_label",
                        bot_select="_bot_select_vote",
                    ),
                    show_in_actions_menu=False,
                )
            )

        elif self.phase == PHASE_MR_WHITE_GUESS and p and p.id == self.mr_white_target_id:
            action_set.add(
                Action(
                    id="mr_white_guess",
                    label=Localization.get(locale, "infiltrado-action-mr-white-guess"),
                    handler="_action_mr_white_guess",
                    is_enabled="_is_mr_white_guess_enabled",
                    is_hidden="_is_mr_white_guess_hidden",
                    input_request=EditboxInput(
                        prompt="infiltrado-prompt-mr-white-guess",
                        bot_input="_bot_mr_white_guess",
                    ),
                    show_in_actions_menu=False,
                )
            )

        return action_set

    def create_standard_action_set(self, player: Player) -> ActionSet:
        action_set = super().create_standard_action_set(player)
        locale = self._locale(player)

        action_set.add(
            Action(
                id="check_secret_word",
                label=Localization.get(locale, "infiltrado-action-check-secret-word"),
                handler="_action_check_secret_word",
                is_enabled="_is_always_enabled",
                is_hidden="_is_gameplay_visible",
                include_spectators=False,
            )
        )
        action_set.add(
            Action(
                id="check_clues_history",
                label=Localization.get(locale, "infiltrado-action-check-clues-history"),
                handler="_action_check_clues_history",
                is_enabled="_is_always_enabled",
                is_hidden="_is_gameplay_visible",
                include_spectators=True,
            )
        )
        action_set.add(
            Action(
                id="check_alive_players",
                label=Localization.get(locale, "infiltrado-action-check-alive-players"),
                handler="_action_check_alive_players",
                is_enabled="_is_always_enabled",
                is_hidden="_is_gameplay_visible",
                include_spectators=True,
            )
        )

        user = self.get_user(player)
        if user and is_touch_client(user):
            self._order_touch_standard_actions(action_set, self._STANDARD_TOUCH_ORDER)
        return action_set

    def before_menu_build(self, player: Player) -> None:
        turn_set = self.get_action_set(player, "turn")
        fresh_turn = self.create_turn_action_set(player)
        if turn_set is not None:
            turn_set._actions = fresh_turn._actions.copy()
            turn_set._order = list(fresh_turn._order)
        else:
            if player.id not in self.player_action_sets:
                self.player_action_sets[player.id] = []
            self.player_action_sets[player.id].insert(0, fresh_turn)

    _STANDARD_TOUCH_ORDER: ClassVar[list[str]] = [
        "check_secret_word",
        "check_clues_history",
        "check_alive_players",
        "whose_turn",
        "whos_at_table",
    ]

    # ------------------------------------------------------------------ #
    # Helper Queries                                                     #
    # ------------------------------------------------------------------ #

    def _is_always_enabled(self, player: Player) -> str | None:
        if self.status != "playing":
            return "action-not-playing"
        return None

    def _is_gameplay_visible(self, player: Player) -> Visibility:
        if self.status == "playing":
            return Visibility.VISIBLE
        return Visibility.HIDDEN

    def _as_infiltrado_player(self, player: Player | None) -> InfiltradoPlayer | None:
        if isinstance(player, InfiltradoPlayer):
            return player
        return None

    def _living_players(self) -> list[InfiltradoPlayer]:
        return [p for p in self.get_active_players() if isinstance(p, InfiltradoPlayer) and p.is_alive]

    def _is_clue_turn_enabled(self, player: Player) -> str | None:
        if self.phase != PHASE_CLUES:
            return "infiltrado-error-not-your-turn"
        current = self.current_player
        if not current or current.id != player.id:
            return "infiltrado-error-not-your-turn"
        p = self._as_infiltrado_player(player)
        if not p or not p.is_alive:
            return "infiltrado-error-not-your-turn"
        return None

    def _is_clue_turn_hidden(self, player: Player) -> Visibility:
        if self.phase != PHASE_CLUES:
            return Visibility.HIDDEN
        current = self.current_player
        if not current or current.id != player.id:
            return Visibility.HIDDEN
        return Visibility.VISIBLE

    def _is_voting_enabled(self, player: Player) -> str | None:
        if self.phase != PHASE_VOTING:
            return "infiltrado-error-not-in-voting"
        p = self._as_infiltrado_player(player)
        if not p or not p.is_alive:
            return "infiltrado-error-not-in-voting"
        return None

    def _is_voting_hidden(self, player: Player) -> Visibility:
        if self.phase != PHASE_VOTING:
            return Visibility.HIDDEN
        p = self._as_infiltrado_player(player)
        if not p or not p.is_alive:
            return Visibility.HIDDEN
        return Visibility.VISIBLE

    def _is_mr_white_guess_enabled(self, player: Player) -> str | None:
        if self.phase != PHASE_MR_WHITE_GUESS or player.id != self.mr_white_target_id:
            return "infiltrado-error-not-your-turn"
        return None

    def _is_mr_white_guess_hidden(self, player: Player) -> Visibility:
        if self.phase != PHASE_MR_WHITE_GUESS or player.id != self.mr_white_target_id:
            return Visibility.HIDDEN
        return Visibility.VISIBLE

    def _vote_options(self, player: Player) -> list[str]:
        """Return alive players other than the voting player."""
        return [p.id for p in self._living_players() if p.id != player.id]

    def _vote_option_label(self, player: Player, option_id: str) -> str:
        target = self.get_player_by_id(option_id)
        name = target.name if target else option_id
        return Localization.get(self._locale(player), "infiltrado-vote-target-label", player=name)

    # ------------------------------------------------------------------ #
    # Game Lifecycle & Turn Flow                                         #
    # ------------------------------------------------------------------ #

    def on_start(self) -> None:
        super().on_start()
        active = self.get_active_players()
        if len(active) < 3:
            return

        self.game_active = True
        self.status = "playing"
        self._sync_table_status()

        # Fetch word pair
        pair = InfiltradoWordManager.get_random_pair(category=self.options.word_category)
        if not pair:
            pair = InfiltradoWordManager.add_pair(
                "Café",
                "Té",
                ["Caliente", "Taza", "Desayuno", "Granos", "Despertar"],
                ["Infusión", "Hierbas", "Bolsita", "Taza", "Inglaterra"],
            )

        # Randomize which word is civilian vs undercover
        if random.random() < 0.5:
            self.civilian_word = pair.word1
            self.undercover_word = pair.word2
            self.civilian_clues = list(pair.clues_word1)
            self.undercover_clues = list(pair.clues_word2)
        else:
            self.civilian_word = pair.word2
            self.undercover_word = pair.word1
            self.civilian_clues = list(pair.clues_word2)
            self.undercover_clues = list(pair.clues_word1)

        # Determine roles
        shuffled = list(active)
        random.shuffle(shuffled)

        num_undercovers = 2 if self.options.undercover_count == "2" and len(active) >= 5 else 1
        has_mr_white = self.options.include_mr_white == "yes" and len(active) >= 4

        undercover_players = shuffled[:num_undercovers]
        idx = num_undercovers
        mr_white_player = shuffled[idx] if has_mr_white else None
        if mr_white_player:
            idx += 1
        civilian_players = shuffled[idx:]

        for p in active:
            if isinstance(p, InfiltradoPlayer):
                p.is_alive = True
                p.clue_given = ""
                p.voted_for = ""
                if p in undercover_players:
                    p.role = ROLE_UNDERCOVER
                    p.secret_word = self.undercover_word
                elif mr_white_player and p.id == mr_white_player.id:
                    p.role = ROLE_MR_WHITE
                    p.secret_word = ""
                else:
                    p.role = ROLE_CIVILIAN
                    p.secret_word = self.civilian_word

                # Notify privately
                user = self.get_user(p)
                if user:
                    if p.role == ROLE_CIVILIAN:
                        user.speak_l("infiltrado-private-civilian-word", buffer="game", word=p.secret_word)
                    elif p.role == ROLE_UNDERCOVER:
                        user.speak_l("infiltrado-private-undercover-word", buffer="game", word=p.secret_word)
                    elif p.role == ROLE_MR_WHITE:
                        user.speak_l("infiltrado-private-mr-white", buffer="game")

        self.play_sound("menuenter.ogg")
        self.broadcast_l("infiltrado-game-started", buffer="game")

        self.round_number = 1
        self.clue_cycle_round = 1
        self.clue_history = []
        self._start_clue_round()

    def _start_clue_round(self) -> None:
        """Start or restart the clue phase with living players."""
        living = self._living_players()
        if not living:
            return

        self.phase = PHASE_CLUES
        for p in living:
            p.clue_given = ""

        # Set turn order
        self.set_turn_players(living)
        self.start_turn_timer()
        self.refresh_menus()

        current = self.current_player
        if current:
            if current.is_bot:
                self.bot_wait_ticks = 25
            self.broadcast_l("game-turn-start", buffer="game", player=current.name)
            self.request_menu_focus(current, "word_said" if self.options.clue_mode == CLUE_MODE_VOICE else "give_clue_text")

    def _on_turn_timeout(self) -> None:
        """Handle turn timeout during clue giving."""
        current = self.current_player
        if not current:
            return
        self.broadcast_l("infiltrado-clue-timeout", buffer="game", player=current.name)
        self._record_clue(current, "(tiempo agotado)", is_voice=True)
        self._advance_clue_turn()

    def _record_clue(self, player: Player, clue_text: str, is_voice: bool) -> None:
        p = self._as_infiltrado_player(player)
        if p:
            p.clue_given = clue_text
        self.clue_history.append(
            ClueRecord(
                round_number=self.round_number,
                player_id=player.id,
                player_name=player.name,
                clue=clue_text,
                is_voice=is_voice,
            )
        )

    def _advance_clue_turn(self) -> None:
        """Advance to next player or end the clue phase if everyone gave a clue."""
        self.stop_turn_timer()
        living = self._living_players()

        # Check if all living players have given a clue
        all_given = all(p.clue_given for p in living)
        if all_given:
            self._handle_clue_round_completed()
            return

        # Advance to next turn
        next_player = self.advance_turn(announce=True)
        if not next_player or (self._as_infiltrado_player(next_player) and self._as_infiltrado_player(next_player).clue_given):
            # Check remaining
            remaining = [p for p in living if not p.clue_given]
            if not remaining:
                self._handle_clue_round_completed()
                return

        self.start_turn_timer()
        self.refresh_menus()
        cur = self.current_player
        if cur:
            if cur.is_bot:
                self.bot_wait_ticks = 25
            self.request_menu_focus(cur, "word_said" if self.options.clue_mode == CLUE_MODE_VOICE else "give_clue_text")

    def _handle_clue_round_completed(self) -> None:
        """Handle end of a clue round: either advance clue round or start voting."""
        try:
            target_rounds = max(1, int(self.options.clue_rounds_before_vote))
        except (ValueError, TypeError):
            target_rounds = 1

        if self.clue_cycle_round < target_rounds:
            self.round_number += 1
            self.clue_cycle_round += 1
            self.broadcast_l(
                "infiltrado-next-clue-round",
                buffer="game",
                round=self.round_number,
                cycle_round=self.clue_cycle_round,
                total_cycle=target_rounds,
            )
            self._start_clue_round()
        else:
            self._start_voting_phase()

    # ------------------------------------------------------------------ #
    # Clue Actions                                                       #
    # ------------------------------------------------------------------ #

    def _action_word_said(self, player: Player, action_id: str) -> None:
        if self._is_clue_turn_enabled(player) is not None:
            return
        self.play_sound("click.ogg")
        self._record_clue(player, "(dicha por voz)", is_voice=True)
        self.broadcast_l("infiltrado-clue-given-voice", buffer="game", player=player.name)
        self._advance_clue_turn()

    def _action_word_said_voice(self, player: Player, action_id: str) -> None:
        self._action_word_said(player, action_id)

    def _action_give_clue_text(self, player: Player, clue_text: str, action_id: str) -> None:
        if self._is_clue_turn_enabled(player) is not None:
            return
        clean_clue = clue_text.strip()
        if not clean_clue:
            clean_clue = "(pista vacía)"
        self.play_sound("click.ogg")
        self._record_clue(player, clean_clue, is_voice=False)
        self.broadcast_l("infiltrado-clue-given-text", buffer="game", player=player.name, clue=clean_clue)
        self._advance_clue_turn()

    # ------------------------------------------------------------------ #
    # Voting Phase                                                       #
    # ------------------------------------------------------------------ #

    def _start_voting_phase(self) -> None:
        """Transition table to voting phase."""
        self.stop_turn_timer()
        self.phase = PHASE_VOTING
        self.bot_wait_ticks = 30
        living = self._living_players()
        for p in living:
            p.voted_for = ""

        try:
            vote_seconds = max(0, int(self.options.vote_timer))
        except (ValueError, TypeError):
            vote_seconds = 60

        self.vote_timer_ticks = vote_seconds * 20  # 20 ticks per second
        self.play_sound("game_coup/challenge.ogg")

        if vote_seconds > 0:
            self.broadcast_l(
                "infiltrado-voting-phase-started",
                buffer="game",
                round=self.round_number,
                seconds=vote_seconds,
            )
        else:
            self.broadcast_l(
                "infiltrado-voting-phase-started-no-timer",
                buffer="game",
                round=self.round_number,
            )

        self.refresh_menus()
        for p in living:
            self.request_menu_focus(p, "vote_suspect")

    def _action_vote_suspect(self, player: Player, target_id: str, action_id: str) -> None:
        if self._is_voting_enabled(player) is not None:
            return
        p = self._as_infiltrado_player(player)
        target = self.get_player_by_id(target_id)
        if not p or not target or not self._as_infiltrado_player(target) or not self._as_infiltrado_player(target).is_alive:
            return

        p.voted_for = target_id
        user = self.get_user(player)
        if user:
            user.speak_l("infiltrado-player-voted-feedback", buffer="game", target=target.name)
        self.play_sound("click.ogg")

        # Check if all living players have voted
        living = self._living_players()
        if all(lp.voted_for for lp in living):
            self._resolve_voting()

    def _resolve_voting(self) -> None:
        """Count votes, resolve ties or eliminate suspect."""
        living = self._living_players()
        if not living:
            return

        # Tally votes
        vote_counts: dict[str, int] = {}
        for p in living:
            if p.voted_for:
                vote_counts[p.voted_for] = vote_counts.get(p.voted_for, 0) + 1

        if not vote_counts:
            # Nobody voted (e.g. timeout with zero votes)
            self._on_vote_tie([])
            return

        max_votes = max(vote_counts.values())
        top_candidates = [pid for pid, cnt in vote_counts.items() if cnt == max_votes]

        if len(top_candidates) > 1:
            # Tie
            tied_names = [self.get_player_by_id(pid).name for pid in top_candidates if self.get_player_by_id(pid)]
            self._on_vote_tie(tied_names, max_votes)
            return

        eliminated_id = top_candidates[0]
        eliminated_player = self._as_infiltrado_player(self.get_player_by_id(eliminated_id))
        if not eliminated_player:
            return

        self.play_sound("game_coup/chardestroy1.ogg")
        self.broadcast_l(
            "infiltrado-player-eliminated",
            buffer="game",
            player=eliminated_player.name,
            votes=max_votes,
        )

        if eliminated_player.role == ROLE_CIVILIAN:
            eliminated_player.is_alive = False
            self.broadcast_l("infiltrado-revealed-civilian", buffer="game", player=eliminated_player.name)
            self._check_game_over_or_next_round()

        elif eliminated_player.role == ROLE_UNDERCOVER:
            eliminated_player.is_alive = False
            self.broadcast_l("infiltrado-revealed-undercover", buffer="game", player=eliminated_player.name)
            self._check_game_over_or_next_round()

        elif eliminated_player.role == ROLE_MR_WHITE:
            self.broadcast_l("infiltrado-revealed-mr-white", buffer="game", player=eliminated_player.name)
            self.phase = PHASE_MR_WHITE_GUESS
            self.mr_white_target_id = eliminated_player.id
            self.refresh_menus()
            self.request_menu_focus(eliminated_player, "mr_white_guess")

    def _on_vote_tie(self, tied_names: list[str], votes: int = 0) -> None:
        names_str = ", ".join(tied_names) if tied_names else "Varios jugadores"
        self.broadcast_l("infiltrado-voting-tie", buffer="game", players=names_str, votes=votes)
        self._next_round()

    def _action_mr_white_guess(self, player: Player, guess_text: str, action_id: str) -> None:
        if self._is_mr_white_guess_enabled(player) is not None:
            return

        clean_guess = guess_text.strip()
        norm_guess = normalize_word(clean_guess)
        norm_target = normalize_word(self.civilian_word)

        if norm_guess == norm_target:
            # Mr. White guessed correctly and steals the win!
            self.play_sound("gamewin.ogg")
            self.broadcast_l(
                "infiltrado-mr-white-guessed-correct",
                buffer="game",
                player=player.name,
                word=self.civilian_word,
            )
            self.winning_role = ROLE_MR_WHITE
            self.winning_player_ids = [player.id]
            self.finish_game()
        else:
            # Failed
            self.play_sound("lsmack.ogg")
            self.broadcast_l(
                "infiltrado-mr-white-guessed-wrong",
                buffer="game",
                player=player.name,
                guess=clean_guess,
                word=self.civilian_word,
            )
            p = self._as_infiltrado_player(player)
            if p:
                p.is_alive = False
            self._check_game_over_or_next_round()

    def _check_game_over_or_next_round(self) -> None:
        """Check victory conditions for Civilians and Undercovers."""
        living = self._living_players()
        living_civilians = [p for p in living if p.role == ROLE_CIVILIAN]
        living_undercovers = [p for p in living if p.role == ROLE_UNDERCOVER]
        living_mr_white = [p for p in living if p.role == ROLE_MR_WHITE]

        # Condition 1: All undercovers and Mr. White eliminated -> Civilians win
        if len(living_undercovers) == 0 and len(living_mr_white) == 0:
            self.play_sound("gamewin.ogg")
            self.broadcast_l(
                "infiltrado-win-civilians",
                buffer="game",
                civilian_word=self.civilian_word,
                undercover_word=self.undercover_word,
            )
            self.winning_role = ROLE_CIVILIAN
            self.winning_player_ids = [
                p.id for p in self.get_active_players() if self._as_infiltrado_player(p) and self._as_infiltrado_player(p).role == ROLE_CIVILIAN
            ]
            self.finish_game()
            return

        # Condition 2: Undercovers outnumber or equal civilians -> Undercovers win
        if len(living_undercovers) >= len(living_civilians):
            self.play_sound("gamewin.ogg")
            self.broadcast_l(
                "infiltrado-win-undercovers",
                buffer="game",
                civilian_word=self.civilian_word,
                undercover_word=self.undercover_word,
            )
            self.winning_role = ROLE_UNDERCOVER
            self.winning_player_ids = [
                p.id for p in self.get_active_players() if self._as_infiltrado_player(p) and self._as_infiltrado_player(p).role == ROLE_UNDERCOVER
            ]
            self.finish_game()
            return

        # Otherwise continue to next round
        self._next_round()

    def _next_round(self) -> None:
        self.round_number += 1
        self.clue_cycle_round = 1
        living = self._living_players()
        self.broadcast_l(
            "infiltrado-next-round",
            buffer="game",
            round=self.round_number,
            count=len(living),
        )
        self._start_clue_round()

    # ------------------------------------------------------------------ #
    # Bot AI Logic                                                       #
    # ------------------------------------------------------------------ #

    def _bot_input_clue(self, player: Player, action_id: str) -> str:
        p = self._as_infiltrado_player(player)
        if not p:
            return "Algo"
        if p.role == ROLE_CIVILIAN:
            return random.choice(self.civilian_clues) if self.civilian_clues else "Algo"
        if p.role == ROLE_UNDERCOVER:
            return random.choice(self.undercover_clues) if self.undercover_clues else "Cosa"
        # Mr. White: repeat or neutral clue
        if self.clue_history:
            return random.choice(self.clue_history).clue
        return "Objeto"

    def _bot_select_vote(self, player: Player, action_id: str) -> str | None:
        options = self._vote_options(player)
        return random.choice(options) if options else None

    def _bot_mr_white_guess(self, player: Player, action_id: str) -> str:
        # Bot Mr. White guesses a random civilian clue or random word
        return random.choice(self.civilian_clues) if self.civilian_clues else "Café"

    def on_tick(self) -> None:
        super().on_tick()
        self.process_scheduled_sounds()
        self.process_sequences()

        if self.status != "playing":
            return

        # Turn timer for clue giving
        if self.phase == PHASE_CLUES:
            self.on_tick_turn_timer()
            current = self.current_player
            if current and current.is_bot:
                if self.bot_wait_ticks > 0:
                    self.bot_wait_ticks -= 1
                else:
                    clue = self._bot_input_clue(current, "")
                    if self.options.clue_mode == CLUE_MODE_VOICE:
                        self._action_word_said(current, "word_said")
                    else:
                        self._action_give_clue_text(current, clue, "give_clue_text")

        # Vote timer for voting phase
        elif self.phase == PHASE_VOTING:
            if self.vote_timer_ticks > 0:
                self.vote_timer_ticks -= 1
                if self.vote_timer_ticks <= 0:
                    self._resolve_voting()
                    return

            if self.bot_wait_ticks > 0:
                self.bot_wait_ticks -= 1
            else:
                # Let bots vote
                living_bots = [p for p in self._living_players() if p.is_bot and not p.voted_for]
                for bot in living_bots:
                    choice = self._bot_select_vote(bot, "vote_suspect")
                    if choice:
                        self._action_vote_suspect(bot, choice, "vote_suspect")

        # Bot Mr. White guess
        elif self.phase == PHASE_MR_WHITE_GUESS:
            mr_white = self.get_player_by_id(self.mr_white_target_id)
            if mr_white and mr_white.is_bot:
                if self.bot_wait_ticks > 0:
                    self.bot_wait_ticks -= 1
                else:
                    guess = self._bot_mr_white_guess(mr_white, "mr_white_guess")
                    self._action_mr_white_guess(mr_white, guess, "mr_white_guess")

    # ------------------------------------------------------------------ #
    # Info & Status Actions                                              #
    # ------------------------------------------------------------------ #

    def _action_whose_turn(self, player: Player, action_id: str) -> None:
        user = self.get_user(player)
        if not user:
            return

        if self.status != "playing":
            user.speak_l("game-no-turn", buffer="game")
            return

        if self.phase == PHASE_CLUES:
            current = self.current_player
            if not current:
                user.speak_l("game-no-turn", buffer="game")
                return

            try:
                timer_setting = int(self.options.turn_timer)
            except (ValueError, TypeError):
                timer_setting = 0

            seconds = self.timer.seconds_remaining()
            is_you = (player.id == current.id)
            has_timer = (timer_setting > 0 and seconds > 0)

            if is_you:
                if has_timer:
                    user.speak_l("infiltrado-turn-info-you", buffer="game", seconds=seconds)
                else:
                    user.speak_l("infiltrado-turn-info-you-no-timer", buffer="game")
            else:
                if has_timer:
                    user.speak_l("infiltrado-turn-info-other", buffer="game", player=current.name, seconds=seconds)
                else:
                    user.speak_l("infiltrado-turn-info-other-no-timer", buffer="game", player=current.name)

        elif self.phase == PHASE_VOTING:
            try:
                vote_setting = int(self.options.vote_timer)
            except (ValueError, TypeError):
                vote_setting = 0

            seconds = (self.vote_timer_ticks + 19) // 20 if self.vote_timer_ticks > 0 else 0
            if vote_setting > 0 and seconds > 0:
                user.speak_l("infiltrado-turn-info-voting", buffer="game", seconds=seconds)
            else:
                user.speak_l("infiltrado-turn-info-voting-no-timer", buffer="game")

        elif self.phase == PHASE_MR_WHITE_GUESS:
            target = self.get_player_by_id(self.mr_white_target_id)
            name = target.name if target else "Mr. White"
            user.speak_l("infiltrado-turn-info-mr-white", buffer="game", player=name)

        else:
            user.speak_l("game-no-turn", buffer="game")

    def _action_check_secret_word(self, player: Player, action_id: str) -> None:
        user = self.get_user(player)
        p = self._as_infiltrado_player(player)
        if not user or not p:
            return

        if p.role == ROLE_CIVILIAN:
            user.speak_l("infiltrado-secret-word-reminder-civilian", buffer="game", word=p.secret_word)
        elif p.role == ROLE_UNDERCOVER:
            user.speak_l("infiltrado-secret-word-reminder-undercover", buffer="game", word=p.secret_word)
        elif p.role == ROLE_MR_WHITE:
            user.speak_l("infiltrado-secret-word-reminder-mr-white", buffer="game")

    def _action_check_clues_history(self, player: Player, action_id: str) -> None:
        user = self.get_user(player)
        if not user:
            return

        locale = self._locale(player)
        if not self.clue_history:
            lines = [Localization.get(locale, "infiltrado-history-empty")]
        else:
            lines = [Localization.get(locale, "infiltrado-history-title")]
            rounds = sorted(set(c.round_number for c in self.clue_history))
            for r in rounds:
                lines.append("")
                lines.append(Localization.get(locale, "infiltrado-history-round-header", round=r))
                for c in self.clue_history:
                    if c.round_number == r:
                        lines.append(f"  {c.player_name}: {c.clue}")

        self.status_box(player, lines)

    def _action_check_alive_players(self, player: Player, action_id: str) -> None:
        user = self.get_user(player)
        if not user:
            return

        locale = self._locale(player)
        lines = [Localization.get(locale, "infiltrado-alive-players-title")]
        for p in self.get_active_players():
            ip = self._as_infiltrado_player(p)
            if not ip:
                continue
            if ip.is_alive:
                lines.append(Localization.get(locale, "infiltrado-alive-player-entry", player=ip.name))
            else:
                role_key = f"infiltrado-role-label-{ip.role}"
                role_label = Localization.get(locale, role_key)
                lines.append(Localization.get(locale, "infiltrado-eliminated-player-entry", player=ip.name, role=role_label))

        self.status_box(player, lines)

    # ------------------------------------------------------------------ #
    # Game Results                                                       #
    # ------------------------------------------------------------------ #

    def build_game_result(self) -> GameResult:
        active = self.get_active_players()
        return GameResult(
            game_type=self.get_type(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            duration_ticks=self.sound_scheduler_tick,
            player_results=[
                PlayerResult.from_player(player) for player in active
            ],
            custom_data={
                "winner_ids": list(self.winning_player_ids),
                "winning_role": self.winning_role,
                "rounds": self.round_number,
                "civilian_word": self.civilian_word,
                "undercover_word": self.undercover_word,
            },
        )
