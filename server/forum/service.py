"""Forum rules and atomic operations; no UI or client-specific branches."""

import time
from collections.abc import Callable

from ..users.roles import ADMIN_TRUST_LEVEL
from .models import EDIT_WINDOW_SECONDS, MAX_WRITES_PER_WINDOW, WRITE_WINDOW_SECONDS, ForumError
from .repository import ForumRepository
from .text import search_key, validate_search, validate_text
from .conversations import ConversationService
from .polls import PollService
from .attachments import AttachmentService
from .attachment_reviews import AttachmentReviews
from .categories import CategoryService
from .languages import ForumLanguages, validate_language
from .notifications import ForumNotifications
from .file_settings import FileSettings


class ForumService:
    def __init__(self, repository: ForumRepository, clock: Callable[[], float] = time.time):
        self.repository = repository
        self.clock = clock
        self.files = FileSettings(self)
        self.conversations = ConversationService(self)
        self.polls = PollService(self)
        self.thread_polls = PollService(self, scope='thread')
        self.attachments = AttachmentService(self)
        self.attachment_reviews = AttachmentReviews(self)
        self.category_admin = CategoryService(self)
        self.languages = ForumLanguages(self)
        self.notifications = ForumNotifications(self)

    def account(self, user_uuid: str, *, writing: bool = False):
        db = self.repository.database
        account = db.get_user_by_uuid(user_uuid)
        if not account or not account.approved or db.get_active_ban(account.username):
            raise ForumError("forum-error-account")
        if writing and db.get_active_mute(account.username):
            raise ForumError("forum-error-muted")
        return account

    def is_moderator(self, user_uuid: str) -> bool:
        return self.account(user_uuid).trust_level >= ADMIN_TRUST_LEVEL

    def categories(self, viewer: str, *, language: str | None = None):
        self.account(viewer)
        return self.repository.categories(viewer, language=validate_language(language) if language is not None else self.languages.current(viewer))

    def topics(self, viewer: str, **options):
        self.account(viewer)
        language = options.get('language')
        options['language'] = validate_language(language) if language is not None else self.languages.current(viewer)
        if options.get("view") == "search":
            options["query"] = search_key(validate_search(options.get("query")))
        if options.get("view") == "category" and not self.repository.has_category(options.get("category_id", "")):
            raise ForumError("forum-error-missing")
        return self.repository.topics(viewer, **options)

    def topic(self, viewer: str, topic_id: int):
        self.account(viewer)
        topic = self.repository.topic(viewer, topic_id)
        if topic is None:
            raise ForumError("forum-error-missing")
        return topic

    def posts(self, viewer: str, topic_id: int, page: int = 1):
        self.topic(viewer, topic_id)
        return self.repository.posts(viewer, topic_id, page)

    def post(self, viewer: str, post_id: int, *, mark_read: bool = False):
        self.account(viewer)
        post = self.repository.post(viewer, post_id)
        if post is None:
            raise ForumError("forum-error-missing")
        if mark_read:
            with self.repository.atomic():
                self.repository.mark_read(viewer, post)
                if not post.hidden:
                    self.notifications.acknowledge(viewer, post.id)
        return post

    def _check_send(self, account, body: str, now: int) -> None:
        since = now - WRITE_WINDOW_SECONDS
        if self.repository.write_count(account.uuid, since) >= MAX_WRITES_PER_WINDOW:
            raise ForumError("forum-error-rate", seconds=WRITE_WINDOW_SECONDS)
        if self.repository.last_body(account.uuid, since) == search_key(body):
            raise ForumError("forum-error-duplicate")

    def create_topic(self, viewer: str, category_id: str, title: str, body: str, *, poll=None,
                     attachment_ids: tuple[str, ...] = ()) -> tuple[int, int]:
        title, body = validate_text(title, title=True), validate_text(body)
        with self.repository.atomic():
            account = self.account(viewer, writing=True)
            if not self.repository.has_category(category_id):
                raise ForumError("forum-error-missing")
            now = int(self.clock())
            self._check_send(account, body, now)
            topic_id, post_id = self.repository.create_topic(account, category_id, title, body, now)
            if poll is not None:
                self.polls.create_in_transaction(viewer, post_id, poll, now)
            self.attachments.bind_in_transaction(viewer, post_id, attachment_ids)
            self.notifications.record(viewer, post_id, body)
            return topic_id, post_id

    def reply(self, viewer: str, topic_id: int, body: str, *, poll=None, attachment_ids: tuple[str, ...] = ()) -> int:
        body = validate_text(body)
        with self.repository.atomic():
            account = self.account(viewer, writing=True)
            topic = self.topic(viewer, topic_id)
            if topic.closed:
                raise ForumError("forum-error-closed")
            now = int(self.clock())
            self._check_send(account, body, now)
            post_id = self.repository.create_post(account, topic_id, body, now)
            if poll is not None:
                self.polls.create_in_transaction(viewer, post_id, poll, now)
            self.attachments.bind_in_transaction(viewer, post_id, attachment_ids)
            self.notifications.record(viewer, post_id, body)
            return post_id

    def can_edit(self, viewer: str, post) -> bool:
        account = self.account(viewer)
        return not post.hidden and (
            account.trust_level >= ADMIN_TRUST_LEVEL and not self.topic(viewer, post.topic_id).is_private or
            post.author_uuid == viewer and int(self.clock()) - post.created_at <= EDIT_WINDOW_SECONDS
        )

    def edit(self, viewer: str, post_id: int, body: str, revision: int) -> None:
        body = validate_text(body)
        with self.repository.atomic():
            self.account(viewer, writing=True)
            post = self.post(viewer, post_id)
            if not self.can_edit(viewer, post):
                raise ForumError("forum-error-edit-permission")
            if self.topic(viewer, post.topic_id).closed and not self.can_moderate(viewer, post.topic_id):
                raise ForumError("forum-error-closed")
            if revision != post.revision:
                raise ForumError("forum-error-conflict")
            self.repository.edit_post(post_id, body, int(self.clock()))
            self.notifications.record(viewer, post_id, body, editing=True)

    def bookmark(self, viewer: str, topic_id: int, saved: bool) -> None:
        with self.repository.atomic():
            self.topic(viewer, topic_id)
            self.repository.bookmark(viewer, topic_id, saved)

    def moderate(self, viewer: str, topic_id: int, action: str, enabled: bool, post_id: int = 0) -> None:
        with self.repository.atomic():
            self.account(viewer, writing=True)
            if not self.can_moderate(viewer, topic_id):
                raise ForumError("forum-error-moderator")
            self.topic(viewer, topic_id)
            if action == "hidden" and self.post(viewer, post_id).topic_id != topic_id:
                raise ForumError("forum-error-missing")
            self.repository.moderate(viewer, topic_id, action, enabled, int(self.clock()), post_id)

    def can_moderate(self, viewer: str, topic_id: int) -> bool:
        topic = self.topic(viewer, topic_id)
        if topic.is_private:
            return self.conversations.owner(viewer, topic_id)
        return self.is_moderator(viewer)
