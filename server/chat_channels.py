"""Data-driven global-chat language channel registry."""

from dataclasses import dataclass


MAX_CHAT_MESSAGE_LENGTH = 8000
CHAT_REPLY_QUOTE_LIMIT = 2000
CHAT_REPLY_SENDER_LIMIT = 30


def normalize_chat_reply(value: object) -> tuple[dict[str, str] | None, str | None]:
    """Return a bounded reply snapshot, or an error key when the field is unusable.

    A missing field is a normal chat message. The quote is display context and
    is not part of the message body that throttles and logs already bound.
    """
    if value is None:
        return None, None
    if not isinstance(value, dict):
        return None, "chat-reply-invalid"
    sender = value.get("sender")
    message = value.get("message")
    if not isinstance(sender, str) or not isinstance(message, str):
        return None, "chat-reply-invalid"
    sender = sender.strip()
    message = message.strip()
    if (
        not sender
        or len(sender) > CHAT_REPLY_SENDER_LIMIT
        or any(ord(character) < 32 for character in sender)
        or not message
    ):
        return None, "chat-reply-invalid"
    return {"sender": sender, "message": message[:CHAT_REPLY_QUOTE_LIMIT]}, None


@dataclass(frozen=True, slots=True)
class GlobalChatChannel:
    """One selectable language partition for global chat."""

    code: str


# Stable BCP 47 base-language identifiers. Display names are resolved through
# the localization layer, so adding a channel does not require client changes
# or language-specific branches in chat delivery.
GLOBAL_CHAT_CHANNELS: tuple[GlobalChatChannel, ...] = tuple(
    GlobalChatChannel(code)
    for code in (
        "en",
        "es",
        "pt",
        "vi",
        "zh",
        "hi",
        "ar",
        "bn",
        "fr",
        "de",
        "id",
        "ja",
        "ko",
        "ru",
        "tr",
        "uk",
        "fa",
        "ur",
        "it",
        "th",
    )
)
GLOBAL_CHAT_CHANNEL_CODES = frozenset(
    channel.code for channel in GLOBAL_CHAT_CHANNELS
)


def normalize_global_chat_channel(value: object) -> str | None:
    """Return one supported base-language code, or no selection."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower().replace("_", "-").split("-", 1)[0]
    return normalized if normalized in GLOBAL_CHAT_CHANNEL_CODES else None


def recommended_global_chat_channel(locale: object) -> str | None:
    """Return the channel matching an installed UI locale when available."""
    return normalize_global_chat_channel(locale)


def ordered_global_chat_channels(locale: object) -> tuple[GlobalChatChannel, ...]:
    """Place the current UI language first without changing registry order."""
    recommended = recommended_global_chat_channel(locale)
    if recommended is None:
        return GLOBAL_CHAT_CHANNELS
    return tuple(
        sorted(
            GLOBAL_CHAT_CHANNELS,
            key=lambda channel: channel.code != recommended,
        )
    )
