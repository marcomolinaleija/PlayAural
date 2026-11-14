"""Optional human approval without granting staff private-conversation access."""

from ..menu_pagination import PaginatedMenuPage, clamp_page
from .models import ForumError, TOPICS_PER_PAGE
from .repository import _visible


class AttachmentReviews:
    def __init__(self, forum):
        self.forum, self.repository = forum, forum.repository

    @property
    def connection(self):
        return self.repository.connection

    def allowed(self, viewer: str, row) -> bool:
        self.forum.account(viewer)
        if row['published'] or row['state'] != 'ready' or row['approval'] != 'pending' or row['expires_at'] <= self.forum.clock():
            return False
        if not self.connection.execute(f'SELECT 1 WHERE {_visible(":owner")}', {'viewer': viewer, 'owner': row['owner_uuid']}).fetchone():
            return False
        if row['private']:
            try:
                return bool(row['context_topic_id'] and self.forum.conversations.owner(viewer, row['context_topic_id']))
            except ForumError:
                return False
        return self.forum.is_moderator(viewer)

    def request(self, viewer: str, attachment_ids: tuple[str, ...]) -> bool:
        """Publish is the user's explicit consent to share files for review."""
        with self.repository.atomic():
            self.forum.account(viewer, writing=True)
            rows = [self.forum.attachments._row(attachment_id) for attachment_id in attachment_ids]
            for row in rows:
                if row['owner_uuid'] != viewer or row['published'] or row['expires_at'] <= self.forum.clock():
                    raise ForumError('forum-error-media-owner')
                if row['state'] != 'ready' or row['approval'] == 'rejected':
                    raise ForumError('forum-error-media-not-ready')
                if row['context_topic_id']:
                    topic = self.forum.topic(viewer, row['context_topic_id'])
                    if topic.closed:
                        raise ForumError('forum-error-closed')
            for row in rows:
                if row['approval'] == 'unsubmitted':
                    self.connection.execute("UPDATE forum_attachments SET approval = 'pending' WHERE id = ?", (row['id'],))
            return any(row['approval'] in {'unsubmitted', 'pending'} for row in rows)

    def pending(self, viewer: str, *, topic_id: int = 0, page: int = 1):
        self.forum.account(viewer)
        if topic_id:
            if not self.forum.conversations.owner(viewer, topic_id):
                raise ForumError('forum-error-private-owner')
            scope = 'a.private = 1 AND a.context_topic_id = :topic'
        else:
            if not self.forum.is_moderator(viewer):
                raise ForumError('forum-error-moderator')
            scope = 'a.private = 0'
        base = f"""FROM forum_attachments a LEFT JOIN users u ON u.uuid = a.owner_uuid
                   WHERE a.approval = 'pending' AND a.state = 'ready' AND a.published = 0 AND a.expires_at > :now
                   AND {scope} AND {_visible('a.owner_uuid')}"""
        params = {'viewer': viewer, 'topic': topic_id, 'now': int(self.forum.clock())}
        total = self.connection.execute('SELECT COUNT(*) ' + base, params).fetchone()[0]
        safe_page = clamp_page(page, total, TOPICS_PER_PAGE)
        rows = self.connection.execute('SELECT a.*, COALESCE(u.username, \'\') AS owner_name ' + base +
                                       ' ORDER BY a.created_at, a.id LIMIT :limit OFFSET :offset',
                                       {**params, 'limit': TOPICS_PER_PAGE, 'offset': (safe_page - 1) * TOPICS_PER_PAGE}).fetchall()
        return PaginatedMenuPage([dict(row) for row in rows], total, safe_page, TOPICS_PER_PAGE)

    def review(self, viewer: str, attachment_id: str, *, approve: bool) -> dict:
        with self.repository.atomic():
            self.forum.account(viewer, writing=True)
            row = self.forum.attachments._row(attachment_id)
            if not self.allowed(viewer, row):
                raise ForumError('forum-error-moderator')
            if row['approval'] != 'pending':
                raise ForumError('forum-error-conflict')
            decision = 'approved' if approve else 'rejected'
            self.connection.execute('UPDATE forum_attachments SET approval = ? WHERE id = ?', (decision, attachment_id))
            self.connection.execute(
                'INSERT INTO forum_attachment_reviews(attachment_id, actor_uuid, decision, created_at) VALUES (?, ?, ?, ?)',
                (attachment_id, viewer, decision, int(self.forum.clock())),
            )
            return {**dict(row), 'approval': decision}
