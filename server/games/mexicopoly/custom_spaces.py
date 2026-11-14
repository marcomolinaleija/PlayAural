"""Extensible custom space landing handlers for Mexipoly."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .game import MexicopolyGame
    from ..monopoly.game import MonopolyPlayer
    from ..monopoly.models import BoardSpaceDefinition

JUZGADO_COURT_FEE = 150

# Registry mapping space IDs to custom landing handlers.
# Signature: (game, player, space) -> bool (True if landing handled, False if fallthrough)
CUSTOM_SPACE_HANDLERS: dict[
    str,
    Callable[[MexicopolyGame, MonopolyPlayer, BoardSpaceDefinition], bool],
] = {}


def handle_juzgado_landing(
    game: MexicopolyGame,
    player: MonopolyPlayer,
    space: BoardSpaceDefinition,
) -> bool:
    """Handle landing on the District Court (Juzgado de Distrito)."""
    state = game.property_states.get(space.id)
    if not state or not state.owner_id:
        # Unowned: let standard property landing offer purchase or auction
        return False

    owner = game._alive_player_by_id(state.owner_id)
    if not owner:
        return False

    if owner.id == player.id:
        game._broadcast_actor(
            player,
            "mexicopoly-you-juzgado-welcome",
            "mexicopoly-player-juzgado-welcome",
        )
        game._finish_landing()
        return True

    if state.mortgaged:
        game._broadcast_actor(
            player,
            "mexicopoly-you-juzgado-mortgaged-visit",
            "mexicopoly-player-juzgado-mortgaged-visit",
            owner=owner.name,
        )
        game._finish_landing()
        return True

    # Owner is another player and court is active: pay legal processing fee
    fee = JUZGADO_COURT_FEE
    if player.cash < fee:
        game._start_debt(
            player,
            owner.id,
            fee,
            "mexicopoly-debt-juzgado-fee",
            continuation="finish_landing",
        )
        return True

    player.cash -= fee
    owner.cash += fee
    game._broadcast_actor(
        player,
        "mexicopoly-you-juzgado-fee",
        "mexicopoly-player-juzgado-fee",
        owner=owner.name,
        amount=lambda locale: game._money(locale, fee),
        cash=lambda locale: game._money(locale, player.cash),
    )
    game._finish_landing()
    return True


CUSTOM_SPACE_HANDLERS["juzgado"] = handle_juzgado_landing
