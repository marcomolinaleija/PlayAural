"""Forum schema owned by the central, backed-up SQLite migration lifecycle."""

import sqlite3

from .models import DEFAULT_CATEGORIES
from . import schema_v5


CHECK_CONSTRAINTS = {
    **schema_v5.CHECK_CONSTRAINTS,
    "forum_topics": (
        "CHECK (length(title) BETWEEN 1 AND 120)",
        "CHECK (pinned IN (0, 1))", "CHECK (closed IN (0, 1))",
    ),
    "forum_posts": (
        "CHECK (length(body) BETWEEN 1 AND 8000)",
        "CHECK (revision >= 0)", "CHECK (hidden IN (0, 1))",
    ),
    "forum_read_positions": ("CHECK (last_post_id >= 0)",),
    "forum_moderation_events": (
        "CHECK (action IN ('closed', 'pinned', 'hidden'))", "CHECK (enabled IN (0, 1))",
    ),
}


def create_schema(cursor: sqlite3.Cursor, *, version: int = 5) -> None:
    # Statements run in Database's migration transaction, never executescript
    # (which would implicitly commit its caller's transaction).
    statements = (
        """CREATE TABLE IF NOT EXISTS forum_categories (
            id TEXT PRIMARY KEY NOT NULL,
            position INTEGER NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS forum_topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id TEXT NOT NULL REFERENCES forum_categories(id),
            author_uuid TEXT REFERENCES users(uuid) ON DELETE SET NULL,
            author_name TEXT NOT NULL,
            title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 120),
            title_search TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            pinned INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1)),
            closed INTEGER NOT NULL DEFAULT 0 CHECK (closed IN (0, 1))
        )""",
        """CREATE TABLE IF NOT EXISTS forum_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL REFERENCES forum_topics(id) ON DELETE CASCADE,
            author_uuid TEXT REFERENCES users(uuid) ON DELETE SET NULL,
            author_name TEXT NOT NULL,
            body TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 8000),
            body_search TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            edited_at INTEGER,
            revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
            hidden INTEGER NOT NULL DEFAULT 0 CHECK (hidden IN (0, 1))
        )""",
        """CREATE TABLE IF NOT EXISTS forum_read_positions (
            user_uuid TEXT NOT NULL REFERENCES users(uuid) ON DELETE CASCADE,
            topic_id INTEGER NOT NULL REFERENCES forum_topics(id) ON DELETE CASCADE,
            last_post_id INTEGER NOT NULL DEFAULT 0 CHECK (last_post_id >= 0),
            PRIMARY KEY (user_uuid, topic_id)
        )""",
        """CREATE TABLE IF NOT EXISTS forum_bookmarks (
            user_uuid TEXT NOT NULL REFERENCES users(uuid) ON DELETE CASCADE,
            topic_id INTEGER NOT NULL REFERENCES forum_topics(id) ON DELETE CASCADE,
            PRIMARY KEY (user_uuid, topic_id)
        )""",
        """CREATE TABLE IF NOT EXISTS forum_moderation_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL REFERENCES forum_topics(id) ON DELETE CASCADE,
            post_id INTEGER REFERENCES forum_posts(id) ON DELETE CASCADE,
            actor_uuid TEXT REFERENCES users(uuid) ON DELETE SET NULL,
            action TEXT NOT NULL CHECK (action IN ('closed', 'pinned', 'hidden')),
            enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
            created_at INTEGER NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_forum_topics_category ON forum_topics(category_id, pinned DESC, id DESC)",
        "CREATE INDEX IF NOT EXISTS idx_forum_posts_topic ON forum_posts(topic_id, id)",
        "CREATE INDEX IF NOT EXISTS idx_forum_posts_author_time ON forum_posts(author_uuid, created_at DESC)",
    )
    for statement in statements:
        cursor.execute(statement)
    for position, category in enumerate(DEFAULT_CATEGORIES):
        cursor.execute(
            "INSERT OR IGNORE INTO forum_categories(id, position) VALUES (?, ?)",
            (category, position),
        )
    if version >= 5:
        schema_v5.create_schema(cursor)


def erase_account(cursor: sqlite3.Cursor, user_uuid: str) -> None:
    """Retain public discussions, erase attribution and personal reading data."""
    schema_v5.erase_private_account(cursor, user_uuid)
    for table in ("forum_topics", "forum_posts"):
        cursor.execute(
            f"UPDATE {table} SET author_uuid = NULL, author_name = '' WHERE author_uuid = ?",
            (user_uuid,),
        )
    for table in ("forum_bookmarks", "forum_read_positions"):
        cursor.execute(f"DELETE FROM {table} WHERE user_uuid = ?", (user_uuid,))
    cursor.execute("UPDATE forum_moderation_events SET actor_uuid = NULL WHERE actor_uuid = ?", (user_uuid,))
