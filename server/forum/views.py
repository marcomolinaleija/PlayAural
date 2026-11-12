"""Content-first forum views: context is announced; actions follow content."""

from datetime import datetime, timezone

from ..menu_pagination import pagination_menu_items
from ..messages.localization import Localization
from ..messages.relative_time import format_relative_time
from ..users.base import EscapeBehavior, MenuItem
from . import navigation as nav
from .models import ForumError
from .text import excerpt


def label(user, key: str, **values) -> str:
    return Localization.get(user.locale, key, **values)


def item(user, key: str, item_id: str, *, read_only: bool = False, **values) -> MenuItem:
    return MenuItem(text=label(user, key, **values), id=item_id, read_only=read_only)


def category_name(user, category) -> str:
    return category.name or Localization.get(category.language, f"forum-category-{category.id.rsplit(':', 1)[-1]}")


def author(user, record) -> str:
    return record.author_name if record.author_uuid else label(user, "forum-deleted-account")


def attachment_action(user, key: str, item_id: str, attachments) -> MenuItem:
    """Keep attachment feedback on its action, including failed preparation."""
    action = label(user, key)
    if not attachments:
        return MenuItem(text=action, id=item_id)
    parts = [label(user, 'forum-media-selected-count', count=len(attachments))]
    for state in ('ready', 'failed'):
        count = sum(row['state'] == state for row in attachments)
        if count or state == 'ready':
            parts.append(label(user, 'forum-media-count-' + state, count=count))
    return MenuItem(text=label(user, 'forum-media-action-summary', action=action, summary='; '.join(parts)), id=item_id)


def age(user, timestamp: int) -> str:
    return format_relative_time(user.locale, datetime.fromtimestamp(timestamp, timezone.utc))


