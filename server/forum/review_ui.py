"""Contextual moderation of explicitly submitted attachments."""

from ..menu_pagination import page_for_selection
from ..ui.confirmation import show_confirmation_menu
from . import navigation as nav
from .models import ForumError
from .views import item, label


class ReviewController:
    def __init__(self, manager):
        self.manager, self.server, self.service = manager, manager.server, manager.service

    def pending(self, user, topic_id: int = 0, page: int = 1) -> None:
        data = self.service.attachment_reviews.pending(user.uuid, topic_id=topic_id, page=page)
        rows = [item(user, 'forum-media-review-row', f"review:{row['id']}", name=row['name'],
                     author=row['owner_name'] or label(user, 'forum-deleted-account')) for row in data.items]
        rows.extend(self.manager.views.page_controls(user, data))
        self.manager.views.render(user, nav.PENDING_MEDIA, rows, title=label(user, 'forum-media-review-heading'),
                                  announcement=('forum-entry-reviews', {'count': data.total, 'page': data.page, 'pages': data.total_pages}),
                                  forum_topic=topic_id, forum_page=data.page, forum_pages=data.total_pages)

    def review(self, user, attachment_id: str) -> None:
        row = self.service.attachments._row(attachment_id)
        if not self.service.attachment_reviews.allowed(user.uuid, row):
            raise ForumError('forum-error-missing')
        rows = [item(user, 'forum-media-post-row', 'open', name=row['name'], kind=label(user, 'forum-media-kind-' + row['kind']))]
        if row['description']:
            rows.append(item(user, 'forum-media-description-text', 'description', read_only=True, text=row['description']))
        rows.extend([item(user, 'forum-media-approve', 'approve'), item(user, 'forum-media-reject', 'reject')])
        self.manager.views.render(user, nav.REVIEW_MEDIA, rows, title=row['name'],
                                  announcement=('forum-entry-simple', {'title': row['name']}),
                                  forum_attachment=attachment_id, forum_topic=row['context_topic_id'] or 0)

    def confirm(self, user, attachment_id: str, approve: bool) -> None:
        row = self.service.attachments._row(attachment_id)
        if not self.service.attachment_reviews.allowed(user.uuid, row):
            raise ForumError('forum-error-missing')
        show_confirmation_menu(user, nav.CONFIRM_MEDIA_REVIEW, prompt_key='forum-media-review-prompt', buffer='system',
                               prompt_kwargs={'action': label(user, 'forum-media-approve' if approve else 'forum-media-reject'), 'name': row['name']})
        self.server._user_states[user.username] = {'menu': nav.CONFIRM_MEDIA_REVIEW, 'forum_attachment': attachment_id, 'forum_approve': approve}

    def restore(self, user, state: dict) -> bool:
        if state['menu'] == nav.PENDING_MEDIA:
            self.pending(user, state.get('forum_topic', 0), state.get('forum_page', 1))
        elif state['menu'] == nav.REVIEW_MEDIA:
            self.review(user, state['forum_attachment'])
        else:
            return False
        return True

    def handle(self, user, selection: str, state: dict) -> bool:
        menu = state['menu']
        push, refresh = self.server._nav_push, self.server._nav_refresh
        if menu == nav.HOME and selection == 'review_media':
            push(user, self.pending)
        elif menu == nav.THREAD and selection == 'review_media':
            push(user, self.pending, state['forum_topic'])
        elif menu == nav.PENDING_MEDIA:
            if selection.startswith('review:'):
                push(user, self.review, selection.removeprefix('review:'))
            else:
                page = page_for_selection(selection, state['forum_page'], state['forum_pages'])
                if page is not None:
                    refresh(user, self.pending, state['forum_topic'], page)
        elif menu == nav.REVIEW_MEDIA:
            attachment_id = state['forum_attachment']
            if selection == 'open':
                self.manager.media_ui.open(user, attachment_id)
            elif selection in {'approve', 'reject'}:
                push(user, self.confirm, attachment_id, selection == 'approve')
        elif menu == nav.CONFIRM_MEDIA_REVIEW:
            if selection == 'yes':
                row = self.service.attachment_reviews.review(user.uuid, state['forum_attachment'], approve=state['forum_approve'])
                state['_stack'] = [frame for frame in state.get('_stack', [])
                                   if not (frame.get('menu') == nav.REVIEW_MEDIA and frame.get('forum_attachment') == row['id'])]
                self.server._nav_back(user)
                self.notify_owner(row)
                user.speak_l('forum-media-review-saved', buffer='system')
            elif selection == 'no':
                self.server._nav_back(user)
        else:
            return False
        return True

    def notify_owner(self, row):
        account = self.service.repository.database.get_user_by_uuid(row['owner_uuid'])
        user = self.server._users.get(account.username) if account else None
        if not user:
            return
        state = self.server._user_states.get(user.username, {})
        if state.get('menu') == nav.COMPOSER and row['id'] in state.get('forum_draft', {}).get('attachment_ids', ()):
            self.server._nav_refresh(user, self.manager.composer.show, self.manager.composer.draft(state))
        user.speak_l('forum-media-review-notice', name=row['name'],
                     status=label(user, 'forum-media-approval-' + row['approval']), buffer='system')
