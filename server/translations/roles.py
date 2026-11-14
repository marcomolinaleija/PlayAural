"""Scoped translator roles, independent of moderation trust levels."""

from ..users.roles import ADMIN_TRUST_LEVEL
from .models import TranslationError


class TranslatorRoles:
    def __init__(self, service):
        self.service = service

    def languages(self, viewer):
        self.service.account(viewer)
        return {row[0] for row in self.service.connection.execute(
            'SELECT language FROM translation_roles WHERE user_uuid = ? AND enabled = 1', (viewer,))}

    def is_translator(self, viewer):
        connection = self.service.connection
        return bool(connection and connection.execute(
            'SELECT 1 FROM translation_roles WHERE user_uuid = ? AND enabled = 1 LIMIT 1', (viewer,)).fetchone())

    def can_review(self, viewer, language=None):
        account = self.service.account(viewer)
        if account.trust_level >= ADMIN_TRUST_LEVEL:
            return True
        assigned = self.languages(viewer)
        return language in assigned if language else bool(assigned)

    def require_review(self, viewer, language=None):
        if not self.can_review(viewer, language):
            raise TranslationError('translation-error-reviewer')

    def require_admin(self, viewer):
        account = self.service.account(viewer)
        if account.trust_level < ADMIN_TRUST_LEVEL:
            raise TranslationError('translation-error-role-admin')
        return account

    def assignments(self, viewer, target):
        self.require_admin(viewer)
        if self.service.db.get_user_by_uuid(target) is None:
            raise TranslationError('translation-error-account')
        return {row['language']: dict(row) for row in self.service.connection.execute(
            'SELECT * FROM translation_roles WHERE user_uuid = ?', (target,))}

    def set(self, viewer, target, language, enabled, expected):
        service = self.service
        with service.atomic():
            self.require_admin(viewer)
            service.account(viewer, writing=True)
            if enabled:
                service.account(target)
            elif service.db.get_user_by_uuid(target) is None:
                raise TranslationError('translation-error-account')
            service.language(viewer, language)
            current = service.connection.execute('SELECT * FROM translation_roles WHERE user_uuid = ? AND language = ?',
                                                 (target, language)).fetchone()
            if type(enabled) is not bool or type(expected) is not int or (current['revision'] if current else 0) != expected:
                raise TranslationError('translation-error-changed')
            service.connection.execute('''INSERT INTO translation_roles
                (user_uuid, language, revision, enabled, granted_by, granted_at) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_uuid, language) DO UPDATE SET revision = excluded.revision,
                enabled = excluded.enabled, granted_by = excluded.granted_by, granted_at = excluded.granted_at''',
                (target, language, expected + 1, int(enabled), viewer, int(service.clock())))
            service._event(None, viewer, 'role_granted' if enabled else 'role_revoked', target_uuid=target, language=language)
