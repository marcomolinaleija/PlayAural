"""Translation schemas, installed through the central backed-up lifecycle."""

import sqlite3

CHECK_CONSTRAINTS = {
    'translation_languages': ("CHECK (status IN ('proposed', 'approved'))", "CHECK (revision >= 0)"),
    'translation_proposals': (
        "CHECK (status IN ('draft', 'pending', 'changes_requested', 'approved', 'rejected', 'withdrawn', 'reverted'))",
        "CHECK (revision >= 0)", "CHECK (length(value) <= 64000)",
        "CHECK (length(note) <= 1000)",
        "CHECK (notice_pending IN (0, 1))",
    ),
    'translation_accepted': ("CHECK (revision >= 1)",),
    'translation_reservations': ("CHECK (expires_at >= 0)",),
    'translation_roles': ("CHECK (revision >= 1)", "CHECK (enabled IN (0, 1))"),
}


def create_schema(cursor: sqlite3.Cursor, *, version=14) -> None:
    cursor.execute('''CREATE TABLE IF NOT EXISTS translation_languages (
        code TEXT PRIMARY KEY, name TEXT NOT NULL, native_name TEXT NOT NULL,
        creator_uuid TEXT REFERENCES users(uuid) ON DELETE SET NULL,
        status TEXT NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'approved')),
        revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0), created_at INTEGER NOT NULL
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS translation_proposals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        author_uuid TEXT REFERENCES users(uuid) ON DELETE SET NULL,
        author_name TEXT NOT NULL, language TEXT NOT NULL, unit_id TEXT NOT NULL,
        source_text TEXT NOT NULL, source_hash TEXT NOT NULL, base_hash TEXT NOT NULL,
        value TEXT NOT NULL CHECK (length(value) <= 64000),
        forms_json TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'draft'
            CHECK (status IN ('draft', 'pending', 'changes_requested', 'approved', 'rejected', 'withdrawn', 'reverted')),
        revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
        note TEXT NOT NULL DEFAULT '' CHECK (length(note) <= 1000),
        notice_pending INTEGER NOT NULL DEFAULT 0 CHECK (notice_pending IN (0, 1)),
        created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
        reviewer_uuid TEXT REFERENCES users(uuid) ON DELETE SET NULL
    )''')
    cursor.execute('''CREATE UNIQUE INDEX IF NOT EXISTS idx_translation_open
        ON translation_proposals(author_uuid, language, unit_id)
        WHERE status IN ('draft', 'pending', 'changes_requested')''')
    cursor.execute('''CREATE INDEX IF NOT EXISTS idx_translation_review
        ON translation_proposals(status, language, updated_at, id)''')
    cursor.execute('''CREATE INDEX IF NOT EXISTS idx_translation_author
        ON translation_proposals(author_uuid, updated_at, id)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS translation_accepted (
        language TEXT NOT NULL, unit_id TEXT NOT NULL, value TEXT NOT NULL,
        source_hash TEXT NOT NULL,
        proposal_id INTEGER REFERENCES translation_proposals(id) ON DELETE SET NULL,
        revision INTEGER NOT NULL CHECK (revision >= 1),
        PRIMARY KEY(language, unit_id)
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS translation_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        proposal_id INTEGER REFERENCES translation_proposals(id) ON DELETE CASCADE,
        actor_uuid TEXT REFERENCES users(uuid) ON DELETE SET NULL,
        action TEXT NOT NULL, value_json TEXT NOT NULL, created_at INTEGER NOT NULL
    )''')
    cursor.execute('''CREATE INDEX IF NOT EXISTS idx_translation_events
        ON translation_events(proposal_id, id)''')
    if version >= 14:
        existed = cursor.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'translation_reservations'").fetchone()
        cursor.execute('''CREATE TABLE IF NOT EXISTS translation_reservations (
            language TEXT NOT NULL, unit_id TEXT NOT NULL,
            proposal_id INTEGER NOT NULL UNIQUE REFERENCES translation_proposals(id) ON DELETE CASCADE,
            owner_uuid TEXT NOT NULL REFERENCES users(uuid) ON DELETE CASCADE,
            expires_at INTEGER NOT NULL CHECK (expires_at >= 0),
            PRIMARY KEY(language, unit_id)
        )''')
        cursor.execute('''CREATE INDEX IF NOT EXISTS idx_translation_reservation_expiry
            ON translation_reservations(expires_at) WHERE expires_at > 0''')
        if not existed:
            # Older versions permitted duplicate pending submissions. Keep all
            # evidence and reserve the oldest; reviewers may still compare them.
            cursor.execute('''INSERT INTO translation_reservations
                SELECT p.language, p.unit_id, p.id, p.author_uuid, 0
                FROM translation_proposals p WHERE p.status = 'pending' AND p.author_uuid IS NOT NULL
                AND p.id = (SELECT MIN(other.id) FROM translation_proposals other
                    WHERE other.language = p.language AND other.unit_id = p.unit_id
                    AND other.status = 'pending' AND other.author_uuid IS NOT NULL)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS translation_roles (
            user_uuid TEXT NOT NULL REFERENCES users(uuid) ON DELETE CASCADE,
            language TEXT NOT NULL, revision INTEGER NOT NULL CHECK (revision >= 1),
            enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
            granted_by TEXT REFERENCES users(uuid) ON DELETE SET NULL,
            granted_at INTEGER NOT NULL, PRIMARY KEY(user_uuid, language)
        )''')


def erase_account(cursor: sqlite3.Cursor, user_uuid: str) -> None:
    cursor.execute("DELETE FROM translation_proposals WHERE author_uuid = ? AND status IN ('draft', 'pending', 'changes_requested')", (user_uuid,))
    cursor.execute("UPDATE translation_proposals SET author_name = '' WHERE author_uuid = ?", (user_uuid,))
