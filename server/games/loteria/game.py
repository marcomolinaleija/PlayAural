"""Traditional Mexican Loteria (Lotería Mexicana).

Standard 4x4 card board (16 pictures per tabla) drawn from the traditional
54-card Mexican deck. One card at a time is drawn and called by "El Gritón"
at a configurable interval. Players place beans ("frijolitos") on matching
cards. The first player to complete the chosen winning pattern and shout
"¡Buenas!" / "¡Lotería!" wins.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import ClassVar

from ...game_utils.actions import Action, ActionSet, Visibility
from ...game_utils.game_result import GameResult, PlayerResult
from ...game_utils.grid_mixin import GridCursor, GridGameMixin
from ...game_utils.options import MenuOption, option_field
from ...game_utils.sequence_runner_mixin import SequenceBeat, SequenceOperation
from ...messages.localization import Localization
from ...ui.keybinds import KeybindState
from ...users.base import MenuItem
from ..base import Game, GameOptions, Player
from ..categories import CATEGORY_MISC
from ..registry import register_game
from . import audio as loteria_audio
from .cards import TOTAL_CARDS

# --------------------------------------------------------------------- #
# Constants                                                              #
# --------------------------------------------------------------------- #

TICKS_PER_SECOND = 20

CARD_ROWS = 4
CARD_COLS = 4
TABLA_SIZE = CARD_ROWS * CARD_COLS

PATTERN_CHORRO = "chorro"
PATTERN_CUATRO_ESQUINAS = "cuatro_esquinas"
PATTERN_CENTRO = "centro"
PATTERN_CUADRO_CHICO = "cuadro_chico"
PATTERN_LLENO = "lleno"

PATTERN_CHOICES = [
    PATTERN_CHORRO,
    PATTERN_CUATRO_ESQUINAS,
    PATTERN_CENTRO,
    PATTERN_CUADRO_CHICO,
    PATTERN_LLENO,
]

PATTERN_LABELS = {
    PATTERN_CHORRO: "loteria-pattern-chorro",
    PATTERN_CUATRO_ESQUINAS: "loteria-pattern-cuatro-esquinas",
    PATTERN_CENTRO: "loteria-pattern-centro",
    PATTERN_CUADRO_CHICO: "loteria-pattern-cuadro-chico",
    PATTERN_LLENO: "loteria-pattern-lleno",
}

DEFAULT_CALL_INTERVAL_SECONDS = "15"
CALL_INTERVAL_CHOICES = ["5", "10", "15", "20", "30"]
CALL_INTERVAL_LABELS = {
    "5": "loteria-call-interval-5",
    "10": "loteria-call-interval-10",
    "15": "loteria-call-interval-15",
    "20": "loteria-call-interval-20",
    "30": "loteria-call-interval-30",
}

VERSES_WITH_VERSES = "with_verses"
VERSES_NAMES_ONLY = "names_only"
VERSES_CHOICES = [VERSES_WITH_VERSES, VERSES_NAMES_ONLY]
VERSES_LABELS = {
    VERSES_WITH_VERSES: "loteria-verses-with-verses",
    VERSES_NAMES_ONLY: "loteria-verses-names-only",
}

CALL_WARMUP_TICKS = 3 * TICKS_PER_SECOND
CALL_DRAW_DELAY_TICKS = loteria_audio.sound_ticks(loteria_audio.SOUND_DRAW)

MIN_CLAIM_WINDOW_SECONDS = 4
MIN_CLAIM_WINDOW_TICKS = MIN_CLAIM_WINDOW_SECONDS * TICKS_PER_SECOND
CALL_SEQUENCE_TAG = "loteria_call"

CLAIM_SUSPENSE_TICKS = loteria_audio.sound_ticks(loteria_audio.SOUND_SUSPENSE)
CLAIM_SEQUENCE_TAG = "loteria_claim"
CLAIM_RESULT_SOUND_DELAY_TICKS = TICKS_PER_SECOND

STATUS_RECENT_CALLS_SHOWN = 10

BOT_MARK_DELAY_MIN_SECONDS = 1
BOT_MARK_DELAY_MAX_SECONDS = 5
BOT_REACTION_MIN_TICKS = 10
BOT_REACTION_MAX_TICKS = 40

SOUND_DRAW = loteria_audio.SOUND_DRAW
SOUND_PLACE_BEAN = loteria_audio.SOUND_PLACE_BEAN
SOUND_REMOVE_BEAN = loteria_audio.SOUND_REMOVE_BEAN
SOUND_ERROR = loteria_audio.SOUND_ERROR
SOUND_WIN = loteria_audio.SOUND_WIN
SOUND_SUSPENSE = loteria_audio.SOUND_SUSPENSE
SOUND_CYMBAL = loteria_audio.SOUND_CYMBAL


# --------------------------------------------------------------------- #
# Player / Options                                                      #
# --------------------------------------------------------------------- #


@dataclass
class LoteriaPlayer(Player):
    """Per-player Loteria state: 4x4 tabla, bean marks, and win flag."""

    tabla: list[list[int]] = field(default_factory=list)
    marked: list[list[bool]] = field(default_factory=list)
    has_loteria: bool = False

    rejected_claim_signatures: list[str] = field(default_factory=list)

    pending_mark_card: int | None = None
    pending_mark_ticks: int = 0


@dataclass
class LoteriaOptions(GameOptions):
    """Host-configurable settings for Mexican Loteria."""

    pattern: str = option_field(
        MenuOption(
            default=PATTERN_CHORRO,
            choices=PATTERN_CHOICES,
            value_key="pattern",
            label="loteria-set-pattern",
            prompt="loteria-select-pattern",
            change_msg="loteria-option-changed-pattern",
            description="loteria-desc-pattern",
            choice_labels=PATTERN_LABELS,
        )
    )
    call_interval: str = option_field(
        MenuOption(
            choices=CALL_INTERVAL_CHOICES,
            default=DEFAULT_CALL_INTERVAL_SECONDS,
            value_key="seconds",
            label="loteria-set-call-interval",
            prompt="loteria-select-call-interval",
            change_msg="loteria-option-changed-interval",
            description="loteria-desc-call-interval",
            choice_labels=CALL_INTERVAL_LABELS,
        )
    )
    verses: str = option_field(
        MenuOption(
            choices=VERSES_CHOICES,
            default=VERSES_WITH_VERSES,
            value_key="mode",
            label="loteria-set-verses",
            prompt="loteria-select-verses",
            change_msg="loteria-option-changed-verses",
            description="loteria-desc-verses",
            choice_labels=VERSES_LABELS,
        )
    )


# --------------------------------------------------------------------- #
# Game                                                                   #
# --------------------------------------------------------------------- #


@register_game
@dataclass
class LoteriaGame(GridGameMixin, Game):
    """Traditional Mexican Loteria with configurable winning patterns."""

    players: list[LoteriaPlayer] = field(default_factory=list)
    options: LoteriaOptions = field(default_factory=LoteriaOptions)

    grid_rows: int = CARD_ROWS
    grid_cols: int = CARD_COLS
    grid_cursors: dict[str, GridCursor] = field(default_factory=dict)
    grid_row_labels: list[str] = field(default_factory=list)
    grid_col_labels: list[str] = field(default_factory=list)

    available_cards: list[int] = field(default_factory=list)
    called_cards: list[int] = field(default_factory=list)
    call_countdown_ticks: int = 0
    winner_ids: list[str] = field(default_factory=list)

    pending_call_card: int | None = None
    pending_claim_player_id: str | None = None

    # ------------------------------------------------------------------ #
    # Metadata                                                            #
    # ------------------------------------------------------------------ #

    @classmethod
    def get_name(cls) -> str:
        return "Lotería Mexicana"

    @classmethod
    def get_type(cls) -> str:
        return "loteria"

    @classmethod
    def get_category(cls) -> str:
        return CATEGORY_MISC

    @classmethod
    def get_min_players(cls) -> int:
        return 2

    @classmethod
    def get_max_players(cls) -> int:
        return 12

    @classmethod
    def get_supported_leaderboards(cls) -> list[str]:
        return ["wins", "games_played"]

    def create_player(
        self, player_id: str, name: str, is_bot: bool = False
    ) -> LoteriaPlayer:
        return LoteriaPlayer(id=player_id, name=name, is_bot=is_bot)

    def create_player(
        self, player_id: str, name: str, is_bot: bool = False
    ) -> LoteriaPlayer:
        return LoteriaPlayer(id=player_id, name=name, is_bot=is_bot)

    def _locale(self, player: Player) -> str:
        user = self.get_user(player)
        return user.locale if user else "es"

    def _card_name(self, card_id: int, locale: str) -> str:
        return Localization.get(locale, f"loteria-card-{card_id}")

    def _card_rhyme(self, card_id: int, locale: str) -> str:
        return Localization.get(locale, f"loteria-rhyme-{card_id}")

    # ------------------------------------------------------------------ #
    # Tabla generation                                                   #
    # ------------------------------------------------------------------ #

    def _generate_tabla(self) -> tuple[list[list[int]], list[list[bool]]]:
        """Build one independent 4x4 tabla: 16 unique cards from the 54-card deck."""
        sample = random.sample(range(1, TOTAL_CARDS + 1), TABLA_SIZE)
        tabla = [
            sample[row * CARD_COLS : (row + 1) * CARD_COLS]
            for row in range(CARD_ROWS)
        ]
        marked = [[False] * CARD_COLS for _ in range(CARD_ROWS)]
        return tabla, marked

    # ------------------------------------------------------------------ #
    # Grid mixin overrides (the player's board)                          #
    # ------------------------------------------------------------------ #

    def get_cell_label(
        self, row: int, col: int, player: Player, locale: str
    ) -> str:
        if not isinstance(player, LoteriaPlayer) or not player.tabla:
            return ""
        card_id = player.tabla[row][col]
        card_name = self._card_name(card_id, locale)
        key = "loteria-cell-marked" if player.marked[row][col] else "loteria-cell-unmarked"
        return Localization.get(
            locale, key, row=row + 1, col=col + 1, card=card_name
        )

    def is_grid_cell_enabled(
        self, player: Player, row: int, col: int
    ) -> str | None:
        if self.status != "playing":
            return "action-not-playing"
        if player.is_spectator:
            return "action-spectator"
        if isinstance(player, LoteriaPlayer) and player.has_loteria:
            return "loteria-you-already-won"
        if self.is_sequence_gameplay_locked():
            if self.pending_claim_player_id == player.id:
                return "loteria-claim-in-progress-you"
            return "loteria-claim-in-progress"
        return None

    def is_grid_cell_hidden(
        self, player: Player, row: int, col: int
    ) -> Visibility:
        if self.status != "playing" or player.is_spectator:
            return Visibility.HIDDEN
        return Visibility.VISIBLE

    def on_grid_select(self, player: Player, row: int, col: int) -> None:
        if not isinstance(player, LoteriaPlayer):
            return
        if self.is_grid_cell_enabled(player, row, col) is not None:
            return

        card_id = player.tabla[row][col]
        player.marked[row][col] = not player.marked[row][col]
        user = self.get_user(player)
        if user:
            sound = SOUND_PLACE_BEAN if player.marked[row][col] else SOUND_REMOVE_BEAN
            user.play_sound(sound)
            key = "loteria-you-mark" if player.marked[row][col] else "loteria-you-unmark"
            card_name = self._card_name(card_id, user.locale)
            user.speak_l(key, buffer="game", card=card_name)
        self.refresh_menus(player)

    # ------------------------------------------------------------------ #
    # Keybinds                                                            #
    # ------------------------------------------------------------------ #

    def setup_keybinds(self) -> None:
        super().setup_keybinds()
        self.setup_grid_keybinds()
        self.define_keybind(
            "b",
            Localization.get("es", "loteria-claim-loteria"),
            ["claim_loteria"],
            state=KeybindState.ACTIVE,
        )
        self.define_keybind(
            "shift+enter",
            Localization.get("es", "loteria-claim-loteria"),
            ["claim_loteria_gesture"],
            state=KeybindState.ACTIVE,
        )
        self.define_keybind(
            "r",
            Localization.get("es", "loteria-repeat-call"),
            ["repeat_call"],
            state=KeybindState.ACTIVE,
            include_spectators=True,
        )
        self.define_keybind(
            "c",
            Localization.get("es", "loteria-check-called"),
            ["check_called"],
            state=KeybindState.ACTIVE,
            include_spectators=True,
        )

    # ------------------------------------------------------------------ #
    # Actions and menus                                                   #
    # ------------------------------------------------------------------ #

    def create_turn_action_set(self, player: LoteriaPlayer) -> ActionSet:
        action_set = ActionSet(name="turn")

        for action in self.build_grid_actions(player):
            action_set.add(action)
        for action in self.build_grid_nav_actions():
            action_set.add(action)

        action_set.add(
            Action(
                id="claim_loteria",
                label=Localization.get(self._locale(player), "loteria-claim-loteria"),
                handler="_action_claim_loteria",
                is_enabled="_is_claim_enabled",
                is_hidden="_is_claim_hidden",
            )
        )

        action_set.add(
            Action(
                id="claim_loteria_gesture",
                label=Localization.get(self._locale(player), "loteria-claim-loteria"),
                handler="_action_claim_loteria",
                is_enabled="_is_claim_gesture_enabled",
                is_hidden="_is_claim_gesture_hidden",
                show_in_actions_menu=False,
            )
        )

        return action_set

    def create_standard_action_set(self, player: Player) -> ActionSet:
        action_set = super().create_standard_action_set(player)
        locale = self._locale(player)

        action_set.add(
            Action(
                id="repeat_call",
                label=Localization.get(locale, "loteria-repeat-call"),
                handler="_action_repeat_call",
                is_enabled="_is_repeat_call_enabled",
                is_hidden="_is_repeat_call_hidden",
                include_spectators=True,
            )
        )
        action_set.add(
            Action(
                id="check_called",
                label=Localization.get(locale, "loteria-check-called"),
                handler="_action_check_called",
                is_enabled="_is_check_called_enabled",
                is_hidden="_is_check_called_hidden",
                include_spectators=True,
            )
        )
        table = getattr(self, "_table", None)
        if table and getattr(table, "bet", 0) > 0:
            action_set.add(
                Action(
                    id="check_pot",
                    label=Localization.get(locale, "loteria-action-check-pot"),
                    handler="_action_check_pot",
                    is_enabled="_is_check_pot_enabled",
                    is_hidden="_is_check_pot_hidden",
                    include_spectators=True,
                )
            )

        self._apply_standard_touch_order(action_set, self.get_user(player))
        return action_set

    _STANDARD_TOUCH_ORDER: ClassVar[list[str]] = [
        "repeat_call",
        "check_called",
        "check_pot",
        "check_scores",
        "whose_turn",
        "whos_at_table",
    ]

    def _apply_standard_touch_order(self, action_set: ActionSet, user) -> None:
        if self.is_touch_client(user):
            self._order_touch_standard_actions(action_set, self._STANDARD_TOUCH_ORDER)

    def before_menu_build(self, player: Player) -> None:
        if self.get_action_set(player, "standard") is None:
            return
        self.remove_action_set(player, "standard")
        self.add_action_set(player, self.create_standard_action_set(player))

    def _is_whose_turn_hidden(self, player: Player) -> Visibility:
        user = self.get_user(player)
        if self.is_touch_client(user) and self.status == "playing":
            return Visibility.VISIBLE
        return super()._is_whose_turn_hidden(player)

    def _is_whos_at_table_hidden(self, player: Player) -> Visibility:
        user = self.get_user(player)
        if self.is_touch_client(user):
            return Visibility.VISIBLE
        return super()._is_whos_at_table_hidden(player)

    def _is_claim_enabled(self, player: Player) -> str | None:
        if self.status != "playing":
            return "action-not-playing"
        if player.is_spectator:
            return "action-spectator"
        if isinstance(player, LoteriaPlayer) and player.has_loteria:
            return "loteria-you-already-won"
        if self.is_sequence_gameplay_locked():
            if self.pending_claim_player_id == player.id:
                return "loteria-claim-in-progress-you"
            return "loteria-claim-in-progress"
        if self.pending_call_card is not None:
            return "loteria-claim-wait-for-call"
        if (
            isinstance(player, LoteriaPlayer)
            and self._claim_signature(player) in player.rejected_claim_signatures
        ):
            return "loteria-claim-unchanged"
        return None

    def _claim_signature(self, player: LoteriaPlayer) -> str:
        bits = "".join("1" if cell else "0" for row in player.marked for cell in row)
        return f"{len(self.called_cards)}:{bits}"

    def _is_claim_gesture_enabled(self, player: Player) -> str | None:
        if not self.is_touch_client(self.get_user(player)):
            return "action-not-available"
        return self._is_claim_enabled(player)

    def _is_claim_gesture_hidden(self, player: Player) -> Visibility:
        return Visibility.HIDDEN

    def _is_claim_hidden(self, player: Player) -> Visibility:
        if self.status != "playing" or player.is_spectator:
            return Visibility.HIDDEN
        if self.is_touch_client(self.get_user(player)):
            return Visibility.VISIBLE
        return Visibility.HIDDEN

    def _is_repeat_call_enabled(self, player: Player) -> str | None:
        if self.status != "playing":
            return "action-not-playing"
        if not self.called_cards:
            return "loteria-no-calls-yet"
        return None

    def _is_repeat_call_hidden(self, player: Player) -> Visibility:
        if self.status == "playing" and self.is_touch_client(self.get_user(player)):
            return Visibility.VISIBLE
        return Visibility.HIDDEN

    def _is_check_called_enabled(self, player: Player) -> str | None:
        return None if self.status == "playing" else "action-not-playing"

    def _is_check_called_hidden(self, player: Player) -> Visibility:
        if self.status == "playing" and self.is_touch_client(self.get_user(player)):
            return Visibility.VISIBLE
        return Visibility.HIDDEN

    def _is_check_pot_enabled(self, player: Player) -> str | None:
        return None if self.status == "playing" else "action-not-playing"

    def _is_check_pot_hidden(self, player: Player) -> Visibility:
        table = getattr(self, "_table", None)
        if self.status == "playing" and self.is_touch_client(self.get_user(player)) and table and getattr(table, "bet", 0) > 0:
            return Visibility.VISIBLE
        return Visibility.HIDDEN

    # ------------------------------------------------------------------ #
    # Action handlers                                                     #
    # ------------------------------------------------------------------ #

    def _action_claim_loteria(self, player: Player, action_id: str) -> None:
        if not isinstance(player, LoteriaPlayer):
            return
        if self._is_claim_enabled(player) is not None:
            return

        self.pending_claim_player_id = player.id
        self.broadcast_personal_l(
            player, "loteria-checking-claim-you", "loteria-checking-claim", buffer="game"
        )
        self.start_sequence(
            CLAIM_SEQUENCE_TAG,
            [
                SequenceBeat.after_audio(
                    CLAIM_SUSPENSE_TICKS, ops=[SequenceOperation.sound_op(SOUND_SUSPENSE)]
                ),
                SequenceBeat(
                    ops=[
                        SequenceOperation.callback_op(
                            "loteria_resolve_claim", {"player_id": player.id}
                        )
                    ]
                ),
            ],
            tag=CLAIM_SEQUENCE_TAG,
            lock_scope=self.SEQUENCE_LOCK_GAMEPLAY,
            pause_bots=True,
        )
        self.refresh_menus()

    def _action_whose_turn(self, player: Player, action_id: str) -> None:
        _ = action_id
        user = self.get_user(player)
        if not user:
            return
        if self.pending_claim_player_id is not None:
            claimer = next(
                (p for p in self.get_active_players() if p.id == self.pending_claim_player_id),
                None,
            )
            if claimer is not None and claimer.id == player.id:
                user.speak_l("loteria-whose-turn-checking-you", buffer="game")
            elif claimer is None:
                user.speak_l("loteria-whose-turn-checking-card", buffer="game")
            else:
                user.speak_l(
                    "loteria-whose-turn-checking",
                    buffer="game",
                    player=claimer.name,
                )
        elif self.pending_call_card is not None:
            user.speak_l("loteria-whose-turn-drawing", buffer="game")
        else:
            seconds_left = -(-self.call_countdown_ticks // TICKS_PER_SECOND)
            user.speak_l(
                "loteria-whose-turn-waiting", buffer="game", seconds=seconds_left
            )

    def _action_repeat_call(self, player: Player, action_id: str) -> None:
        user = self.get_user(player)
        if not user or not self.called_cards:
            return
        last = self.called_cards[-1]
        card_name = self._card_name(last, user.locale)
        if self.options.verses == VERSES_WITH_VERSES:
            rhyme = self._card_rhyme(last, user.locale)
            user.speak_l(
                "loteria-last-call-with-rhyme",
                buffer="game",
                number=last,
                card=card_name,
                rhyme=rhyme,
            )
        else:
            user.speak_l(
                "loteria-last-call",
                buffer="game",
                number=last,
                card=card_name,
            )

    def _action_check_pot(self, player: Player, action_id: str) -> None:
        user = self.get_user(player)
        if user:
            table = getattr(self, "_table", None)
            pot_amount = getattr(table, "pot", 0) if table else 0
            bet_amount = getattr(table, "bet", 0) if table else 0
            user.speak_l(
                "loteria-check-pot-info",
                buffer="game",
                pot=pot_amount,
                bet=bet_amount,
            )

    def _action_check_called(self, player: Player, action_id: str) -> None:
        self.live_status_box(
            player, "loteria_called", self._called_cards_items, focus_id="called_count"
        )

    def _called_cards_items(self, player: Player, user) -> list[MenuItem]:
        locale = user.locale
        items = [
            MenuItem(
                text=Localization.get(
                    locale,
                    "loteria-status-called-count",
                    count=len(self.called_cards),
                    total=TOTAL_CARDS,
                ),
                id="called_count",
            )
        ]
        recent = self.called_cards[-STATUS_RECENT_CALLS_SHOWN:]
        for card_id in reversed(recent):
            card_name = self._card_name(card_id, locale)
            items.append(
                MenuItem(
                    text=Localization.get(
                        locale,
                        "loteria-status-called-entry",
                        number=card_id,
                        card=card_name,
                    ),
                    id=f"card:{card_id}",
                )
            )
        return items

    # ------------------------------------------------------------------ #
    # Pattern checking                                                    #
    # ------------------------------------------------------------------ #

    def _pattern_candidate_cells(self, pattern: str) -> list[list[tuple[int, int]]]:
        if pattern == PATTERN_LLENO:
            return [[(r, c) for r in range(CARD_ROWS) for c in range(CARD_COLS)]]
        if pattern == PATTERN_CUATRO_ESQUINAS:
            return [
                [
                    (0, 0),
                    (0, CARD_COLS - 1),
                    (CARD_ROWS - 1, 0),
                    (CARD_ROWS - 1, CARD_COLS - 1),
                ]
            ]
        if pattern == PATTERN_CENTRO:
            return [[(1, 1), (1, 2), (2, 1), (2, 2)]]
        if pattern == PATTERN_CUADRO_CHICO:
            squares = []
            for r in range(CARD_ROWS - 1):
                for c in range(CARD_COLS - 1):
                    squares.append([(r, c), (r, c + 1), (r + 1, c), (r + 1, c + 1)])
            return squares

        # PATTERN_CHORRO (default): any line (4 rows, 4 columns, 2 diagonals)
        candidates = [[(r, c) for c in range(CARD_COLS)] for r in range(CARD_ROWS)]
        candidates += [[(r, c) for r in range(CARD_ROWS)] for c in range(CARD_COLS)]
        candidates.append([(i, i) for i in range(CARD_ROWS)])
        candidates.append([(i, CARD_COLS - 1 - i) for i in range(CARD_ROWS)])
        return candidates

    def _check_pattern(self, player: LoteriaPlayer) -> bool:
        for cells in self._pattern_candidate_cells(self.options.pattern):
            if all(player.marked[r][c] for r, c in cells):
                return True
        return False

    def _verify_claim(
        self, player: LoteriaPlayer
    ) -> tuple[bool, int | None, list[int] | None]:
        first_bad_card: int | None = None
        for cells in self._pattern_candidate_cells(self.options.pattern):
            if not all(player.marked[r][c] for r, c in cells):
                continue
            uncalled = [
                (r, c)
                for r, c in cells
                if player.tabla[r][c] not in self.called_cards
            ]
            if not uncalled:
                winning_cards = [player.tabla[r][c] for r, c in cells]
                return True, None, winning_cards
            if first_bad_card is None:
                bad_row, bad_col = uncalled[0]
                first_bad_card = player.tabla[bad_row][bad_col]
        return False, first_bad_card, None

    # ------------------------------------------------------------------ #
    # Game flow                                                           #
    # ------------------------------------------------------------------ #

    def _get_database(self) -> Any:
        if hasattr(self, "_db") and self._db is not None:
            return self._db
        table = getattr(self, "_table", None)
        if table is not None:
            if hasattr(table, "_db") and table._db is not None:
                return table._db
            server = getattr(table, "_server", None)
            if server is not None:
                return getattr(server, "db", getattr(server, "_db", None))
        return None

    def prestart_validate(self) -> list[str | tuple[str, dict]]:
        errors: list[str | tuple[str, dict]] = list(super().prestart_validate())
        if self.options.call_interval not in CALL_INTERVAL_CHOICES:
            errors.append(
                ("loteria-error-invalid-interval", {"value": self.options.call_interval})
            )
        if self.options.pattern not in PATTERN_CHOICES:
            errors.append(("loteria-error-invalid-pattern", {"value": self.options.pattern}))
        if self.options.verses not in VERSES_CHOICES:
            errors.append(("loteria-error-invalid-verses", {"value": self.options.verses}))
        return errors

    def on_start(self) -> None:
        self.cancel_sequences_by_tag(CALL_SEQUENCE_TAG)
        self.cancel_sequences_by_tag(CLAIM_SEQUENCE_TAG)
        self.status = "playing"
        self._sync_table_status()
        self.game_active = True
        self.round = 0
        self.called_cards = []
        self.available_cards = list(range(1, TOTAL_CARDS + 1))
        random.shuffle(self.available_cards)
        self.winner_ids = []
        self.call_countdown_ticks = CALL_WARMUP_TICKS
        self.pending_call_card = None
        self.pending_claim_player_id = None

        active_players = [
            player
            for player in self.get_active_players()
            if isinstance(player, LoteriaPlayer)
        ]
        self.set_turn_players(active_players)
        self.grid_cursors = {}
        self._init_grid()
        self.grid_col_labels = [str(i + 1) for i in range(CARD_COLS)]
        self.grid_row_labels = [str(i + 1) for i in range(CARD_ROWS)]

        for player in active_players:
            player.tabla, player.marked = self._generate_tabla()
            player.has_loteria = False
            player.rejected_claim_signatures = []
            player.pending_mark_card = None
            player.pending_mark_ticks = 0
            player.bot_pending_action = None
            player.bot_think_ticks = 0

        for listener in self.players:
            user = self.get_user(listener)
            if not user:
                continue
            if listener.is_spectator:
                start_key = "loteria-game-start-spectator"
            elif self.is_touch_client(user):
                start_key = "loteria-game-start-touch"
            else:
                start_key = "loteria-game-start"
            user.speak_l(
                start_key,
                buffer="game",
                pattern=Localization.get(
                    user.locale,
                    PATTERN_LABELS.get(self.options.pattern, PATTERN_LABELS[PATTERN_CHORRO]),
                ),
                interval=self.options.call_interval,
            )
        self.refresh_menus()

    def on_tick(self) -> None:
        super().on_tick()
        self.process_scheduled_sounds()
        self.process_sequences()

        if self.status != "playing":
            return

        if not self.is_sequence_gameplay_locked() and self.pending_call_card is None:
            if self.call_countdown_ticks > 0:
                self.call_countdown_ticks -= 1
            else:
                self._start_next_call()

        if (
            self.game_active
            and self.status == "playing"
            and not self.is_sequence_bot_paused()
        ):
            self._process_bots()

    def _process_bots(self) -> None:
        for player in self.get_active_players():
            if self.is_sequence_bot_paused():
                return
            if not isinstance(player, LoteriaPlayer) or not player.is_bot:
                continue

            self._sync_bot_card_to_calls(player)

            if player.pending_mark_card is not None:
                if player.pending_mark_ticks > 0:
                    player.pending_mark_ticks -= 1
                else:
                    self._execute_bot_mark(player)
                continue

            if not player.bot_pending_action:
                if self._check_pattern(player):
                    player.bot_pending_action = "claim_loteria"
                    player.bot_think_ticks = random.randint(
                        BOT_REACTION_MIN_TICKS, BOT_REACTION_MAX_TICKS
                    )
                continue
            if player.bot_think_ticks > 0:
                player.bot_think_ticks -= 1
                continue
            action_id = player.bot_pending_action
            if action_id == "claim_loteria" and self._is_claim_enabled(player) is not None:
                continue
            player.bot_pending_action = None
            self.execute_action(player, action_id)

    def _sync_bot_card_to_calls(self, player: LoteriaPlayer) -> None:
        called = set(self.called_cards)
        pending = player.pending_mark_card
        for row in range(CARD_ROWS):
            for col in range(CARD_COLS):
                card_id = player.tabla[row][col]
                player.marked[row][col] = card_id in called and card_id != pending

    def _execute_bot_mark(self, player: LoteriaPlayer) -> None:
        card_id = player.pending_mark_card
        player.pending_mark_card = None
        if card_id is None or player.has_loteria:
            return

        self._auto_mark(player, card_id)
        if self._check_pattern(player) and not player.bot_pending_action:
            player.bot_pending_action = "claim_loteria"
            player.bot_think_ticks = random.randint(
                BOT_REACTION_MIN_TICKS, BOT_REACTION_MAX_TICKS
            )

    def _start_next_call(self) -> None:
        if not self.available_cards:
            self._finish_no_further_calls()
            return

        card_id = self.available_cards.pop()
        self.pending_call_card = card_id
        self.start_sequence(
            CALL_SEQUENCE_TAG,
            [
                SequenceBeat.after_audio(
                    CALL_DRAW_DELAY_TICKS, ops=[SequenceOperation.sound_op(SOUND_DRAW)]
                ),
                SequenceBeat(
                    ops=[
                        SequenceOperation.callback_op(
                            "loteria_announce_call", {"card_id": card_id}
                        )
                    ]
                ),
            ],
            tag=CALL_SEQUENCE_TAG,
        )

    def _handle_announce_call(self, payload: dict) -> None:
        card_id = payload.get("card_id")
        self.pending_call_card = None
        if (
            not isinstance(card_id, int)
            or isinstance(card_id, bool)
            or not 1 <= card_id <= TOTAL_CARDS
            or card_id in self.called_cards
        ):
            self.call_countdown_ticks = 0
            self.refresh_menus()
            return

        self.called_cards.append(card_id)
        for player in self.get_active_players():
            if isinstance(player, LoteriaPlayer):
                player.rejected_claim_signatures = []

        interval_ticks = int(self.options.call_interval) * TICKS_PER_SECOND
        if self.available_cards:
            remainder = interval_ticks - CALL_DRAW_DELAY_TICKS
        else:
            remainder = interval_ticks
        self.call_countdown_ticks = max(MIN_CLAIM_WINDOW_TICKS, remainder)

        for listener in self.players:
            user = self.get_user(listener)
            if not user:
                continue
            card_name = self._card_name(card_id, user.locale)
            if self.options.verses == VERSES_WITH_VERSES:
                rhyme = self._card_rhyme(card_id, user.locale)
                user.speak_l(
                    "loteria-card-called-with-rhyme",
                    buffer="game",
                    number=card_id,
                    card=card_name,
                    rhyme=rhyme,
                )
            else:
                user.speak_l(
                    "loteria-card-called",
                    buffer="game",
                    number=card_id,
                    card=card_name,
                )

        for player in self.get_active_players():
            if not isinstance(player, LoteriaPlayer) or player.has_loteria:
                continue
            had_card = self._tabla_has_card(player, card_id)
            if not (player.is_bot and had_card):
                continue

            interval_seconds = int(self.options.call_interval)
            max_delay_seconds = max(
                BOT_MARK_DELAY_MIN_SECONDS,
                min(BOT_MARK_DELAY_MAX_SECONDS, interval_seconds - 1),
            )
            player.pending_mark_card = card_id
            player.pending_mark_ticks = random.randint(
                BOT_MARK_DELAY_MIN_SECONDS * TICKS_PER_SECOND,
                max_delay_seconds * TICKS_PER_SECOND,
            )

        self.refresh_menus()

    def _tabla_has_card(self, player: LoteriaPlayer, card_id: int) -> bool:
        return any(card_id in row for row in player.tabla)

    def _find_card_coords(
        self, player: LoteriaPlayer, card_id: int
    ) -> tuple[int, int] | None:
        for r in range(CARD_ROWS):
            for c in range(CARD_COLS):
                if player.tabla[r][c] == card_id:
                    return r, c
        return None

    def _auto_mark(self, player: LoteriaPlayer, card_id: int) -> None:
        coords = self._find_card_coords(player, card_id)
        if coords is not None:
            r, c = coords
            player.marked[r][c] = True

    def _handle_resolve_claim(self, payload: dict) -> None:
        player_id = payload.get("player_id")
        self.pending_claim_player_id = None

        player = next(
            (p for p in self.get_active_players() if p.id == player_id), None
        )
        if not isinstance(player, LoteriaPlayer):
            self.refresh_menus()
            return

        is_valid, bad_card, winning_cards = self._verify_claim(player)
        self.play_sound(SOUND_CYMBAL)

        if is_valid:
            self.schedule_sound(SOUND_WIN, delay_ticks=CLAIM_RESULT_SOUND_DELAY_TICKS)
            self._declare_winner(player, winning_cards or [])
        else:
            current_count = len(self.called_cards)
            player.rejected_claim_signatures = [
                sig
                for sig in player.rejected_claim_signatures
                if sig.startswith(f"{current_count}:")
            ] + [self._claim_signature(player)]
            if bad_card is not None:
                self.broadcast_personal_l(
                    player,
                    "loteria-claim-incorrect-you",
                    "loteria-claim-incorrect",
                    buffer="game",
                )
                user = self.get_user(player)
                if user:
                    card_name = self._card_name(bad_card, user.locale)
                    user.speak_l(
                        "loteria-marked-card-not-called",
                        buffer="game",
                        card=card_name,
                    )
            else:
                self.broadcast_personal_l(
                    player,
                    "loteria-claim-incomplete-you",
                    "loteria-claim-incomplete",
                    buffer="game",
                )
            self.schedule_sound(SOUND_ERROR, delay_ticks=CLAIM_RESULT_SOUND_DELAY_TICKS)
            self.refresh_menus()

    def on_sequence_callback(
        self, sequence_id: str, callback_id: str, payload: dict
    ) -> None:
        if callback_id == "loteria_announce_call":
            self._handle_announce_call(payload)
        elif callback_id == "loteria_resolve_claim":
            self._handle_resolve_claim(payload)

    def _declare_winner(self, player: LoteriaPlayer, winning_cards: list[int]) -> None:
        player.has_loteria = True
        self.winner_ids.append(player.id)

        if winning_cards and self.options.pattern != PATTERN_LLENO:
            self.broadcast_personal_l(
                player,
                "loteria-claim-correct-you",
                "loteria-claim-correct",
                buffer="game",
                cards=lambda locale: Localization.format_list_and(
                    locale,
                    [self._card_name(c, locale) for c in winning_cards],
                ),
            )
        else:
            self.broadcast_personal_l(
                player,
                "loteria-claim-correct-no-cards-you",
                "loteria-claim-correct-no-cards",
                buffer="game",
            )
        self.finish_game()

    def _finish_no_further_calls(self) -> None:
        if self.status != "playing":
            return
        for listener in self.players:
            user = self.get_user(listener)
            if user:
                user.speak_l("loteria-deck-exhausted", buffer="game")
        self.finish_game()

    # ------------------------------------------------------------------ #
    # Results                                                             #
    # ------------------------------------------------------------------ #

    def build_game_result(self) -> GameResult:
        active_players = self.get_active_players()
        winner_names = [
            player.name for player in active_players if player.id in self.winner_ids
        ]
        return GameResult(
            game_type=self.get_type(),
            timestamp=datetime.now(timezone.utc).isoformat(),
            duration_ticks=self.sound_scheduler_tick,
            player_results=[
                PlayerResult.from_player(player)
                for player in active_players
            ],
            custom_data={
                "winner_ids": self.winner_ids,
                "winner_names": winner_names,
                "pattern": self.options.pattern,
                "calls_made": len(self.called_cards),
            },
        )

    def format_end_screen(self, result: GameResult, locale: str) -> list[str]:
        lines = [
            Localization.get(
                locale, "loteria-end-calls", count=result.custom_data.get("calls_made", 0)
            )
        ]
        winners = result.custom_data.get("winner_names") or []
        if winners:
            for name in winners:
                lines.append(Localization.get(locale, "loteria-end-winner-line", player=name))
        else:
            lines.append(Localization.get(locale, "loteria-end-no-winner"))
        return lines

