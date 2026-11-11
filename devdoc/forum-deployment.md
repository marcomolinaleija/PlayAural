# Forum media configuration and recovery

Forum messages, memberships, polls, file metadata and review decisions use the
central schema-v5 SQLite database. File bytes live in a private object store;
they are not stored in SQLite or sent through the gameplay WebSocket. Desktop,
web and mobile use the same authorized HTTP service.

## Enable media

Install the server's locked dependencies and make `ffmpeg` and `ffprobe`
available on its PATH. Both are required for audio/video preparation; Pillow
handles images. Configure a persistent private directory outside every static
web root. Its `staging` subdirectory contains temporary uploads; `objects`
contains immutable prepared files when using local storage.

Example for local development (one command):

```text
python -m server --host 127.0.0.1 --forum-media-url http://127.0.0.1:8001 --forum-media-origin http://127.0.0.1:8080 --forum-media-dir PRIVATE_DIRECTORY
```

`--forum-media-url` enables the service and advertises the externally reachable
URL, optionally ending in `/forum-media`. HTTP is permitted only on loopback;
use HTTPS for any deployment. `--forum-media-port` defaults to 8001 and listens
on the server host. A configured server certificate/key also protects the media
listener. With a reverse proxy, forward `/forum-media/` to the media listener and
preserve paths, Authorization, cookies, Origin, Range and HEAD. Keep a listener
without its own TLS private behind the proxy.

Prefer the web client's own HTTPS origin for media. Repeat
`--forum-media-origin` for each additional trusted web origin, including its
scheme and port. Cookie streaming uses HttpOnly, Secure on HTTPS, SameSite=Lax
cookies; unrelated third-party origins can be blocked by browser cookie policy.
Desktop/native mobile authenticate with request headers. Do not put tokens in
URLs, expose the object directory through static hosting, or cache media at a
CDN/proxy. Responses are private and no-store. A URL by itself grants no access.

Environment equivalents are `PLAYAURAL_FORUM_MEDIA_URL`,
`PLAYAURAL_FORUM_MEDIA_PORT` and `PLAYAURAL_FORUM_MEDIA_DIR`. Web origins use
the repeatable command-line argument. Without a media URL, uploads/players are
disabled while the rest of the forum remains available. Keep the same directory
and storage settings when disabling HTTP: central maintenance still needs them
to back up previously published attachments. The default directory, if omitted,
is the database path with its suffix replaced by `.forum-media`.

## Optional private S3 or B2 store

Install the server's `s3` extra and configure:

```text
PLAYAURAL_FORUM_STORAGE=s3
PLAYAURAL_FORUM_BUCKET=PRIVATE_BUCKET_NAME
PLAYAURAL_FORUM_S3_ENDPOINT=PROVIDER_ENDPOINT_IF_REQUIRED
PLAYAURAL_FORUM_S3_REGION=PROVIDER_REGION_IF_REQUIRED
```

Credentials come from the SDK's standard server credential chain. They never
enter client packets. The adapter uses a `forum/` prefix and private opaque
object keys. Keep the bucket private and distinct from backup storage. Downloads
remain proxied through PlayAural so membership, blocks and hidden-post state are
checked for every request, including seeking. The local private directory is
still required for staging. Switching storage settings does not migrate files;
copy and verify existing objects before changing the configured backend.
Production credentials/buckets have not been exercised in this delivery.

## Approval and limits

`PLAYAURAL_FORUM_MEDIA_APPROVAL=1` enables human review; the default is `0`.
Public attachments from ordinary members need a moderator's approval. In an
existing private group, other members' attachments need the current owner's
approval. Group owners' own private attachments and moderators' own public
attachments are approved automatically. Global administrators never gain private
group access through this setting.

Upload completion alone does not submit a file to review. The author first
chooses Publish, which shares the ready file with its authorized reviewer and
keeps the post in the session draft. After approval, the author must Publish
again. Rejected files must be removed or replaced. Neither reviewers nor other
members can inspect unsubmitted uploads.

Limits are 128 MiB per file, 15 minutes per audio/video, 40 million image pixels,
eight pending attachments and 256 MiB pending bytes per account. Unpublished
files expire after 24 hours, including approved or pending-review files.
The collector runs every minute and skips active uploads/preparation. Restart
marks interrupted work failed and removes only owned `upload-*` staging
directories. It leaves unknown files alone.

Preparation uses up to two spawned workers; FFmpeg is bounded to two threads
per job and a 180-second subprocess timeout. Images become still JPEG/PNG files
without their original metadata, audio becomes MP3 and video becomes MP4 with a
thumbnail. Supported embedded text subtitles produce WebVTT as well as an MP4
subtitle track. No transcription or separate subtitle association is provided.
PDF, ZIP and UTF-8 text are explicit downloads rather than embedded documents.

## Backups

Use the server's central administration backup operation. When media is enabled,
or published attachment records exist with HTTP disabled, it creates a verified
`.forum.zip` companion to the SQLite snapshot. The ZIP contains:

- `database.sqlite3`: the exact verified database snapshot;
- `objects/<opaque key>`: published content, thumbnail and caption objects;
- `manifest.json`: snapshot/object sizes and SHA-256 checksums.

The archive includes private membership and content. Store it with the same
access restrictions as the live private data. Archive creation verifies every
member before publishing its final filename and fails if required objects are
missing, corrupt or there is insufficient disk space. Cleanup and compaction
require this complete safety archive before changing storage. The successful
administration message names the ZIP when present.

Direct low-level `Database.backup_database()` calls produce only SQLite. They
are not a complete attachment backup. If invoking that API outside central
maintenance, also run `ForumObjectBackups(storage).capture(snapshot.path)` with
the same configured store, then verify the archive. Do not discard the objects
because a SQLite-only backup succeeded.

Published objects are retained even after the live post/group disappears, so
older database snapshots keep working. Unpublished draft files are excluded
from standalone archives. Published-object garbage collection is deliberately
not implemented; operators need a retention-aware plan covering historical
backups before deleting any such objects.

## Restore to a clean destination

1. Stop the destination server and keep the current database, storage and
   configuration intact as a recovery copy. Do not restore over an active server.
2. Run `ForumObjectBackups.verify(Path(archive_path))` using the bundled server
   environment. It checks exact archive members, safe opaque keys, sizes and
   checksums without extracting. Reject an archive that fails verification.
3. Use new, empty destinations. Restore `database.sqlite3` as the server database.
   For local storage, copy each verified `objects/<key>` entry to
   `PRIVATE_DIRECTORY/objects/<key>`. For S3/B2, upload those entries under the
   adapter's `forum/<key>` prefix with private access. Preserve keys exactly;
   none are public URLs. Do not extract arbitrary unverified ZIP paths.
4. Configure that database and the matching object store/directory together.
   Prepared content, thumbnails and captions must all be present. Start in a
   restricted environment first; check database validation, private membership,
   public/private file access, playback and a fresh complete backup before
   allowing normal connections.

Unpublished drafts may contain expired or unavailable upload references after
recovery; authors must upload those files again. A restored private conversation
retains the membership from the restored snapshot. Review who has access before
bringing a historical backup online.

## Verification still required

Focused tests exercise local storage, checksummed archives, private access,
HTTP Range/cookies/session revocation, approval and expiry. The S3 adapter uses
test doubles; production S3/B2 access and an operator restore drill remain
unverified. See [forum-enhancements.md](forum-enhancements.md) for client and
resource-constrained validation status. Do not treat this guide as a release
approval or restart heavy validation without the user's agreement.
