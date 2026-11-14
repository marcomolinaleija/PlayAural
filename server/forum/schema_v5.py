"""Private conversations, polls and private object metadata (schema v5)."""

CHECK_CONSTRAINTS = {
    "forum_private_invites": (
        "CHECK (status IN ('pending', 'accepted', 'declined', 'revoked'))",
    ),
    "forum_polls": (
        "CHECK (length(question) BETWEEN 1 AND 240)",
        "CHECK (multiple IN (0, 1))", "CHECK (change_vote IN (0, 1))",
        "CHECK (results IN ('always', 'after_vote', 'after_close'))",
        "CHECK (closed IN (0, 1))",
        "CHECK (started IN (0, 1))",
    ),
    "forum_poll_options": ("CHECK (length(label) BETWEEN 1 AND 160)",),
    "forum_attachments": (
        "CHECK (state IN ('uploading', 'processing', 'ready', 'failed', 'retired'))",
        "CHECK (approval IN ('unsubmitted', 'pending', 'approved', 'rejected'))",
        "CHECK (kind IN ('image', 'audio', 'video', 'file'))",
        "CHECK (size >= 0)", "CHECK (published IN (0, 1))",
        "CHECK (length(description) <= 1000)",
        "CHECK (private IN (0, 1))",
    ),
    'forum_attachment_reviews': ("CHECK (decision IN ('approved', 'rejected'))",),
}


