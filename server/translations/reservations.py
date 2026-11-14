"""Atomic per-language/text leases; never expose another author's draft."""

from .models import TranslationError

RESERVATION_SECONDS = 24 * 60 * 60


class Reservations:
    def __init__(self, service):
        self.service = service

    def active(self, language, unit_id=None):
        where = ' AND r.unit_id = ?' if unit_id is not None else ''
        params = [language, int(self.service.clock())]
        if unit_id is not None:
            params.append(unit_id)
        return {row['unit_id']: dict(row) for row in self.service.connection.execute('''
            SELECT r.*, u.username, p.status FROM translation_reservations r
            JOIN translation_proposals p ON p.id = r.proposal_id
            JOIN users u ON u.uuid = r.owner_uuid
            WHERE r.language = ? AND p.author_uuid = r.owner_uuid
            AND p.status IN ('draft', 'pending', 'changes_requested')
            AND (p.status = 'pending' OR r.expires_at > ?)''' + where, params)}

    def claim(self, proposal):
        """Caller owns an immediate transaction and has checked write access."""
        service = self.service
        now = int(service.clock())
        service.connection.execute('''DELETE FROM translation_reservations WHERE proposal_id IN (
            SELECT r.proposal_id FROM translation_reservations r
            JOIN translation_proposals p ON p.id = r.proposal_id
            WHERE r.expires_at > 0 AND r.expires_at <= ? AND p.status != 'pending'
            ORDER BY r.expires_at LIMIT 100)''', (now,))
        existing = self.active(proposal['language'], proposal['unit_id']).get(proposal['unit_id'])
        if existing and existing['proposal_id'] != proposal['id']:
            key = 'translation-error-reserved-review' if existing['status'] == 'pending' else 'translation-error-reserved'
            raise TranslationError(key, author=existing['username'])
        # Retained pre-14 duplicate submissions must also prevent new editing,
        # even if the first migrated lease has since been reviewed.
        pending = service.connection.execute('''SELECT u.username FROM translation_proposals p
            JOIN users u ON u.uuid = p.author_uuid WHERE p.language = ? AND p.unit_id = ?
            AND p.status = 'pending' AND p.id != ? ORDER BY p.id LIMIT 1''',
            (proposal['language'], proposal['unit_id'], proposal['id'])).fetchone()
        if pending:
            raise TranslationError('translation-error-reserved-review', author=pending['username'])
        service.connection.execute('''INSERT INTO translation_reservations
            (language, unit_id, proposal_id, owner_uuid, expires_at) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(language, unit_id) DO UPDATE SET proposal_id = excluded.proposal_id,
            owner_uuid = excluded.owner_uuid, expires_at = excluded.expires_at''',
            (proposal['language'], proposal['unit_id'], proposal['id'], proposal['author_uuid'],
             0 if proposal['status'] == 'pending' else now + RESERVATION_SECONDS))

    def drop(self, proposal):
        self.service.connection.execute('DELETE FROM translation_reservations WHERE proposal_id = ?', (proposal['id'],))

    def reserve(self, viewer, proposal_id, expected):
        service = self.service
        with service.atomic():
            service.account(viewer, writing=True)
            proposal = service.get(viewer, proposal_id)
            service.revision(proposal, expected)
            if proposal['status'] not in {'draft', 'changes_requested'}:
                raise TranslationError('translation-error-readonly')
            service.catalog.get(proposal['unit_id'])
            self.claim(proposal)

    def release(self, viewer, proposal_id, expected):
        service = self.service
        with service.atomic():
            service.account(viewer, writing=True)
            proposal = service.get(viewer, proposal_id)
            service.revision(proposal, expected)
            if proposal['status'] not in {'draft', 'changes_requested'}:
                raise TranslationError('translation-error-readonly')
            self.drop(proposal)
            service.connection.execute('''UPDATE translation_proposals SET revision = revision + 1,
                updated_at = ? WHERE id = ?''', (int(service.clock()), proposal_id))
            service._event(proposal_id, viewer, 'released')
