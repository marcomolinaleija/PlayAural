# Public forum reports

Users can report someone else's public thread or message through the shared
menu protocol. Actions follow content, on desktop and web without client-specific
code. Private conversations are excluded, including for accepted members and
staff. Muted users can still report; approval, active bans, bilateral blocks,
hidden content and current visibility are rechecked at submission.

The compact form holds a required existing moderation reason and optional
details (500 characters). Sending requires a fresh confirmation; No/Back sends
nothing, and reconnect cannot restore consent. If the message revision changes,
the user must reopen the publication before reporting its new version.

## Persistence and review

Schema **8** extends the existing `moderation_reports` table with manual
`context_code = 'forum'` cases. `evidence_json` contains a versioned, immutable
server-generated snapshot: public title, selected message text, topic/post ids,
revision, and author UUID/name. A thread report captures its opening message,
not every reply. Files are not duplicated into evidence; current attachments
remain subject to ordinary authenticated access and their own lifecycle.

`forum_report_targets` uniquely identifies reporter UUID, target kind/id and
revision. A repeat returns an acknowledgement without another case or staff
notification. Different messages and revised versions can be reported
independently. Chat and forum share the five-per-hour reporter quota; the
chat-specific same-account cooldown does not conflate distinct forum messages.

Submission owns one central immediate SQLite transaction. It captures current
public evidence, enforces limits and inserts both rows atomically. The new
context never becomes a valid automated-spam scope. Reports neither hide
content nor apply sanctions, and the author receives no notification.

Staff use the existing Administration → Moderation and sanctions → Chat
moderation queue. Detail shows immutable evidence separately from chat history,
with the existing reviewed/dismissed/actioned statuses. View current publication
uses normal forum availability and access checks. Static evidence remains
reviewable when the forum is disabled.

Snapshots survive source edits, source deletion, and deletion of either account.
Deleted-author public content remains reportable with explicitly absent
attribution (empty target identity and null author UUID, never an invented UUID).
Existing manual closed-report cleanup removes both the case and its dedupe key
through a cascading foreign key. Evidence follows the established report and
historical-backup retention policy, rather than forum account-erasure rules.

## Migration and validation

The central validated migration creates a verified pre-migration backup and
rebuilds report constraints inside its existing transaction. It preserves all
manual and automatic cases, statuses, chat anchors, indexes and the report
autoincrement high-water mark, including deleted ids. A failure rolls back both
the report rebuild and forum extension. Legacy canonical contracts still use
their original report constraints. No SQLite JSON extension is required.

`server/tests/test_forum_reports.py` covers snapshots, shared quotas, revision
conflicts, deduplication, access revocation, accepted private members, deleted
accounts, rollback, explicit cleanup, schema-7 migration and retry, and real
WebSocket desktop/web submission with optional details and cancellation.
Native mobile development remains paused.

Validation on 2026-11-11: the complete server suite passed **5,269 tests** with
**15 skipped** (`-n 2`). After strengthening migration copies to name columns
explicitly, the affected report, migration, category and database suites passed
**143 tests**, including a legacy table with reordered physical columns. Real
WebSocket flows cover both `python` (desktop) and `web` clients. No native mobile
build or emulator was started.
