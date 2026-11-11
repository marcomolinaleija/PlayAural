"""Data-driven timing and audio definitions for Toma Todo (Pirinola)."""

from __future__ import annotations

from functools import cache
from pathlib import Path, PurePosixPath

from ...game_utils.audio_duration import measure_audio_duration_ticks

TICKS_PER_SECOND = 20

SOUND_SPIN = "game_tomatodo/spin.ogg"
SOUND_SPIN_FAST = "game_tomatodo/spin_fast.ogg"
SOUND_COINS = "game_tomatodo/coins.ogg"
SOUND_WIN = "applause.ogg"

AUDIO_DURATIONS_TICKS = {
    SOUND_SPIN: 221,
    SOUND_SPIN_FAST: 70,
    SOUND_COINS: 35,
}

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
