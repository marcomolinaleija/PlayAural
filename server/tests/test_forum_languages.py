"""Independent public communities share accounts, private chats and moderation."""

import asyncio
import json
import sqlite3
from types import SimpleNamespace

import pytest
from websockets.asyncio.client import connect

from ..core.server import Server, VERSION
from ..auth.auth import AuthManager
from ..forum import navigation as nav
from ..forum.languages import FORUM_LANGUAGES
from ..forum.models import Draft, ForumError
from ..forum.polls import PollConfig
from ..forum.reporting import capture_public_report, ForumReportEvidence
from ..forum.repository import ForumRepository
from ..forum.service import ForumService
from ..persistence import database as database_module
from ..persistence.database import Database
from ..users.network_user import NetworkUser


@pytest.fixture
def forum(tmp_path):
    server = Server(db_path=str(tmp_path / 'languages.db'))
    server.db.connect()
    users = {}
    for name, locale, level in (('Staff', 'es', 3), ('Spanish', 'es', 1), ('English', 'en', 1), ('Vietnamese', 'vi', 1)):
        account = server.db.create_user(name, 'hash', locale=locale, trust_level=level)
        server.db.approve_user(name)
        user = NetworkUser(name, locale, SimpleNamespace(username=name, authenticated=True, retired=False),
                           uuid=account.uuid, approved=True, trust_level=level)
        server._users[name] = users[name] = user
        server._show_main_menu(user)
        user.get_queued_messages()
    yield server, server.forum_manager.service, users
    server.db.close()


def test_initial_interface_language_explicit_selection_and_persistence_are_independent(forum):
    server, service, users = forum
    for name, language in (('Spanish', 'es'), ('English', 'en'), ('Vietnamese', 'vi')):
        assert service.languages.current(users[name].uuid) == language
    actor = users['Spanish']
    service.languages.select(actor.uuid, 'en')
    server.db.update_user_locale(actor.username, 'vi')
    server.db.close()
    server.db.connect()
    assert service.languages.current(actor.uuid) == 'en'
    assert server.db.get_user(actor.username).locale == 'vi'
    assert actor.locale == 'es'
    with pytest.raises(ForumError, match='forum-error-language'):
        service.languages.select(actor.uuid, 'xx')
    assert service.languages.current(actor.uuid) == 'en'


@pytest.mark.parametrize('view', ['recent', 'unread', 'saved', 'search', 'category'])
def test_all_public_views_and_counts_are_scoped_to_selected_language(forum, view):
    _, service, users = forum
    es, en = users['Spanish'].uuid, users['English'].uuid
    spanish, _ = service.create_topic(es, 'general', 'Shared search texto', 'Spanish content')
    english, _ = service.create_topic(en, 'en:general', 'Shared search text', 'English content')
    for topic in (spanish, english):
        service.bookmark(es, topic, True)
    for language, expected, category in (('es', spanish, 'general'), ('en', english, 'en:general')):
        service.languages.select(es, language)
        data = service.topics(es, view=view, query='Shared search' if view == 'search' else '', category_id=category)
        assert [topic.id for topic in data.items] == [expected]
        categories = service.categories(es)
        assert sum(category.topic_count for category in categories) == 1
        assert all(category.language == language for category in categories)
    # Both ids remain valid public references; language is navigation, not a new ACL.
    assert service.topic(es, spanish).id == spanish


def test_every_language_has_independent_defaults_and_private_membership_ignores_language(forum):
    _, service, users = forum
    actor, recipient = users['Spanish'].uuid, users['English'].uuid
    seen = set()
    for language in FORUM_LANGUAGES:
        categories = service.categories(actor, language=language)
        assert len(categories) == 3
        assert not seen.intersection(category.id for category in categories)
        seen.update(category.id for category in categories)
    topic, post = service.conversations.create(actor, 'Private', 'Private content', (recipient,))
    invite = service.conversations.invitations(recipient)[0]['id']
    service.conversations.respond(recipient, invite, accept=True)
    service.bookmark(recipient, topic, True)
    for language in ('es', 'en', 'vi'):
        service.languages.select(recipient, language)
        assert [t.id for t in service.topics(recipient, view='private').items] == [topic]
        assert [t.id for t in service.topics(recipient, view='saved').items] == [topic]
        assert service.post(recipient, post).body == 'Private content'
        assert sum(c.topic_count for c in service.categories(recipient)) == 0
        assert service.topics(recipient).total == 0
    with pytest.raises(ForumError):
        service.post(users['Staff'].uuid, post)


