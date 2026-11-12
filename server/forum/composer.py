"""Compact editable fields, with one bounded draft in the user's nav frame."""

from dataclasses import asdict, replace

from ..ui.confirmation import show_confirmation_menu
from . import navigation as nav
from .models import Draft, ForumError, MAX_BODY_LENGTH, MAX_TITLE_LENGTH
from .text import excerpt, validate_text
from .views import attachment_action, item, label
from .poll_ui import draft_poll
from .polls import validate_config


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
        if draft.kind in {"topic", "private"}:
            heading = label(user, "forum-private-new" if draft.kind == 'private' else "forum-new-topic")
        else:
            topic = self.service.topic(user.uuid, draft.topic_id)
            heading = label(user, "forum-edit-heading" if draft.kind == "edit" else "forum-reply-heading", title=topic.title)
        rows = []
        if draft.kind in {"topic", "private"}:
            rows.append(item(user, "forum-draft-title", "edit_title", title=draft.title or label(user, "forum-not-written")))
        rows.append(item(user, "forum-write-body", "edit_body",
                         body=excerpt(draft.body) if draft.body else label(user, "forum-not-written")))
        if draft.poll:
            rows.append(item(user, 'forum-poll-preview', 'poll',
                             question=draft.poll['question'] or label(user, 'forum-not-written')))
        attachments = []
        for attachment_id in draft.attachment_ids:
            attachment = self.service.attachments._row(attachment_id)
            attachments.append(attachment)
            rows.append(item(user, 'forum-media-row', f'attachment:{attachment_id}', name=attachment['name'],
                             status=label(user, 'forum-media-approval-' + attachment['approval']) if attachment['state'] == 'ready'
                             else label(user, 'forum-media-' + attachment['state'])))
        if draft.kind == 'private':
            names = [account.username for user_uuid in draft.recipients
                     if (account := self.service.repository.database.get_user_by_uuid(user_uuid))]
            rows.append(item(user, 'forum-private-recipients', 'recipients',
                             names=', '.join(names) or label(user, 'forum-not-written')))
        if draft.kind != 'edit':
            rows.append(attachment_action(user, 'forum-add-more', 'extras', attachments))
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
        state["_parent_frame"]["_restore_focus_id"] = "edit_title" if title else "edit_body"
        user.remove_editbox(input_id)
        self.server._restore_input_parent(user, state)

    def discard(self, user, draft: Draft) -> None:
        show_confirmation_menu(user, nav.DISCARD, prompt_key="forum-discard-prompt", buffer="system")
        self.server._user_states[user.username] = {"menu": nav.DISCARD, "forum_draft": asdict(draft)}

    def publish(self, user, draft: Draft) -> None:
        poll = draft_poll(draft)
        if poll is not None:
            # Incomplete polls must not send otherwise-private files to review.
            poll = validate_config(poll, int(self.service.clock()))
        if draft.attachment_ids and draft.kind != 'edit':
            validate_text(draft.body)
            if draft.kind in {'topic', 'private'}:
                validate_text(draft.title, title=True)
            if self.service.attachment_reviews.request(user.uuid, draft.attachment_ids):
                user.speak_l('forum-media-review-requested', buffer='system')
                self.server._nav_refresh(user, self.show, draft)
                return
        if draft.kind == "topic":
            topic_id, post_id = self.service.create_topic(user.uuid, draft.category_id, draft.title, draft.body,
                                                         poll=poll, attachment_ids=draft.attachment_ids)
        elif draft.kind == "reply":
            post_id = self.service.reply(user.uuid, draft.topic_id, draft.body, poll=poll, attachment_ids=draft.attachment_ids)
        elif draft.kind == "edit":
            self.service.edit(user.uuid, draft.post_id, draft.body, draft.revision)
            post_id = draft.post_id
        elif draft.kind == 'private':
            topic_id, post_id = self.service.conversations.create(user.uuid, draft.title, draft.body, draft.recipients,
                                                                  poll=poll, attachment_ids=draft.attachment_ids)
        else:
            raise ValueError("Unsupported forum draft")
        # Finish directly on the message list, without briefly rendering old
        # context menus or stacking duplicate pages of the same conversation.
        topic_id = self.service.post(user.uuid, post_id).topic_id
        state = self.server._user_states[user.username]
        stack = list(state.get('_stack', []))
        while stack and stack[-1].get('menu') in {nav.THREAD, nav.POST} and stack[-1].get('forum_topic') == topic_id:
            stack.pop()
        state['_stack'] = stack
        self.open_post(user, post_id)
        user.speak_l("forum-edit-saved" if draft.kind == "edit" else "forum-published", buffer="system")
        self.server.forum_manager.notifications.deliver_post(post_id)

    def open_post(self, user, post_id: int) -> None:
        self.service.post(user.uuid, post_id, mark_read=True)
        self.server._nav_refresh(user, self.server.forum_manager.reader.locate, post_id)
