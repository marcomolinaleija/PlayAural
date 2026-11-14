"""Rebuild only the post table, retaining ids and all inbound foreign keys."""

import sqlite3

from .models import MAX_BODY_LENGTH


def posts_ddl(table: str, limit: int) -> str:
    # Identifiers are internal constants, never request data.
    if table not in {'forum_posts', '__forum_posts_v10'}:
        raise ValueError('Invalid post migration table')
    return f'''CREATE TABLE IF NOT EXISTS {table} (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic_id INTEGER NOT NULL REFERENCES forum_topics(id) ON DELETE CASCADE,
        author_uuid TEXT REFERENCES users(uuid) ON DELETE SET NULL,
        author_name TEXT NOT NULL,
        body TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND {limit}),
        body_search TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        edited_at INTEGER,
        revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
        hidden INTEGER NOT NULL DEFAULT 0 CHECK (hidden IN (0, 1))
    )'''


def expand_posts(cursor: sqlite3.Cursor) -> None:
    """The central startup migration owns the FK-off transaction and checks."""
    if cursor.execute('PRAGMA foreign_keys').fetchone()[0]:
        raise sqlite3.DatabaseError('Post migration requires foreign keys disabled before BEGIN')
    sequence = cursor.execute("SELECT seq FROM sqlite_sequence WHERE name = 'forum_posts'").fetchone()
    sequence = int(sequence[0]) if sequence else 0
    if cursor.execute("SELECT 1 FROM sqlite_master WHERE name = '__forum_posts_v10'").fetchone():
        raise sqlite3.DatabaseError('Reserved post migration table already exists')
    cursor.execute(posts_ddl('__forum_posts_v10', MAX_BODY_LENGTH))
    columns = ('id, topic_id, author_uuid, author_name, body, body_search, created_at, '
               'edited_at, revision, hidden')
    cursor.execute(f'INSERT INTO __forum_posts_v10 ({columns}) SELECT {columns} FROM forum_posts')
    # Keeping the old name on inbound references avoids cascading poll/vote
    # deletion, SET NULL on files/audits and foreign-key target rewriting.
    cursor.execute('DROP TABLE forum_posts')
    cursor.execute('ALTER TABLE __forum_posts_v10 RENAME TO forum_posts')
    cursor.execute("DELETE FROM sqlite_sequence WHERE name = 'forum_posts'")
    cursor.execute("INSERT INTO sqlite_sequence(name, seq) VALUES ('forum_posts', ?)", (sequence,))
