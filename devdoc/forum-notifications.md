# Forum notifications and mentions

Forum notifications use existing server-owned menus, input and localized speech
on all clients. No client protocol, dependencies or mobile work is required.
Private conversations and Recent activity retain their fixed home positions;
Notifications and Forum alerts are actions below the language subforums.

## Ownership and persistence

Schema 11 adds four tables through the central startup migration, with its
verified pre-migration backup and transaction rollback. Historical posts do not
generate retroactive notifications. Existing content and reading positions stay
unchanged; schema-10 post rebuilding is not repeated for a v10 source.

- `forum_mentions`: post/recipient UUID and active state. Retains removed/read
  mention identities until the post or recipient is deleted, preventing an
  edit/remove/re-add loop from notifying again.
- `forum_notifications`: one pending event per recipient UUID/post, kind,
  creation time and announcement state. Mention wins over private activity.
  No cached body/title or username is used to authorize a destination.
- `forum_notification_settings`: account-owned spoken-private/mention toggles.
- `forum_muted_topics`: account/topic mutes for both spoken alert types.

All relationships cascade from their users/posts/topics. Account deletion also
discards attributable notices before removing public attribution. Blocking
atomically discards affected pending events in both directions, including
public topics whose owner becomes inaccessible; unblocking cannot restore them.
Leaving/removal discards the former member's pending private notices and mute.

## Publishing and delivery

`ForumNotifications.record` runs in the same transaction as topic/reply/edit,
poll and attachment binding. Explicit `@Name` and `@{Spaced Name}` use the shared
Unicode-aware account resolver. Email addresses, doubled @ and backslash-escaped
tokens are not mentions. Unknown names reject publication with the draft intact;
at most ten distinct normalized mention names are accepted. Private mentions
of outsiders never notify or admit them. Self-mentions never notify.

Creation/edit stores mention UUIDs; edits notify only first-time recipients.
Moderator edits cannot issue new mentions as the original author. Private
reply notices go only to accepted members except the author. Invitations have
their existing independent membership flow and do not receive post notices.

After composer publication commits, the controller delivers speech to online
recipients. Offline rows survive restart. Login announces a single grouped
summary of not-yet-announced eligible events, then marks them announced. Private
speech coalesces until pending private activity has been consulted. No speech
is emitted for the currently read conversation, a muted topic or disabled alert
kind. These events remain in the inbox; announcement never changes read position.
Disabled forums do not announce or navigate to pending notices.

Pending events are lazily pruned per recipient during publication/inbox/delivery:
90 days, newest 500 events. Mention history is not a second pending queue and
has at most ten UUID targets per post over its lifetime, including later edits.
This also bounds edit-based fanout within the existing 30-minute edit window.

## Inbox and navigation

Lists group ordinary private activity per topic and retain individual mentions.
Each private group opens its first pending post; its label identifies the latest
private activity author. Lists use standard 15-row pagination and bottom actions.
Every display/delivery/open checks current account, bilateral blocks, private
membership and hidden state, without filtering by the recipient's selected
public language. Opening a notice does not change that language preference.

Empty entry is checked before navigation: one transient spoken notice, no menu
packet and no return frame. Empty refresh/restore returns to the parent with
spoken feedback instead of rendering an empty list. Opening an eligible post
removes that post's pending notice inside the existing mark-read transaction.
Alert speech and previews never do so. Explicit full-body speech and optional
read-only text do mark the post read. Exact post IDs now locate the message in
its thread and read it aloud, preserving draft/game return context; see
`forum-post-navigation.md` for the current keyboard behavior.

The first delivery deliberately has no mention autocomplete, email delivery,
OS/browser push subscription, public-thread subscriptions or new media behavior.
Localized server labels are provided in all seven forum languages; player manuals
are updated in Spanish, English and Vietnamese.

## Validation

- 26 new tests cover mention parsing, lifetime fanout, transaction rollback,
  private membership, blocks, edits, deletion, retention, alert settings,
  empty/stale inbox navigation, pagination, migration and actual desktop/web
  WebSocket delivery plus full-message opening.
- Full server: 5,342 passed, 15 skipped. Desktop: 334 passed. Web: 92 passed.
- All 126 new Fluent messages parse and format in the seven forum languages.
- A read-only backup copy of the local schema-10 test database migrated to 11
  with all 35 existing tables' row counts preserved and clean integrity/FK checks.
- Historical migration fixtures omit v11 features while seeding old schemas.
  Authentication/reconnect fixtures use the actual server-owned database, keeping
  forum and other services on the same connection as production.
