# Forum messages up to 64,000 characters

`MAX_BODY_LENGTH` is **64,000** (decimal characters). The same policy applies to
the first message of a topic, replies, edits and private-conversation posts.
Titles remain limited to 120 characters. English, Spanish and Vietnamese prompts
and help reflect the new limit.

The existing shared editor packet supplies `max_length = 64000`; desktop and web
already consume it. Drafts and edit defaults retain the full text, while composer
rows still contain a short excerpt. Full messages open in a read-only multiline
reader. Report evidence uses the same body constant, so a report retains
the complete message instead of truncating it. No native mobile work is needed.

## Schema 10 migration

The old SQLite post CHECK constraint capped stored text at 8,000. Schema **10**
rebuilds only `forum_posts`, copying explicitly named columns and preserving the
autoincrement high-water mark, including deleted ids. The normal schema builder
recreates the two post indexes. Posts keep their ids and metadata; polls, votes,
attachments, moderation events, bookmarks, reading positions, private membership,
language choices and reports retain their original relations and snapshots.

The central startup migration validates the source schema and creates its normal
verified backup before mutation. For an existing pre-10 post table, it disables
foreign-key enforcement **before** opening its immediate transaction, creates
the replacement table, copies rows, drops the old table and renames the new one
to the original name. This avoids cascades or SET NULL changes on inbound links.
It validates the complete canonical schema and performs SQLite integrity and
foreign-key checks before commit. A `finally` block restores and verifies FK
enforcement after success or rollback. Startup has not admitted any sessions.

Legacy canonical contracts still use their original 8,000-character constraint;
new databases start directly with the expanded CHECK. No writable-schema edits,
content truncation or changes to file storage are involved. SQLite syntax stays
within the existing 3.25 baseline.

## Verification

`server/tests/test_forum_long_posts.py` exercises a genuine schema-9 database with
public/private posts, a linked attachment, a poll and ballot, moderation events,
bookmarks/read positions, a language preference and a report. Migration preserves
every row and permits the next post id after a retained high-water mark. Tests
also inject a failure after rebuilding and a broken foreign key; both roll back
to schema 9 and reuse the verified backup on retry.

Boundary checks accept exactly 64,000 characters and reject 64,001 in the service
and SQL CHECK. Actual WebSocket `python`/`web` flows send 64,000 supplementary
Unicode characters, read the full message and reopen its full edit default.
The larger escaped JSON payload stays within the existing WebSocket frame limit.
Compact-field tests cover full multiline drafts and cancellation at the new cap.

Validation on 2026-11-11: **5,292 server tests passed, 15 skipped** (`-n 2`).
The focused migration/database/language suites passed **82 tests**, including
rollback and foreign-key violation recovery. No client build or emulator was
required; native mobile work remains paused.
