"""Ephemeral media credentials tied to the exact currently owning socket."""

from dataclasses import dataclass
import secrets
import time

from .models import ForumError

SESSION_LIFETIME = 60 * 60


@dataclass(frozen=True)
class MediaGrant:
    user: object
    expires_at: float


class MediaSessions:
    def __init__(self, server, service, clock=time.time):
        self.server, self.service, self.clock = server, service, clock
        self._grants: dict[str, MediaGrant] = {}

    def _owns_session(self, user) -> bool:
        return (not getattr(self.server, '_stopping', False)
                and self.server._users.get(user.username) is user
                and self.server._active_user_for_client(user._connection) is user)

    def issue(self, user) -> tuple[str, int]:
        if not getattr(self.server, 'forum_enabled', True):
            raise ForumError('forum-unavailable')
        self.service.account(user.uuid)
        if not self._owns_session(user):
            raise ForumError('forum-error-account')
        now = self.clock()
        self._grants = {token: grant for token, grant in self._grants.items()
                        if grant.expires_at > now and self._owns_session(grant.user)}
        for token, grant in self._grants.items():
            if grant.user is user and grant.expires_at > now + 15 * 60:
                return token, int(grant.expires_at)
        # Keep the previous grant until its original expiry so a rolling
        # credential cannot interrupt an in-flight upload. The 45-minute reuse
        # window bounds overlap to two grants per exact owning connection.
        token = secrets.token_urlsafe(32)
        expiry = now + SESSION_LIFETIME
        self._grants[token] = MediaGrant(user, expiry)
        return token, int(expiry)

    def authenticate(self, token: str):
        grant = self._grants.get(token)
        if grant is None or grant.expires_at <= self.clock() or not self._owns_session(grant.user):
            self._grants.pop(token, None)
            raise ForumError('forum-error-account')
        if not getattr(self.server, 'forum_enabled', True):
            raise ForumError('forum-unavailable')
        self.service.account(grant.user.uuid)
        return grant.user

    def clear(self) -> None:
        self._grants.clear()
