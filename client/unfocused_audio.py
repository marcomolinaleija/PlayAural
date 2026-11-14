"""Per-category silence while the desktop window is unfocused.

Categories match the audio options:

- game: messages and sounds from the match being played
- table: table chat
- invitations: table invitations
- system: admin and system messages
- private: private messages

The personal "it is your turn" alert stays audible in every category. Other
players' turn announcements still follow the game switch.
"""

from __future__ import annotations

from typing import Any

UNFOCUSED_SILENCE_CATEGORIES = (
    "game",
    "table",
    "invitations",
    "system",
    "private",
)

_INVITE_SPEAK_PREFIXES = ("table-invite-",)
_INVITE_SPEAK_KEYS = {"host-invite-declined"}
_INVITE_ASSETS = {"table_invite.ogg"}
_PRIVATE_ASSETS = {"pm.ogg"}
_TABLE_ASSETS = {"chatlocal.ogg"}
_UNCLASSIFIED_ASSETS = {"chat.ogg"}
_SYSTEM_ASSETS = {
    "coins_grant.ogg",
    "disconnect.ogg",
    "kick.ogg",
    "lsmack.ogg",
    "mention.ogg",
    "moderation_report.ogg",
    "reconnect.ogg",
    "table_created.ogg",
    "table_join.ogg",
    "table_kick.ogg",
    "table_leave.ogg",
    "update_alert.ogg",
    "update_complete.ogg",
    "welcome.ogg",
}
_SYSTEM_PREFIXES = (
    "account",
    "friend_",
    "notify",
    "offline",
    "online",
    "server_alert_",
    "voice_",
)
# Personal turn-start speech, such as game-turn-start-you. A bare "turn"
# substring would also match typing_return.ogg, so the sound check is exact.
_TURN_ALERT_SPEAK_SUFFIX = "-turn-start-you"
_TURN_ALERT_ASSETS = {"turn.ogg", "begin turn.ogg"}


def default_unfocused_silence() -> dict[str, bool]:
    """Return every category audible."""
    return {category: False for category in UNFOCUSED_SILENCE_CATEGORIES}


def migrate_client_audio_options(
    audio: dict[str, Any], *, had_explicit_categories: bool
) -> None:
    """Fill category flags and fold the old single switch into them once."""
    silence = audio.get("unfocused_silence")
    if not isinstance(silence, dict):
        silence = {}
        audio["unfocused_silence"] = silence
    for category in UNFOCUSED_SILENCE_CATEGORIES:
        silence.setdefault(category, False)
    if not had_explicit_categories and audio.get("limit_unfocused_audio_and_tts"):
        for category in UNFOCUSED_SILENCE_CATEGORIES:
            silence[category] = True
    audio["limit_unfocused_audio_and_tts"] = False


def silence_flags(audio: dict[str, Any] | None) -> dict[str, bool]:
    """Return one boolean per category, honoring a legacy all-or-nothing flag."""
    audio = audio or {}
    raw = audio.get("unfocused_silence")
    flags: dict[str, bool] = {}
    if isinstance(raw, dict):
        for category in UNFOCUSED_SILENCE_CATEGORIES:
            if category in raw:
                flags[category] = bool(raw[category])
    if len(flags) < len(UNFOCUSED_SILENCE_CATEGORIES):
        legacy = bool(audio.get("limit_unfocused_audio_and_tts", False))
        for category in UNFOCUSED_SILENCE_CATEGORIES:
            flags.setdefault(category, legacy)
    return flags


def should_silence_unfocused(
    audio: dict[str, Any] | None, category: str, *, window_active: bool
) -> bool:
    """Return whether this category is quiet because the window is unfocused."""
    if window_active or category not in UNFOCUSED_SILENCE_CATEGORIES:
        return False
    return silence_flags(audio).get(category, False)


def speak_category(buffer_name: str, key: str = "") -> str:
    """Classify a speak packet. An empty result is never silenced by these options."""
    message_key = str(key or "")
    if message_key.endswith(_TURN_ALERT_SPEAK_SUFFIX):
        return ""
    if message_key in _INVITE_SPEAK_KEYS or message_key.startswith(_INVITE_SPEAK_PREFIXES):
        return "invitations"
    if buffer_name == "game":
        return "game"
    if buffer_name == "private":
        return "private"
    if buffer_name == "chat":
        return "table"
    if buffer_name in {"system", "misc"}:
        return "system"
    return ""


def chat_category(convo: str) -> str:
    """Classify a chat packet. Global chat stays outside these switches."""
    if convo == "private":
        return "private"
    if convo == "announcement":
        return "system"
    if convo == "global":
        return ""
    return "table"


def audio_category(packet: dict[str, Any]) -> str:
    """Classify one audio command. Lifecycle commands other than play stay audible."""
    command = str(packet.get("command") or "play")
    if command != "play":
        return ""
    buffer_name = str(packet.get("buffer") or "")
    asset = _asset_basename(packet)
    if asset in _TURN_ALERT_ASSETS:
        return ""
    if asset in _INVITE_ASSETS:
        return "invitations"
    if asset in _PRIVATE_ASSETS or buffer_name == "private":
        return "private"
    if asset in _TABLE_ASSETS or buffer_name == "chat":
        return "table"
    if asset in _UNCLASSIFIED_ASSETS:
        return ""
    if buffer_name == "game":
        return "game"
    if buffer_name in {"system", "misc"} or _is_system_asset(asset):
        return "system"
    return "game"


def _asset_basename(packet: dict[str, Any]) -> str:
    raw = str(packet.get("asset") or packet.get("family") or "")
    return raw.replace("\\", "/").rsplit("/", 1)[-1].lower()


def _is_system_asset(asset: str) -> bool:
    if asset in _SYSTEM_ASSETS:
        return True
    return asset.startswith(_SYSTEM_PREFIXES)
