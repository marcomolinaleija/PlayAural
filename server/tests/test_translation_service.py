"""Translation ownership, durable review and conflicts use the actual database."""

from dataclasses import replace
import json
import zipfile

import pytest

from ..persistence.database import Database
from ..translations.catalog import Catalog, read_web_object
from ..translations.models import TranslationError
from ..translations.service import TranslationService
from ..translations.validation import validate, example
from ..translations.forms import forms, assemble
from ..translations.exporter import snapshot, export_bundle
from ..translations.catalog import fluent_messages


@pytest.fixture
def workbench(tmp_path):
    root = tmp_path / 'source'
    for language in ('en', 'es', 'fr'):
        folder = root / 'server/locales' / language
        folder.mkdir(parents=True)
        (folder / 'metadata.json').write_text(json.dumps({'code': language, 'name': language, 'native_name': language}), encoding='utf-8')
    (root / 'server/locales/es/main.ftl').write_text('greeting = Hola, { $player }.\nplain = Hola.\n', encoding='utf-8')
    (root / 'server/locales/en/main.ftl').write_text('greeting = Hello, { $player }.\nplain = Hello.\nonly-english = English source.\n', encoding='utf-8')
    (root / 'server/locales/fr/main.ftl').write_text('plain = Salut.\n', encoding='utf-8')
    db = Database(tmp_path / 'workbench.db')
    db.connect()
    accounts = {}
    for name, level in (('Author', 1), ('Other', 1), ('Admin', 2), ('Developer', 3)):
        accounts[name] = db.create_user(name, 'hash', locale='es', trust_level=level, approved=True).uuid
    service = TranslationService(db, Catalog(root))
    yield service, accounts, root
    db.close()


def unit(service, key='greeting'):
    return next(u for u in service.catalog.units.values() if u.key == key)


def ready(service, owner, *, key='greeting', value='Bonjour, { $player }.'):
    row = service.draft(owner, 'fr', unit(service, key).id)
    row = service.save(owner, row['id'], value, row['revision'])
    service.submit(owner, [(row['id'], row['revision'])])
    return service.get(owner, row['id'])


def test_catalog_covers_english_only_originals_and_never_executes_modules(workbench):
    service, _, _ = workbench
    assert unit(service).source_locale == 'es'
    assert unit(service, 'only-english').source_locale == 'en'
    assert read_web_object('export default {"link":"https://example.test/", // comment\n "key":"Value",};') == {'link': 'https://example.test/', 'key': 'Value'}
    with pytest.raises(ValueError):
        read_web_object('export default (() => { throw Error("execute"); })();')


@pytest.mark.parametrize('reviewer', ['Admin', 'Developer'])
def test_draft_submission_review_preview_credit_and_persistence(workbench, reviewer):
    service, accounts, _ = workbench
    owner, staff = accounts['Author'], accounts[reviewer]
    row = service.draft(owner, 'fr', unit(service).id)
    assert service.draft(owner, 'fr', unit(service).id)['id'] == row['id']
    row = service.save(owner, row['id'], 'Bonjour, { $player }.', row['revision'])
    assert service.preview(owner, row['id']) == 'Bonjour, Alex.'
    assert service.current('fr', unit(service).id) == ''
    service.submit(owner, [(row['id'], row['revision'])])
    row = service.get(owner, row['id'])
    assert len(service.proposals(staff, pending=True)) == 1
    service.review(staff, row['id'], row['revision'], 'approved')
    assert service.current('fr', unit(service).id) == 'Bonjour, { $player }.'
    assert service.credits(owner, 'fr') == [{'uuid': owner, 'username': 'Author', 'contributions': 1}]
    service.db.close()
    service.db.connect()
    assert service.get(owner, row['id'])['status'] == 'approved'
    assert service.current('fr', unit(service).id) == 'Bonjour, { $player }.'


def test_drafts_and_history_are_private_and_staff_cannot_self_approve(workbench):
    service, accounts, _ = workbench
    draft = service.draft(accounts['Author'], 'fr', unit(service).id)
    with pytest.raises(TranslationError, match='proposal'):
        service.get(accounts['Admin'], draft['id'], review=True)
    row = ready(service, accounts['Admin'])
    with pytest.raises(TranslationError, match='self-review'):
        service.review(accounts['Admin'], row['id'], row['revision'], 'approved')
    with pytest.raises(TranslationError, match='proposal'):
        service.get(accounts['Other'], row['id'])
    with pytest.raises(TranslationError, match='reviewer'):
        service.get(accounts['Other'], row['id'], review=True)
    with pytest.raises(TranslationError, match='reviewer'):
        service.proposals(accounts['Other'], pending=True)
    assert service.get(accounts['Developer'], row['id'], review=True)['value'] == row['value']


