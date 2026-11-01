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
