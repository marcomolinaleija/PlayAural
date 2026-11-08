"""Configurable sound events registry and definitions for PlayAural."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class SoundEventDef:
    """Definition of a configurable sound event."""

    id: str
    label_key: str
    default_sound: str
    description_key: str | None = None


# Core configurable sound events
SOUND_EVENTS: Final[dict[str, SoundEventDef]] = {
    "table_created": SoundEventDef(
        id="table_created",
        label_key="sound-event-table-created",
        default_sound="table_created.ogg",
        description_key="sound-event-desc-table-created",
    ),
    "table_joined": SoundEventDef(
        id="table_joined",
        label_key="sound-event-table-joined",
        default_sound="table_join.ogg",
        description_key="sound-event-desc-table-joined",
    ),
    "table_left": SoundEventDef(
        id="table_left",
        label_key="sound-event-table-left",
        default_sound="table_leave.ogg",
        description_key="sound-event-desc-table-left",
    ),
    "table_invite": SoundEventDef(
        id="table_invite",
        label_key="sound-event-table-invite",
        default_sound="table_invite.ogg",
        description_key="sound-event-desc-table-invite",
    ),
    "private_message": SoundEventDef(
        id="private_message",
        label_key="sound-event-private-message",
        default_sound="pm.ogg",
        description_key="sound-event-desc-private-message",
    ),
    "friend_request": SoundEventDef(
        id="friend_request",
        label_key="sound-event-friend-request",
        default_sound="friend_request_received.ogg",
        description_key="sound-event-desc-friend-request",
    ),
}

# Standard sound assets available across all PlayAural clients
AVAILABLE_SOUND_ASSETS: Final[list[str]] = sorted([
    "accountactionnotify.ogg",
    "accountapprove.ogg",
    "accountban.ogg",
    "accountdemoteadmin.ogg",
    "accountdeni.ogg",
    "accounterror.ogg",
    "accountpromoteadmin.ogg",
    "accountrequest.ogg",
    "chat.ogg",
    "chatlocal.ogg",
    "click.ogg",
    "disconnect.ogg",
    "enter.ogg",
    "findgamedone.ogg",
    "findgamejoin.ogg",
    "findgamestart.ogg",
    "friend_accepted.ogg",
    "friend_declined.ogg",
    "friend_removed.ogg",
    "friend_request_received.ogg",
    "friend_request_sent.ogg",
    "gamewin.ogg",
    "join_spectator.ogg",
    "kick.ogg",
    "leave_spectator.ogg",
    "lsmack.ogg",
    "mention.ogg",
    "menuclick.ogg",
    "menuenter.ogg",
    "moderation_report.ogg",
    "notify1.ogg",
    "notify2.ogg",
    "notify3.ogg",
    "notify4.ogg",
    "offline.ogg",
    "offlineadmin.ogg",
    "offlinedev.ogg",
    "offlinefriend.ogg",
    "online.ogg",
    "onlineadmin.ogg",
    "onlinedev.ogg",
    "onlinefriend.ogg",
    "open.ogg",
    "pm.ogg",
    "ranked.ogg",
    "reconnect.ogg",
    "server_alert_shutdown.ogg",
    "server_alert_tick.ogg",
    "server_alert_warning.ogg",
    "table_created.ogg",
    "table_invite.ogg",
    "table_join.ogg",
    "table_kick.ogg",
    "table_leave.ogg",
    "turn.ogg",
    "update_alert.ogg",
    "update_complete.ogg",
    "voice_join.ogg",
    "voice_leave.ogg",
    "voice_mic_error.ogg",
    "voice_mic_off.ogg",
    "voice_mic_on.ogg",
    "welcome.ogg",
])
