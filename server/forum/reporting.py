"""Public-content reports; evidence is captured by the database transaction."""

import json
from dataclasses import asdict, dataclass

from .models import ForumError, MAX_BODY_LENGTH, MAX_TITLE_LENGTH


@dataclass(frozen=True)
class ReportTarget:
    kind: str
    id: int
    revision: int


@dataclass(frozen=True)
class ForumReportEvidence:
    kind: str
    topic_id: int
    post_id: int
    revision: int
    title: str
    body: str
    author_uuid: str | None
    author_name: str

    @property
    def target(self) -> ReportTarget:
        return ReportTarget(self.kind, self.topic_id if self.kind == 'thread' else self.post_id, self.revision)

    def to_json(self) -> str:
        return json.dumps({'version': 1, **asdict(self)}, ensure_ascii=False, separators=(',', ':'))

    @classmethod
    def from_json(cls, value: str):
        try:
            data = json.loads(value)
            if not isinstance(data, dict) or data.pop('version', None) != 1:
                return None
            result = cls(**data)
            if result.kind not in {'thread', 'post'}:
                return None
            if any(type(n) is not int for n in (result.topic_id, result.post_id, result.revision)):
                return None
            if min(result.topic_id, result.post_id) < 1 or result.revision < 0:
                return None
            if not isinstance(result.title, str) or not 1 <= len(result.title) <= MAX_TITLE_LENGTH:
                return None
            if not isinstance(result.body, str) or not 1 <= len(result.body) <= MAX_BODY_LENGTH:
                return None
            if not isinstance(result.author_name, str) or not (result.author_uuid is None or isinstance(result.author_uuid, str)):
                return None
            return result
        except (TypeError, ValueError):
            return None


def capture_public_report(service, viewer: str, kind: str, target_id: int) -> ForumReportEvidence:
    """Recheck approval, bans, bilateral blocks, membership and hidden state."""
    service.account(viewer)
    if kind == 'thread':
        topic = service.topic(viewer, target_id)
        first = service.repository.connection.execute(
            'SELECT id FROM forum_posts WHERE topic_id = ? ORDER BY id LIMIT 1', (topic.id,)
        ).fetchone()
        if first is None:
            raise ForumError('forum-error-missing')
        post = service.post(viewer, first[0])
    elif kind == 'post':
        post = service.post(viewer, target_id)
        topic = service.topic(viewer, post.topic_id)
    else:
        raise ForumError('forum-error-missing')
    if topic.is_private or post.hidden:
        raise ForumError('forum-error-missing')
    if post.author_uuid == viewer:
        raise ForumError('forum-report-self')
    return ForumReportEvidence(kind, topic.id, post.id, post.revision, topic.title,
                               post.body, post.author_uuid, post.author_name)
