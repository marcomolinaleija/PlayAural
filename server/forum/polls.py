"""Atomic UUID-owned ballots for message polls and general thread polls."""

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
    def __init__(self, forum, *, scope='post'):
        self.forum = forum
        self.repository = forum.repository
        # Identifiers come from this closed map, never client text.
        self.table, self.options_table, self.votes_table, self.key = {
            'post': ('forum_polls', 'forum_poll_options', 'forum_poll_votes', 'post_id'),
            'thread': ('forum_thread_polls', 'forum_thread_poll_options', 'forum_thread_poll_votes', 'topic_id'),
        }[scope]
        self.scope = scope

    @property
    def connection(self):
        return self.repository.connection

    def exists(self, target_id):
        return bool(self.connection.execute(f'SELECT 1 FROM {self.table} WHERE {self.key} = ?', (target_id,)).fetchone())

    def can_create(self, viewer, topic_id):
        topic = self.forum.topic(viewer, topic_id)
        permitted = (self.forum.conversations.owner(viewer, topic_id) if topic.is_private
                     else topic.author_uuid == viewer or self.forum.is_moderator(viewer))
        return permitted and not topic.closed and not self.exists(topic_id)

    def create(self, viewer, topic_id, config):
        if self.scope != 'thread':
            raise ValueError('Message polls are created with their post')
        with self.repository.atomic():
            self.forum.account(viewer, writing=True)
            self.create_in_transaction(viewer, topic_id, config, int(self.forum.clock()))

    def create_in_transaction(self, viewer: str, post_id: int, config: PollConfig, now: int) -> None:
        config = validate_config(config, now)
        if self.scope == 'thread':
            self.forum.topic(viewer, post_id)
            if self.exists(post_id):
                raise ForumError('forum-error-thread-poll-exists')
            if not self.can_create(viewer, post_id):
                raise ForumError('forum-error-edit-permission')
        else:
            post = self.forum.post(viewer, post_id)
            if post.author_uuid != viewer or post.hidden:
                raise ForumError('forum-error-edit-permission')
        columns = f'{self.key}, question, multiple, change_vote, results, closes_at, created_at'
        values = (post_id, config.question, int(config.multiple), int(config.change_vote), config.results, config.closes_at, now)
        if self.scope == 'thread':
            columns += ', author_uuid'
            values += (viewer,)
        self.connection.execute(f"INSERT INTO {self.table} ({columns}) VALUES ({', '.join('?' for _ in values)})", values)
        self._options(post_id, config)

    def _options(self, target_id, config):
        self.connection.executemany(
            f'INSERT INTO {self.options_table}({self.key}, position, label) VALUES (?, ?, ?)',
            [(target_id, index, label) for index, label in enumerate(config.options)])

    def _row(self, viewer: str, post_id: int):
        context = self.forum.topic(viewer, post_id) if self.scope == 'thread' else self.forum.post(viewer, post_id)
        if self.scope == 'post' and context.hidden:
            raise ForumError('forum-error-missing')
        row = self.connection.execute(f'SELECT * FROM {self.table} WHERE {self.key} = ?', (post_id,)).fetchone()
        if row is None or (self.scope == 'thread' and row['author_uuid']
                          and self.repository.database.has_block_between(viewer, row['author_uuid'])):
            raise ForumError('forum-error-missing')
        return context, row

    def _topic_id(self, context):
        return context.id if self.scope == 'thread' else context.topic_id

    def _author(self, context, row):
        return row['author_uuid'] if self.scope == 'thread' else context.author_uuid

    def _closed(self, row) -> bool:
        return bool(row['closed'] or row['closes_at'] is not None and int(self.forum.clock()) >= row['closes_at'])

    def get(self, viewer: str, post_id: int) -> dict:
        context, row = self._row(viewer, post_id)
        own = self.connection.execute(
            f'SELECT option_id FROM {self.votes_table} WHERE {self.key} = ? AND user_uuid = ? ORDER BY option_id',
            (post_id, viewer)).fetchall()
        selected = tuple(vote[0] for vote in own)
        closed = self._closed(row)
        visible = row['results'] == 'always' or closed or row['results'] == 'after_vote' and bool(selected)
        options = self.connection.execute(
            f'SELECT id, label FROM {self.options_table} WHERE {self.key} = ? ORDER BY position', (post_id,)).fetchall()
        result = dict(row)
        result.update(closed=closed, selected=selected, results_visible=visible,
                      topic_id=self._topic_id(context), author_uuid=self._author(context, row),
                      options=[{'id': option['id'], 'label': option['label']} for option in options])
        if visible:
            counts = dict(self.connection.execute(
                f'SELECT option_id, COUNT(*) FROM {self.votes_table} WHERE {self.key} = ? GROUP BY option_id', (post_id,)).fetchall())
            for option in result['options']:
                option['votes'] = counts.get(option['id'], 0)
            result['voters'] = self.connection.execute(
                f'SELECT COUNT(DISTINCT user_uuid) FROM {self.votes_table} WHERE {self.key} = ?', (post_id,)).fetchone()[0]
        return result

    def vote(self, viewer: str, post_id: int, choices: tuple[int, ...]) -> None:
        if not isinstance(choices, (tuple, list)) or len(choices) > MAX_OPTIONS or any(type(c) is not int for c in choices):
            raise ForumError('forum-error-poll-choice')
        if len(set(choices)) != len(choices):
            raise ForumError('forum-error-poll-choice')
        with self.repository.atomic():
            self.forum.account(viewer, writing=True)
            context, row = self._row(viewer, post_id)
            if self._closed(row) or self.forum.topic(viewer, self._topic_id(context)).closed:
                raise ForumError('forum-error-poll-closed')
            valid = {option[0] for option in self.connection.execute(
                f'SELECT id FROM {self.options_table} WHERE {self.key} = ?', (post_id,)).fetchall()}
            if not set(choices) <= valid or not row['multiple'] and len(choices) > 1:
                raise ForumError('forum-error-poll-choice')
            previous = {vote[0] for vote in self.connection.execute(
                f'SELECT option_id FROM {self.votes_table} WHERE {self.key} = ? AND user_uuid = ?', (post_id, viewer)).fetchall()}
            if not choices and not previous:
                raise ForumError('forum-error-poll-choice')
            if previous == set(choices):
                return
            if previous and not row['change_vote']:
                raise ForumError('forum-error-poll-fixed-vote')
            self.connection.execute(f'DELETE FROM {self.votes_table} WHERE {self.key} = ? AND user_uuid = ?', (post_id, viewer))
            self.connection.executemany(f'INSERT INTO {self.votes_table} VALUES (?, ?, ?, ?)',
                [(post_id, option, viewer, int(self.forum.clock())) for option in choices])
            self.connection.execute(f'UPDATE {self.table} SET started = 1 WHERE {self.key} = ?', (post_id,))

    def can_edit(self, viewer, target_id):
        context, row = self._row(viewer, target_id)
        if row['started'] or self._closed(row) or self.forum.topic(viewer, self._topic_id(context)).closed:
            return False
        if self.scope == 'thread':
            return self._author(context, row) == viewer or self.forum.can_moderate(viewer, self._topic_id(context))
        return context.author_uuid == viewer and self.forum.can_edit(viewer, context)

    def edit(self, viewer: str, post_id: int, config: PollConfig, *, revision=None) -> None:
        with self.repository.atomic():
            self.forum.account(viewer, writing=True)
            context, row = self._row(viewer, post_id)
            permitted = (self._author(context, row) == viewer or self.forum.can_moderate(viewer, self._topic_id(context))
                         if self.scope == 'thread' else context.author_uuid == viewer and self.forum.can_edit(viewer, context))
            if not permitted:
                raise ForumError('forum-error-edit-permission')
            if self._closed(row) or self.forum.topic(viewer, self._topic_id(context)).closed:
                raise ForumError('forum-error-poll-closed')
            if row['started']:
                raise ForumError('forum-error-poll-started')
            if self.scope == 'thread' and revision != row['revision']:
                raise ForumError('forum-error-conflict')
            config = validate_config(config, int(self.forum.clock()))
            revision_sql = ', revision = revision + 1' if self.scope == 'thread' else ''
            self.connection.execute(f'''UPDATE {self.table} SET question = ?, multiple = ?, change_vote = ?,
                results = ?, closes_at = ?{revision_sql} WHERE {self.key} = ?''',
                (config.question, int(config.multiple), int(config.change_vote), config.results, config.closes_at, post_id))
            self.connection.execute(f'DELETE FROM {self.options_table} WHERE {self.key} = ?', (post_id,))
            self._options(post_id, config)

    def close(self, viewer: str, post_id: int) -> None:
        with self.repository.atomic():
            self.forum.account(viewer, writing=True)
            context, row = self._row(viewer, post_id)
            if self._author(context, row) != viewer and not self.forum.can_moderate(viewer, self._topic_id(context)):
                raise ForumError('forum-error-edit-permission')
            self.connection.execute(f'UPDATE {self.table} SET closed = 1 WHERE {self.key} = ?', (post_id,))
