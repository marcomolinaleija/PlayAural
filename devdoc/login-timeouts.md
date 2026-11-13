# Desktop sign-in on slow connections

The local `network/login_timeout_seconds` preference accepts 30 (default) or 60.
It is available before signing in and in Client Options > Interface. Both views
save the same preference in the existing private identities file. Missing,
boolean, string or unsupported values fall back to 30; existing preferences and
accounts retain their normal migration behavior.

The selected duration applies separately to opening the WebSocket and to sending
authorization/waiting for its terminal response. The two stages may therefore
use up to 60 seconds by default, or 120 with the extended setting, plus bounded
socket closing. Fast responses complete immediately. Nonterminal packets do not
reset the authorization deadline. A login rejection still returns the server's
normal reason, and account approval, bans and failed-login limits are unchanged.

The old five-second window timer is removed. The network worker owns deadlines
and reports timeout to wx. Initial timeout closes the main window through normal
cleanup and returns to sign-in with its existing feedback, bypassing auto-login
so the user can select a longer wait. Normal close remains available while the
connection is pending.

Manual verification runs in `LoginAttempt` on a background thread. Cancel/Escape
stops the opening/authentication coroutine and keeps the sign-in window usable.
Closing or destroying the dialog also cancels it. Generation checks reject late
callbacks before touching wx or saving credentials. The destination and chosen
timeout are captured before the worker starts; controls cannot switch the
destination during verification. A cancelled attempt never saves its password.

The main network worker likewise cancels its pending task before a socket exists
and guards queued packets/end callbacks with an attempt id. It becomes connected
only after `authorize_success`. Retries wait for pending/closing attempts without
joining threads on wx or disconnecting every three seconds. Silent reconnect
uses a budget derived from the same preference and lets an already-running,
bounded attempt finish. Transport closing has a two-second timeout.

Client ping response deadlines follow the selected wait; the interval remains
20 seconds. The server allows 60 seconds for handshake and ping responses so its
former defaults do not defeat the extended client setting. This also extends
the server's detection time for a peer that stops answering pings. Socket closure
still disconnects immediately. No database migration or protocol change is used.

Tests exercise actual delayed authorization beyond the former five seconds,
actual server opening beyond ten seconds, cancellation without an established
socket, cancellation during authentication, stale callback rejection, pending
retry preservation, saved preference validation, both native option controls,
and a queued success cancelled before credentials can be written.

Native mobile work remains paused. The new desktop policy does not change the
web/mobile clients' local connection handling.

Validation: full server suite 5,441 passed and 15 skipped; full desktop suite
382 passed, including 22 new desktop cases and the new slow server-handshake
case. All 21 new labels format correctly in the seven desktop locales.
