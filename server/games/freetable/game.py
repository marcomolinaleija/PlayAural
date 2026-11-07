"""A social activity hosted by the existing durable table session."""

from dataclasses import dataclass
from typing import ClassVar

from ..base import Game, Player
from ..registry import register_game
from ...game_utils.actions import Action, ActionSet, Visibility
from ...game_utils.menu_management_mixin import MenuBuild
from ...messages.localization import Localization
from ...users.base import MenuItem, User


@register_game
@dataclass
class FreeTable(Game):
    """An always-open conversation, with no match, bots, or scores."""

    is_social_activity: ClassVar[bool] = True
    supports_bots: ClassVar[bool] = False

    @classmethod
    def get_name(cls) -> str:
        return "Free table"

    @classmethod
    def get_type(cls) -> str:
        return "freetable"

    @classmethod
    def get_min_players(cls) -> int:
        return 1

    @classmethod
    def get_max_players(cls) -> int:
        return 100

    def create_player(self, player_id: str, name: str, is_bot: bool = False) -> Player:
        if is_bot:
            raise ValueError("Free tables only admit people")
        return Player(id=player_id, name=name)

    def build_menu_items(self, player: Player, user: User) -> MenuBuild:
        # No menu items; keep the turn menu completely empty.
        return MenuBuild(items=[])

    def create_lobby_action_set(self, player: Player) -> ActionSet:
        actions = super().create_lobby_action_set(player)
        for action_id in list(actions._order):
            if action_id not in {"host_management", "toggle_privacy"}:
                actions.remove(action_id)
        user = self.get_user(player)
        actions.add(
            Action(
                id="switch_game",
                label=Localization.get(
                    user.locale if user else "en", "free-table-choose-game"
                ),
                handler="_action_switch_game",
                is_enabled="_is_host_management_enabled",
                is_hidden="_is_host_management_hidden",
                include_spectators=True,
            )
        )
        return actions

    def _action_switch_game(self, player: Player, action_id: str) -> None:
        user = self.get_user(player)
        table = self._table
        if user and table and table._server and self._is_host_or_admin(player):
            table._server._nav_push(
                user,
                table._server._show_host_game_switch_menu,
                table,
                game_return_focus_id=action_id,
            )

    def create_standard_action_set(self, player: Player) -> ActionSet:
        actions = super().create_standard_action_set(player)
        for action_id in (
            "save_table", "whose_turn", "check_scores", "check_scores_detailed", "game_info"
        ):
            actions.remove(action_id)
        user = self.get_user(player)
        locale = user.locale if user else "en"
        actions.get_action("game_rules").label = Localization.get(
            locale, "free-table-help"
        )
        # Place leave_game after game_rules (free table help) and before go_back
        actions.add(
            Action(
                id="leave_game",
                label=Localization.get(locale, "leave-table"),
                handler="_action_leave_game",
                is_enabled="_is_leave_game_enabled",
                is_hidden="_is_leave_game_hidden",
                include_spectators=True,
            )
        )
        return actions

    def _is_host_management_hidden(self, player: Player) -> Visibility:
        return Visibility.VISIBLE if self._is_host_or_admin(player) else Visibility.HIDDEN

    def _is_leave_game_hidden(self, player: Player) -> Visibility:
        return Visibility.VISIBLE

    def _is_whos_at_table_hidden(self, player: Player) -> Visibility:
        return Visibility.VISIBLE

    def _is_read_table_presence_hidden(self, player: Player) -> Visibility:
        return Visibility.VISIBLE

    def prestart_validate(self) -> list[str]:
        return ["free-table-no-match"]

    def on_start(self) -> None:
        """There is no match to start; the table remains open for conversation."""
