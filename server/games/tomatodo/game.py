"""Toma Todo (Pirinola Mexicana) game implementation."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import random
from typing import ClassVar

from mashumaro.mixins.json import DataClassJSONMixin

from ..base import Game, GameOptions, Player
from ..categories import CATEGORY_DICE
from ..registry import register_game
from ...game_utils.actions import Action, ActionSet, Visibility
from ...game_utils.game_result import GameResult, PlayerResult
from ...game_utils.options import MenuOption, option_field
from ...game_utils.sequence_runner_mixin import (
    SequenceBeat,
    SequenceOperation,
)
from ...messages.localization import Localization
from ...ui.keybinds import KeybindState
from . import audio as tomatodo_audio

# --------------------------------------------------------------------- #
# Constants                                                             #
# --------------------------------------------------------------------- #

FACE_PON_1 = "pon_1"
FACE_PON_2 = "pon_2"
FACE_TOMA_1 = "toma_1"
FACE_TOMA_2 = "toma_2"
FACE_TODOS_PONEN = "todos_ponen"
FACE_TOMA_TODO = "toma_todo"

PIRINOLA_FACES = (
    FACE_PON_1,
    FACE_PON_2,
    FACE_TOMA_1,
    FACE_TOMA_2,
    FACE_TODOS_PONEN,
    FACE_TOMA_TODO,
)

COIN_UNIT_CHOICES = ["1", "5", "10", "25", "50"]
COIN_UNIT_LABELS = {
    "1": "tomatodo-unit-1",
    "5": "tomatodo-unit-5",
    "10": "tomatodo-unit-10",
    "25": "tomatodo-unit-25",
    "50": "tomatodo-unit-50",
}

ANTE_CHOICES = ["1", "2"]
ANTE_LABELS = {
    "1": "tomatodo-ante-1",
    "2": "tomatodo-ante-2",
}

ROUNDS_CHOICES = ["0", "10", "15", "20"]
ROUNDS_LABELS = {
    "0": "tomatodo-rounds-continuous",
    "10": "tomatodo-rounds-10",
    "15": "tomatodo-rounds-15",
    "20": "tomatodo-rounds-20",
}

SPIN_SPEED_CHOICES = ["fast", "full"]
SPIN_SPEED_LABELS = {
    "fast": "tomatodo-speed-fast",
    "full": "tomatodo-speed-full",
}

SPIN_SEQUENCE_TAG = "tomatodo_spin"
BOT_STARTING_BALANCE = 250


# --------------------------------------------------------------------- #
# Dataclasses                                                           #
# --------------------------------------------------------------------- #


@dataclass
class TomaTodoPlayer(Player):
    """Player state for Toma Todo."""

    coins: int = 0
    bankrupt: bool = False
    total_won: int = 0
    total_lost: int = 0


@dataclass
class TomaTodoOptions(GameOptions):
    """Host options for Toma Todo."""

    coin_unit: str = option_field(
        MenuOption(
            choices=COIN_UNIT_CHOICES,
            default="5",
            value_key="unit",
            label="tomatodo-set-coin-unit",
            prompt="tomatodo-select-coin-unit",
            change_msg="tomatodo-option-changed-coin-unit",
            description="tomatodo-desc-coin-unit",
            choice_labels=COIN_UNIT_LABELS,
        )
    )
    ante: str = option_field(
        MenuOption(
            choices=ANTE_CHOICES,
            default="1",
            value_key="ante",
            label="tomatodo-set-ante",
            prompt="tomatodo-select-ante",
            change_msg="tomatodo-option-changed-ante",
            description="tomatodo-desc-ante",
            choice_labels=ANTE_LABELS,
        )
    )
    max_rounds: str = option_field(
        MenuOption(
            choices=ROUNDS_CHOICES,
            default="0",
            value_key="rounds",
            label="tomatodo-set-rounds",
            prompt="tomatodo-select-rounds",
            change_msg="tomatodo-option-changed-rounds",
            description="tomatodo-desc-rounds",
            choice_labels=ROUNDS_LABELS,
        )
    )
    spin_speed: str = option_field(
        MenuOption(
            choices=SPIN_SPEED_CHOICES,
            default="fast",
            value_key="speed",
            label="tomatodo-set-speed",
            prompt="tomatodo-select-speed",
            change_msg="tomatodo-option-changed-speed",
            description="tomatodo-desc-speed",
            choice_labels=SPIN_SPEED_LABELS,
        )
    )


# --------------------------------------------------------------------- #
# Game                                                                   #
# --------------------------------------------------------------------- #


@register_game
@dataclass
class TomaTodoGame(Game):
    """Toma Todo - Traditional Mexican spinning top game using platform coins."""

    supports_bots: ClassVar[bool] = False

    players: list[TomaTodoPlayer] = field(default_factory=list)
    options: TomaTodoOptions = field(default_factory=TomaTodoOptions)

    pot: int = 0
    round_number: int = 1
    last_face: str = ""
    last_player_id: str = ""
    last_pot_taken: int = 0
    winner_ids: list[str] = field(default_factory=list)

    def __post_init__(self):
        super().__post_init__()

    # ------------------------------------------------------------------ #
    # Metadata                                                            #
    # ------------------------------------------------------------------ #

    @classmethod
    def get_name(cls) -> str:
        return "Toma Todo"

    @classmethod
    def get_name_key(cls) -> str:
        return "game-name-tomatodo"

    @classmethod
    def get_type(cls) -> str:
        return "tomatodo"

    @classmethod
    def get_category(cls) -> str:
        return CATEGORY_DICE

    @classmethod
    def get_min_players(cls) -> int:
        return 2

    @classmethod
    def get_max_players(cls) -> int:
        return 8

    def create_player(
        self, player_id: str, name: str, is_bot: bool = False
    ) -> TomaTodoPlayer:
        return TomaTodoPlayer(id=player_id, name=name, is_bot=is_bot)

    def _get_database(self):
        table = getattr(self, "_table", None)
        if table:
            return getattr(table, "_db", None) or getattr(getattr(table, "_server", None), "_db", None)
        return getattr(self, "_db", None)

    def _get_coin_unit(self) -> int:
        try:
            return max(1, int(self.options.coin_unit))
        except (ValueError, TypeError):
            return 5

    def _get_ante_multiplier(self) -> int:
        try:
            return max(1, int(self.options.ante))
        except (ValueError, TypeError):
            return 1

    def _get_ante_amount(self) -> int:
        return self._get_coin_unit() * self._get_ante_multiplier()

    # ------------------------------------------------------------------ #
    # Keybinds & Actions                                                  #
    # ------------------------------------------------------------------ #

    def setup_keybinds(self) -> None:
        super().setup_keybinds()
        self._keybinds.pop("shift+b", None)
        if "b" in self._keybinds:
            self._keybinds["b"] = [
                k for k in self._keybinds["b"] if "add_bot" not in k.actions
            ]
        self.define_keybind(
            "space",
            "Spin top",
            ["spin_top"],
            state=KeybindState.ACTIVE,
        )
        self.define_keybind(
            "g",
            "Spin top",
            ["spin_top"],
            state=KeybindState.ACTIVE,
        )
        self.define_keybind(
            "c",
            "Check pot",
            ["check_pot"],
            state=KeybindState.ACTIVE,
            include_spectators=True,
        )
        self.define_keybind(
            "b",
            "Check balances",
            ["check_balances"],
            state=KeybindState.ACTIVE,
            include_spectators=True,
        )
        self.define_keybind(
            "l",
            "Check last spin",
            ["check_last_spin"],
            state=KeybindState.ACTIVE,
            include_spectators=True,
        )

    def create_lobby_action_set(self, player: Player) -> ActionSet:
        actions = super().create_lobby_action_set(player)
        for action_id in ("add_bot", "remove_bot"):
            if action_id in actions._actions:
                actions.remove(action_id)
        return actions

    def _is_add_bot_enabled(self, player: Player) -> str | None:
        return "tomatodo-error-bots-not-supported"

    def _is_add_bot_hidden(self, player: Player) -> Visibility:
        return Visibility.HIDDEN

    def _is_remove_bot_enabled(self, player: Player) -> str | None:
        return "tomatodo-error-bots-not-supported"

    def _is_remove_bot_hidden(self, player: Player) -> Visibility:
        return Visibility.HIDDEN

    def _player_locale(self, player: Player) -> str:
        user = self.get_user(player)
        return user.locale if user else "es"

    def create_turn_action_set(self, player: Player) -> ActionSet:
        action_set = ActionSet(name="turn")
        locale = self._player_locale(player)
        action_set.add(
            Action(
                id="spin_top",
                label=Localization.get(locale, "tomatodo-action-spin"),
                handler="_action_spin_top",
                is_enabled="_is_spin_top_enabled",
                is_hidden="_is_spin_top_hidden",
                show_in_actions_menu=False,
            )
        )
        return action_set

    def create_standard_action_set(self, player: Player) -> ActionSet:
        action_set = super().create_standard_action_set(player)
        locale = self._player_locale(player)
        action_set.add(
            Action(
                id="check_pot",
                label=Localization.get(locale, "tomatodo-action-check-pot"),
                handler="_action_check_pot",
                is_enabled="_is_always_enabled",
                is_hidden="_is_gameplay_visible",
                include_spectators=True,
            )
        )
        action_set.add(
            Action(
                id="check_balances",
                label=Localization.get(locale, "tomatodo-action-check-balances"),
                handler="_action_check_balances",
                is_enabled="_is_always_enabled",
                is_hidden="_is_gameplay_visible",
                include_spectators=True,
            )
        )
        action_set.add(
            Action(
                id="check_last_spin",
                label=Localization.get(locale, "tomatodo-action-check-last-spin"),
                handler="_action_check_last_spin",
                is_enabled="_is_always_enabled",
                is_hidden="_is_gameplay_visible",
                include_spectators=True,
            )
        )
        self._apply_standard_touch_order(action_set, self.get_user(player))
        return action_set

    _STANDARD_TOUCH_ORDER: ClassVar[list[str]] = [
        "check_pot",
        "check_balances",
        "check_last_spin",
        "whose_turn",
        "whos_at_table",
    ]

    def _apply_standard_touch_order(self, action_set: ActionSet, user) -> None:
        if self.is_touch_client(user):
            self._order_touch_standard_actions(action_set, self._STANDARD_TOUCH_ORDER)

    def _is_spin_top_enabled(self, player: Player) -> str | None:
        if self.status != "playing":
            return "action-not-playing"
        if self.current_player != player:
            return "action-not-your-turn"
        if self.has_active_sequence():
            return "action-sequence-running"
        if getattr(player, "bankrupt", False):
            return "tomatodo-error-player-bankrupt"
        return None

    def _is_spin_top_hidden(self, player: Player) -> Visibility:
        if self.status == "playing" and self.current_player == player and not getattr(player, "bankrupt", False):
            return Visibility.VISIBLE
        return Visibility.HIDDEN

    def _is_always_enabled(self, player: Player) -> str | None:
        return None if self.status == "playing" else "action-not-playing"

    def _is_gameplay_visible(self, player: Player) -> Visibility:
        if self.status == "playing":
            return Visibility.VISIBLE
        return Visibility.HIDDEN

    # ------------------------------------------------------------------ #
    # Action handlers                                                     #
    # ------------------------------------------------------------------ #

    def _action_spin_top(self, player: Player, action_id: str) -> None:
        if self._is_spin_top_enabled(player) is not None:
            return
        self._execute_spin(player)

    def _action_check_pot(self, player: Player, action_id: str) -> None:
        user = self.get_user(player)
        if user:
            user.speak_l(
                "tomatodo-check-pot-info",
                buffer="game",
                pot=self.pot,
                unit=self._get_coin_unit(),
            )

    def _action_check_balances(self, player: Player, action_id: str) -> None:
        user = self.get_user(player)
        if not user:
            return
        lines = []
        for p in self.get_active_players():
            if isinstance(p, TomaTodoPlayer):
                status_key = "tomatodo-player-balance-bankrupt" if p.bankrupt else "tomatodo-player-balance"
                lines.append(
                    Localization.get(
                        user.locale,
                        status_key,
                        player=p.name,
                        coins=p.coins,
                    )
                )
        user.speak(", ".join(lines), buffer="game")

    def _action_check_last_spin(self, player: Player, action_id: str) -> None:
        user = self.get_user(player)
        if not user:
            return
        if not self.last_face:
            user.speak_l("tomatodo-no-last-spin", buffer="game")
            return
        last_player = next((p.name for p in self.players if p.id == self.last_player_id), "Jugador")
        face_label = Localization.get(user.locale, f"tomatodo-face-{self.last_face}")
        user.speak_l(
            "tomatodo-last-spin-info",
            buffer="game",
            player=last_player,
            face=face_label,
        )

    # ------------------------------------------------------------------ #
    # Validation                                                          #
    # ------------------------------------------------------------------ #

    def prestart_validate(self) -> list[str | tuple[str, dict]]:
        errors = super().prestart_validate()
        if any(p.is_bot for p in self.get_active_players()):
            errors.append("tomatodo-error-bots-not-supported")
        ante_amount = self._get_ante_amount()
        db = self._get_database()

        if db is not None:
            for p in self.get_active_players():
                if not p.is_bot:
                    wallet = db.get_wallet(p.id)
                    # Must have at least enough for initial ante + 2 units of safety
                    min_needed = ante_amount + (self._get_coin_unit() * 2)
                    if wallet.balance < min_needed:
                        errors.append(
                            (
                                "tomatodo-error-insufficient-coins",
                                {
                                    "player": p.name,
                                    "coins": wallet.balance,
                                    "required": min_needed,
                                },
                            )
                        )
        return errors

    # ------------------------------------------------------------------ #
    # Lifecycle & Flow                                                    #
    # ------------------------------------------------------------------ #

    def on_start(self) -> None:
        self.cancel_sequences_by_tag(SPIN_SEQUENCE_TAG)
        self.status = "playing"
        self._sync_table_status()
        self.game_active = True
        self.round_number = 1
        self.pot = 0
        self.last_face = ""
        self.last_player_id = ""
        self.last_pot_taken = 0
        self.winner_ids = []

        active_players = [
            p for p in self.get_active_players() if isinstance(p, TomaTodoPlayer)
        ]
        self.set_turn_players(active_players)

        db = self._get_database()
        ante = self._get_ante_amount()

        # Initialize player coin balances from wallet
        for player in active_players:
            player.bankrupt = False
            player.total_won = 0
            player.total_lost = 0
            if db is not None:
                wallet = db.get_wallet(player.id)
                player.coins = wallet.balance
            else:
                player.coins = 100

        # Ante collection
        pot_accumulated = 0
        for player in active_players:
            collected = self._deduct_coins(player, ante)
            pot_accumulated += collected

        self.pot = pot_accumulated
        self.play_sound(tomatodo_audio.SOUND_COINS)
        self.broadcast_l(
            "tomatodo-pot-started",
            buffer="game",
            ante=ante,
            pot=self.pot,
        )
        self.refresh_menus()

    def _deduct_coins(self, player: TomaTodoPlayer, amount: int) -> int:
        """Deduct coins from a player's wallet and active match balance.

        Returns actual amount deducted.
        """
        if amount <= 0:
            return 0
        actual = min(amount, player.coins)
        if actual <= 0:
            return 0

        player.coins -= actual
        player.total_lost += actual

        db = self._get_database()
        if db is not None:
            try:
                db.adjust_wallet_balance(player.id, -actual, is_bet=True)
            except Exception:
                pass

        if player.coins <= 0:
            player.bankrupt = True
        return actual

    def _credit_coins(self, player: TomaTodoPlayer, amount: int) -> None:
        """Credit coins to a player's wallet and active match balance."""
        if amount <= 0:
            return
        player.coins += amount
        player.total_won += amount

        db = self._get_database()
        if db is not None:
            try:
                db.adjust_wallet_balance(player.id, amount, is_win=True)
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # Spin Execution via Sequence                                         #
    # ------------------------------------------------------------------ #

    def _execute_spin(self, player: Player) -> None:
        if getattr(self.options, "spin_speed", "fast") == "full":
            sound = tomatodo_audio.SOUND_SPIN
        else:
            sound = tomatodo_audio.SOUND_SPIN_FAST
        duration = tomatodo_audio.sound_ticks(sound)
        beats = [
            SequenceBeat.after_audio(
                duration,
                ops=[SequenceOperation.sound_op(sound)],
            ),
            SequenceBeat(
                ops=[
                    SequenceOperation.callback_op(
                        "resolve_spin",
                        payload={"player_id": player.id},
                    )
                ]
            ),
        ]
        self.start_sequence(
            SPIN_SEQUENCE_TAG,
            beats,
            tag=SPIN_SEQUENCE_TAG,
            lock_scope=self.SEQUENCE_LOCK_GAMEPLAY,
            pause_bots=True,
        )

    def on_sequence_callback(
        self, sequence_id: str, callback_id: str, payload: dict
    ) -> None:
        super().on_sequence_callback(sequence_id, callback_id, payload)
        if callback_id == "resolve_spin":
            player_id = payload.get("player_id", "")
            player = next((p for p in self.players if p.id == player_id), None)
            if player and isinstance(player, TomaTodoPlayer):
                self._resolve_spin_face(player)

    def _resolve_spin_face(self, player: TomaTodoPlayer, face: str | None = None) -> None:
        if face is None:
            face = random.choice(PIRINOLA_FACES)
        self.last_face = face
        self.last_player_id = player.id
        unit = self._get_coin_unit()

        if face == FACE_PON_1:
            put = self._deduct_coins(player, unit)
            self.pot += put
            self.play_sound(tomatodo_audio.SOUND_COINS)
            self.broadcast_l(
                "tomatodo-result-pon-1",
                buffer="game",
                player=player.name,
                coins=put,
                pot=self.pot,
            )
            if player.bankrupt:
                self.broadcast_l("tomatodo-player-bankrupt", buffer="game", player=player.name)

        elif face == FACE_PON_2:
            put = self._deduct_coins(player, unit * 2)
            self.pot += put
            self.play_sound(tomatodo_audio.SOUND_COINS)
            self.broadcast_l(
                "tomatodo-result-pon-2",
                buffer="game",
                player=player.name,
                coins=put,
                pot=self.pot,
            )
            if player.bankrupt:
                self.broadcast_l("tomatodo-player-bankrupt", buffer="game", player=player.name)

        elif face == FACE_TOMA_1:
            take = min(unit, self.pot)
            if take > 0:
                self.pot -= take
                self._credit_coins(player, take)
                self.play_sound(tomatodo_audio.SOUND_COINS)
                self.broadcast_l(
                    "tomatodo-result-toma-1",
                    buffer="game",
                    player=player.name,
                    coins=take,
                    pot=self.pot,
                )
            else:
                self.broadcast_l("tomatodo-pot-empty", buffer="game")

            if self.pot == 0:
                self._replenish_pot()

        elif face == FACE_TOMA_2:
            take = min(unit * 2, self.pot)
            if take > 0:
                self.pot -= take
                self._credit_coins(player, take)
                self.play_sound(tomatodo_audio.SOUND_COINS)
                self.broadcast_l(
                    "tomatodo-result-toma-2",
                    buffer="game",
                    player=player.name,
                    coins=take,
                    pot=self.pot,
                )
            else:
                self.broadcast_l("tomatodo-pot-empty", buffer="game")

            if self.pot == 0:
                self._replenish_pot()

        elif face == FACE_TODOS_PONEN:
            total_added = 0
            for p in self._living_players():
                added = self._deduct_coins(p, unit)
                total_added += added
                if p.bankrupt:
                    self.broadcast_l("tomatodo-player-bankrupt", buffer="game", player=p.name)

            self.pot += total_added
            self.play_sound(tomatodo_audio.SOUND_COINS)
            self.broadcast_l(
                "tomatodo-result-todos-ponen",
                buffer="game",
                unit=unit,
                pot=self.pot,
            )

        elif face == FACE_TOMA_TODO:
            won_amount = self.pot
            self._credit_coins(player, won_amount)
            self.pot = 0
            self.last_pot_taken = won_amount
            self.play_sound(tomatodo_audio.SOUND_COINS)
            self.broadcast_l(
                "tomatodo-result-toma-todo",
                buffer="game",
                player=player.name,
                coins=won_amount,
            )
            # Cycle restarts with an ante replenishment
            self._replenish_pot()

        self._check_game_end_or_advance()

    def _replenish_pot(self) -> None:
        """Replenish the pot when emptied."""
        unit = self._get_coin_unit()
        added = 0
        for p in self._living_players():
            collected = self._deduct_coins(p, unit)
            added += collected
            if p.bankrupt:
                self.broadcast_l("tomatodo-player-bankrupt", buffer="game", player=p.name)

        self.pot += added
        self.play_sound(tomatodo_audio.SOUND_COINS)
        self.broadcast_l(
            "tomatodo-pot-replenished",
            buffer="game",
            unit=unit,
            pot=self.pot,
        )

    def _living_players(self) -> list[TomaTodoPlayer]:
        return [
            p
            for p in self.get_active_players()
            if isinstance(p, TomaTodoPlayer) and not p.bankrupt
        ]

    def _check_game_end_or_advance(self) -> None:
        survivors = self._living_players()

        # Only 1 survivor left -> Winner!
        if len(survivors) <= 1:
            winner = survivors[0] if survivors else None
            if winner:
                # Award any remaining pot
                if self.pot > 0:
                    self._credit_coins(winner, self.pot)
                    self.pot = 0
                self.winner_ids = [winner.id]
                self.play_sound(tomatodo_audio.SOUND_WIN)
                self.broadcast_l(
                    "tomatodo-game-won-last-standing",
                    buffer="game",
                    winner=winner.name,
                    coins=winner.coins,
                )
            self.finish_game()
            return

        # Check round limits if configured
        try:
            max_r = int(self.options.max_rounds)
        except (ValueError, TypeError):
            max_r = 0

        if max_r > 0 and self.round_number >= max_r:
            # Highest coins wins
            survivors.sort(key=lambda p: p.coins, reverse=True)
            top_coins = survivors[0].coins
            top_winners = [p for p in survivors if p.coins == top_coins]
            self.winner_ids = [w.id for w in top_winners]

            # Split remaining pot among winners
            if self.pot > 0:
                share = self.pot // len(top_winners)
                for w in top_winners:
                    self._credit_coins(w, share)
                self.pot = 0

            self.play_sound(tomatodo_audio.SOUND_WIN)
            if len(top_winners) == 1:
                self.broadcast_l(
                    "tomatodo-game-won-rounds",
                    buffer="game",
                    winner=top_winners[0].name,
                    coins=top_winners[0].coins,
                )
            else:
                names = ", ".join(w.name for w in top_winners)
                self.broadcast_l(
                    "tomatodo-game-tie-rounds",
                    buffer="game",
                    winners=names,
                    coins=top_coins,
                )
            self.finish_game()
            return

        # Advance turn to next living player
        self.round_number += 1
        self._advance_to_next_living_player()
        self.refresh_menus()

    def _advance_to_next_living_player(self) -> None:
        active = self.get_active_players()
        if not active:
            return

        for _ in range(len(active)):
            self.advance_turn()
            current = self.current_player
            if isinstance(current, TomaTodoPlayer) and not current.bankrupt:
                break

    # ------------------------------------------------------------------ #
    # Ticks & Flow                                                       #
    # ------------------------------------------------------------------ #

    def on_tick(self) -> None:
        super().on_tick()
        self.process_scheduled_sounds()
        self.process_sequences()

    # ------------------------------------------------------------------ #
    # Results & Cleanup                                                   #
    # ------------------------------------------------------------------ #

    def build_game_result(self) -> GameResult:
        return GameResult(
            game_type=self.get_type(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            duration_ticks=self.sound_scheduler_tick,
            player_results=[
                PlayerResult.from_player(player) for player in self.players
            ],
            custom_data={
                "winner_ids": list(self.winner_ids),
                "pot": self.pot,
                "rounds": self.round_number,
            },
        )

    def on_discard(self) -> None:
        """Ensure no coins are stuck in the game pot if abandoned."""
        if self.pot > 0:
            survivors = self._living_players()
            if survivors:
                share = self.pot // len(survivors)
                if share > 0:
                    for p in survivors:
                        self._credit_coins(p, share)
            self.pot = 0
        super().on_discard()
