"""Persistent forum mentions, pending notices and account-owned alert settings."""

CHECK_CONSTRAINTS = {
    'forum_mentions': ('CHECK (active IN (0, 1))',),
    'forum_notifications': ("CHECK (kind IN ('private', 'mention'))", 'CHECK (announced IN (0, 1))'),
    'forum_notification_settings': ('CHECK (private_alerts IN (0, 1))', 'CHECK (mention_alerts IN (0, 1))'),
}


def create_schema(cursor):
    for statement in (
        '''CREATE TABLE IF NOT EXISTS forum_mentions (
            post_id INTEGER NOT NULL REFERENCES forum_posts(id) ON DELETE CASCADE,
            user_uuid TEXT NOT NULL REFERENCES users(uuid) ON DELETE CASCADE,
            active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
            PRIMARY KEY (post_id, user_uuid)
        )''',
        '''CREATE TABLE IF NOT EXISTS forum_notifications (
            user_uuid TEXT NOT NULL REFERENCES users(uuid) ON DELETE CASCADE,
            post_id INTEGER NOT NULL REFERENCES forum_posts(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK (kind IN ('private', 'mention')),
            announced INTEGER NOT NULL DEFAULT 0 CHECK (announced IN (0, 1)),
            created_at INTEGER NOT NULL,
            PRIMARY KEY (user_uuid, post_id)
        )''',
        '''CREATE TABLE IF NOT EXISTS forum_notification_settings (
            user_uuid TEXT PRIMARY KEY NOT NULL REFERENCES users(uuid) ON DELETE CASCADE,
            private_alerts INTEGER NOT NULL DEFAULT 1 CHECK (private_alerts IN (0, 1)),
            mention_alerts INTEGER NOT NULL DEFAULT 1 CHECK (mention_alerts IN (0, 1))
        )''',
        '''CREATE TABLE IF NOT EXISTS forum_muted_topics (
            user_uuid TEXT NOT NULL REFERENCES users(uuid) ON DELETE CASCADE,
            topic_id INTEGER NOT NULL REFERENCES forum_topics(id) ON DELETE CASCADE,
            PRIMARY KEY (user_uuid, topic_id)
        )''',
        'CREATE INDEX IF NOT EXISTS idx_forum_notifications_post ON forum_notifications(post_id)',
        'CREATE INDEX IF NOT EXISTS idx_forum_notifications_time ON forum_notifications(created_at)',
    ):
        cursor.execute(statement)
