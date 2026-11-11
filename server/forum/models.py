"""Transport-independent forum records and bounded feature policies."""

from dataclasses import dataclass, field
from uuid import uuid4


TOPICS_PER_PAGE = 15
POSTS_PER_PAGE = 8
MAX_TITLE_LENGTH = 120
MAX_BODY_LENGTH = 8000
MAX_SEARCH_LENGTH = 100
EDIT_WINDOW_SECONDS = 30 * 60
WRITE_WINDOW_SECONDS = 60
MAX_WRITES_PER_WINDOW = 6
DEFAULT_CATEGORIES = ("general", "help", "ideas")
PRIVATE_CATEGORY_ID = "__private__"
MAX_CATEGORIES = 64
MAX_CATEGORY_NAME_LENGTH = 80
MAX_CATEGORY_DESCRIPTION_LENGTH = 500


class ForumError(ValueError):
    """An expected user-facing failure, identified by a Fluent key."""

    def __init__(self, key: str, **values):
        super().__init__(key)
        self.key = key
        self.values = values


@dataclass(frozen=True)
class Category:
    id: str
    topic_count: int
    name: str = ""
    description: str = ""
    revision: int = 0
    language: str = 'es'


@dataclass(frozen=True)
class Topic:
    id: int
    category_id: str
    title: str
    author_uuid: str | None
    author_name: str
    created_at: int
    pinned: bool
    closed: bool
    post_count: int
    unread_count: int
    last_post_id: int
    last_activity: int
    bookmarked: bool
    is_private: bool = False


@dataclass(frozen=True)
class Post:
    id: int
    topic_id: int
    author_uuid: str | None
    author_name: str
    body: str
    created_at: int
    edited_at: int | None
    revision: int
    hidden: bool


@dataclass(frozen=True)
class Draft:
    """A bounded, session-owned draft; never written to account preferences."""

    kind: str
    category_id: str = ""
    topic_id: int = 0
    post_id: int = 0
    revision: int = 0
    title: str = ""
    body: str = ""
    poll: dict | None = None
    recipients: tuple[str, ...] = ()
    attachment_ids: tuple[str, ...] = ()
    token: str = field(default_factory=lambda: str(uuid4()))
