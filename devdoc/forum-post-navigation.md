# Forum post reading and actions

Thread message rows retain their bounded previews. Right reads the
complete body in place, including line breaks and up to 64,000 characters.
It does not open another menu or input, change selection, or retain the body in
the client's history. Explicit reading interrupts queued speech, while desktop
and web clients continue to honor muted buffers and inactive-window preferences.

Enter reads a text-only post, opens its sole poll or attachment directly, or
opens a compact content-only chooser when several resources are attached. Poll
and file rows precede Back in that chooser. It never opens a post action page
just to reach one resource. Poll Escape returns to the originating list/chooser;
media closure restores the existing client focus. Applications still opens all
post actions, and Shift+Enter always opens the body's read-only text.

Post queries compute the count of published ready approved attachments alongside
poll presence, suppressing both on hidden posts. Rows, full speech and reader
prompts announce these resources without putting full bodies through Fluent
interpolation. Opening resources or the chooser alone does not mark the body
read. Every selection rechecks post visibility, membership, blocks, availability
and attachment ownership by that post; no cached file metadata grants access.

Descriptions are displayed below images as focusable read-only multiline text
on desktop/web, preserving the full description and allowing selection/copy.
An image with a description initially focuses that text; image alternate names
remain available. Audio/video retain explicit playback and their description
text is also accessible. These changes do not resume native mobile work.

Applications or Shift+F10 opens the server-owned action menu for the focused
post. It contains speech, optional text reading, reply, editing, attachments,
polls, moderation and reporting as allowed by existing permissions. The body is
not duplicated as a menu row. Opening actions alone does not mark the post read.
Escape restores the thread page and focused post.

Shift+Enter opens the full body in the existing read-only multiline input.
Opening text from the action menu first returns to the thread, so Escape always
closes directly to the post list. Submitted input text is ignored. Selecting or
copying the text never becomes an edit operation.

## Navigation and protocol

Desktop and web reuse the existing `keybind` packet with `menu_id`,
`menu_item_id`, and the current one-based `menu_index`. The server checks the
active thread, exact visible row, supplied position, and current post ownership
by that thread. Recheck account access, forum availability, hidden state,
bilateral blocks and private membership on every entry point. These keys never
fall through to gameplay. Other rows, including general thread polls, retain
their normal activation and arrow behavior.

Web context click and long press open actions; Shift+Enter explicitly requests
text. Native mobile keyboard handling is outside this change.

The speech packet has an optional `interrupt: true`; absent or false preserves
existing queued-speech behavior. Post bodies use `history: false`. Speaking the
complete post or opening its text advances the existing read position and clears
its pending notices; focusing a preview or opening actions does not.

Notifications and unread continuation locate the exact post on its real thread
page and read it. Publishing or editing returns directly to the focused post
list, removing only redundant frames of that thread and preserving unrelated
drafts and game context. No database migration or message data change is needed.

## Verification

`test_forum_reader.py` covers full-length speech without navigation, text closure
and focus, context actions without read side effects, stale keys and access
revocation, disabled-forum draft preservation, unread continuation, and actual
desktop/web WebSocket round trips. Related forum suites cover publication,
editing, notifications, private conversations, reports and long messages.

Desktop tests cover all key mappings and interrupted speech with mute and focus
settings. Web layout tests cover post chords without selection movement and
unchanged arrow navigation on other rows. Run the complete server, desktop and
web suites before integration.

Validation: server 5,371 passed and 15 skipped; desktop 359 passed; web 94
passed, plus two chat-reply tests outside the default npm suite. The three new
Fluent labels parse and format in all seven server locales (21 messages).

Content follow-up validation: 24 resource-navigation tests pass, including real
desktop/web WebSockets and authenticated image HTTP retrieval. Full suites:
server 5,440 passed / 15 skipped, desktop 360 passed, web 95 passed plus two
chat-reply tests. A real wx text-control test and a web media-view test verify
full read-only descriptions, selection and focus. The 14 new labels parse and
format for all seven locales, with singular/plural count checks.