class ForumViews:
    def __init__(self, server, service):
        self.server = server
        self.service = service

    @staticmethod
    def identity(state: dict) -> tuple:
        return tuple(state.get(key) for key in (
            "menu", "forum_topic", "forum_post", "forum_view", "forum_category", "forum_query", "forum_page", 'forum_invitation', 'forum_attachment', 'forum_language',
        ))

    def render(self, user, menu: str, rows: list[MenuItem], *, title: str,
               announcement: tuple[str, dict], **state) -> None:
        before = self.server._user_states.get(user.username, {})
        next_state = {"menu": menu, **state}
        previous_visible = getattr(user, "_last_menu_packet_id", menu)
        entering = (self.identity(before) != self.identity(next_state)
                    or previous_visible not in {None, menu})
        rows.append(item(user, "back", "back"))
        user.show_menu(menu, rows, title=title, multiletter=True, escape_behavior=EscapeBehavior.SELECT_LAST)
        self.server._user_states[user.username] = next_state
        if entering:
            key, values = announcement
            user.speak_l(key, buffer="misc", history=False, **values)

    def home(self, user, language: str | None = None) -> None:
        language = language or self.service.languages.current(user.uuid)
        language_name = label(user, 'forum-language-' + language)
        rows = [item(user, 'forum-private', 'private'), item(user, 'forum-recent', 'recent')]
        rows.extend(item(user, "forum-category-row", f"category:{category.id}",
                     name=category_name(user, category), count=category.topic_count)
                    for category in self.service.categories(user.uuid, language=language))
        rows.extend([item(user, "forum-unread", "unread"),
                     item(user, "forum-saved", "saved"), item(user, "forum-search", "search")])
        rows.extend([item(user, 'forum-notifications', 'notifications'),
                     item(user, 'forum-notification-settings', 'notification_settings')])
        if self.service.attachments.require_approval and self.service.is_moderator(user.uuid):
            rows.append(item(user, 'forum-media-review-heading', 'review_media'))
        if self.service.is_moderator(user.uuid):
            rows.append(item(user, 'forum-categories-manage', 'manage_categories'))
        rows.append(item(user, 'forum-language-current', 'language', language=language_name))
        self.render(user, nav.HOME, rows, title=label(user, "forum-heading-language", language=language_name),
                    announcement=("forum-entry-home-language", {'language': language_name}), forum_language=language)

    def topics(self, user, view: str = "recent", category_id: str = "", query: str = "", page: int = 1,
               language: str | None = None) -> None:
        category = self.service.repository.category(category_id) if view == 'category' else None
        language = category.language if category else language or self.service.languages.current(user.uuid)
        data = self.service.topics(user.uuid, view=view, category_id=category_id, query=query, page=page, language=language)
        heading = category_name(user, category) if category else label(user, f"forum-{view}")
        rows = []
        for topic in data.items:
            flags = []
            if view == "saved" and topic.is_private:
                flags.append(label(user, "forum-private"))
            if topic.pinned:
                flags.append(label(user, "forum-pinned"))
            if topic.closed:
                flags.append(label(user, "forum-closed"))
            flags.append(label(user, "forum-unread-count", count=topic.unread_count)
                         if topic.unread_count else label(user, "forum-read"))
            rows.append(item(user, "forum-topic-row", f"topic:{topic.id}", title=topic.title,
                             author=author(user, topic), count=topic.post_count, age=age(user, topic.last_activity),
                             status=Localization.format_list(user.locale, flags)))
        if view == "category":
            rows.append(item(user, "forum-new-topic", "new_topic"))
        elif view == 'private':
            rows.append(item(user, 'forum-private-new', 'new_private'))
            invitations = self.service.conversations.invitations(user.uuid)
            rows.append(item(user, 'forum-private-invitations-count', 'invitations', count=len(invitations)))
        rows.extend(self.page_controls(user, data))
        context = {"title": heading, "count": data.total, "page": data.page, "pages": data.total_pages,
                   "empty": label(user, "forum-no-topics") if not data.total else ""}
        if query:
            context["query"] = query
        if category:
            context['description'] = category.description
        self.render(user, nav.TOPICS, rows, title=heading,
                    announcement=("forum-entry-search" if query else "forum-entry-category" if category else "forum-entry-topics", context),
                    forum_view=view, forum_category=category_id, forum_query=query,
                    forum_page=data.page, forum_pages=data.total_pages, forum_language=language)

    @staticmethod
    def page_controls(user, data) -> list[MenuItem]:
        rows = pagination_menu_items(user.locale, data)
        rows.append(item(user, "menu-page-refresh", "refresh"))
        return rows

    def thread(self, user, topic_id: int, page: int | None = None) -> None:
        topic = self.service.topic(user.uuid, topic_id)
        category = None if topic.is_private else self.service.repository.category(topic.category_id)
        language = category.language if category else None
        resume = self.service.repository.resume_post(user.uuid, topic_id)
        if page is None:
            target = resume or topic.last_post_id
            page = self.service.repository.post_page(user.uuid, topic_id, target)
        data = self.service.posts(user.uuid, topic_id, page)
        rows = []
        for post in data.items:
            text = label(user, 'forum-post-row', author=author(user, post), age=age(user, post.created_at),
                         body=label(user, 'forum-hidden-post') if post.hidden else excerpt(post.body))
            if post.has_poll:
                text = label(user, 'forum-post-with-poll', text=text)
            rows.append(MenuItem(text=text, id=f'post:{post.id}'))
        if self.service.thread_polls.exists(topic_id):
            try:
                poll = self.service.thread_polls.get(user.uuid, topic_id)
            except ForumError as error:
                if error.key != 'forum-error-missing':
                    raise
            else:
                rows.insert(0, item(user, 'forum-thread-poll-row', 'thread_poll', question=poll['question'],
                                    status=label(user, 'forum-poll-closed' if poll['closed'] or topic.closed else 'forum-thread-poll-open')))
        if not topic.closed:
            rows.append(item(user, "forum-reply", "reply"))
            if self.service.thread_polls.can_create(user.uuid, topic_id):
                rows.append(item(user, 'forum-thread-poll-create', 'create_thread_poll'))
        rows.append(item(user, 'forum-notification-unmute-topic' if self.service.notifications.muted(user.uuid, topic_id)
                         else 'forum-notification-mute-topic', 'mute_notifications'))
        rows.append(item(user, "forum-unsave" if topic.bookmarked else "forum-save", "bookmark"))
        if resume:
            rows.append(item(user, "forum-continue", "continue"))
        rows.extend(self.page_controls(user, data))
        if topic.is_private:
            rows.append(item(user, 'forum-private-members', 'members'))
            if self.service.attachments.require_approval and self.service.conversations.owner(user.uuid, topic_id):
                rows.append(item(user, 'forum-media-review-heading', 'review_media'))
        if self.service.can_moderate(user.uuid, topic_id):
            rows.extend([
                item(user, "forum-reopen" if topic.closed else "forum-close", "toggle_closed"),
                item(user, "forum-unpin" if topic.pinned else "forum-pin", "toggle_pinned"),
            ])
        if not topic.is_private and topic.author_uuid != user.uuid:
            rows.append(item(user, 'forum-report-thread', 'report_thread'))
        self.render(user, nav.THREAD, rows, title=topic.title,
                    announcement=("forum-entry-thread" if topic.is_private else "forum-entry-thread-language", {
                        "language": label(user, "forum-language-" + language) if language else "",
                        "title": topic.title, "author": author(user, topic),
                        "category": (label(user, 'forum-private') if topic.is_private
                                     else category_name(user, category)),
                        "count": topic.post_count,
                        "status": label(user, "forum-closed-help" if topic.closed else "forum-open-help"),
                        "page": data.page, "pages": data.total_pages,
                    }), forum_topic=topic_id, forum_page=data.page, forum_pages=data.total_pages, forum_language=language)

    def post(self, user, post_id: int) -> None:
        post = self.service.post(user.uuid, post_id)
        topic = self.service.topic(user.uuid, post.topic_id)
        category = None if topic.is_private else self.service.repository.category(topic.category_id)
        language = category.language if category else None
        if post.hidden:
            rows = []
        else:
            rows = [item(user, 'forum-post-speak', 'speak_body'), item(user, 'forum-post-text', 'read_body')]
            rows.extend(item(user, 'forum-media-post-row', f"attachment:{attachment['id']}", name=attachment['name'],
                             kind=label(user, 'forum-media-kind-' + attachment['kind']))
                        for attachment in self.service.attachments.for_post(user.uuid, post_id))
            if post.has_poll:
                poll = self.service.polls.get(user.uuid, post_id)
                rows.append(item(user, 'forum-poll-preview', 'poll', question=poll['question']))
        next_post = self.service.repository.resume_post(user.uuid, post.topic_id)
        if next_post:
            rows.append(item(user, "forum-next-unread", "next_unread"))
        if not topic.closed:
            rows.append(item(user, "forum-reply", "reply"))
        if self.service.can_edit(user.uuid, post) and (not topic.closed or self.service.can_moderate(user.uuid, topic.id)):
            rows.append(item(user, "forum-edit", "edit"))
        if self.service.can_moderate(user.uuid, topic.id):
            rows.append(item(user, "forum-restore-post" if post.hidden else "forum-hide-post", "toggle_hidden"))
        if not topic.is_private and not post.hidden and post.author_uuid != user.uuid:
            rows.append(item(user, 'forum-report-post', 'report_post'))
        self.render(user, nav.POST, rows, title=label(user, 'forum-post-actions'),
                    announcement=("forum-entry-post" if topic.is_private else "forum-entry-post-language", {
                        "language": label(user, "forum-language-" + language) if language else "",
                        "title": topic.title, "author": author(user, post), "age": age(user, post.created_at),
                        "edited": label(user, "forum-edited", age=age(user, post.edited_at)) if post.edited_at else "",
                    }), forum_topic=post.topic_id, forum_post=post.id, forum_language=language)
        if post.hidden:
            user.speak_l('forum-hidden-post', buffer='misc', history=False)
