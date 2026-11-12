# General thread polls and compact editing

One independent general poll may belong to a public or private thread. It is
displayed as an actionable first row on every message page, including after
closure. Missing or inaccessible polls add no placeholder. Ordinary message
polls remain attached to their posts and are not promoted or migrated.

## Storage and rules

Schema 12 adds `forum_thread_polls`, `forum_thread_poll_options` and
`forum_thread_poll_votes`. The thread id is the unique poll key; no synthetic
post, extra message count, read position or private-message notification is
created. Existing message-poll tables and votes stay intact. Central startup
backup/migration/validation owns creation, rollback and source-version support.

Both scopes use PollService with identifiers selected from a fixed constructor
map. Ballots, maximum options, deadlines, hidden-result policy, fixed/changeable
votes and permanent first-vote freeze share one implementation. Compound foreign
keys bind option ids to their own poll, and account/topic cascades own cleanup.
Deleting voters never resets `started`; author deletion anonymizes general polls.

Creation requires a public thread's author or staff, or a private thread's current
owner. Existing account/mute/closed-thread gates apply. Reads and writes recheck
private membership and bilateral blocks, including the poll author's visibility.
The author or current thread moderator may edit an open, never-voted general
poll. A revision check prevents lost edits; voting and closure are authoritative
inside the same immediate transaction. Closure is explicit and confirmed.

## Editing and navigation

Each poll field is one editable label/value row. Question/options are not
repeated as preview-only rows plus separate commands. Options keep a bounded
menu excerpt but open all values in the existing multiline input. Message
composers show one actionable Poll row instead of separate answer previews.

Creating a general poll uses the same editor, with an explicit publish action;
editing uses an explicit save action. The original config and revision remain
bounded session state. Input cancellation, drafts, game return context and
focus use existing navigation helpers. Back asks for discard confirmation only
when a standalone general poll has unsaved changes. Existing exact deadlines
are displayed as localized UTC timestamps and are not extended by opening or
saving other fields.

Poll menu state carries a server-owned scope and target id, keeping message ids
separate from thread ids even when integer values overlap. No new protocol,
client dependencies or mobile implementation is needed. Spanish, English and
Vietnamese manuals and all seven forum UI languages describe the new behavior.

## Removal and discovery

Both published poll scopes offer Delete poll to the poll's author or the current
thread moderator. This includes closed polls, polls with existing votes, expired
polls and polls in closed threads; the 30-minute post-edit window does not apply.
Private membership and current ownership remain authoritative: global staff
privileges never grant private moderation. Account, mute, block and visibility
rules are rechecked in the immediate deletion transaction.

Confirmation identifies the question and warns that options and all votes will
be removed. The server stores the ordered option ids in its confirmation frame;
AUTOINCREMENT ids change on editing or recreating a poll, so a stale confirmation
cannot delete its replacement, even at the same target id and timestamp. A later
vote on the confirmed poll is included in the deletion. Existing cascades remove
only that poll's options/ballots. Posts, thread metadata, read positions and the
other poll scope are unaffected. No schema migration is needed.

After deletion, navigation skips the deleted ballot and restores the thread or
post actions without losing earlier drafts/game context. Cancel/Escape returns
to the ballot. A deleted general poll can be replaced through the existing
Create thread poll action when the thread is open and creation rights allow it.

Post queries compute `has_poll` with EXISTS in the same query, avoiding per-row
poll lookups. Hidden posts suppress the flag. Message rows and complete spoken
reading announce Contains a poll; optional read-only text includes that notice
in its prompt while preserving the original body for copying. Reply actions use
Reply to thread, including the message context menu. These changes use only
shared server menus/speech, without new client code or native mobile work.

Subsequent content navigation makes Enter open a message poll directly when it
is the only resource, or list it alongside attachments in a compact chooser.
Right always reads the full post. See `forum-post-navigation.md` for the current
resource and description behavior.

`test_forum_poll_management.py` verifies deletion/cascades and preserved content,
authority and revocation, cancellation/return frames, stale confirmations,
discovery and hidden-post suppression, and desktop/web WebSocket round trips.

## Original delivery validation

Poll-management follow-up validation: all 44 new focused tests pass; full server
suite 5,416 passed and 15 skipped. All 56 relevant labels (including the explicit
thread-reply action) parse and format in the seven forum languages. The maximum
64,000-character speech test keeps the body outside Fluent interpolation limits.

The following figures describe the earlier general-poll delivery:

- 11 new tests cover compact editable fields, multiline values, both poll
  scopes, per-page pinning, permissions/blocks, revision conflicts, vote freeze,
  deadlines/closure, deletion, discard behavior, migration rollback/backups and
  real desktop/web WebSocket creation and voting.
- Full server: 5,355 passed, 15 skipped. Desktop: 338 passed. Web: 92 passed.
- All 63 new labels parse and format in the seven forum languages.
- A copy of the local schema-11 test database migrated to 12 with all 39 existing
  tables' row counts preserved and clean integrity/foreign-key checks.
- The latest develop audio change required updating its localization test's
  simulated window and binding the existing chat-category helper. That isolated
  fixture correction is committed separately; audio behavior is unchanged here.
