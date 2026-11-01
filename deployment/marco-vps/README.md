# Installation at play.marco-ml.com

The fork tracks Daoductrung/PlayAural. Production uses an approved commit and
Docker images, never a moving `latest` tag. SQLite, backups, API keys, account
credentials, release manifests and Android signing keys remain outside Git.

`PLAYAURAL_RELEASE_MANIFEST` optionally loads a JSON object with the exact
server `version`, `sounds_version`, and a `targets` object. Each target may
contain `application` and `sounds` with `url`, `delivery` and optional `sha256`.
Deliveries retain upstream validation and platform rules. Missing artifacts
remain unavailable; stale versions and moving `/latest/` URLs prevent startup.
Without this environment variable the upstream behavior is unchanged.

Example manifest before native clients are approved:

```json
{"version":"1.0.5.3","sounds_version":"13","targets":{}}
```

The web client and server are built from the same commit. Publish native
artifacts only after building their matching sources and testing them. Keep
APK signatures stable. Keep exact source archives and dependency license
notices with each release. The upstream sound-asset permission caveat in
THIRD_PARTY_NOTICES.md still applies; this fork does not grant additional rights.

Before promotion: test the candidate, validate client compatibility, stop
writes, back up SQLite and the existing manifest, then restart the coordinated
release. For rollback restore the previous images, manifest and corresponding
database. Restoring a database discards writes made after its backup.

The gateway listens on loopback TCP 3048; the host Nginx terminates HTTPS.
The game listens on loopback TCP 3047. LiveKit exposes RTC TCP 7881, multiplexed
RTC UDP 7882 and TURN UDP 443. Its API TCP 7880 is loopback-only. `/rtc` and
`/twirp/` are proxied on the same HTTPS hostname as `/ws` and the web client.
TURN/TLS over TCP 443 is not enabled; networks that block UDP and TCP 7881 may
need a separate TURN/TLS service. Provider firewalls must allow the RTC ports.

The operator owns account initialization and SMTP configuration. Create the
first account while the game endpoint is private: upstream grants that account
developer privileges. Never commit its password or production database.

## Client release procedure

On Windows, run `build-desktop.ps1` with Python 3.13 (including Tk for the
updater), and `build-android.ps1` from a short checkout path such as
`C:/Users/leija/Documents/Codex/work/pa`. Long Windows CMake paths can fail.
Android builds set a separate application id, `com.marcoml.playaural`, so they
can coexist with the official application. Increase the deployment's Android
versionCode on each publication. The Gradle 8.14.3 pin works around the pinned
React Native Foojay plugin's use of a JVM vendor removed in Gradle 9.

Use `sign-android.ps1` with the existing private deployment keystore and signing
configuration outside Git. It verifies APK signatures and 16 KiB alignment.
Use `make_release.py` to package the desktop folder, sound pack, signed APK and
version/commit/hash manifest under an immutable commit-named download path.
The Android browser-download delivery does not enforce the manifest checksum;
HTTPS and the stable APK signature protect native updates. Windows ZIP
delivery enforces the configured SHA-256.

Prefer `build-android.sh` inside the pinned Android Docker builder on the VPS
when local disk space is limited. Mount only an isolated build checkout at
`/workspace`; do not expose production data or signing keys to npm/build steps.
The Windows script rejects builds with less than 15 GB free. Signing is a
separate, offline step using the existing deployment key.

The verified builder is `cimg/android:2026.10.1-node`, pinned as
`cimg/android@sha256:7cf8be3b40321a557dc4c1eebbec711903cbef6ed14484e724a558687893ff52`.
It provides JDK 21, Node 24 and Android build-tools 36.0.0. Run the build with
three CPUs, 8 GiB RAM, a persistent SDK volume at `/home/circleci/android-sdk`
and Gradle cache at `/root/.gradle`; the script limits Gradle workers to two.
The SDK installs the NDK/CMake versions selected by the locked React Native
dependencies on its first build.

Upload and verify downloads before promotion. `promote.sh FULL_COMMIT MANIFEST`
requires the manifest's source_commit to match the approved commit on the
fork's main history. It builds isolated images, checks manifest compatibility,
runs the full Linux server suite, stops writes, verifies a SQLite backup and
starts the candidate. A failed startup restores the previous images, manifest
and database through `rollback.sh`. Both scripts run as marco, using Docker.
Only the host HTTPS proxy initially required sudo.
Startup probes verify service ownership and fsync on the live/backup
filesystems. Game crashes have at most three automatic restarts, so persistent
migration failures do not loop indefinitely. After a host reboot, the user
startup service brings the stack back up.
Backups hold one SQLite read snapshot, compare schema and row counts, run full
integrity and foreign-key checks, fsync the saved file and atomically publish
it. Daily backups share the promotion lock and incomplete directories are
explicitly marked and rejected by rollback.

Keep small fork changes visible in PRs and run CI before merging upstream.
The Codex daily check prepares and validates updates; a failed build or merge
must retain the current production version. Running code from main and
installing the newest upstream APK are separate operations: neither alone
proves compatibility.

## Private Backblaze backups

The separate mode-600 `config/rclone-b2.conf` contains remote `b2playaural`,
restricted to private bucket `marcoml-playaural-backups`. It is excluded from
Git and kept in the operator's private local recovery files. Existing rclone
remotes are untouched. Backblaze-managed encryption at rest is enabled.

Install `upload_backup_b2.py` at `ops/upload_backup_b2.py` and the B2 upload
service/timer in the user's systemd directory. Install `playaural-backup-b2.conf`
as `playaural-backup.service.d/backblaze.conf`: a successful daily SQLite backup
then queues cloud upload. The hourly timer retries pending uploads without
creating another SQLite snapshot and without needing the operator's PC.

Only complete snapshot folders with the database, previous environment and
matching release manifest are archived. An internal manifest records SHA-256
for every included file; arbitrary files, credentials and incomplete snapshots
are excluded. The uploader validates SQLite, uses deterministic immutable
archives, reads each newly uploaded archive back and compares SHA-256 before
recording success in `ops/b2-upload-state.json`. It never synchronizes deletions
or removes local/cloud backups. Signing keys, SMTP/voice credentials and the
rclone key are not included in these database snapshots; keep their existing
private recovery copies separately.

Cloud archives live at `b2playaural:marcoml-playaural-backups/snapshots/`.
To restore, download a selected archive with the private rclone configuration,
validate its outer digest against the upload ledger, validate every file
against its internal `MANIFEST.json`, then check SQLite using the canonical
username functions. Extract only the expected regular snapshot files into a
new private backup directory; use the existing rollback procedure after
reviewing which database and release are being restored. Do not overwrite
production just to test retrieval.
