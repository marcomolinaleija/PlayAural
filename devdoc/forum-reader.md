# Full-message read-only reader

This records the original automatic-reader delivery. Current navigation uses
in-place speech, a contextual action menu, and optional text on Shift+Enter;
see `forum-post-navigation.md`. Escape now returns directly to the thread list.

Thread lists show 160-character excerpts. Opening a visible message now displays
its complete text in the existing `request_input` multiline/read-only surface.
The underlying message menu contains one short, actionable body row followed by
its attachments, poll and ordinary actions. It does not expand the body into
hundreds of menu rows. After closing, that same body row reopens the full text.

`MessageReader` coordinates initial opening and explicit reopening. Normal
navigation restoration renders only the compact message menu, avoiding a loop
that reopens the text box when it closes. Enter or Escape returns focus to the
body row; Back then returns to the originating thread row. Continue and Next
unread open the full text of the selected unread message. Publishing a message
returns to its actions without forcing a readback of the author's own text.

The new `forum_body_reader` input id uses the existing shared protocol. Its
server handler ignores submitted text entirely: a forged edited return payload
can close the viewer but cannot edit a post or draft. It accepts only matching
input ids, rechecks account/visibility/block/membership/hidden state on every
open, and sends no body for hidden posts. Restoring after reconnect retains ids
and action focus, not a cached full-body reader. The existing reading high-water
mark semantics remain intact.

Closing remains available after forum deactivation. It skips unavailable reading
surfaces while preserving an earlier local composer or non-forum return context.
No public text is refreshed through the closing action while the forum is off.

Desktop read-only multiline controls position the caret and viewport at zero
instead of selecting the whole body. Web read-only inputs likewise use a collapsed
selection at zero and scroll to the top. Editable fields retain Select All.
Neither client explicitly speaks the full body on opening; users can navigate,
select and copy through their normal text/screen-reader controls.

No database migration is required. Public and private posts share the same
64,000-character reader, with existing private membership rules. Staff report
snapshots remain immutable reading rows in the moderation queue; its View current
publication action opens this normal, access-checked reader. Native mobile work
remains paused.

Validation on 2026-11-11: the complete server suite passed **5,303 tests with 15
skipped**; desktop passed **334 tests** and web **91 tests**. The final reader
suite passed **12 tests**, including preservation of an earlier draft when closing
after forum deactivation. Coverage includes full 64,000-character text, forged
payload rejection, focus restoration, stale inputs, hidden/blocked/revoked private
access, reconnect normalization, exact unread navigation and real desktop/web
WebSocket opening and closing. Client tests verify full-body retention and initial
caret/viewport selection without a graphical session.
