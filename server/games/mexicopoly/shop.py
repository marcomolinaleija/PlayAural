"""Shop items and catalog architecture for Mexipoly."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

from ...messages.localization import Localization
from ..monopoly import audio as game_audio

if TYPE_CHECKING:
    from .game import MexicopolyGame
    from ..monopoly.game import MonopolyPlayer

AIRPLANE_PRICE = 1500
CAR_PRICE = 600
CAR_INITIAL_FUEL = 4
FUEL_PRICE = 200
FUEL_REFILL_AMOUNT = 4


@dataclass(frozen=True)
class ShopItem:
    """A purchasable item or upgrade in the Mexipoly shop."""

    id: str
    price: int
    is_unlocked: Callable[[MexicopolyGame, MonopolyPlayer], bool]
    can_buy: Callable[[MexicopolyGame, MonopolyPlayer], tuple[bool, str | None]]
    on_buy: Callable[[MexicopolyGame, MonopolyPlayer], None]
    get_label: Callable[[MexicopolyGame, MonopolyPlayer], str]
    get_description: Callable[[MexicopolyGame, MonopolyPlayer], str]


def _airplane_unlocked(game: MexicopolyGame, player: MonopolyPlayer) -> bool:
    airport_ids = {s.id for s in game.board.spaces if s.group_id == "airports"}
    visited = set(game.visited_airports.get(player.id, []))
    return airport_ids.issubset(visited)


def _airplane_can_buy(
    game: MexicopolyGame, player: MonopolyPlayer
) -> tuple[bool, str | None]:
    if game.has_airplane.get(player.id, False):
        return False, "mexicopoly-shop-item-airplane-owned"
    if not _airplane_unlocked(game, player):
        return False, "mexicopoly-error-airplane-locked"
    if player.cash < AIRPLANE_PRICE:
        return False, "monopoly-error-not-enough-cash"
    return True, None


def _airplane_on_buy(game: MexicopolyGame, player: MonopolyPlayer) -> None:
    player.cash -= AIRPLANE_PRICE
    game.has_airplane[player.id] = True
    game.play_sound(game_audio.SOUND_PROPERTY_PURCHASED)
    game._broadcast_actor(
        player,
        "mexicopoly-you-bought-airplane",
        "mexicopoly-player-bought-airplane",
        price=lambda locale: game._money(locale, AIRPLANE_PRICE),
        cash=lambda locale: game._money(locale, player.cash),
    )


def _airplane_label(game: MexicopolyGame, player: MonopolyPlayer) -> str:
    locale = game._locale(player)
    if game.has_airplane.get(player.id, False):
        return Localization.get(locale, "mexicopoly-shop-item-airplane-owned")
    airport_ids = {s.id for s in game.board.spaces if s.group_id == "airports"}
    visited = set(game.visited_airports.get(player.id, []))
    if not airport_ids.issubset(visited):
        return Localization.get(
            locale,
            "mexicopoly-shop-item-airplane-locked",
            price=game._money(locale, AIRPLANE_PRICE),
            visited=len(visited.intersection(airport_ids)),
            total=len(airport_ids),
        )
    return Localization.get(
        locale,
        "mexicopoly-shop-item-airplane",
        price=game._money(locale, AIRPLANE_PRICE),
    )


def _airplane_description(game: MexicopolyGame, player: MonopolyPlayer) -> str:
    locale = game._locale(player)
    return Localization.get(locale, "mexicopoly-desc-shop-airplane")


def _car_can_buy(
    game: MexicopolyGame, player: MonopolyPlayer
) -> tuple[bool, str | None]:
    if game.has_car.get(player.id, False):
        return False, "mexicopoly-shop-item-car-owned"
    if player.cash < CAR_PRICE:
        return False, "monopoly-error-not-enough-cash"
    return True, None


def _car_on_buy(game: MexicopolyGame, player: MonopolyPlayer) -> None:
    player.cash -= CAR_PRICE
    game.has_car[player.id] = True
    game.car_fuel[player.id] = CAR_INITIAL_FUEL
    game.play_sound(game_audio.SOUND_PROPERTY_PURCHASED)
    game._broadcast_actor(
        player,
        "mexicopoly-you-bought-car",
        "mexicopoly-player-bought-car",
        price=lambda locale: game._money(locale, CAR_PRICE),
        cash=lambda locale: game._money(locale, player.cash),
        fuel=CAR_INITIAL_FUEL,
    )


def _car_label(game: MexicopolyGame, player: MonopolyPlayer) -> str:
    locale = game._locale(player)
    if game.has_car.get(player.id, False):
        return Localization.get(locale, "mexicopoly-shop-item-car-owned")
    return Localization.get(
        locale,
        "mexicopoly-shop-item-car",
        price=game._money(locale, CAR_PRICE),
    )


def _car_description(game: MexicopolyGame, player: MonopolyPlayer) -> str:
    locale = game._locale(player)
    return Localization.get(locale, "mexicopoly-desc-shop-car")


def _fuel_can_buy(
    game: MexicopolyGame, player: MonopolyPlayer
) -> tuple[bool, str | None]:
    if not game.has_car.get(player.id, False):
        return False, "mexicopoly-shop-item-fuel-no-car"
    fuel = game.car_fuel.get(player.id, 0)
    if fuel >= FUEL_REFILL_AMOUNT:
        return False, "mexicopoly-shop-item-fuel-full"
    if player.cash < FUEL_PRICE:
        return False, "monopoly-error-not-enough-cash"
    return True, None


def _fuel_on_buy(game: MexicopolyGame, player: MonopolyPlayer) -> None:
    player.cash -= FUEL_PRICE
    game.car_fuel[player.id] = FUEL_REFILL_AMOUNT
    game.play_sound(game_audio.SOUND_PROPERTY_PURCHASED)
    game._broadcast_actor(
        player,
        "mexicopoly-you-bought-fuel",
        "mexicopoly-player-bought-fuel",
        price=lambda locale: game._money(locale, FUEL_PRICE),
        cash=lambda locale: game._money(locale, player.cash),
        fuel=FUEL_REFILL_AMOUNT,
    )


def _fuel_label(game: MexicopolyGame, player: MonopolyPlayer) -> str:
    locale = game._locale(player)
    if not game.has_car.get(player.id, False):
        return Localization.get(locale, "mexicopoly-shop-item-fuel-no-car")
    fuel = game.car_fuel.get(player.id, 0)
    if fuel >= FUEL_REFILL_AMOUNT:
        return Localization.get(locale, "mexicopoly-shop-item-fuel-full")
    return Localization.get(
        locale,
        "mexicopoly-shop-item-fuel",
        price=game._money(locale, FUEL_PRICE),
        current=fuel,
        max=FUEL_REFILL_AMOUNT,
    )


def _fuel_description(game: MexicopolyGame, player: MonopolyPlayer) -> str:
    locale = game._locale(player)
    return Localization.get(locale, "mexicopoly-desc-shop-fuel")


MEXICOPOLY_SHOP_ITEMS: dict[str, ShopItem] = {
    "airplane": ShopItem(
        id="airplane",
        price=AIRPLANE_PRICE,
        is_unlocked=_airplane_unlocked,
        can_buy=_airplane_can_buy,
        on_buy=_airplane_on_buy,
        get_label=_airplane_label,
        get_description=_airplane_description,
    ),
    "car": ShopItem(
        id="car",
        price=CAR_PRICE,
        is_unlocked=lambda g, p: True,
        can_buy=_car_can_buy,
        on_buy=_car_on_buy,
        get_label=_car_label,
        get_description=_car_description,
    ),
    "fuel": ShopItem(
        id="fuel",
        price=FUEL_PRICE,
        is_unlocked=lambda g, p: g.has_car.get(p.id, False),
        can_buy=_fuel_can_buy,
        on_buy=_fuel_on_buy,
        get_label=_fuel_label,
        get_description=_fuel_description,
    ),
}
