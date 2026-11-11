"""Atomic mention resolution and bounded, permission-checked forum notices."""

import re

from ..users.identity import username_key
from .models import ForumError
from .repository import _admitted, _visible

MAX_MENTIONS = 10
MAX_NOTIFICATIONS = 500
RETENTION_SECONDS = 90 * 24 * 60 * 60
MENTION_PATTERN = re.compile(r'(?<![\w@\\])@(?:\{([^{}\r\n]{1,30})\}|([^\W_]+))')


def mention_names(body):
    names = {}
    for match in MENTION_PATTERN.finditer(body):
        name = match[1] or match[2]
        names.setdefault(username_key(name), name)
        if len(names) > MAX_MENTIONS:
            raise ForumError('forum-error-mention-limit', limit=MAX_MENTIONS)
    return tuple(names.values())


class ForumNotifications:
    def __init__(self, forum):
        self.forum = forum
        self.repository = forum.repository

    @property
    def connection(self):
        return self.repository.connection

    def prune(self, viewer):
        self.connection.execute('DELETE FROM forum_notifications WHERE user_uuid = ? AND created_at < ?',
                                (viewer, int(self.forum.clock()) - RETENTION_SECONDS))
        self.connection.execute('''DELETE FROM forum_notifications WHERE user_uuid = ? AND post_id IN (
            SELECT post_id FROM forum_notifications WHERE user_uuid = ?
            ORDER BY created_at DESC, post_id DESC LIMIT -1 OFFSET ?)''', (viewer, viewer, MAX_NOTIFICATIONS))

    def record(self, viewer, post_id, body, *, editing=False):
        """Called only inside the post transaction; never sends network output."""
        post = self.forum.post(viewer, post_id)
        targets = []
        for name in mention_names(body):
            account = self.repository.database.get_user(name)
            if not account:
                raise ForumError('forum-error-mention-user', name=name)
            if account.uuid != post.author_uuid:
                targets.append(account.uuid)
        topic = self.forum.topic(viewer, post.topic_id)
        now = int(self.forum.clock())
        historical = {row[0] for row in self.connection.execute(
            'SELECT user_uuid FROM forum_mentions WHERE post_id = ?', (post_id,))}
        if len(historical | set(targets)) > MAX_MENTIONS:
            raise ForumError('forum-error-mention-limit', limit=MAX_MENTIONS)
        # Retain the mention identity after removal/reading, so editing cannot
        # repeatedly notify the same person about the same message.
        old_active = [row[0] for row in self.connection.execute(
            'SELECT user_uuid FROM forum_mentions WHERE post_id = ? AND active = 1', (post_id,))]
        self.connection.execute('UPDATE forum_mentions SET active = 0 WHERE post_id = ?', (post_id,))
        for target in old_active:
            if target not in targets:
                if topic.is_private:
                    self.connection.execute("UPDATE forum_notifications SET kind = 'private' WHERE user_uuid = ? AND post_id = ?",
                                            (target, post_id))
                else:
                    self.connection.execute('DELETE FROM forum_notifications WHERE user_uuid = ? AND post_id = ?', (target, post_id))
        recipients = set()
        if topic.is_private and not editing:
            recipients = {row[0] for row in self.connection.execute(
                'SELECT user_uuid FROM forum_private_members WHERE topic_id = ? AND user_uuid != ?', (topic.id, viewer))}
            for target in recipients:
                if self.can_receive(target, post_id):
                    self.connection.execute('''INSERT OR IGNORE INTO forum_notifications
                        (user_uuid, post_id, kind, created_at) VALUES (?, ?, 'private', ?)''', (target, post_id, now))
        for target in targets:
            if editing and viewer != post.author_uuid and target not in historical:
                continue
            fresh = self.connection.execute('INSERT OR IGNORE INTO forum_mentions(post_id, user_uuid) VALUES (?, ?)',
                                            (post_id, target)).rowcount
            self.connection.execute('UPDATE forum_mentions SET active = 1 WHERE post_id = ? AND user_uuid = ?', (post_id, target))
            if fresh and viewer == post.author_uuid and self.can_receive(target, post_id):
                self.connection.execute('''INSERT INTO forum_notifications(user_uuid, post_id, kind, created_at)
                    VALUES (?, ?, 'mention', ?) ON CONFLICT(user_uuid, post_id) DO UPDATE
                    SET kind = 'mention', announced = 0, created_at = excluded.created_at''', (target, post_id, now))
                recipients.add(target)
        for target in recipients:
            self.prune(target)

    def can_receive(self, viewer, post_id):
        try:
            return not self.forum.post(viewer, post_id).hidden
        except ForumError:
            return False

    def pending(self, viewer):
        self.forum.account(viewer)
        with self.repository.atomic():
            self.prune(viewer)
        # Recheck current membership, hidden posts, topic-author visibility and
        # bilateral blocks at every read. No stored title/body can leak access.
        return [dict(row) for row in self.connection.execute(f'''
            SELECT n.*, p.topic_id, p.author_uuid, p.author_name, t.title,
                   EXISTS(SELECT 1 FROM forum_private_topics ft WHERE ft.topic_id = t.id) AS is_private
            FROM forum_notifications n JOIN forum_posts p ON p.id = n.post_id
            JOIN forum_topics t ON t.id = p.topic_id
            WHERE n.user_uuid = :viewer AND p.hidden = 0 AND p.author_uuid IS NOT NULL
              AND {_visible('p.author_uuid')} AND {_admitted()}
            ORDER BY n.created_at DESC, n.post_id DESC LIMIT :limit''',
            {'viewer': viewer, 'limit': MAX_NOTIFICATIONS})]

    def acknowledge(self, viewer, post_id):
        self.connection.execute('DELETE FROM forum_notifications WHERE user_uuid = ? AND post_id = ?', (viewer, post_id))

    def settings(self, viewer):
        self.forum.account(viewer)
        row = self.connection.execute('SELECT private_alerts, mention_alerts FROM forum_notification_settings WHERE user_uuid = ?',
                                      (viewer,)).fetchone()
        return dict(row) if row else {'private_alerts': 1, 'mention_alerts': 1}

    def set_setting(self, viewer, setting, enabled):
        if setting not in {'private_alerts', 'mention_alerts'}:
            raise ValueError('Unknown forum alert setting')
        with self.repository.atomic():
            self.forum.account(viewer)
            self.connection.execute('INSERT OR IGNORE INTO forum_notification_settings(user_uuid) VALUES (?)', (viewer,))
            self.connection.execute(f'UPDATE forum_notification_settings SET {setting} = ? WHERE user_uuid = ?', (int(enabled), viewer))

    def muted(self, viewer, topic_id):
        return bool(self.connection.execute('SELECT 1 FROM forum_muted_topics WHERE user_uuid = ? AND topic_id = ?',
                                           (viewer, topic_id)).fetchone())

    def set_muted(self, viewer, topic_id, enabled):
        with self.repository.atomic():
            self.forum.topic(viewer, topic_id)
            if enabled:
                self.connection.execute('INSERT OR IGNORE INTO forum_muted_topics VALUES (?, ?)', (viewer, topic_id))
            else:
                self.connection.execute('DELETE FROM forum_muted_topics WHERE user_uuid = ? AND topic_id = ?', (viewer, topic_id))

    def announced(self, viewer, post_ids):
        with self.repository.atomic():
            self.connection.executemany('UPDATE forum_notifications SET announced = 1 WHERE user_uuid = ? AND post_id = ?',
                                        ((viewer, post_id) for post_id in post_ids))
