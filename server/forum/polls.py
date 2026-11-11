"""Atomic, UUID-owned ballots shared by public and private messages."""

from dataclasses import dataclass

from .models import ForumError
from .text import search_key, validate_text

MAX_OPTIONS = 10
MAX_POLL_SECONDS = 365 * 24 * 60 * 60


@dataclass(frozen=True)
class PollConfig:
    question: str
    options: tuple[str, ...]
    multiple: bool = False
    change_vote: bool = True
    results: str = 'after_vote'
    closes_at: int | None = None


def validate_config(config: PollConfig, now: int) -> PollConfig:
    if not isinstance(config, PollConfig):
        raise ForumError('forum-error-poll-config')
    if not isinstance(config.options, (tuple, list)) or not 2 <= len(config.options) <= MAX_OPTIONS:
        raise ForumError('forum-error-poll-options', limit=MAX_OPTIONS)
    question = validate_text(config.question)
    options = tuple(' '.join(validate_text(option).split()) for option in config.options)
    if len(question) > 240 or any(len(option) > 160 for option in options):
        raise ForumError('forum-error-poll-length')
    if len({search_key(option) for option in options}) != len(options):
        raise ForumError('forum-error-poll-duplicate')
    if type(config.multiple) is not bool or type(config.change_vote) is not bool:
        raise ForumError('forum-error-poll-config')
    if config.results not in {'always', 'after_vote', 'after_close'}:
        raise ForumError('forum-error-poll-config')
    if config.closes_at is not None and (
        type(config.closes_at) is not int or not now < config.closes_at <= now + MAX_POLL_SECONDS
    ):
        raise ForumError('forum-error-poll-deadline')
    return PollConfig(question, options, config.multiple, config.change_vote, config.results, config.closes_at)


class PollService:
    def __init__(self, forum):
        self.forum = forum
        self.repository = forum.repository

    @property
    def connection(self):
        return self.repository.connection

    def create_in_transaction(self, viewer: str, post_id: int, config: PollConfig, now: int) -> None:
        """Called in the publishing transaction: invalid polls publish nothing."""
        config = validate_config(config, now)
        post = self.forum.post(viewer, post_id)
        if post.author_uuid != viewer or post.hidden:
            raise ForumError('forum-error-edit-permission')
        self.connection.execute(
            """INSERT INTO forum_polls(post_id, question, multiple, change_vote, results, closes_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (post_id, config.question, int(config.multiple), int(config.change_vote), config.results, config.closes_at, now),
        )
        self.connection.executemany(
            'INSERT INTO forum_poll_options(post_id, position, label) VALUES (?, ?, ?)',
            [(post_id, index, label) for index, label in enumerate(config.options)],
        )

    def _row(self, viewer: str, post_id: int):
        post = self.forum.post(viewer, post_id)
        if post.hidden:
            raise ForumError('forum-error-missing')
        row = self.connection.execute('SELECT * FROM forum_polls WHERE post_id = ?', (post_id,)).fetchone()
        if row is None:
            raise ForumError('forum-error-missing')
        return post, row

    def _closed(self, row) -> bool:
        return bool(row['closed'] or row['closes_at'] is not None and int(self.forum.clock()) >= row['closes_at'])

    def get(self, viewer: str, post_id: int) -> dict:
        _, row = self._row(viewer, post_id)
        own = self.connection.execute(
            'SELECT option_id FROM forum_poll_votes WHERE post_id = ? AND user_uuid = ? ORDER BY option_id',
            (post_id, viewer),
        ).fetchall()
        selected = tuple(vote[0] for vote in own)
        closed = self._closed(row)
        visible = row['results'] == 'always' or closed or row['results'] == 'after_vote' and bool(selected)
        # Do not send hidden aggregates to a client and rely on its UI to hide them.
        options = self.connection.execute(
            'SELECT id, label FROM forum_poll_options WHERE post_id = ? ORDER BY position', (post_id,),
        ).fetchall()
        result = dict(row)
        result.update(closed=closed, selected=selected, results_visible=visible,
                      options=[{'id': option['id'], 'label': option['label']} for option in options])
        if visible:
            counts = dict(self.connection.execute(
                'SELECT option_id, COUNT(*) FROM forum_poll_votes WHERE post_id = ? GROUP BY option_id', (post_id,),
            ).fetchall())
            for option in result['options']:
                option['votes'] = counts.get(option['id'], 0)
            result['voters'] = self.connection.execute(
                'SELECT COUNT(DISTINCT user_uuid) FROM forum_poll_votes WHERE post_id = ?', (post_id,),
            ).fetchone()[0]
        return result

    def vote(self, viewer: str, post_id: int, choices: tuple[int, ...]) -> None:
        if not isinstance(choices, (tuple, list)) or len(choices) > MAX_OPTIONS or any(type(c) is not int for c in choices):
            raise ForumError('forum-error-poll-choice')
        if len(set(choices)) != len(choices):
            raise ForumError('forum-error-poll-choice')
        with self.repository.atomic():
            self.forum.account(viewer, writing=True)
            post, row = self._row(viewer, post_id)
            if self._closed(row) or self.forum.topic(viewer, post.topic_id).closed:
                raise ForumError('forum-error-poll-closed')
            valid = {option[0] for option in self.connection.execute(
                'SELECT id FROM forum_poll_options WHERE post_id = ?', (post_id,),
            ).fetchall()}
            if not set(choices) <= valid or not row['multiple'] and len(choices) > 1:
                raise ForumError('forum-error-poll-choice')
            previous = {vote[0] for vote in self.connection.execute(
                'SELECT option_id FROM forum_poll_votes WHERE post_id = ? AND user_uuid = ?', (post_id, viewer),
            ).fetchall()}
            if not choices and not previous:
                raise ForumError('forum-error-poll-choice')
            if previous == set(choices):
                return
            if previous and not row['change_vote']:
                raise ForumError('forum-error-poll-fixed-vote')
            self.connection.execute('DELETE FROM forum_poll_votes WHERE post_id = ? AND user_uuid = ?', (post_id, viewer))
            self.connection.executemany(
                'INSERT INTO forum_poll_votes VALUES (?, ?, ?, ?)',
                [(post_id, option, viewer, int(self.forum.clock())) for option in choices],
            )
            self.connection.execute('UPDATE forum_polls SET started = 1 WHERE post_id = ?', (post_id,))

    def edit(self, viewer: str, post_id: int, config: PollConfig) -> None:
        with self.repository.atomic():
            self.forum.account(viewer, writing=True)
            post, row = self._row(viewer, post_id)
            if post.author_uuid != viewer or not self.forum.can_edit(viewer, post):
                raise ForumError('forum-error-edit-permission')
            if self._closed(row) or self.forum.topic(viewer, post.topic_id).closed:
                raise ForumError('forum-error-poll-closed')
            if row['started']:
                raise ForumError('forum-error-poll-started')
            now = int(self.forum.clock())
            config = validate_config(config, now)
            self.connection.execute('DELETE FROM forum_polls WHERE post_id = ?', (post_id,))
            self.create_in_transaction(post.author_uuid, post_id, config, now)

    def close(self, viewer: str, post_id: int) -> None:
        with self.repository.atomic():
            self.forum.account(viewer, writing=True)
            post, _ = self._row(viewer, post_id)
            if post.author_uuid != viewer and not self.forum.can_moderate(viewer, post.topic_id):
                raise ForumError('forum-error-edit-permission')
            self.connection.execute('UPDATE forum_polls SET closed = 1 WHERE post_id = ?', (post_id,))
