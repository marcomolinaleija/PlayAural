"""Versioned report constraints and lossless SQLite table migration."""

LEGACY_CHECKS = (
    "CHECK (reporter_uuid != '')",
    "CHECK (reported_uuid != '')",
    "CHECK (reporter_uuid != reported_uuid)",
    "CHECK (status IN ('open', 'reviewed', 'dismissed', 'actioned'))",
    "CHECK (origin_code IN ('manual', 'automated_spam'))",
    "CHECK (context_code IN ('global', 'table'))",
    """CHECK ((origin_code = 'manual' AND context_code = 'global' AND evidence_json IS NULL)
        OR (origin_code = 'automated_spam' AND evidence_json IS NOT NULL AND evidence_json != ''))""",
    """CHECK (context_code != 'table'
        OR (channel_code IS NULL AND context_anchor_message_id IS NULL))""",
    """CHECK (origin_code != 'automated_spam' OR context_code != 'global' OR channel_code IS NOT NULL)""",
)
CURRENT_CHECKS = (
    LEGACY_CHECKS[0],
    "CHECK (reported_uuid != '' OR context_code = 'forum')",
    *LEGACY_CHECKS[2:5],
    "CHECK (context_code IN ('global', 'table', 'forum'))",
    """CHECK ((origin_code = 'manual' AND context_code = 'global' AND evidence_json IS NULL)
        OR (origin_code = 'manual' AND context_code = 'forum' AND evidence_json IS NOT NULL AND evidence_json != '')
        OR (origin_code = 'automated_spam' AND context_code IN ('global', 'table')
            AND evidence_json IS NOT NULL AND evidence_json != ''))""",
    """CHECK (context_code NOT IN ('table', 'forum')
        OR (channel_code IS NULL AND context_anchor_message_id IS NULL))""",
    LEGACY_CHECKS[8],
)


def create_reports_table(cursor, *, forum: bool) -> None:
    checks = ', '.join(CURRENT_CHECKS if forum else LEGACY_CHECKS)
    cursor.execute(f"""CREATE TABLE IF NOT EXISTS moderation_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reporter_uuid TEXT NOT NULL, reporter_username TEXT NOT NULL,
        reported_uuid TEXT NOT NULL, reported_username TEXT NOT NULL,
        reported_at_utc TEXT NOT NULL, reason_code TEXT NOT NULL,
        details TEXT NOT NULL DEFAULT '', channel_code TEXT,
        context_anchor_message_id INTEGER REFERENCES global_chat_messages(id) ON DELETE SET NULL,
        status TEXT NOT NULL DEFAULT 'open', reviewed_by_uuid TEXT,
        reviewed_by_username TEXT, reviewed_at_utc TEXT,
        origin_code TEXT NOT NULL, context_code TEXT NOT NULL, evidence_json TEXT,
        {checks})""")


def migrate_reports_table(cursor) -> None:
    """Called inside the central migration transaction, before index creation."""
    row = cursor.execute("SELECT seq FROM sqlite_sequence WHERE name = 'moderation_reports'").fetchone()
    sequence = row[0] if row else 0
    cursor.execute('ALTER TABLE moderation_reports RENAME TO legacy_moderation_reports')
    create_reports_table(cursor, forum=True)
    # The validated contract permits a different physical column order.
    columns = ('id, reporter_uuid, reporter_username, reported_uuid, reported_username, '
               'reported_at_utc, reason_code, details, channel_code, context_anchor_message_id, '
               'status, reviewed_by_uuid, reviewed_by_username, reviewed_at_utc, '
               'origin_code, context_code, evidence_json')
    cursor.execute(f'INSERT INTO moderation_reports ({columns}) SELECT {columns} FROM legacy_moderation_reports')
    cursor.execute('DROP TABLE legacy_moderation_reports')
    # Preserve deleted high ids too, so an old report reference cannot be reused.
    cursor.execute("DELETE FROM sqlite_sequence WHERE name = 'moderation_reports'")
    cursor.execute("INSERT INTO sqlite_sequence(name, seq) VALUES ('moderation_reports', ?)", (sequence,))
