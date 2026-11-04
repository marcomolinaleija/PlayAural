"""Game registry for registering and looking up game types."""

from typing import Type, TYPE_CHECKING

from .categories import normalize_categories

if TYPE_CHECKING:
    from .base import Game


class GameRegistry:
    """Registry of all available game types."""

    _games: dict[str, Type["Game"]] = {}

    @classmethod
    def register(cls, game_class: Type["Game"]) -> None:
        """Register a game class."""
        game_type = game_class.get_type()
        cls._games[game_type] = game_class

    @classmethod
    def get(cls, game_type: str) -> Type["Game"] | None:
        """Get a game class by type."""
        return cls._games.get(game_type)

    @classmethod
    def get_all(cls, *, include_social: bool = False) -> list[Type["Game"]]:
        """List games, optionally including social activities for table recovery/switching."""
        return [
            game_class for game_class in cls._games.values()
            if include_social or not getattr(game_class, "is_social_activity", False)
        ]

    @classmethod
    def get_games_for_preference(cls, pref_name: str) -> list[str]:
        """Return game type strings that declare a preference as relevant.

        Results are sorted alphabetically for stable menu ordering.
        """
        result = [
            game_type
            for game_type, game_cls in cls._games.items()
            if pref_name in getattr(game_cls, "relevant_preferences", [])
        ]
        result.sort()
        return result

    @classmethod
    def get_by_category(cls) -> dict[str, list[Type["Game"]]]:
        """Get games organized by category."""
        categories: dict[str, list[Type["Game"]]] = {}
        for game_class in cls.get_all():
            for category in normalize_categories(game_class.get_categories()):
                if category not in categories:
                    categories[category] = []
                categories[category].append(game_class)
        return categories


def register_game(game_class: Type["Game"]) -> Type["Game"]:
    """Decorator to register a game class."""
    GameRegistry.register(game_class)
    return game_class


def get_game_class(game_type: str) -> Type["Game"] | None:
    """Get a game class by type."""
    return GameRegistry.get(game_type)
