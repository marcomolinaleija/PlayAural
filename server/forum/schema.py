"""Forum schema owned by the central, backed-up SQLite migration lifecycle."""

import sqlite3

from .models import DEFAULT_CATEGORIES, PRIVATE_CATEGORY_ID
from . import schema_v5
from .languages import FORUM_LANGUAGES, LANGUAGE_CHECK


CHECK_CONSTRAINTS = {
    'forum_language_preferences': (LANGUAGE_CHECK,),
    "forum_report_targets": (
        "CHECK (target_kind IN ('thread', 'post'))",
        "CHECK (target_id > 0)",
        "CHECK (revision >= 0)",
    ),
    **schema_v5.CHECK_CONSTRAINTS,
    "forum_categories": (
        "CHECK (length(name) <= 80)",
        "CHECK (length(description) <= 500)",
        "CHECK (revision >= 0)",
        LANGUAGE_CHECK,
    ),
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


def create_schema(cursor: sqlite3.Cursor, *, version: int = 9) -> None:
    # Statements run in Database's migration transaction, never executescript
    # (which would implicitly commit its caller's transaction).
    categories_existed = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'forum_categories'"
    ).fetchone() is not None
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
    if not categories_existed:
        for position, category in enumerate(DEFAULT_CATEGORIES):
            cursor.execute(
                "INSERT INTO forum_categories(id, position) VALUES (?, ?)",
                (category, position),
            )
    if version >= 5:
        schema_v5.create_schema(cursor)
    if version >= 8:
        # Snapshots survive account/content deletion. Explicit report cleanup
        # owns retention, including the deduplication key.
        cursor.execute('''CREATE TABLE IF NOT EXISTS forum_report_targets (
            report_id INTEGER PRIMARY KEY REFERENCES moderation_reports(id) ON DELETE CASCADE,
            reporter_uuid TEXT NOT NULL,
            target_kind TEXT NOT NULL CHECK (target_kind IN ('thread', 'post')),
            target_id INTEGER NOT NULL CHECK (target_id > 0),
            revision INTEGER NOT NULL CHECK (revision >= 0),
            UNIQUE (reporter_uuid, target_kind, target_id, revision)
        )''')
    if version >= 7:
        columns = {row[1] for row in cursor.execute('PRAGMA table_info(forum_categories)')}
        for name, definition in (
            ('name', "TEXT NOT NULL DEFAULT '' CHECK (length(name) <= 80)"),
            ('description', "TEXT NOT NULL DEFAULT '' CHECK (length(description) <= 500)"),
            ('revision', 'INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0)'),
        ):
            if name not in columns:
                cursor.execute(f'ALTER TABLE forum_categories ADD COLUMN {name} {definition}')
        cursor.execute('INSERT OR IGNORE INTO forum_categories(id, position) VALUES (?, -1)',
                       (PRIVATE_CATEGORY_ID,))
        cursor.execute('''UPDATE forum_topics SET category_id = ?
                          WHERE id IN (SELECT topic_id FROM forum_private_topics)''',
                       (PRIVATE_CATEGORY_ID,))
    if version >= 9:
        columns = {row[1] for row in cursor.execute('PRAGMA table_info(forum_categories)')}
        if 'language' not in columns:
            # Retain all old ids/relations and deleted defaults in Spanish.
            cursor.execute(f"ALTER TABLE forum_categories ADD COLUMN language TEXT NOT NULL DEFAULT 'es' {LANGUAGE_CHECK}")
            for language in FORUM_LANGUAGES:
                if language != 'es':
                    for position, category in enumerate(DEFAULT_CATEGORIES):
                        cursor.execute('''INSERT INTO forum_categories(id, position, language) VALUES (?, ?, ?)''',
                                       (f'{language}:{category}', position, language))
        cursor.execute(f'''CREATE TABLE IF NOT EXISTS forum_language_preferences (
            user_uuid TEXT PRIMARY KEY NOT NULL REFERENCES users(uuid) ON DELETE CASCADE,
            language TEXT NOT NULL {LANGUAGE_CHECK}
        )''')
        cursor.execute('''CREATE INDEX IF NOT EXISTS idx_forum_categories_language
                          ON forum_categories(language, position, id)''')


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
