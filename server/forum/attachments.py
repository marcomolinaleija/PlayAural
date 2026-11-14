"""Attachment metadata, quotas and ACLs on the central SQLite owner thread."""

from pathlib import PureWindowsPath
from uuid import UUID, uuid4

from .media_processing import ProcessedMedia
from .models import ForumError
from .text import validate_text
from .file_settings import MIB

MAX_ATTACHMENTS = 8
UPLOAD_LIFETIME = 24 * 60 * 60


class AttachmentService:
    def __init__(self, forum, *, require_approval: bool = False):
        self.forum, self.repository = forum, forum.repository
        self.require_approval = require_approval

    @property
    def require_approval(self):
        return self.forum.files.policy().require_approval

    @require_approval.setter
    def require_approval(self, value):
        self.forum.files.default_approval = value

    @property
    def connection(self):
        return self.repository.connection

    def reserve(self, viewer: str, name: str, size: int, description: str = '', *,
                topic_id: int = 0, private: bool = False) -> dict:
        policy = self.forum.files.require_uploads()
        if type(size) is not int or not 0 < size <= policy.max_file_mib * MIB:
            raise ForumError('forum-error-limite-carga', limite=policy.max_file_mib)
        name = validate_text(name, title=True)
        name = PureWindowsPath(name).name
        if not name or name in {'.', '..'}:
            raise ForumError('forum-error-media-name')
        if not isinstance(description, str) or len(description) > 1000:
            raise ForumError('forum-error-media-description')
        description = validate_text(description) if description.strip() else ''
        with self.repository.atomic():
            self.forum.account(viewer, writing=True)
            if topic_id:
                topic = self.forum.topic(viewer, topic_id)
                if topic.closed:
                    raise ForumError('forum-error-closed')
                private = bool(topic.is_private)
            needs_approval = self.require_approval and (
                private and bool(topic_id) and not self.forum.conversations.owner(viewer, topic_id)
                or not private and not self.forum.is_moderator(viewer)
            )
            now = int(self.forum.clock())
            count, pending_bytes = self.connection.execute(
                """SELECT COUNT(*), COALESCE(SUM(size), 0) FROM forum_attachments WHERE owner_uuid = ?
                   AND published = 0 AND expires_at > ? AND state IN ('uploading', 'processing', 'ready')""", (viewer, now),
            ).fetchone()
            if count >= MAX_ATTACHMENTS or pending_bytes + size > policy.pending_mib * MIB:
                raise ForumError('forum-error-cuota-carga', cantidad=MAX_ATTACHMENTS, limite=policy.pending_mib)
            attachment_id = str(uuid4())
            self.connection.execute(
                """INSERT INTO forum_attachments(id, owner_uuid, name, description, context_topic_id, private, state, approval, kind,
                   mime, size, object_key, created_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'uploading', ?, 'file', 'application/octet-stream', ?, ?, ?, ?)""",
                (attachment_id, viewer, name, description, topic_id or None, int(private), 'unsubmitted' if needs_approval else 'approved',
                 size, UUID(attachment_id).hex + '/content', now, now + UPLOAD_LIFETIME),
            )
            return dict(self._row(attachment_id))

    def _row(self, attachment_id: str):
        row = self.connection.execute('SELECT * FROM forum_attachments WHERE id = ?', (attachment_id,)).fetchone()
        if row is None:
            raise ForumError('forum-error-missing')
        return row

    def upload(self, viewer: str, attachment_id: str) -> dict:
        policy = self.forum.files.require_uploads()
        self.forum.account(viewer, writing=True)
        row = self._row(attachment_id)
        if row['owner_uuid'] != viewer or row['published'] or row['state'] != 'uploading' or row['expires_at'] <= self.forum.clock():
            raise ForumError('forum-error-missing')
        if row['size'] > policy.max_file_mib * MIB:
            raise ForumError('forum-error-limite-carga', limite=policy.max_file_mib)
        return dict(row)

    def processing(self, viewer: str, attachment_id: str) -> None:
        with self.repository.atomic():
            self.upload(viewer, attachment_id)
            self.connection.execute("UPDATE forum_attachments SET state = 'processing' WHERE id = ?", (attachment_id,))

    def complete(self, viewer: str, attachment_id: str, media: ProcessedMedia) -> None:
        """Only the worker coordinator calls this after storing every variant."""
        with self.repository.atomic():
            self.forum.account(viewer, writing=True)
            row = self._row(attachment_id)
            if row['owner_uuid'] != viewer or row['state'] != 'processing' or row['published'] or row['expires_at'] <= self.forum.clock():
                raise ForumError('forum-error-missing')
            name = PureWindowsPath(row['name']).stem[:100] + media.suffix
            self.connection.execute(
                """UPDATE forum_attachments SET state = 'ready', name = ?, mime = ?, kind = ?, size = ?,
                   sha256 = ?, thumbnail_key = ?, captions_key = ?, duration = ?, width = ?, height = ? WHERE id = ?""",
                (name, media.mime, media.kind, media.size, media.sha256,
                 UUID(attachment_id).hex + '/thumbnail' if media.thumbnail else '',
                 UUID(attachment_id).hex + '/captions' if media.captions else '',
                 media.duration, media.width, media.height, attachment_id),
            )

    def fail(self, attachment_id: str) -> None:
        with self.repository.atomic():
            self.connection.execute(
                "UPDATE forum_attachments SET state = 'failed' WHERE id = ? AND published = 0 AND state IN ('uploading', 'processing')",
                (attachment_id,),
            )

    def get(self, viewer: str, attachment_id: str) -> dict:
        self.forum.account(viewer)
        row = self._row(attachment_id)
        if row['state'] != 'ready':
            raise ForumError('forum-error-missing')
        if row['published']:
            if row['approval'] != 'approved':
                raise ForumError('forum-error-missing')
            # A post that was deleted or hidden must not turn into an owner's
            # draft preview. Ownership never overrides a published post's ACL.
            if row['post_id'] is None or self.forum.post(viewer, row['post_id']).hidden:
                raise ForumError('forum-error-missing')
        else:
            if row['expires_at'] <= self.forum.clock():
                raise ForumError('forum-error-missing')
            if row['owner_uuid'] != viewer and not self.forum.attachment_reviews.allowed(viewer, row):
                raise ForumError('forum-error-missing')
        return dict(row)

    def for_post(self, viewer: str, post_id: int) -> list[dict]:
        if self.forum.post(viewer, post_id).hidden:
            return []
        rows = self.connection.execute(
            """SELECT id FROM forum_attachments WHERE post_id = ? AND published = 1
               AND state = 'ready' AND approval = 'approved' ORDER BY created_at, id LIMIT ?""",
            (post_id, MAX_ATTACHMENTS),
        ).fetchall()
        return [self.get(viewer, row[0]) for row in rows]

    def bind_in_transaction(self, viewer: str, post_id: int, attachment_ids: tuple[str, ...]) -> None:
        if not isinstance(attachment_ids, (tuple, list)) or len(attachment_ids) > MAX_ATTACHMENTS or len(set(attachment_ids)) != len(attachment_ids):
            raise ForumError('forum-error-media-quota', limit=MAX_ATTACHMENTS)
        post = self.forum.post(viewer, post_id)
        topic = self.forum.topic(viewer, post.topic_id)
        if post.author_uuid != viewer:
            raise ForumError('forum-error-edit-permission')
        for attachment_id in attachment_ids:
            row = self._row(attachment_id)
            if row['state'] != 'ready' or row['approval'] != 'approved':
                raise ForumError('forum-error-media-not-ready')
            if row['private'] and (not topic.is_private or row['context_topic_id'] not in {None, topic.id}):
                raise ForumError('forum-error-media-owner')
            if row['published']:
                if row['post_id'] != post_id:
                    raise ForumError('forum-error-media-owner')
            elif row['owner_uuid'] != viewer or row['expires_at'] <= self.forum.clock():
                raise ForumError('forum-error-media-owner')
        for attachment_id in attachment_ids:
            self.connection.execute(
                'UPDATE forum_attachments SET post_id = ?, published = 1 WHERE id = ?', (post_id, attachment_id),
            )

    def describe(self, viewer: str, attachment_id: str, description: str) -> None:
        description = validate_text(description) if description else ''
        if len(description) > 1000:
            raise ForumError('forum-error-media-description')
        with self.repository.atomic():
            self.forum.account(viewer, writing=True)
            row = self._row(attachment_id)
            if row['owner_uuid'] != viewer or row['published']:
                raise ForumError('forum-error-media-owner')
            self.connection.execute('UPDATE forum_attachments SET description = ? WHERE id = ?', (description, attachment_id))

    def discard(self, viewer: str, attachment_id: str) -> None:
        with self.repository.atomic():
            self.forum.account(viewer)
            row = self._row(attachment_id)
            if row['owner_uuid'] != viewer or row['published']:
                raise ForumError('forum-error-media-owner')
            self.connection.execute("UPDATE forum_attachments SET state = 'retired' WHERE id = ?", (attachment_id,))

    def expired(self) -> list[dict]:
        # Published objects are retained, including deleted/hidden posts, so a
        # historical database backup never loses the objects it references.
        rows = self.connection.execute(
            "SELECT * FROM forum_attachments WHERE published = 0 AND (expires_at <= ? OR state = 'retired') LIMIT 100",
            (int(self.forum.clock()),),
        ).fetchall()
        return [dict(row) for row in rows]
