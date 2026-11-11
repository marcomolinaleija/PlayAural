"""Explicit invitation and membership rules for persistent private discussions."""

from uuid import uuid4

from .models import ForumError
from .text import validate_text

MAX_MEMBERS = 12
INVITE_LIFETIME = 7 * 24 * 60 * 60
MAX_INVITES_PER_MINUTE = 20


class ConversationService:
    def __init__(self, forum):
        self.forum = forum
        self.repository = forum.repository

    @property
    def connection(self):
        return self.repository.connection

    def owner(self, viewer: str, topic_id: int) -> bool:
        topic = self.forum.topic(viewer, topic_id)
        return bool(topic.is_private and self.connection.execute(
            "SELECT 1 FROM forum_private_topics WHERE topic_id = ? AND owner_uuid = ?",
            (topic_id, viewer),
        ).fetchone())

    def members(self, viewer: str, topic_id: int) -> list[dict]:
        if not self.forum.topic(viewer, topic_id).is_private:
            raise ForumError('forum-error-missing')
        rows = self.connection.execute(
            """SELECT m.user_uuid, u.username, m.joined_at,
                      m.user_uuid = t.owner_uuid AS is_owner
               FROM forum_private_members m JOIN users u ON u.uuid = m.user_uuid
               JOIN forum_private_topics t ON t.topic_id = m.topic_id
               WHERE m.topic_id = ? ORDER BY m.joined_at, m.user_uuid""", (topic_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def _admit(self, target: str, members: list[str]) -> None:
        self.forum.account(target)
        for member in members:
            if self.connection.execute(
                """SELECT 1 FROM user_blocks WHERE
                   (blocker_id = ? AND blocked_id = ?) OR (blocker_id = ? AND blocked_id = ?)""",
                (target, member, member, target),
            ).fetchone():
                raise ForumError('forum-error-private-contact')

    def create(self, viewer: str, title: str, body: str, recipients: tuple[str, ...], *, poll=None,
               attachment_ids: tuple[str, ...] = ()) -> tuple[int, int]:
        title, body = validate_text(title, title=True), validate_text(body)
        if not isinstance(recipients, (tuple, list)) or not 1 <= len(recipients) < MAX_MEMBERS:
            raise ForumError('forum-error-private-recipients', limit=MAX_MEMBERS - 1)
        if len(set(recipients)) != len(recipients) or viewer in recipients:
            raise ForumError('forum-error-private-recipients', limit=MAX_MEMBERS - 1)
        with self.repository.atomic():
            author = self.forum.account(viewer, writing=True)
            now = int(self.forum.clock())
            self.forum._check_send(author, body, now)
            for recipient in recipients:
                self._admit(recipient, [viewer, *recipients])
            topic_id, post_id = self.repository.create_topic(author, 'general', title, body, now)
            self.connection.execute('INSERT INTO forum_private_topics VALUES (?, ?)', (topic_id, viewer))
            self.connection.execute('INSERT INTO forum_private_members VALUES (?, ?, ?)', (topic_id, viewer, now))
            for recipient in recipients:
                self._invite(viewer, topic_id, recipient, now)
            if poll is not None:
                self.forum.polls.create_in_transaction(viewer, post_id, poll, now)
            self.forum.attachments.bind_in_transaction(viewer, post_id, attachment_ids)
            return topic_id, post_id

    def _invite(self, viewer: str, topic_id: int, recipient: str, now: int) -> str:
        recent = self.connection.execute(
            'SELECT COUNT(*) FROM forum_private_invites WHERE inviter_uuid = ? AND created_at >= ?',
            (viewer, now - 60),
        ).fetchone()[0]
        if recent >= MAX_INVITES_PER_MINUTE:
            raise ForumError('forum-error-rate', seconds=60)
        invite_id = str(uuid4())
        self.connection.execute(
            "INSERT INTO forum_private_invites VALUES (?, ?, ?, ?, 'pending', ?, ?)",
            (invite_id, topic_id, viewer, recipient, now, now + INVITE_LIFETIME),
        )
        return invite_id

    def invite(self, viewer: str, topic_id: int, recipient: str) -> str:
        with self.repository.atomic():
            self.forum.account(viewer, writing=True)
            if not self.owner(viewer, topic_id):
                raise ForumError('forum-error-private-owner')
            members = [row['user_uuid'] for row in self.members(viewer, topic_id)]
            now = int(self.forum.clock())
            pending = self.connection.execute(
                """SELECT invited_uuid FROM forum_private_invites
                   WHERE topic_id = ? AND status = 'pending' AND expires_at > ?""", (topic_id, now),
            ).fetchall()
            reserved = members + [row[0] for row in pending]
            if recipient in reserved or len(reserved) >= MAX_MEMBERS:
                raise ForumError('forum-error-private-recipients', limit=MAX_MEMBERS - 1)
            self._admit(recipient, reserved)
            return self._invite(viewer, topic_id, recipient, now)

    def invitations(self, viewer: str) -> list[dict]:
        self.forum.account(viewer)
        rows = self.connection.execute(
            """SELECT i.id, i.topic_id, t.title, u.username AS inviter_name
               FROM forum_private_invites i JOIN forum_topics t ON t.id = i.topic_id
               JOIN users u ON u.uuid = i.inviter_uuid
               JOIN forum_private_members m ON m.topic_id = i.topic_id AND m.user_uuid = i.inviter_uuid
               WHERE i.invited_uuid = ? AND i.status = 'pending' AND i.expires_at > ?
               AND NOT EXISTS (SELECT 1 FROM user_blocks b WHERE
                 (b.blocker_id = i.invited_uuid AND b.blocked_id = i.inviter_uuid) OR
                 (b.blocker_id = i.inviter_uuid AND b.blocked_id = i.invited_uuid))
               ORDER BY i.created_at DESC, i.id LIMIT 50""", (viewer, int(self.forum.clock())),
        ).fetchall()
        return [dict(row) for row in rows]

    def respond(self, viewer: str, invite_id: str, *, accept: bool) -> int:
        with self.repository.atomic():
            self.forum.account(viewer, writing=True)
            now = int(self.forum.clock())
            invite = self.connection.execute(
                """SELECT * FROM forum_private_invites WHERE id = ? AND invited_uuid = ?
                   AND status = 'pending' AND expires_at > ?""", (invite_id, viewer, now),
            ).fetchone()
            if invite is None:
                raise ForumError('forum-error-missing')
            topic_id = invite['topic_id']
            if accept:
                self.forum.account(invite['inviter_uuid'])
                rows = self.connection.execute(
                    'SELECT user_uuid FROM forum_private_members WHERE topic_id = ?', (topic_id,),
                ).fetchall()
                members = [row[0] for row in rows]
                if invite['inviter_uuid'] not in members or len(members) >= MAX_MEMBERS or viewer in members:
                    raise ForumError('forum-error-missing')
                self._admit(viewer, members)
                self.connection.execute('INSERT INTO forum_private_members VALUES (?, ?, ?)', (topic_id, viewer, now))
            self.connection.execute(
                'UPDATE forum_private_invites SET status = ? WHERE id = ?',
                ('accepted' if accept else 'declined', invite_id),
            )
            return topic_id

    def leave(self, viewer: str, topic_id: int) -> None:
        with self.repository.atomic():
            self.forum.account(viewer)
            members = self.members(viewer, topic_id)
            others = [row for row in members if row['user_uuid'] != viewer]
            if not others:
                self.connection.execute('DELETE FROM forum_topics WHERE id = ?', (topic_id,))
                return
            if self.owner(viewer, topic_id):
                self.connection.execute(
                    'UPDATE forum_private_topics SET owner_uuid = ? WHERE topic_id = ?', (others[0]['user_uuid'], topic_id),
                )
            self.connection.execute('DELETE FROM forum_private_members WHERE topic_id = ? AND user_uuid = ?', (topic_id, viewer))
            self.connection.execute(
                "UPDATE forum_attachments SET state = 'retired' WHERE context_topic_id = ? AND owner_uuid = ? AND published = 0", (topic_id, viewer),
            )
            self.connection.execute(
                "UPDATE forum_private_invites SET status = 'revoked' WHERE topic_id = ? AND inviter_uuid = ? AND status = 'pending'",
                (topic_id, viewer),
            )
            for table in ('forum_bookmarks', 'forum_read_positions'):
                self.connection.execute(f'DELETE FROM {table} WHERE topic_id = ? AND user_uuid = ?', (topic_id, viewer))

    def remove(self, viewer: str, topic_id: int, participant: str) -> None:
        with self.repository.atomic():
            self.forum.account(viewer, writing=True)
            if not self.owner(viewer, topic_id) or participant == viewer:
                raise ForumError('forum-error-private-owner')
            if not any(member['user_uuid'] == participant for member in self.members(viewer, topic_id)):
                raise ForumError('forum-error-missing')
            self.connection.execute('DELETE FROM forum_private_members WHERE topic_id = ? AND user_uuid = ?', (topic_id, participant))
            self.connection.execute(
                "UPDATE forum_attachments SET state = 'retired' WHERE context_topic_id = ? AND owner_uuid = ? AND published = 0", (topic_id, participant),
            )
            self.connection.execute(
                """UPDATE forum_private_invites SET status = 'revoked' WHERE topic_id = ? AND status = 'pending'
                   AND (inviter_uuid = ? OR invited_uuid = ?)""", (topic_id, participant, participant),
            )
            for table in ('forum_bookmarks', 'forum_read_positions'):
                self.connection.execute(f'DELETE FROM {table} WHERE topic_id = ? AND user_uuid = ?', (topic_id, participant))
