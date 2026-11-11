# Forum enhancements — implementation in progress

The requested second delivery covers multimedia attachments, polls and private
conversations in the integrated desktop, web and mobile forum. It uses new
code; the separate forum remains a behavior reference only. This is not yet a
completed release: rendered client review and complete validation remain.

The 2026-11-10 desktop/web/server test stage is recorded in
[forum-validation.md](forum-validation.md): complete suites pass, the server wheel
was inspected and exercised, and a standalone backup was restored and served.
Public attachment review and private invitation/poll flows were exercised in
the browser. Native desktop interaction remains limited by the current graphical
session; mobile remains paused. The historical progress notes below do not
supersede that report.

Mobile work is paused at the user's explicit request on 2026-11-06. Preserve its
current code and partial dependency layout; do not resume mobile edits, repair,
Android compilation or emulator work until the user asks to resume. The saved
state and exact remaining work are in [forum-checkpoint.md](forum-checkpoint.md).

## Implemented and focused verification

- Schema v5 extends v4 without rewriting public forum records. Historical
  contracts remain version-specific; genuine v3/v4 migration, backups and drift
  rejection are covered by tests.
- Private discussions require explicit accepted UUID membership. Invitations
  expire in seven days, groups hold at most 12 people, blocks are rechecked at
  acceptance. Global administrator status does not grant private access. Group
  ownership transfers when its owner leaves or is deleted; removing the last
  member deletes the topic, never converts it to public content.
- The shared menu UI handles private composing, invitations, participants,
  leaving and polls on desktop/web/mobile. Real WebSocket tests exercise all
  three client identifiers. Content precedes actions; optional composing tools
  live under Add. Publication sends invitations only after explicit confirmation
  through Publish. Poll choices are reviewed before Submit vote.
- Polls support single/multiple choices, vote replacement, automatic/manual
  closing and results visibility. Hidden counts are omitted from responses.
  Question/options freeze permanently after the first ballot, including if all
  votes are withdrawn or a voting account is deleted.
- Attachments reserve private metadata, upload through authenticated HTTP, then
  prepare outside the event loop. Pillow decodes/re-encodes images and drops
  EXIF metadata. FFmpeg/FFprobe normalize audio to MP3, video to MP4 and create
  thumbnails. Files are limited to 128 MiB, media to 15 minutes, images to 40
  megapixels; at most eight attachments/256 MiB pending per user. PDF/ZIP/text
  are explicit downloads, never HTML/WebView content.
- Publication atomically binds only ready, approved, owned files to their post.
  Access follows current post visibility, blocks and private membership.
  Published files never regain draft privileges after their post disappears.
- Personal Saved discussions includes accepted private conversations, marked as
  private. Public categories, recent/unread lists and search exclude them.
  Leaving or removal revokes access and clears the person's saved/read state.
- Media credentials are ephemeral and bound to the owning socket. Handover
  invalidates the former credential. Bearer headers or an HttpOnly cookie
  authorize HTTP; URLs alone never do. Real HTTP tests cover upload, Range,
  HEAD, cookies, origin rejection, revocation and the database maintenance
  barrier. Local and optional S3/B2 storage adapters use private opaque keys.
- Web has an explicit picker and one media dialog with keyboard/native controls,
  speed, image zoom, downloading and focus restoration. Opening does not play.
  Playing cancels pending app TTS and temporarily lowers music/ambience; pause,
  end/error/close restores mixing. No microphone is enabled. Service-worker
  caching excludes private media and no-store responses.
- Desktop has a native file picker, authenticated Range relay for the Windows
  player, image zoom/description, downloads and timed text subtitles. A small
  native harness loaded both MP3 and MP4, confirmed initial pause, explicit
  playback, seeking and speed changes. The full desktop suite passed 324 tests
  before the subsequent server-only/documentation changes.
- Mobile source includes DocumentPicker uploads, Expo audio/video players,
  image zoom, explicit save/share and player-first Back behavior. Temporary
  copies and late callbacks are session-scoped; playback uses the existing
  audio-focus coordinator. Native rendering/playback remains unverified.
- Optional approval begins only after the composer explicitly chooses Publish.
  Public reviewers are moderators; private reviewers are the current group
  owner. Unsubmitted drafts are not visible to reviewers, and approval never
  automatically publishes the message. Removing a participant revokes file
  access and their unpublished group uploads.
- Restart reconciliation fails interrupted uploads, clears only application-owned
  staging directories, and expires unpublished uploads after 24 hours. Published
  objects remain for historical snapshots. Central backup, cleanup and compaction
  require a verified standalone SQLite/object ZIP, including when media HTTP is
  disabled but published attachments exist. Missing/corrupt objects fail before
  cleanup or compaction changes storage.
- Supported embedded text subtitles are preserved in MP4 and exported as WebVTT
  for web/desktop. Bitmap captions, separate subtitle-file association and
  automatic transcription are not implemented. Mobile native subtitle controls
  and the Expo web video path still need direct verification.
- EN/ES/VI player manuals cover attachments, review, polls and private groups.
  See [forum-deployment.md](forum-deployment.md) for configuration, backups and
  recovery. Vietnamese additions remain provisional pending native review.

Focused server checks currently cover the forum, migrations and database
maintenance; web baseline checks and media lifecycle tests pass. These are not
a substitute for the final complete validation listed below.