def test_return_for_corrections_withdraw_and_resubmit_preserve_work(workbench):
    service, accounts, _ = workbench
    owner, staff = accounts['Author'], accounts['Admin']
    row = ready(service, owner)
    with pytest.raises(TranslationError, match='text'):
        service.review(staff, row['id'], row['revision'], 'changes_requested')
    row = service.review(staff, row['id'], row['revision'], 'changes_requested', 'Usa un saludo menos formal.')
    assert row['note'] == 'Usa un saludo menos formal.'
    row = service.save(owner, row['id'], 'Salut, { $player }.', row['revision'])
    service.submit(owner, [(row['id'], row['revision'])])
    row = service.get(owner, row['id'])
    row = service.withdraw(owner, row['id'], row['revision'])
    assert row['value'] == 'Salut, { $player }.' and row['status'] == 'draft'
    service.submit(owner, [(row['id'], row['revision'])])
    assert len(service.history(owner, row['id'])) >= 5


def test_batch_validation_is_all_or_nothing_and_invalid_drafts_survive(workbench):
    service, accounts, _ = workbench
    owner = accounts['Author']
    valid = service.draft(owner, 'fr', unit(service, 'plain').id)
    valid = service.save(owner, valid['id'], 'Bonjour.', valid['revision'])
    invalid = service.draft(owner, 'fr', unit(service).id)
    invalid = service.save(owner, invalid['id'], 'Bonjour.', invalid['revision'])
    with pytest.raises(TranslationError, match='variables'):
        service.submit(owner, [(valid['id'], valid['revision']), (invalid['id'], invalid['revision'])])
    assert service.get(owner, valid['id'])['status'] == 'draft'
    assert service.get(owner, invalid['id'])['value'] == 'Bonjour.'


def test_source_changes_and_concurrent_approvals_require_author_reconciliation(workbench):
    service, accounts, _ = workbench
    first = ready(service, accounts['Author'])
    # Retained pre-reservation submissions can overlap. Review still protects
    # their comparison base without dropping either author's existing work.
    with service.atomic():
        cursor = service.connection.execute('''INSERT INTO translation_proposals
            (author_uuid, author_name, language, unit_id, source_text, source_hash, base_hash, value,
             status, created_at, updated_at) VALUES (?, 'Other', 'fr', ?, ?, ?, ?, ?, 'pending', 1, 1)''',
            (accounts['Other'], first['unit_id'], first['source_text'], first['source_hash'], first['base_hash'], 'Salut, { $player }.'))
    second = service.get(accounts['Other'], cursor.lastrowid)
    service.review(accounts['Admin'], first['id'], first['revision'], 'approved')
    with pytest.raises(TranslationError, match='target-changed'):
        service.review(accounts['Admin'], second['id'], second['revision'], 'approved')
    returned = service.review(accounts['Admin'], second['id'], second['revision'], 'changes_requested', 'Revisa la nueva traducción aprobada.')
    returned = service.refresh_source(accounts['Other'], second['id'], returned['revision'])
    service.submit(accounts['Other'], [(returned['id'], returned['revision'])])
    pending = service.get(accounts['Other'], returned['id'])
    original = unit(service)
    service.catalog.units[original.id] = replace(original, original='Buenos días, { $player }.')
    with pytest.raises(TranslationError, match='source-changed'):
        service.review(accounts['Admin'], pending['id'], pending['revision'], 'approved')


def test_stale_edit_lost_permissions_and_account_deletion(workbench):
    service, accounts, _ = workbench
    row = ready(service, accounts['Author'])
    with pytest.raises(TranslationError, match='changed'):
        service.review(accounts['Admin'], row['id'], row['revision'] - 1, 'approved')
    service.db.update_user_trust_level('Admin', 1)
    with pytest.raises(TranslationError, match='reviewer'):
        service.review(accounts['Admin'], row['id'], row['revision'], 'approved')
    assert service.get(accounts['Author'], row['id'])['status'] == 'pending'
    service.db.delete_user('Author')
    assert not service.proposals(accounts['Developer'], pending=True)