def test_language_changes_preserve_blocks_read_positions_and_bookmarks(forum):
    server, service, users = forum
    es, en = users['Spanish'].uuid, users['English'].uuid
    topic, post = service.create_topic(en, 'en:general', 'Topic', 'Body')
    service.languages.select(es, 'en')
    service.bookmark(es, topic, True)
    service.post(es, post, mark_read=True)
    service.languages.select(es, 'es')
    assert service.topics(es, view='saved').total == 0
    service.languages.select(es, 'en')
    assert service.topics(es, view='saved').items[0].unread_count == 0
    server.db.block_user(es, en)
    assert service.topics(es).total == 0
    assert service.topics(es, view='saved').total == 0
    assert sum(c.topic_count for c in service.categories(es)) == 0


def test_category_names_limits_and_move_destinations_are_per_language(forum, monkeypatch):
    _, service, users = forum
    staff = users['Staff'].uuid
    es = service.category_admin.create(staff, 'Events', language='es')
    en = service.category_admin.create(staff, 'Events', language='en')
    with pytest.raises(ForumError, match='category-duplicate'):
        service.category_admin.create(staff, 'Events', language='es')
    service.create_topic(users['Spanish'].uuid, es, 'Retained', 'Body')
    with pytest.raises(ForumError, match='category-language'):
        service.category_admin.delete(staff, es, 0, destination=en)
    assert service.repository.category(es).topic_count == 1
    monkeypatch.setattr('server.forum.categories.MAX_CATEGORIES', 4)
    with pytest.raises(ForumError, match='category-limit'):
        service.category_admin.create(staff, 'Fifth', language='es')
    assert service.category_admin.create(staff, 'Fourth', language='vi')


def test_draft_category_is_frozen_when_another_language_is_selected(forum):
    server, service, users = forum
    actor = users['Spanish']
    draft = Draft('topic', category_id='general', title='Original Spanish draft', body='Body')
    service.languages.select(actor.uuid, 'en')
    server._nav_push(actor, server.forum_manager.composer.show, draft)
    server.forum_manager.handle_menu(actor, 'publish', server._user_states[actor.username])
    assert service.topics(actor.uuid).total == 0
    data = service.topics(actor.uuid, language='es')
    assert data.items[0].title == draft.title
    # Category-editor creation similarly keeps the language visible when opened.
    actor = users['Staff']
    service.languages.select(actor.uuid, 'en')
    editor = {'id': '', 'name': 'Pinned creation', 'description': '', 'revision': 0, 'language': 'es'}
    server.forum_manager.categories.editor(actor, editor)
    server.forum_manager.categories.handle(actor, 'save_category', server._user_states[actor.username])
    assert any(c.name == 'Pinned creation' for c in service.categories(actor.uuid, language='es'))
    assert not any(c.name == 'Pinned creation' for c in service.categories(actor.uuid, language='en'))


def test_report_evidence_keeps_content_language_even_if_reporter_switches(forum):
    server, service, users = forum
    _, post = service.create_topic(users['English'].uuid, 'en:general', 'English topic', 'Body')
    reporter = users['Spanish']
    evidence = capture_public_report(service, reporter.uuid, 'post', post)
    assert evidence.language == 'en'
    result = server.db.submit_moderation_report(reporter_uuid=reporter.uuid, reporter_username=reporter.username,
        forum_target=evidence.target, reason_code='spam')
    service.languages.select(reporter.uuid, 'vi')
    retained = ForumReportEvidence.from_json(server.db.get_moderation_report(result.report_id).evidence_json)
    assert retained.language == 'en'
    legacy_json = json.loads(retained.to_json())
    legacy_json.pop('language')
    assert ForumReportEvidence.from_json(json.dumps(legacy_json)).language == 'es'