## Required before completion

- Real rendered UI review and full end-to-end uploads/playback on the clients;
  confirm focus, back behavior, screen-reader announcements and error recovery.
- Verify mobile audio failure reporting (the installed Android Expo audio status
  API does not expose a distinct playback-error state), fullscreen behavior and
  subtitles with self-voicing as well as system accessibility. Video has status
  error feedback and explicit shared audio coordination for every Play action.
- Run the full server, desktop, web, mobile and locale checks, build the server
  wheel and inspect bundled artifacts before committing the completed delivery.

## Resource-constrained validation state

Android compilation and the full server run were cancelled after the user
reported the computer slowing down. No APK was produced: the attempted native
build had also encountered Windows path-length limits. The emulator is off.
Do not restart it, Android compilation, bulk transfers or other heavy validation
without consulting the user.

A dependency relocation was interrupted while moving this worktree's independent
`mobile_client/node_modules` to `D:\pa-forum-01a1afb7\node_modules`. Both locations
currently contain physical directories; treat the mobile installation as partial
until reconciled. The Android directory remains in the worktree. No source files
or original-checkout dependencies were moved. Repair needs an explicit resource
plan before further package installation or bulk copying.

Subsequent light checks passed: 2 private-Saved ACL tests, the private
invitation/poll/Saved flow for all 3 client identifiers, 12 media lifecycle/backup
tests, 6 approval tests, 10 central maintenance tests, 3 rolling-credential tests,
20 mobile transport/player tests and the complete 86-test web suite. EN/VI/ES locale parity
checks pass, with existing plural review warnings outside the forum. These
checks do not prove native mobile rendering or replace the cancelled full suite.

Mobile tests cover late picker/reservation/sharing results after session reset,
explicit Play, audio coordination, pending Play after close/backgrounding,
duplicate Save suppression, self-voicing speed/volume (including zero), seek
drag stability and one-time video error feedback. Both playback panes place
their content inside the gesture surface, with actions below it.

Real browser review in the disposable loopback demo exercised a three-second
MP3 through upload, preparation, draft preview, explicit playback, 1.5x speed,
download, publication and reopening from its published post. The player opened
paused with decoded duration 3 seconds; closing restored focus to the attachment.
The published post showed body, attachment, then actions. Screenshot evidence:
`C:\Users\leija\Documents\Codex\2026-10-31\re\work\forum-validation\web-audio-player.png`
and `web-audio-published.png` in the same local validation folder outside this
worktree. This covers audio; rendered image/video, private review
and mobile device scenarios remain required. The demo was stopped afterward.

Browser testing exposed stale cached assets during iteration. The new web shell
cache is 24, native fetch retains its Window receiver, and transfer callbacks use
the opening surface's AbortSignal/generation. Downloads are single activation
and cannot open after the player closes. Temporary cache/service-worker bypass
used to verify the updated client was reset, and diagnostic DOM attributes were
removed. No browser security settings were changed.

## Local configuration

Media is enabled by an explicit public URL. For local development:

```text
python -m server --host 127.0.0.1 --forum-media-url http://127.0.0.1:8001 \
  --forum-media-origin http://127.0.0.1:8080 --forum-media-dir PRIVATE_DIRECTORY
```

Use HTTPS outside loopback. Prefer a same-origin reverse proxy for
`/forum-media/` so cookie streaming works without third-party-cookie exceptions.
Keep the object directory outside all static document roots.
`scripts/run_forum_demo.py` uses ports 18765 (WS), 18766 (web), 18767 (media) and
disposable data, without touching production accounts.

Local storage is the default. The optional `s3` extra enables the S3/B2 adapter:
set `PLAYAURAL_FORUM_STORAGE=s3`, `PLAYAURAL_FORUM_BUCKET` and optionally
`PLAYAURAL_FORUM_S3_ENDPOINT`/`PLAYAURAL_FORUM_S3_REGION`. Credentials use the
standard SDK chain and never enter client packets. The bucket must be private
and distinct from backups. External credentials and a production bucket have
not been configured or tested in this delivery.

## Attachment selection feedback (2026-11-11)

The composer Add action and Attach a file action include selected counts and
prepared/failed counts. Uploading and processing files are not yet prepared.
Reservation and completion refresh the visible draft surface without adding status rows or repeating entry speech.
Removing an attachment updates the same bounded draft and clears the count when
empty. Prepared refers to media processing; any required approval remains a
separate per-file state.

The picker packet optionally carries `accepted_extensions`, derived from the
server media processor's supported families. Desktop builds a localized file
filter with an All files alternative; web uses the native input's `accept` hint.
Selection is one file at a time, and an accessible announcement precedes upload.
The existing content-signature/decoder validation and quotas stay authoritative:
8 files per message and 8 pending per account, 128 MiB per file, 256 MiB pending,
15-minute AV duration, 40-million-pixel images and 1 MiB plain text. No schema
migration is needed. Native mobile work remains paused.

Validation: server suite 5,271 passed / 15 skipped; desktop suite 333 passed;
web suite 90 passed. Final selected/prepared summary transition check passed,
including reservation, preparation, removal and entry-speech suppression.
The native picker filter and selection announcement were also verified with
wxPython and a substituted file dialog, without opening a graphical session.
