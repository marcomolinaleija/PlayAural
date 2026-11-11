"""Small integration boundary between server navigation and the forum domain."""

from ..menu_pagination import page_for_selection
from ..ui.confirmation import show_confirmation_menu
from . import navigation as nav
from .composer import ForumComposer
from .models import Draft, ForumError, MAX_SEARCH_LENGTH
from .repository import ForumRepository
from .service import ForumService
from .text import validate_search
from .views import ForumViews, label
from .poll_ui import PollController
from .private_ui import PrivateController
from .media_ui import MediaController
from .review_ui import ReviewController


class ForumManager:
    def __init__(self, server):
        self.server = server
        self.service = ForumService(ForumRepository(server.db))
        self.views = ForumViews(server, self.service)
        self.composer = ForumComposer(server, self.service, self.views)
        self.polls = PollController(self)
        self.private = PrivateController(self)
        self.media = None
        self.media_ui = MediaController(self)
        self.reviews = ReviewController(self)

    def home(self, user) -> None:
        self.views.home(user)

    def restore(self, user, frame: dict) -> None:
        menu = frame["menu"]
        try:
            if menu == nav.HOME:
                self.views.home(user)
            elif menu == nav.TOPICS:
                self.views.topics(user, frame.get("forum_view", "recent"), frame.get("forum_category", ""),
                                  frame.get("forum_query", ""), frame.get("forum_page", 1))
            elif menu == nav.THREAD:
                self.views.thread(user, frame["forum_topic"], frame.get("forum_page"))
            elif menu == nav.POST:
                self.views.post(user, frame["forum_post"])
            elif menu == nav.COMPOSER:
                self.composer.show(user, self.composer.draft(frame))
            elif menu == nav.ATTACHMENT:
                self.media_ui.attachment(user, self.composer.draft(frame), frame['forum_attachment'])
            elif menu in nav.CONFIRMATION_IDS:
                # A confirmation's authority never crosses a reconnect.
                self.views.home(user)
            elif not (self.polls.restore(user, frame) or self.private.restore(user, frame) or self.reviews.restore(user, frame)):
                self.views.home(user)
        except ForumError as error:
            user.speak_l(error.key, buffer="system", **error.values)
            if error.key == "forum-error-account":
                self.server._show_main_menu(user)
            else:
                self.views.home(user)

    def handle_menu(self, user, selection: str, state: dict) -> None:
        try:
            self._handle_menu(user, selection, state)
        except ForumError as error:
            user.speak_l(error.key, buffer="system", **error.values)
            if error.key == "forum-error-missing" and state["menu"] not in {nav.COMPOSER, nav.EXTRAS, nav.POLL_EDITOR}:
                self.server._nav_refresh(user, self.home)

    def _handle_menu(self, user, selection: str, state: dict) -> None:
        menu = state["menu"]
        self.service.account(user.uuid)
        push, refresh = self.server._nav_push, self.server._nav_refresh
        if selection == "back":
            if menu == nav.COMPOSER:
                draft = self.composer.draft(state)
                if draft.title or draft.body or draft.poll or draft.recipients or draft.attachment_ids:
                    push(user, self.composer.discard, draft)
                    return
            self.server._nav_back(user)
            return
        if (self.reviews.handle(user, selection, state) or self.media_ui.handle(user, selection, state) or self.polls.handle(user, selection, state)
                or self.private.handle(user, selection, state)):
            return
        if menu == nav.HOME:
            if selection in {"recent", "unread", "saved"}:
                push(user, self.views.topics, selection)
            elif selection.startswith("category:"):
                push(user, self.views.topics, "category", selection.removeprefix("category:"))
            elif selection == "search":
                self.server.enter_input_state(user, nav.SEARCH_INPUT)
                user.show_editbox(nav.SEARCH_INPUT, label(user, "forum-search-prompt"), max_length=MAX_SEARCH_LENGTH)
            elif selection == 'private':
                push(user, self.views.topics, 'private')
        elif menu == nav.TOPICS:
            if selection == "new_topic":
                push(user, self.composer.show, Draft("topic", category_id=state["forum_category"]))
            elif selection == 'new_private':
                push(user, self.composer.show, Draft('private'))
            elif selection == 'invitations':
                push(user, self.private.invitations)
            elif selection.startswith("topic:"):
                push(user, self.views.thread, int(selection.removeprefix("topic:")))
            else:
                page = page_for_selection(selection, state["forum_page"], state["forum_pages"])
                if page is not None:
                    refresh(user, self.views.topics, state["forum_view"], state["forum_category"], state["forum_query"], page)
        elif menu == nav.THREAD:
            topic_id = state["forum_topic"]
            topic = self.service.topic(user.uuid, topic_id)
            if selection == "reply":
                push(user, self.composer.show, Draft("reply", topic_id=topic_id))
            elif selection == 'members' and topic.is_private:
                push(user, self.private.members, topic_id)
            elif selection == "bookmark":
                self.service.bookmark(user.uuid, topic_id, not topic.bookmarked)
                user.speak_l("forum-saved-feedback" if not topic.bookmarked else "forum-unsaved-feedback", buffer="system")
                refresh(user, self.views.thread, topic_id, state["forum_page"])
            elif selection == "continue":
                post_id = self.service.repository.resume_post(user.uuid, topic_id)
                if post_id:
                    push(user, self.views.post, post_id)
                else:
                    refresh(user, self.views.thread, topic_id, state["forum_page"])
            elif selection.startswith("post:"):
                push(user, self.views.post, int(selection.removeprefix("post:")))
            elif selection in {"toggle_closed", "toggle_pinned"}:
                action = selection.removeprefix("toggle_")
                push(user, self.confirm_moderation, topic_id, action, not getattr(topic, action))
            else:
                page = page_for_selection(selection, state["forum_page"], state["forum_pages"])
                if page is not None:
                    refresh(user, self.views.thread, topic_id, page)
        elif menu == nav.POST:
            post = self.service.post(user.uuid, state["forum_post"])
            if selection == "reply":
                push(user, self.composer.show, Draft("reply", topic_id=post.topic_id))
            elif selection == 'poll':
                push(user, self.polls.ballot, post.id)
            elif selection == "edit":
                if not self.service.can_edit(user.uuid, post):
                    raise ForumError("forum-error-edit-permission")
                push(user, self.composer.show, Draft("edit", topic_id=post.topic_id, post_id=post.id,
                                                   revision=post.revision, body=post.body))
            elif selection == "next_unread":
                next_post = self.service.repository.resume_post(user.uuid, post.topic_id)
                if next_post:
                    refresh(user, self.views.post, next_post)
            elif selection == "toggle_hidden":
                push(user, self.confirm_moderation, post.topic_id, "hidden", not post.hidden, post.id)
        elif menu == nav.COMPOSER:
            draft = self.composer.draft(state)
            if selection in {"edit_title", "edit_body"}:
                self.composer.begin_input(user, draft, title=selection == "edit_title")
            elif selection == "publish":
                self.composer.publish(user, draft)
            elif selection == 'extras' and draft.kind != 'edit':
                push(user, self.polls.extras, draft)
            elif selection == 'recipients' and draft.kind == 'private':
                self.private.edit_recipients(user, draft)
        elif menu == nav.DISCARD:
            if selection == "yes":
                for attachment_id in self.composer.draft(state).attachment_ids:
                    self.service.attachments.discard(user.uuid, attachment_id)
                self.server._nav_back(user)
                self.server._nav_back(user)
                user.speak_l("forum-draft-discarded", buffer="system")
            elif selection == "no":
                self.server._nav_back(user)
        elif menu == nav.MODERATE:
            if selection == "yes":
                self.service.moderate(user.uuid, state["forum_topic"], state["forum_action"],
                                      state["forum_enabled"], state["forum_post"])
                self.server._nav_back(user)
                user.speak_l("forum-moderation-saved", buffer="system")
            elif selection == "no":
                self.server._nav_back(user)

    def confirm_moderation(self, user, topic_id: int, action: str, enabled: bool, post_id: int = 0) -> None:
        if not self.service.can_moderate(user.uuid, topic_id):
            raise ForumError("forum-error-moderator")
        topic = self.service.topic(user.uuid, topic_id)
        verb = {("closed", True): "close", ("closed", False): "reopen",
                ("pinned", True): "pin", ("pinned", False): "unpin",
                ("hidden", True): "hide-post", ("hidden", False): "restore-post"}[(action, enabled)]
        show_confirmation_menu(user, nav.MODERATE, prompt_key="forum-moderation-prompt", buffer="system",
                               prompt_kwargs={"action": label(user, f"forum-{verb}"), "title": topic.title})
        self.server._user_states[user.username] = {"menu": nav.MODERATE, "forum_topic": topic_id,
                                                  "forum_action": action, "forum_enabled": enabled,
                                                  "forum_post": post_id}

    def handle_input(self, user, packet: dict, state: dict) -> None:
        if state["menu"] not in nav.INPUT_IDS or packet.get("input_id") != state["menu"]:
            return
        if state["menu"] in {nav.TITLE_INPUT, nav.BODY_INPUT}:
            self.composer.handle_input(user, packet, state)
            return
        if state['menu'] in nav.POLL_INPUT_IDS:
            self.polls.handle_input(user, packet, state)
            return
        if state['menu'] in nav.PRIVATE_INPUT_IDS:
            self.private.handle_input(user, packet, state)
            return
        if state['menu'] == nav.MEDIA_DESCRIPTION_INPUT:
            self.media_ui.handle_input(user, packet, state)
            return
        if packet.get("input_id") != nav.SEARCH_INPUT:
            return
        if packet.get("cancelled"):
            user.remove_editbox(nav.SEARCH_INPUT)
            self.server._restore_input_parent(user, state)
            return
        try:
            query = validate_search(packet.get("text"))
        except ForumError as error:
            user.speak_l(error.key, buffer="system", **error.values)
            user.show_editbox(nav.SEARCH_INPUT, label(user, "forum-search-prompt"), max_length=MAX_SEARCH_LENGTH)
            return
        user.remove_editbox(nav.SEARCH_INPUT)
        self.server._nav_push_from_input(user, self.views.topics, "search", "", query)
