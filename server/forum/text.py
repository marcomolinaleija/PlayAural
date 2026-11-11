"""Plain-text validation and accessible reading, without HTML rendering."""

import unicodedata

from .models import ForumError, MAX_BODY_LENGTH, MAX_SEARCH_LENGTH, MAX_TITLE_LENGTH


def search_key(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def validate_text(value: object, *, title: bool = False) -> str:
    limit = MAX_TITLE_LENGTH if title else MAX_BODY_LENGTH
    if not isinstance(value, str) or len(value) > limit:
        raise ForumError("forum-error-title-length" if title else "forum-error-body-length", limit=limit)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    # Keep letters in every language, ZWJ emoji, and ordinary line breaks.
    # Reject embedded controls and bidi overrides that can disguise actions.
    if any(unicodedata.category(c) == "Cc" and c not in "\n\t" or c in "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069" for c in value):
        raise ForumError("forum-error-text-controls")
    value = value.strip()
    if title:
        value = " ".join(value.split())
    if not value:
        raise ForumError("forum-error-title-empty" if title else "forum-error-body-empty")
    return value


def validate_search(value: object) -> str:
    if not isinstance(value, str) or not 2 <= len(value.strip()) <= MAX_SEARCH_LENGTH:
        raise ForumError("forum-error-search", limit=MAX_SEARCH_LENGTH)
    return value.strip()


def reading_chunks(body: str, limit: int = 500) -> list[str]:
    """Bound reading rows even when a message contains thousands of lines."""
    chunks = []
    remaining = body.strip()
    while remaining:
        end = min(len(remaining), limit)
        if end < len(remaining):
            boundary = max(remaining.rfind("\n", 0, end), remaining.rfind(" ", 0, end))
            if boundary > limit // 2:
                end = boundary
        chunks.append(remaining[:end])
        remaining = remaining[end:].lstrip()
    return chunks


def excerpt(body: str, limit: int = 160) -> str:
    text = " ".join(body.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"
