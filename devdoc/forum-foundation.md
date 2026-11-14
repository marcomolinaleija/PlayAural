# Native forum foundation

This first delivery implements a new forum inside PlayAural. The separate
Django forum was used to identify useful behavior; none of its implementation,
templates, database, users, or dependencies were imported.

## Delivered behavior

- A Forum option in the existing desktop, web, and mobile main menu.
- Three localized categories: Community, Questions and help, Ideas and feedback.
- Topic creation, paginated conversations, full-message reading, replies, and
  author editing within 30 minutes, with optimistic revision checks.
- Recent activity, unread topics, private per-account bookmarks, literal text
  search with Unicode normalization, and persistent reading positions.
- Preview before publishing, explicit discard confirmation, bounded runtime
  drafts, and safe navigation/focus restoration.
- Content first; actions at the bottom. Titles are menu metadata, not dummy
  rows. A transient localized entry announcement supplies context and counts;
  identical refreshes and returning from text input do not repeat it.
- Current-account checks, approval, bans, mutes, mutual block filtering,
  persistent send limits and duplicate rejection.
- Administrator/developer close, reopen, pin, unpin, hide and restore actions,
  with confirmation and an atomic moderation audit record.
- English, Spanish and Vietnamese UI and manuals. Agent-authored Vietnamese
  remains provisional and needs native review.

Attachments, polls, reactions, mentions, private forum threads, subscriptions,
email notifications, category management, revision history, and legacy-content
import are future deliveries. Existing game chat, voice, and friends remain
their existing shared services; the forum does not introduce parallel ones.

## Responsibilities

| File | Responsibility |
| --- | --- |
| `server/forum/models.py` | Immutable records and feature limits |
| `server/forum/text.py` | Plain-text validation, search keys, bounded reading chunks |
| `server/forum/schema.py` | Migration DDL, initial categories, account erasure |
| `server/forum/repository.py` | Parameterized queries, SQL pagination, storage primitives |
| `server/forum/service.py` | Authoritative permissions, atomic writes and domain rules |
| `server/forum/navigation.py` | Stable surfaces, inputs and non-resumable confirmations |
| `server/forum/views.py` | Content-first shared presentation and entry announcements |
| `server/forum/composer.py` | Bounded session drafts, input ownership and explicit publishing |
| `server/forum/manager.py` | Navigation, selection, input and restore dispatch |

`core/server.py` only registers and delegates the feature. The forum reuses the
authenticated WebSocket stream and existing `menu`, `request_input`, and `speak`
packets. Optional `menu.title` supplies a localized accessible name without
adding an item. Desktop updates the existing label and list name, mobile the
existing panel heading, and web its menu state/ARIA name. No new framework or
HTTP service is required for normal operation.

## Persistence and lifecycle

Schema version **4** adds `forum_categories`, `forum_topics`, `forum_posts`,
`forum_read_positions`, `forum_bookmarks`, and `forum_moderation_events`.
The repository borrows the central Database connection and transaction helper;
it never opens a competing runtime connection. Database maintenance continues
to own storage barriers, backups, cleanup, and compaction.

Migration from versions 0–3 uses the existing integrity, schema-validation,
capacity-preflight, verified backup, and atomic-transaction machinery. Version 3
is validated against the genuine pre-forum DDL, including its identity trigger.
Unexpected objects or newer versions fail closed. SQLite syntax remains within
the existing 3.25.0 baseline. Forum tables are included in ordinary validated
backups and are not a retention-cleanup category.

Public topics, messages, and moderation events are retained indefinitely.
Hiding a message is reversible and retains its stored text; ordinary readers
receive a placeholder, and search excludes hidden text. Authors keep immutable
account UUIDs. Account deletion removes UUID/name attribution from their topics
and posts, clears personal bookmarks/read positions, and removes moderator
identity from retained audit events. Public text itself remains. Historical
backup files follow the existing operational retention policy.

Reading a full message advances the account/topic high-water mark through that
message. Opening a preview list never marks it read. Older reads cannot move
the high-water mark backwards. Blocks filter both directions in topics, counts,
message queries, direct object lookup, search, and writes; text already received
by a client is not retroactively erased.

