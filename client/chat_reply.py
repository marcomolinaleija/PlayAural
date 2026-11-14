"""Reply targets for a focused chat message.

The quoted text is clipped to 2,000 characters when the reply is sent. The
channel stays the one the focused message used, so a table quote is not
republished as global chat.
"""

from __future__ import annotations

from typing import Any

REPLY_QUOTE_LIMIT = 2000
_PRIVATE_SPEAK_KEYS = {
    "pm-received",
    "pm-sent-content",
    "pm-received-reply",
    "pm-sent-content-reply",
}


def clip_quote(message: str) -> str:
    """Return the quoted message body, bounded for the reply announcement."""
    text = message.strip()
    if len(text) <= REPLY_QUOTE_LIMIT:
        return text
    return text[:REPLY_QUOTE_LIMIT]


def metadata_from_chat_packet(packet: dict[str, Any]) -> dict[str, str] | None:
    """Return reply metadata for a chat packet, or None when it is not chat."""
    convo = packet.get("convo")
    sender = packet.get("sender")
    message = packet.get("message")
    if convo == "global":
        destination = "global"
    elif convo == "private":
        destination = "private"
    elif convo in {"local", "table", "game"}:
        destination = "table"
    else:
        return None
    if not isinstance(sender, str) or not isinstance(message, str):
        return None
    sender = sender.strip()
    if not sender or not message.strip():
        return None
    return {"kind": "chat", "convo": destination, "sender": sender, "message": message}


def metadata_from_speak_packet(packet: dict[str, Any]) -> dict[str, str] | None:
    """Return reply metadata for a private-message announcement."""
    if packet.get("key") not in _PRIVATE_SPEAK_KEYS:
        return None
    params = packet.get("params")
    if not isinstance(params, dict):
        return None
    sender = params.get("username")
    message = params.get("message")
    if not isinstance(sender, str) or not isinstance(message, str):
        return None
    sender = sender.strip()
    if not sender or not message.strip():
        return None
    return {"kind": "chat", "convo": "private", "sender": sender, "message": message}


def reply_format_key(convo: str) -> str:
    """Return the history line used when a message answers another."""
    if convo == "global":
        return "chat-global-reply"
    if convo == "private":
        return "chat-private-reply"
    return "chat-local-reply"


def reply_channel_key(convo: str) -> str:
    """Return the short channel name spoken when a reply starts."""
    if convo == "global":
        return "chat-reply-channel-global"
    if convo == "private":
        return "chat-reply-channel-private"
    return "chat-reply-channel-table"


def chat_alert_sound(convo: str) -> str | None:
    """Return the earcon for a chat packet.

    Local, table, and game chat are the same table channel. They share the
    table earcon so an explicit table reply does not sound like global chat.
    Announcements use the notify family instead of one asset.
    """
    if convo == "announcement":
        return None
    if convo == "private":
        return "pm.ogg"
    if convo in {"local", "table", "game"}:
        return "chatlocal.ogg"
    return "chat.ogg"


def outgoing_chat_packet(message: str, reply: dict[str, str] | None) -> dict[str, Any]:
    """Build the chat packet for a plain message or an active reply."""
    text = message.strip()
    if not reply:
        return {"type": "chat", "convo": "local", "message": text}
    sender = str(reply.get("sender") or "").strip()
    quote = clip_quote(str(reply.get("message") or ""))
    convo = reply.get("convo")
    if convo == "private" and sender:
        packet: dict[str, Any] = {
            "type": "chat",
            "convo": "local",
            "message": f"@{sender} {text}",
        }
    elif convo == "global":
        packet = {"type": "chat", "convo": "global", "message": text}
    else:
        # Explicit table delivery. Local chat would become global after leaving.
        packet = {"type": "chat", "convo": "table", "message": text}
    if sender and quote:
        packet["reply_to"] = {"sender": sender, "message": quote}
    return packet
