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

## Validation

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