def test_revert_keeps_revision_monotonic_and_does_not_overwrite_newer_approval(workbench):
    service, accounts, _ = workbench
    row = ready(service, accounts['Author'])
    row = service.review(accounts['Admin'], row['id'], row['revision'], 'approved')
    service.revert(accounts['Admin'], row['id'], row['revision'])
    assert service.current('fr', unit(service).id) == ''
    next_row = ready(service, accounts['Other'])
    service.review(accounts['Admin'], next_row['id'], next_row['revision'], 'approved')
    with pytest.raises(TranslationError, match='changed'):
        service.revert(accounts['Admin'], row['id'], row['revision'])


def test_new_language_approval_does_not_grant_staff_permissions(workbench):
    service, accounts, _ = workbench
    owner = accounts['Author']
    assert service.create_language(owner, 'de', 'Alemán', 'Deutsch') == 'de'
    with pytest.raises(TranslationError, match='language-exists'):
        service.create_language(owner, 'de', 'Otra', 'Otra')
    with pytest.raises(TranslationError, match='language'):
        service.create_language(owner, '../x', 'Otra', 'Otra')
    row = service.draft(owner, 'de', unit(service, 'plain').id)
    row = service.save(owner, row['id'], 'Hallo.', row['revision'])
    service.submit(owner, [(row['id'], row['revision'])])
    row = service.get(owner, row['id'])
    service.review(accounts['Admin'], row['id'], row['revision'], 'approved')
    assert service.language(owner, 'de')['status'] == 'approved'
    assert service.db.get_user('Author').trust_level == 1


def test_only_reviewed_current_translations_are_exported_with_credits_and_registries(workbench, tmp_path):
    service, accounts, _ = workbench
    row = ready(service, accounts['Author'])
    service.review(accounts['Admin'], row['id'], row['revision'], 'approved')
    pending = ready(service, accounts['Other'], key='plain', value='Bonjour.')
    data = snapshot(service, accounts['Admin'])
    assert len(data['entries']) == 1
    destination = export_bundle(data, service.catalog, tmp_path / 'translations.zip')
    with zipfile.ZipFile(destination) as archive:
        assert archive.testzip() is None
        source = archive.read('server/locales/fr/main.ftl').decode('utf-8')
        assert 'Bonjour, { $player }.' in source
        assert 'plain = Salut.' in source
        assert 'plain = Bonjour.' not in source
        assert 'Author' in archive.read('server/locales/fr/metadata.json').decode('utf-8')
        assert 'fr' in archive.read('web_client/locales/manifest.js').decode('utf-8')
        assert 'catalog_fr' in archive.read('mobile_client/src/i18n/localeCatalogs.ts').decode('utf-8')
    with pytest.raises(FileExistsError):
        export_bundle(data, service.catalog, destination)
    assert service.get(accounts['Other'], pending['id'])['status'] == 'pending'


def test_missing_references_are_exported_as_explicit_untranslated_fallbacks(workbench, tmp_path):
    service, accounts, _ = workbench
    original = replace(unit(service), original='{ only-english }')
    service.catalog.units[original.id] = original
    row = ready(service, accounts['Author'], value='Référence: { only-english }')
    assert service.preview(accounts['Author'], row['id']) == 'Référence: English source.'
    service.review(accounts['Admin'], row['id'], row['revision'], 'approved')
    destination = export_bundle(snapshot(service, accounts['Admin']), service.catalog, tmp_path / 'references.zip')
    with zipfile.ZipFile(destination) as archive:
        messages = fluent_messages(archive.read('server/locales/fr/main.ftl').decode())
        assert messages['only-english'] == 'English source.'
        metadata = json.loads(archive.read('server/locales/fr/metadata.json'))
        assert unit(service, 'only-english').id in metadata['fallback_units']


def test_notifications_are_owner_scoped_and_reverts_remain_in_review_history(workbench):
    service, accounts, _ = workbench
    row = ready(service, accounts['Author'])
    row = service.review(accounts['Admin'], row['id'], row['revision'], 'approved')
    assert service.notice_count(accounts['Author']) == 1
    assert service.notice_count(accounts['Other']) == 0
    service.mark_seen(accounts['Author'], row['id'])
    assert service.notice_count(accounts['Author']) == 0
    service.revert(accounts['Admin'], row['id'], row['revision'], accepted_revision=1)
    assert service.notice_count(accounts['Author']) == 1
    assert service.proposal_page(accounts['Admin'], review=True, history=True).items[0]['status'] == 'reverted'


def test_reviewer_cannot_read_work_withdrawn_for_private_edits(workbench):
    service, accounts, _ = workbench
    row = ready(service, accounts['Author'])
    row = service.withdraw(accounts['Author'], row['id'], row['revision'])
    with pytest.raises(TranslationError, match='proposal'):
        service.get(accounts['Admin'], row['id'], review=True)
    assert service.get(accounts['Author'], row['id'])['value'] == row['value']


