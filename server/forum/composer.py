"""Preview-first composing, with one bounded draft in the user's nav frame."""

from dataclasses import asdict, replace

from ..ui.confirmation import show_confirmation_menu
from ..users.base import MenuItem
from . import navigation as nav
from .models import Draft, ForumError, MAX_BODY_LENGTH, MAX_TITLE_LENGTH
from .text import reading_chunks, validate_text
from .views import item, label


class ForumComposer:
    def __init__(self, server, service, views):
        self.server = server
        self.service = service
        self.views = views

    @staticmethod
    def draft(state) -> Draft:
        return Draft(**state["forum_draft"])

    def show(self, user, draft: Draft) -> None:
        self.service.account(user.uuid)
        if draft.kind == "topic":
            heading = label(user, "forum-new-topic")
        else:
            topic = self.service.topic(user.uuid, draft.topic_id)
            heading = label(user, "forum-edit-heading" if draft.kind == "edit" else "forum-reply-heading", title=topic.title)
        rows = []
        if draft.body:
            rows.extend(MenuItem(text=text, id=f"preview:{index}", read_only=True)
                        for index, text in enumerate(reading_chunks(draft.body)))
        if draft.kind == "topic":
            rows.append(item(user, "forum-draft-title", "edit_title", title=draft.title or label(user, "forum-not-written")))
        rows.append(item(user, "forum-write-body", "edit_body"))
        rows.append(item(user, "forum-save-edit" if draft.kind == "edit" else "forum-publish", "publish"))
        self.views.render(user, nav.COMPOSER, rows, title=heading,
                          announcement=("forum-entry-composer", {"heading": heading}),
                          forum_draft=asdict(draft), forum_topic=draft.topic_id)

    def begin_input(self, user, draft: Draft, *, title: bool = False) -> None:
        input_id = nav.TITLE_INPUT if title else nav.BODY_INPUT
        self.server.enter_input_state(user, input_id, forum_draft=asdict(draft))
        self.show_input(user, input_id, draft.title if title else draft.body)

    @staticmethod
    def show_input(user, input_id: str, value: str) -> None:
        title = input_id == nav.TITLE_INPUT
        user.show_editbox(input_id, label(user, "forum-title-prompt" if title else "forum-body-prompt"),
                          value, multiline=not title,
                          max_length=MAX_TITLE_LENGTH if title else MAX_BODY_LENGTH)

    def handle_input(self, user, packet: dict, state: dict) -> None:
        input_id = state["menu"]
        if packet.get("input_id") != input_id:
            return
        if packet.get("cancelled"):
            user.remove_editbox(input_id)
            self.server._restore_input_parent(user, state)
            return
        title = input_id == nav.TITLE_INPUT
        value = packet.get("text")
        try:
            value = validate_text(value, title=title)
        except ForumError as error:
            user.speak_l(error.key, buffer="system", **error.values)
            limit = MAX_TITLE_LENGTH if title else MAX_BODY_LENGTH
            self.show_input(user, input_id, value[:limit] if isinstance(value, str) else "")
            return
        draft = replace(self.draft(state), **{"title" if title else "body": value})
        state["_parent_frame"]["forum_draft"] = asdict(draft)
        if not title:
            state["_parent_frame"]["_restore_focus_id"] = "preview:0"
        user.remove_editbox(input_id)
        self.server._restore_input_parent(user, state)

    def discard(self, user, draft: Draft) -> None:
        show_confirmation_menu(user, nav.DISCARD, prompt_key="forum-discard-prompt", buffer="system")
        self.server._user_states[user.username] = {"menu": nav.DISCARD, "forum_draft": asdict(draft)}

    def publish(self, user, draft: Draft) -> None:
        if draft.kind == "topic":
            topic_id, post_id = self.service.create_topic(user.uuid, draft.category_id, draft.title, draft.body)
            self.server._nav_back(user)
            self.server._nav_push(user, self.views.thread, topic_id)
            self.open_post(user, post_id)
        elif draft.kind == "reply":
            post_id = self.service.reply(user.uuid, draft.topic_id, draft.body)
            self.server._nav_back(user)
            if self.server._user_states[user.username]["menu"] == nav.POST:
                self.server._nav_back(user)
            self.open_post(user, post_id)
        elif draft.kind == "edit":
            self.service.edit(user.uuid, draft.post_id, draft.body, draft.revision)
            self.server._nav_back(user)
        else:
            raise ValueError("Unsupported forum draft")
        user.speak_l("forum-edit-saved" if draft.kind == "edit" else "forum-published", buffer="system")

    def open_post(self, user, post_id: int) -> None:
        # Return to the message just published rather than stacking message
        # readers indefinitely or returning focus to a now-stale unread link.
        self.server._remember_current_menu_focus(
            user, nav.THREAD, {"selection_id": f"post:{post_id}"},
        )
        self.server._nav_push(user, self.views.post, post_id)
