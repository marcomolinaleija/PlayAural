"""One independent general poll per thread; existing message polls stay intact."""

from .schema_v5 import CHECK_CONSTRAINTS as MESSAGE_CHECKS

CHECK_CONSTRAINTS = {
    'forum_thread_polls': (*MESSAGE_CHECKS['forum_polls'], 'CHECK (revision >= 0)'),
    'forum_thread_poll_options': MESSAGE_CHECKS['forum_poll_options'],
}


def create_schema(cursor):
    for statement in (
        '''CREATE TABLE IF NOT EXISTS forum_thread_polls (
            topic_id INTEGER PRIMARY KEY REFERENCES forum_topics(id) ON DELETE CASCADE,
            author_uuid TEXT REFERENCES users(uuid) ON DELETE SET NULL,
            question TEXT NOT NULL CHECK (length(question) BETWEEN 1 AND 240),
            multiple INTEGER NOT NULL DEFAULT 0 CHECK (multiple IN (0, 1)),
            change_vote INTEGER NOT NULL DEFAULT 1 CHECK (change_vote IN (0, 1)),
            results TEXT NOT NULL DEFAULT 'after_vote' CHECK (results IN ('always', 'after_vote', 'after_close')),
            closes_at INTEGER,
            closed INTEGER NOT NULL DEFAULT 0 CHECK (closed IN (0, 1)),
            started INTEGER NOT NULL DEFAULT 0 CHECK (started IN (0, 1)),
            created_at INTEGER NOT NULL,
            revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0)
        )''',
        '''CREATE TABLE IF NOT EXISTS forum_thread_poll_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL REFERENCES forum_thread_polls(topic_id) ON DELETE CASCADE,
            position INTEGER NOT NULL,
            label TEXT NOT NULL CHECK (length(label) BETWEEN 1 AND 160),
            UNIQUE (id, topic_id), UNIQUE (topic_id, position)
        )''',
        '''CREATE TABLE IF NOT EXISTS forum_thread_poll_votes (
            topic_id INTEGER NOT NULL,
            option_id INTEGER NOT NULL,
            user_uuid TEXT NOT NULL REFERENCES users(uuid) ON DELETE CASCADE,
            created_at INTEGER NOT NULL,
            PRIMARY KEY (topic_id, user_uuid, option_id),
            FOREIGN KEY (option_id, topic_id) REFERENCES forum_thread_poll_options(id, topic_id) ON DELETE CASCADE
        )''',
        'CREATE INDEX IF NOT EXISTS idx_forum_thread_poll_votes_user ON forum_thread_poll_votes(user_uuid)',
    ):
        cursor.execute(statement)
