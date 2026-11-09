"""Data-driven timing for Loteria's sequence-timed sound effects."""

from __future__ import annotations

from functools import cache
from pathlib import Path, PurePosixPath

from ...game_utils.audio_duration import measure_audio_duration_ticks

TICKS_PER_SECOND = 20

SOUND_DRAW = "game_cards/draw1.ogg"
SOUND_SUSPENSE = "game_bingo/suspense.ogg"
SOUND_CYMBAL = "game_bingo/cymbal.ogg"
SOUND_WIN = "game_bingo/win.ogg"
SOUND_ERROR = "game_bingo/error.ogg"
SOUND_PLACE_BEAN = "game_bingo/daub.ogg"
SOUND_REMOVE_BEAN = "game_bingo/undaub.ogg"

AUDIO_DURATIONS_TICKS = {
    SOUND_DRAW: 11,
    SOUND_SUSPENSE: 42,
}

LOTERIA_TIMED_ASSET_PATHS = tuple(AUDIO_DURATIONS_TICKS)

_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_SOUND_ASSET_ROOTS = (
    _REPOSITORY_ROOT / "client" / "sounds",
    _REPOSITORY_ROOT / "web_client" / "sounds",
    _REPOSITORY_ROOT / "mobile_client" / "sounds",
)


@cache
def sound_ticks(sound: str) -> int:
    """Return the shipped asset's duration in ticks, with a tested fallback."""
    relative_path = PurePosixPath(sound)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        return AUDIO_DURATIONS_TICKS.get(sound, 0)
    for asset_root in _SOUND_ASSET_ROOTS:
        measured = measure_audio_duration_ticks(
            asset_root.joinpath(*relative_path.parts),
            ticks_per_second=TICKS_PER_SECOND,
        )
        if measured is not None:
            return measured
    return AUDIO_DURATIONS_TICKS.get(sound, 0)

