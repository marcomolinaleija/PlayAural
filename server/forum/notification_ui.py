"""Shared-menu inbox and post-commit speech delivery, without client protocols."""

from ..menu_pagination import PaginatedMenuPage, clamp_page, page_for_selection
from . import navigation as nav
from .models import ForumError, TOPICS_PER_PAGE
from .views import item, label


class NotificationController:
    def __init__(self, manager):
        self.manager = manager
        self.server, self.service, self.views = manager.server, manager.service, manager.views
        self.notices = self.service.notifications

    def grouped(self, user):
        groups = {}
        for notice in self.notices.pending(user.uuid):
            key = ('private', notice['topic_id']) if notice['kind'] == 'private' else ('mention', notice['post_id'])
            if key not in groups:
                groups[key] = {**notice, 'count': 1}
            else:
                groups[key]['count'] += 1
                # Open the first pending message in a grouped private notice.
                groups[key]['post_id'] = min(groups[key]['post_id'], notice['post_id'])
        return list(groups.values())

    def enter(self, user):
        # Preflight before pushing: an empty inbox must not add a blank menu
        # or a duplicate return frame. Refresh/reconnect use the same guard.
        if not self.grouped(user):
            user.speak_l('forum-notifications-empty', buffer='system', history=False)
            return
        self.server._nav_push(user, self.show)

    def show(self, user, page=1):
        notices = self.grouped(user)
        if not notices:
            user.speak_l('forum-notifications-empty', buffer='system', history=False)
            if self.server._user_states.get(user.username, {}).get('menu') == nav.NOTIFICATIONS:
                self.server._nav_back(user)
            return
        page = clamp_page(page, len(notices), TOPICS_PER_PAGE)
        data = PaginatedMenuPage(notices[(page - 1) * TOPICS_PER_PAGE:page * TOPICS_PER_PAGE], len(notices), page, TOPICS_PER_PAGE)
        rows = [item(user, 'forum-notification-mention' if n['kind'] == 'mention' else 'forum-notification-private-group',
                     f"notice:{n['post_id']}", name=n['author_name'], title=n['title'], **({'count': n['count']} if n['kind'] == 'private' else {}))
                for n in data.items]
        rows.extend(self.views.page_controls(user, data))
        self.views.render(user, nav.NOTIFICATIONS, rows, title=label(user, 'forum-notifications'),
                          announcement=('forum-notifications-entry', {'count': len(notices), 'page': page, 'pages': data.total_pages}),
                          forum_page=page, forum_pages=data.total_pages)

    def settings(self, user):
        settings = self.notices.settings(user.uuid)
        rows = [item(user, 'forum-notification-' + key.replace('_', '-'), key,
                     status=label(user, 'option-on' if value else 'option-off')) for key, value in settings.items()]
        self.views.render(user, nav.NOTIFICATION_SETTINGS, rows, title=label(user, 'forum-notification-settings'),
                          announcement=('forum-notification-settings-help', {}))

    def handle(self, user, selection, state):
        if state['menu'] == nav.HOME:
            if selection == 'notifications':
                self.enter(user)
            elif selection == 'notification_settings':
                self.server._nav_push(user, self.settings)
            else:
                return False
        elif state['menu'] == nav.NOTIFICATIONS:
            if selection.startswith('notice:'):
                post_id = int(selection.removeprefix('notice:'))
                if not any(n['post_id'] == post_id for n in self.grouped(user)):
                    user.speak_l('forum-notification-unavailable', buffer='system')
                    self.server._nav_refresh(user, self.show, state.get('forum_page', 1))
                else:
                    self.server._nav_push(user, self.manager.reader.open, post_id)
            else:
                page = page_for_selection(selection, state['forum_page'], state['forum_pages'])
                if page is not None:
                    self.server._nav_refresh(user, self.show, page)
        elif state['menu'] == nav.NOTIFICATION_SETTINGS:
            settings = self.notices.settings(user.uuid)
            if selection in settings:
                self.notices.set_setting(user.uuid, selection, not settings[selection])
                self.server._nav_refresh(user, self.settings)
        elif state['menu'] == nav.THREAD and selection == 'mute_notifications':
            topic_id = state['forum_topic']
            enabled = not self.notices.muted(user.uuid, topic_id)
            self.notices.set_muted(user.uuid, topic_id, enabled)
            user.speak_l('forum-notification-muted' if enabled else 'forum-notification-unmuted', buffer='system')
            self.server._nav_refresh(user, self.views.thread, topic_id, state['forum_page'])
        else:
            return False
        return True

    def restore(self, user, state):
        if state['menu'] == nav.NOTIFICATIONS:
            self.show(user, state.get('forum_page', 1))
        elif state['menu'] == nav.NOTIFICATION_SETTINGS:
            self.settings(user)
        else:
            return False
        return True

    def deliver_post(self, post_id):
        # Publishing already committed. Offline recipients keep the same rows
        # for login; network delivery never runs in a database transaction.
        recipients = [row[0] for row in self.notices.connection.execute(
            'SELECT user_uuid FROM forum_notifications WHERE post_id = ? AND announced = 0', (post_id,))]
        for recipient in recipients:
            account = self.server.db.get_user_by_uuid(recipient)
            user = self.server._users.get(account.username) if account else None
            if user:
                self.deliver(user, post_id=post_id)

    def deliver(self, user, *, post_id=None):
        if not self.server.forum_enabled:
            return
        try:
            pending = self.notices.pending(user.uuid)
            settings = self.notices.settings(user.uuid)
        except ForumError:
            return
        fresh = [n for n in pending if not n['announced'] and (post_id is None or n['post_id'] == post_id)]
        if not fresh:
            return
        state = self.server._user_states.get(user.username, {})
        reading_topic = state.get('forum_topic') if state.get('menu') in {nav.THREAD, nav.POST, nav.BODY_READER} else None
        if state.get('menu') == nav.BODY_READER:
            reading_topic = state.get('_parent_frame', {}).get('forum_topic')
        audible = [n for n in fresh if settings['mention_alerts' if n['kind'] == 'mention' else 'private_alerts']
                   and not self.notices.muted(user.uuid, n['topic_id']) and n['topic_id'] != reading_topic]
        if post_id is None:
            if audible:
                count = len({(n['kind'], n['topic_id'] if n['kind'] == 'private' else n['post_id']) for n in audible})
                user.speak_l('forum-notification-summary', count=count, buffer='system')
        else:
            for notice in audible:
                # One private alert until its pending activity is consulted.
                if notice['kind'] == 'private' and any(
                    n['kind'] == 'private' and n['announced'] and n['topic_id'] == notice['topic_id'] for n in pending
                ):
                    continue
                key = 'forum-notification-mention' if notice['kind'] == 'mention' else 'forum-notification-private'
                user.speak_l(key, name=notice['author_name'], title=notice['title'], buffer='system')
        self.notices.announced(user.uuid, [n['post_id'] for n in fresh])