def test_language_preference_is_removed_with_account(forum):
    server, service, users = forum
    service.languages.select(users['Spanish'].uuid, 'en')
    server.db.delete_user('Spanish')
    assert not server.db._conn.execute('SELECT 1 FROM forum_language_preferences').fetchone()


def legacy_eight(path):
    db = Database(path)
    db._conn = db._open_connection(str(path), timeout=30)
    db._conn.execute('PRAGMA foreign_keys = ON')
    with db._transaction(immediate=True) as cursor:
        db._create_tables_in_transaction(cursor, forum_version=8)
        cursor.execute(f'PRAGMA application_id = {Database.APPLICATION_ID}')
        cursor.execute('PRAGMA user_version = 8')
    actor = db.create_user('Existing', 'hash', locale='es')
    db.approve_user(actor.username)
    service = ForumService(ForumRepository(db))
    topic, post = service.create_topic(actor.uuid, 'general', 'Retained topic', 'Retained body',
                                     poll=PollConfig('Question', ('Yes', 'No')))
    service.bookmark(actor.uuid, topic, True)
    service.post(actor.uuid, post, mark_read=True)
    with db._transaction(immediate=True) as cursor:
        cursor.execute("UPDATE forum_categories SET name = 'Custom name', description = 'Description', revision = 2 WHERE id = 'general'")
        cursor.execute("DELETE FROM forum_categories WHERE id = 'ideas'")
    db.close()
    return actor.uuid, topic, post


def test_v9_migration_preserves_ids_polls_personal_state_and_deleted_defaults(tmp_path):
    path = tmp_path / 'legacy.db'
    actor, topic, post = legacy_eight(path)
    db = Database(path)
    db.connect(migration_backup_dir=tmp_path / 'backups')
    try:
        service = ForumService(ForumRepository(db))
        category = service.repository.category('general')
        assert (category.name, category.description, category.revision, category.language) == ('Custom name', 'Description', 2, 'es')
        assert service.topic(actor, topic).bookmarked and service.topic(actor, topic).unread_count == 0
        assert service.post(actor, post).body == 'Retained body'
        assert service.polls.get(actor, post)['question'] == 'Question'
        assert not service.repository.has_category('ideas')
        assert len(service.categories(actor, language='en')) == 3
        with db._open_connection(str(next((tmp_path / 'backups').glob('*.sqlite3'))), timeout=30) as backup:
            assert backup.execute('PRAGMA user_version').fetchone()[0] == 8
            assert backup.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert 'language' not in [r[1] for r in backup.execute('PRAGMA table_info(forum_categories)')]
        # An empty community must remain empty after restart.
        with db._transaction(immediate=True) as cursor:
            cursor.execute("DELETE FROM forum_categories WHERE language = 'en'")
    finally:
        db.close()
    db.connect()
    assert not ForumService(ForumRepository(db)).categories(actor, language='en')
    db.close()


def test_v9_migration_rolls_back_language_data_and_reuses_verified_backup(tmp_path, monkeypatch):
    path = tmp_path / 'legacy.db'
    actor, topic, post = legacy_eight(path)
    original = database_module.create_forum_schema
    def fail(cursor, **kwargs):
        original(cursor, **kwargs)
        raise sqlite3.DatabaseError('Injected failure')
    monkeypatch.setattr(database_module, 'create_forum_schema', fail)
    with pytest.raises(sqlite3.DatabaseError):
        Database(path).connect(migration_backup_dir=tmp_path / 'backups')
    with sqlite3.connect(path) as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 8
        assert 'language' not in [r[1] for r in connection.execute('PRAGMA table_info(forum_categories)')]
        assert connection.execute('SELECT body FROM forum_posts WHERE id = ?', (post,)).fetchone()[0] == 'Retained body'
    monkeypatch.setattr(database_module, 'create_forum_schema', original)
    db = Database(path)
    db.connect(migration_backup_dir=tmp_path / 'backups')
    assert db._conn.execute('PRAGMA user_version').fetchone()[0] == 9
    assert len(list((tmp_path / 'backups').glob('*.sqlite3'))) == 1
    db.close()