def test_format_validation_rejects_injected_messages_functions_and_lost_variants(workbench):
    service, _, _ = workbench
    source = unit(service)
    for invalid in ('Bonjour.\ninjected = Surprise.', 'Bonjour, { SECRET($player) }.'):
        with pytest.raises(TranslationError):
            validate(source, invalid)
    source = replace(source, original='{ $count ->\n [one] Uno\n *[other] Muchos\n}')
    assert validate(source, '{ $count ->\n [one] Un\n *[other] Plusieurs\n}')
    with pytest.raises(TranslationError, match='variants'):
        validate(source, '{ $count ->\n *[other] Plusieurs\n}')


def test_guided_forms_preserve_selectors_require_each_form_and_validate_each_variable(workbench):
    service, accounts, _ = workbench
    source = unit(service)
    source = replace(source, original='{ $gender ->\n [male] Bienvenido, { $player }.\n [female] Bienvenida, { $player }.\n *[other] Hola, { $player }.\n}')
    service.catalog.units[source.id] = source
    fields = forms(source)
    assert len(fields) == 3
    row = service.draft(accounts['Author'], 'fr', source.id)
    row = service.save_form(accounts['Author'], row['id'], fields[0].id, 'Bienvenue, { $player }.', row['revision'])
    with pytest.raises(TranslationError, match='forms'):
        service.submit(accounts['Author'], [(row['id'], row['revision'])])
    for field in fields[1:]:
        row = service.save_form(accounts['Author'], row['id'], field.id, 'Bonjour, { $player }.', row['revision'])
    assert service.preview(accounts['Author'], row['id'], form_id=fields[0].id) == 'Bienvenue, Alex.'
    service.submit(accounts['Author'], [(row['id'], row['revision'])])
    row = service.get(accounts['Author'], row['id'])
    service.review(accounts['Admin'], row['id'], row['revision'], 'approved')
    assert '[female]' in service.current('fr', source.id)
    assert '{ $gender ->' in service.current('fr', source.id)


def test_guided_forms_preserve_text_around_selectors_and_attributes(workbench):
    service, _, _ = workbench
    source = replace(unit(service), original='Aviso: { $count ->\n [one] Una persona\n *[other] Varias personas\n} conectadas.\n    .label = Personas')
    fields = forms(source)
    assert len(fields) == 5
    values = {field.id: field.value for field in fields}
    assert validate(source, assemble(source, values, validate_fields=True))


def test_rejected_work_can_be_reused_without_overwriting_an_existing_draft(workbench):
    service, accounts, _ = workbench
    author, reviewer = accounts['Author'], accounts['Admin']
    proposal = ready(service, author)
    service.review(reviewer, proposal['id'], proposal['revision'], 'rejected', 'Corrige el saludo.')
    draft = service.draft(author, 'fr', proposal['unit_id'], copy_from=proposal['id'])
    assert draft['id'] != proposal['id'] and draft['value'] == proposal['value']
    draft = service.save(author, draft['id'], 'Salut, { $player }.', draft['revision'])
    assert service.draft(author, 'fr', proposal['unit_id'], copy_from=proposal['id'])['value'] == draft['value']
    with pytest.raises(TranslationError):
        service.draft(accounts['Other'], 'fr', proposal['unit_id'], copy_from=proposal['id'])


def test_v12_migration_has_verified_backup_and_preserves_existing_state(tmp_path):
    path = tmp_path / 'v12.db'
    db = Database(path)
    db._conn = db._open_connection(str(path), timeout=30)
    db._conn.execute('PRAGMA foreign_keys = ON')
    with db._transaction(immediate=True) as cursor:
        db._create_tables_in_transaction(cursor, forum_version=12)
        cursor.execute(f'PRAGMA application_id = {Database.APPLICATION_ID}')
        cursor.execute('PRAGMA user_version = 12')
    account = db.create_user('Existing', 'hash', locale='es', approved=True)
    db.close()
    db.connect(migration_backup_dir=tmp_path / 'backups')
    assert db.get_user('Existing').uuid == account.uuid
    assert db._conn.execute('PRAGMA user_version').fetchone()[0] == Database.CURRENT_SCHEMA_VERSION
    backups = list((tmp_path / 'backups').glob('*.sqlite3'))
    assert len(backups) == 1
    with db._open_connection(str(backups[0]), timeout=30) as backup:
        assert backup.execute('PRAGMA user_version').fetchone()[0] == 12
        assert backup.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    db.close()