Draft data is bounded to one active compose flow in the account's runtime
navigation state. It is not stored in SQLite, preferences, or a manual game
save. Existing session-state retention limits reconnect recovery to five
minutes; logout, account deletion, and state expiry discard it. A replacement
client reconstructs confirmed draft intent, never an old rendered editbox or
moderation confirmation. Keystrokes not yet submitted to the server are local
to the input control.

## Limits

- 120 title characters, 64,000 message characters, 2–100 search characters.
- 15 topics or 8 message previews per page, with SQL LIMIT/OFFSET.
- Full messages are spoken in place on Right (also Enter for text-only posts),
  or opened in optional read-only text on Shift+Enter. Draft fields use a single 160-character excerpt;
  message actions live in a context menu. See `forum-post-navigation.md`.
- Six new messages per rolling 60-second window per immutable account UUID.
  The latest identical normalized message in that window is rejected. This
  check is transactional and persists through reconnects and server restarts.
- Text is never inserted as HTML. Attachments and rendered markup are outside
  this delivery.

## Local review

From the repository root:

```powershell
uv run --project server --extra dev python -m scripts.run_forum_demo
```

Open `http://127.0.0.1:18766/web_client/`. Desktop and mobile may connect to
`ws://127.0.0.1:18765`. Test accounts are `ForumDesktop`, `ForumWeb`, and
`ForumMobile`; their shared test password is `ForumDemo123!`. Use a different
test account on each device to avoid the ordinary single-session handover.
The demo binds only loopback, uses a temporary disposable database, and leaves
real server databases, configurations and accounts untouched. Ctrl+C stops it.

For normal persistent use, run PlayAural's existing server/client commands.
This delivery does not deploy, merge into main, bump client versions, or change
the sound pack.

## Verification

The results below describe the committed foundation delivery. For the ongoing
attachments, polls and private-conversation work, see
[forum-enhancements.md](forum-enhancements.md); its completion checks are separate.

```powershell
uv run --project server --extra dev python -m pytest server/tests/test_forum_service.py server/tests/test_forum_navigation.py server/tests/test_forum_migration.py -q
uv run --project server --extra dev python -m pytest server/tests -q -n 4
uv run --project server --extra dev python server/tools/compare_locales.py vi es
npm --prefix web_client test
uv run --project client --extra dev python -m pytest client/tests -q
npm --prefix mobile_client run typecheck
node --test mobile_client/tests/*.test.mjs
```

On Windows, the shell-management tests require a working Bash, such as Git for
Windows, earlier on PATH than an unconfigured WSL launcher. Web/mobile tests
require their installed package-lock dependencies. Migration tests cover a
genuine v3 database, verified snapshot contents, injected rollback, retry backup
reuse, and structural drift rejection. Network tests perform the full writing
and reading flow over real sockets for `python`, `web`, and `mobile`, and assert
input ownership, stale/forged selection rejection, safe handover, draft
preservation, bottom-placed actions, localized metadata and quiet refreshes.

Verified locally for this delivery: 4853 server tests passed (6 platform skips),
315 desktop tests passed, 77 web tests passed, and 211 mobile source tests
passed. Mobile TypeScript checking and EN/VI/ES locale parity checks passed;
the locale tool still reports pre-existing select/plural review warnings outside
the forum. The server wheel was built and inspected for forum modules, all
three locale catalogs, and their manuals. Browser interaction verified posting
and the revised content-first navigation; the desktop application rendered the
forum. A physical Android device and a packaged APK were not exercised.

Public-content reporting uses the shared moderation queue and schema 8. See
[forum-reports.md](forum-reports.md) for evidence, quotas and retention.

Public communities use schema 9 language scopes; see [forum-languages.md](forum-languages.md).

Schema 10 raises message bodies to 64,000 characters; see [forum-long-posts.md](forum-long-posts.md).

Full-message reading and return-focus behavior are described in [forum-reader.md](forum-reader.md).
