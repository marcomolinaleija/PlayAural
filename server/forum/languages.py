"""Public forum language selection, independent of interface and private chats."""

from .models import ForumError

FORUM_LANGUAGES = ('ar', 'en', 'es', 'fa', 'id', 'pt', 'vi')
LANGUAGE_CHECK = "CHECK (language IN ('ar', 'en', 'es', 'fa', 'id', 'pt', 'vi'))"


def validate_language(value: str) -> str:
    if value not in FORUM_LANGUAGES:
        raise ForumError('forum-error-language')
    return value


class ForumLanguages:
    def __init__(self, forum):
        self.forum = forum
        self.repository = forum.repository

    def current(self, viewer: str) -> str:
        account = self.forum.account(viewer)
        row = self.repository.connection.execute(
            'SELECT language FROM forum_language_preferences WHERE user_uuid = ?', (viewer,)
        ).fetchone()
        if row:
            return validate_language(row[0])
        locale = (account.locale or 'en').replace('_', '-').lower().split('-')[0]
        return locale if locale in FORUM_LANGUAGES else 'en'

    def select(self, viewer: str, language: str) -> None:
        validate_language(language)
        with self.repository.atomic():
            self.forum.account(viewer)
            self.repository.connection.execute(
                '''INSERT INTO forum_language_preferences(user_uuid, language) VALUES (?, ?)
                   ON CONFLICT(user_uuid) DO UPDATE SET language = excluded.language''', (viewer, language)
            )