@pytest.mark.parametrize('client_type', ['python', 'web'])
async def test_language_selection_and_category_management_over_real_socket(tmp_path, client_type):
    server = Server(host='127.0.0.1', port=0, db_path=str(tmp_path / 'socket.db'))
    await server.start()
    try:
        auth = AuthManager(server.db)
        assert auth.register('Staff', 'TestPassword123', locale='es', email='staff@example.test') == 'ok'
        server.db.approve_user('Staff')
        actor = server.db.get_user('Staff').uuid
        server.forum_manager.service.create_topic(actor, 'general', 'Solo español', 'Body')
        server.forum_manager.service.create_topic(actor, 'en:general', 'English only', 'Body in English')
        port = server._ws_server._server.sockets[0].getsockname()[1]
        async def receive(ws, predicate):
            async with asyncio.timeout(15):
                while True:
                    packet = json.loads(await ws.recv())
                    if predicate(packet):
                        return packet
        async def choose(ws, menu, action, result):
            await ws.send(json.dumps({'type': 'menu', 'menu_id': menu, 'selection_id': action}))
            return await receive(ws, lambda p: p.get('menu_id') == result)
        async with connect(f'ws://127.0.0.1:{port}') as ws:
            await ws.send(json.dumps({'type': 'authorize', 'client': client_type, 'version': VERSION,
                                     'username': 'Staff', 'password': 'TestPassword123'}))
            await receive(ws, lambda p: p.get('menu_id') == 'main_menu')
            home = await choose(ws, 'main_menu', 'forum', nav.HOME)
            assert home['title'] == 'Foro: Español' and home['items'][0]['id'] == 'category:general'
            await choose(ws, nav.HOME, 'language', nav.LANGUAGES)
            english = await choose(ws, nav.LANGUAGES, 'language:en', nav.HOME)
            assert english['title'] == 'Foro: Inglés'
            assert english['selection_id'] == 'language'
            assert english['items'][0]['id'] == 'category:en:general'
            assert english['items'][0]['text'].startswith('Community')
            topics = await choose(ws, nav.HOME, 'recent', nav.TOPICS)
            assert any('English only' in row['text'] for row in topics['items'])
            assert not any('Solo español' in row['text'] for row in topics['items'])
            await choose(ws, nav.TOPICS, 'back', nav.HOME)
            categories = await choose(ws, nav.HOME, 'manage_categories', nav.CATEGORIES)
            assert categories['items'][0]['id'] == 'edit_category:en:general'
            await choose(ws, nav.CATEGORIES, 'create_category', nav.CATEGORY_EDITOR)
            await ws.send(json.dumps({'type':'menu','menu_id':nav.CATEGORY_EDITOR,'selection_id':'edit_category_name'}))
            await receive(ws, lambda p: p.get('input_id') == nav.CATEGORY_NAME_INPUT and p.get('type') == 'request_input')
            await ws.send(json.dumps({'type':'editbox','input_id':nav.CATEGORY_NAME_INPUT,'text':'English events'}))
            await receive(ws, lambda p: p.get('menu_id') == nav.CATEGORY_EDITOR)
            await choose(ws, nav.CATEGORY_EDITOR, 'save_category', nav.CATEGORIES)
            assert any(c.name == 'English events' for c in server.forum_manager.service.categories(actor, language='en'))
            assert not any(c.name == 'English events' for c in server.forum_manager.service.categories(actor, language='es'))
            assert server.db.get_user('Staff').locale == 'es'
    finally:
        await server.stop()
