"""Reservations and review groups use real transactions and immutable owners."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from ..persistence.database import Database
from ..translations.models import TranslationError
from ..translations.service import TranslationService
from ..translations.reservations import RESERVATION_SECONDS
from ..translations.exporter import snapshot
from .test_translation_service import workbench, unit, ready


def test_viewing_does_not_reserve_and_expiry_keeps_both_private_drafts(workbench):
    service, users, _ = workbench
    now = [1000]
    service.clock = lambda: now[0]
    first = service.draft(users['Author'], 'fr', unit(service).id)
    second = service.draft(users['Other'], 'fr', unit(service).id)
    assert not service.reservations.active('fr')
    first = service.save(users['Author'], first['id'], 'Bonjour, { $player }.', first['revision'])
    with pytest.raises(TranslationError, match='reserved'):
        service.reservations.reserve(users['Other'], second['id'], second['revision'])
    with pytest.raises(TranslationError, match='proposal'):
        service.get(users['Other'], first['id'])
    now[0] += RESERVATION_SECONDS + 1
    second = service.save(users['Other'], second['id'], 'Salut, { $player }.', second['revision'])
    with pytest.raises(TranslationError, match='reserved'):
        service.save(users['Author'], first['id'], 'Late edit', first['revision'])
    assert service.get(users['Author'], first['id'])['value'] == first['value']
    service.reservations.release(users['Other'], second['id'], second['revision'])
    assert service.get(users['Other'], second['id'])['value'] == second['value']
    service.reservations.reserve(users['Author'], first['id'], first['revision'])


def test_pending_does_not_expire_and_decisions_renew_or_release_reservations(workbench):
    service, users, _ = workbench
    now = [1000]
    service.clock = lambda: now[0]
    first = ready(service, users['Author'])
    second = service.draft(users['Other'], 'fr', unit(service).id)
    now[0] += RESERVATION_SECONDS * 10
    with pytest.raises(TranslationError, match='reserved-review'):
        service.reservations.reserve(users['Other'], second['id'], second['revision'])
    returned = service.review(users['Admin'], first['id'], first['revision'], 'changes_requested', 'Revisa el saludo.')
    with pytest.raises(TranslationError, match='reserved'):
        service.reservations.reserve(users['Other'], second['id'], second['revision'])
    service.reservations.release(users['Author'], returned['id'], returned['revision'])
    returned = service.get(users['Author'], returned['id'])
    service.reservations.reserve(users['Other'], second['id'], second['revision'])
    with pytest.raises(TranslationError, match='reserved'):
        service.submit(users['Author'], [(returned['id'], returned['revision'])])
    service.discard(users['Other'], second['id'], second['revision'])
    service.submit(users['Author'], [(returned['id'], returned['revision'])])
    pending = service.get(users['Author'], first['id'])
    service.review(users['Admin'], pending['id'], pending['revision'], 'approved')
    assert not service.reservations.active('fr')


def test_discarding_an_expired_draft_does_not_release_someone_elses_work(workbench):
    service, users, _ = workbench
    now = [1000]
    service.clock = lambda: now[0]
    first = service.draft(users['Author'], 'fr', unit(service).id)
    service.reservations.reserve(users['Author'], first['id'], first['revision'])
    now[0] += RESERVATION_SECONDS + 1
    second = service.draft(users['Other'], 'fr', unit(service).id)
    service.reservations.reserve(users['Other'], second['id'], second['revision'])
    service.discard(users['Author'], first['id'], first['revision'])
    assert service.reservations.active('fr')[first['unit_id']]['owner_uuid'] == users['Other']
    service.db.delete_user('Other')
    assert not service.reservations.active('fr')
    assert not service.connection.execute('PRAGMA foreign_key_check').fetchall()


def test_review_groups_filter_by_language_and_uuid_without_exposing_drafts(workbench):
    service, users, _ = workbench
    first = ready(service, users['Author'])
    ready(service, users['Other'], key='plain', value='Bonjour.')
    service.draft(users['Other'], 'fr', unit(service, 'only-english').id)
    service.create_language(users['Author'], 'de', 'German', 'Deutsch')
    draft = service.draft(users['Author'], 'de', unit(service).id)
    draft = service.save(users['Author'], draft['id'], 'Hallo, { $player }.', draft['revision'])
    service.submit(users['Author'], [(draft['id'], draft['revision'])])
    groups = service.review_groups(users['Admin'])
    assert {g['language']: g['count'] for g in groups.items} == {'fr': 2, 'de': 1}
    people = service.review_groups(users['Admin'], language='fr')
    assert {g['author']: g['count'] for g in people.items} == {'Author': 1, 'Other': 1}
    page = service.proposal_page(users['Admin'], language='fr', review=True, author=users['Author'])
    assert [row['id'] for row in page.items] == [first['id']]
    service.review(users['Admin'], first['id'], first['revision'], 'approved')
    service.db.delete_user('Author')
    history = service.review_groups(users['Admin'], language='fr', history=True)
    assert history.items == [{'author_id': 'deleted', 'author': '', 'count': 1}]
    with pytest.raises(TranslationError, match='reviewer'):
        service.review_groups(users['Other'])


def test_competing_database_connections_cannot_both_reserve_a_text(workbench):
    service, users, _ = workbench
    proposals = [(owner, service.draft(owner, 'fr', unit(service).id)) for owner in (users['Author'], users['Other'])]
    database_path = service.db.db_path
    barrier = Barrier(2)

    def reserve(entry):
        owner, proposal = entry
        db = Database(database_path)
        db.connect()
        try:
            contender = TranslationService(db, service.catalog)
            barrier.wait(timeout=15)
            try:
                contender.reservations.reserve(owner, proposal['id'], proposal['revision'])
                return 'reserved'
            except TranslationError as error:
                return error.key
        finally:
            db.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(reserve, proposals))
    assert sorted(outcomes) == ['reserved', 'translation-error-reserved']


def test_v13_migration_preserves_duplicate_pending_work_and_private_drafts(workbench, tmp_path):
    service, _, _ = workbench
    path = tmp_path / 'schema13.db'
    old = Database(path)
    old._conn = old._open_connection(path, timeout=30)
    old._conn.execute('PRAGMA foreign_keys = ON')
    with old._transaction(immediate=True) as cursor:
        old._create_tables_in_transaction(cursor, forum_version=13)
        cursor.execute(f'PRAGMA application_id = {Database.APPLICATION_ID}')
        cursor.execute('PRAGMA user_version = 13')
    old_service = TranslationService(old, service.catalog)
    ids = []
    for name in ('First', 'Second'):
        owner = old.create_user(name, 'hash', locale='es', approved=True)
        proposal = old_service.draft(owner.uuid, 'fr', unit(service).id)
        old._conn.execute("UPDATE translation_proposals SET status = 'pending', value = ? WHERE id = ?",
                          ('Bonjour, { $player }.', proposal['id']))
        ids.append(proposal['id'])
    old_service.draft(owner.uuid, 'fr', unit(service, 'only-english').id)
    old.close()
    old.connect(migration_backup_dir=tmp_path / 'backups')
    try:
        assert old._conn.execute('SELECT COUNT(*) FROM translation_proposals').fetchone()[0] == 3
        reservation = old._conn.execute('SELECT proposal_id, expires_at FROM translation_reservations').fetchone()
        assert tuple(reservation) == (ids[0], 0)
        assert old._conn.execute('PRAGMA user_version').fetchone()[0] == 14
        backup = next((tmp_path / 'backups').glob('*.sqlite3'))
        with old._open_read_only_connection(backup, timeout=5) as copied:
            assert copied.execute('PRAGMA user_version').fetchone()[0] == 13
            assert copied.execute('SELECT COUNT(*) FROM translation_proposals').fetchone()[0] == 3
    finally:
        old.close()


def test_translator_reviews_only_assigned_languages_without_admin_permissions(workbench):
    service, users, _ = workbench
    french = ready(service, users['Author'])
    service.create_language(users['Author'], 'de', 'German', 'Deutsch')
    german = service.draft(users['Author'], 'de', unit(service).id)
    german = service.save(users['Author'], german['id'], 'Hallo, { $player }.', german['revision'])
    service.submit(users['Author'], [(german['id'], german['revision'])])
    german = service.get(users['Author'], german['id'])
    service.roles.set(users['Admin'], users['Other'], 'fr', True, 0)
    assert service.db.get_user('Other').trust_level == 1
    assert service.roles.can_review(users['Other'], 'fr')
    assert not service.roles.can_review(users['Other'], 'de')
    assert {group['language'] for group in service.review_groups(users['Other']).items} == {'fr'}
    assert [row['id'] for row in service.proposals(users['Other'], pending=True)] == [french['id']]
    for operation in (
        lambda: service.get(users['Other'], german['id'], review=True),
        lambda: service.preview(users['Other'], german['id'], review=True),
        lambda: service.history(users['Other'], german['id'], review=True),
        lambda: service.proposal_page(users['Other'], language='de', review=True),
        lambda: service.review(users['Other'], german['id'], german['revision'], 'approved'),
    ):
        with pytest.raises(TranslationError, match='reviewer'):
            operation()
    with pytest.raises(TranslationError, match='role-admin'):
        service.roles.set(users['Other'], users['Other'], 'de', True, 0)
    with pytest.raises(TranslationError, match='role-admin'):
        snapshot(service, users['Other'])
    service.review(users['Other'], french['id'], french['revision'], 'approved')
    own = ready(service, users['Other'], key='plain', value='Bonjour.')
    with pytest.raises(TranslationError, match='self-review'):
        service.review(users['Other'], own['id'], own['revision'], 'approved')
    service.roles.set(users['Admin'], users['Other'], 'fr', False, 1)
    with pytest.raises(TranslationError, match='reviewer'):
        service.get(users['Other'], own['id'], review=True)
    assert service.get(users['Other'], own['id'])['status'] == 'pending'


def test_role_revocations_are_monotonic_persist_and_follow_account_deletion(workbench):
    service, users, _ = workbench
    service.roles.set(users['Admin'], users['Other'], 'fr', True, 0)
    service.roles.set(users['Admin'], users['Other'], 'fr', False, 1)
    with pytest.raises(TranslationError, match='changed'):
        service.roles.set(users['Admin'], users['Other'], 'fr', True, 0)
    service.roles.set(users['Admin'], users['Other'], 'fr', True, 2)
    service.db.close()
    service.db.connect()
    assert service.roles.languages(users['Other']) == {'fr'}
    service.db.delete_user('Admin')
    assert service.roles.languages(users['Other']) == {'fr'}
    assert service.roles.assignments(users['Developer'], users['Other'])['fr']['granted_by'] is None
    service.db.delete_user('Other')
    assert not service.connection.execute('SELECT 1 FROM translation_roles WHERE user_uuid = ?', (users['Other'],)).fetchone()
    assert not service.connection.execute('PRAGMA foreign_key_check').fetchall()


def test_admin_can_revoke_role_from_an_unapproved_account(workbench):
    service, users, _ = workbench
    service.roles.set(users['Admin'], users['Other'], 'fr', True, 0)
    with service.atomic():
        service.connection.execute('UPDATE users SET approved = 0 WHERE uuid = ?', (users['Other'],))
    assert service.roles.assignments(users['Admin'], users['Other'])['fr']['enabled']
    service.roles.set(users['Admin'], users['Other'], 'fr', False, 1)
    assert not service.roles.is_translator(users['Other'])