def create_schema(cursor) -> None:
    statements = (
        """CREATE TABLE IF NOT EXISTS forum_private_topics (
            topic_id INTEGER PRIMARY KEY REFERENCES forum_topics(id) ON DELETE CASCADE,
            owner_uuid TEXT REFERENCES users(uuid) ON DELETE SET NULL
        )""",
        """CREATE TABLE IF NOT EXISTS forum_private_members (
            topic_id INTEGER NOT NULL REFERENCES forum_private_topics(topic_id) ON DELETE CASCADE,
            user_uuid TEXT NOT NULL REFERENCES users(uuid) ON DELETE CASCADE,
            joined_at INTEGER NOT NULL,
            PRIMARY KEY (topic_id, user_uuid)
        )""",
        """CREATE TABLE IF NOT EXISTS forum_private_invites (
            id TEXT PRIMARY KEY NOT NULL,
            topic_id INTEGER NOT NULL REFERENCES forum_private_topics(topic_id) ON DELETE CASCADE,
            inviter_uuid TEXT REFERENCES users(uuid) ON DELETE SET NULL,
            invited_uuid TEXT NOT NULL REFERENCES users(uuid) ON DELETE CASCADE,
            status TEXT NOT NULL CHECK (status IN ('pending', 'accepted', 'declined', 'revoked')),
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS forum_polls (
            post_id INTEGER PRIMARY KEY REFERENCES forum_posts(id) ON DELETE CASCADE,
            question TEXT NOT NULL CHECK (length(question) BETWEEN 1 AND 240),
            multiple INTEGER NOT NULL DEFAULT 0 CHECK (multiple IN (0, 1)),
            change_vote INTEGER NOT NULL DEFAULT 1 CHECK (change_vote IN (0, 1)),
            results TEXT NOT NULL DEFAULT 'after_vote' CHECK (results IN ('always', 'after_vote', 'after_close')),
            closes_at INTEGER,
            closed INTEGER NOT NULL DEFAULT 0 CHECK (closed IN (0, 1)),
            started INTEGER NOT NULL DEFAULT 0 CHECK (started IN (0, 1)),
            created_at INTEGER NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS forum_poll_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_id INTEGER NOT NULL REFERENCES forum_polls(post_id) ON DELETE CASCADE,
            position INTEGER NOT NULL,
            label TEXT NOT NULL CHECK (length(label) BETWEEN 1 AND 160),
            UNIQUE (id, post_id),
            UNIQUE (post_id, position)
        )""",
        """CREATE TABLE IF NOT EXISTS forum_poll_votes (
            post_id INTEGER NOT NULL,
            option_id INTEGER NOT NULL,
            user_uuid TEXT NOT NULL REFERENCES users(uuid) ON DELETE CASCADE,
            created_at INTEGER NOT NULL,
            PRIMARY KEY (post_id, user_uuid, option_id),
            FOREIGN KEY (option_id, post_id) REFERENCES forum_poll_options(id, post_id) ON DELETE CASCADE
        )""",
        """CREATE TABLE IF NOT EXISTS forum_attachments (
            id TEXT PRIMARY KEY NOT NULL,
            owner_uuid TEXT REFERENCES users(uuid) ON DELETE SET NULL,
            post_id INTEGER REFERENCES forum_posts(id) ON DELETE SET NULL,
            context_topic_id INTEGER REFERENCES forum_topics(id) ON DELETE SET NULL,
            private INTEGER NOT NULL DEFAULT 0 CHECK (private IN (0, 1)),
            published INTEGER NOT NULL DEFAULT 0 CHECK (published IN (0, 1)),
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '' CHECK (length(description) <= 1000),
            state TEXT NOT NULL CHECK (state IN ('uploading', 'processing', 'ready', 'failed', 'retired')),
            approval TEXT NOT NULL CHECK (approval IN ('unsubmitted', 'pending', 'approved', 'rejected')),
            kind TEXT NOT NULL CHECK (kind IN ('image', 'audio', 'video', 'file')),
            mime TEXT NOT NULL,
            size INTEGER NOT NULL DEFAULT 0 CHECK (size >= 0),
            sha256 TEXT NOT NULL DEFAULT '',
            object_key TEXT NOT NULL,
            thumbnail_key TEXT NOT NULL DEFAULT '',
            captions_key TEXT NOT NULL DEFAULT '',
            duration REAL,
            width INTEGER,
            height INTEGER,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS forum_attachment_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attachment_id TEXT NOT NULL REFERENCES forum_attachments(id) ON DELETE CASCADE,
            actor_uuid TEXT REFERENCES users(uuid) ON DELETE SET NULL,
            decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
            created_at INTEGER NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_forum_private_members_user ON forum_private_members(user_uuid, topic_id)",
        "CREATE INDEX IF NOT EXISTS idx_forum_private_invites_user ON forum_private_invites(invited_uuid, status, expires_at)",
        "CREATE INDEX IF NOT EXISTS idx_forum_poll_votes_option ON forum_poll_votes(option_id)",
        "CREATE INDEX IF NOT EXISTS idx_forum_attachments_post ON forum_attachments(post_id)",
        "CREATE INDEX IF NOT EXISTS idx_forum_attachments_expiry ON forum_attachments(published, expires_at)",
        "CREATE INDEX IF NOT EXISTS idx_forum_attachments_review ON forum_attachments(approval, private, context_topic_id, created_at)",
    )
    for statement in statements:
        cursor.execute(statement)


def erase_private_account(cursor, user_uuid: str) -> None:
    """Transfer owned groups before deleting membership; never make them public."""
    topics = cursor.execute(
        "SELECT topic_id FROM forum_private_members WHERE user_uuid = ?", (user_uuid,),
    ).fetchall()
    for row in topics:
        topic_id = row[0]
        successor = cursor.execute(
            """SELECT user_uuid FROM forum_private_members WHERE topic_id = ? AND user_uuid != ?
               ORDER BY joined_at, user_uuid LIMIT 1""", (topic_id, user_uuid),
        ).fetchone()
        if successor is None:
            cursor.execute("DELETE FROM forum_topics WHERE id = ?", (topic_id,))
        else:
            cursor.execute(
                "UPDATE forum_private_topics SET owner_uuid = ? WHERE topic_id = ? AND owner_uuid = ?",
                (successor[0], topic_id, user_uuid),
            )
    # Files already published retain their ACL through the post. Unpublished
    # objects become inaccessible and are collected by the expiry worker.
    cursor.execute(
        "UPDATE forum_attachments SET state = 'retired' WHERE owner_uuid = ? AND published = 0", (user_uuid,),
    )
