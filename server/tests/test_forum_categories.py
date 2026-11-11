"""Subforum permissions, data preservation and shared navigation."""

import asyncio
import json
import sqlite3
from unittest.mock import patch

import pytest
from websockets.asyncio.client import connect

from ..auth.auth import AuthManager
from ..core.server import Server, VERSION
from ..forum import navigation as nav
from ..forum.models import ForumError, PRIVATE_CATEGORY_ID, MAX_CATEGORIES
from ..forum.polls import PollConfig
from ..forum.repository import ForumRepository
from ..forum.service import ForumService
from ..persistence.database import Database
from ..persistence import database as database_module


@pytest.fixture
def forum(tmp_path):
    db = Database(tmp_path / 'categories.db')
    db.connect()
    users = {}
    for name in ('Developer', 'Administrator', 'Alice', 'Bob'):
        users[name] = db.create_user(name, 'hash').uuid
        db.approve_user(name)
    db.update_user_trust_level('Developer', 3)
    db.update_user_trust_level('Administrator', 2)
    db.update_user_trust_level('Alice', 1)
    db.update_user_trust_level('Bob', 1)
    service = ForumService(ForumRepository(db))
    yield service, db, users
    db.close()


@pytest.mark.parametrize('staff', ['Developer', 'Administrator'])
def test_staff_can_create_edit_and_delete_empty_subforum_across_restart(forum, staff):
    service, db, users = forum
    admin = service.category_admin
    category_id = admin.create(users[staff], 'Novedades', 'Noticias de la comunidad')
    assert category_id not in ('general', 'help', 'ideas')
    category = admin.get(users[staff], category_id)
    assert category.name == 'Novedades' and category.description == 'Noticias de la comunidad'
    admin.edit(users[staff], category_id, 'Eventos', '', category.revision)
    db.close()
    db.connect()
    category = admin.get(users[staff], category_id)
    assert category.name == 'Eventos' and category.description == '' and category.revision == 1
    admin.delete(users[staff], category_id, category.revision)
    db.close()
    db.connect()
    assert not service.repository.has_category(category_id)


def test_ordinary_and_revoked_accounts_cannot_manage_subforums(forum):
    service, db, users = forum
    admin = service.category_admin
    for action in (
        lambda: admin.get(users['Alice'], 'general'),
        lambda: admin.create(users['Alice'], 'Forged'),
        lambda: admin.edit(users['Alice'], 'general', 'Forged', '', 0),
        lambda: admin.delete(users['Alice'], 'general', 0),
    ):
        with pytest.raises(ForumError, match='forum-error-category-admin'):
            action()
    db.update_user_trust_level('Administrator', 1)
    with pytest.raises(ForumError, match='forum-error-category-admin'):
        admin.edit(users['Administrator'], 'general', 'Revoked', '', 0)
    assert service.repository.category('general').name == ''


@pytest.mark.parametrize(('name', 'description', 'key'), [
    ('', '', 'category-name'), ('a' * 81, '', 'category-name'),
    ('Valid', 'x' * 501, 'category-description'),
    ('Disguised\u202e', '', 'text-controls'), ('Valid', 'Bad\x00', 'text-controls'),
    (None, '', 'category-name'), ('Valid', None, 'category-description'),
])
def test_category_validation_is_atomic(forum, name, description, key):
    service, _, users = forum
    before = service.categories(users['Alice'])
    with pytest.raises(ForumError, match=key):
        service.category_admin.create(users['Administrator'], name, description)
    assert service.categories(users['Alice']) == before


def test_duplicate_names_and_stale_edits_do_not_overwrite_saved_changes(forum):
    service, _, users = forum
    admin = service.category_admin
    category_id = admin.create(users['Administrator'], 'Café')
    with pytest.raises(ForumError, match='category-duplicate'):
        admin.create(users['Developer'], '  CAFE\u0301  ')
    admin.edit(users['Administrator'], category_id, 'Noticias', '', 0)
    with pytest.raises(ForumError, match='category-conflict'):
        admin.edit(users['Developer'], category_id, 'Stale name', '', 0)
    with pytest.raises(ForumError, match='category-conflict'):
        admin.delete(users['Developer'], category_id, 0)
    assert admin.get(users['Administrator'], category_id).name == 'Noticias'


def test_deletion_preserves_messages_votes_bookmarks_and_privacy(forum):
    service, db, users = forum
    owner = users['Alice']
    category_id = service.category_admin.create(users['Administrator'], 'Temporal')
    topic, post = service.create_topic(owner, category_id, 'Retained topic', 'Retained message',
                                       poll=PollConfig('Retained poll', ('One', 'Two')))
    option = service.polls.get(owner, post)['options'][0]['id']
    service.polls.vote(owner, post, (option,))
    service.bookmark(owner, topic, True)
    service.post(owner, post, mark_read=True)
    private, private_post = service.conversations.create(owner, 'Private', 'Private message', (users['Bob'],))
    before = {
        name: [tuple(row) for row in db._conn.execute(f'SELECT * FROM {name}')]
        for name in ('forum_posts', 'forum_poll_votes', 'forum_bookmarks', 'forum_read_positions', 'forum_private_members')
    }
    with pytest.raises(ForumError, match='category-destination'):
        service.category_admin.delete(users['Administrator'], category_id, 0)
    service.category_admin.delete(users['Administrator'], category_id, 0, destination='ideas')
    assert service.topic(owner, topic).category_id == 'ideas'
    assert service.post(owner, post).body == 'Retained message'
    assert service.polls.get(owner, post)['voters'] == 1
    assert service.topic(owner, topic).bookmarked
    for name, rows in before.items():
        assert [tuple(row) for row in db._conn.execute(f'SELECT * FROM {name}')] == rows
    assert service.topic(owner, private).category_id == PRIVATE_CATEGORY_ID
    with pytest.raises(ForumError, match='forum-error-missing'):
        service.post(users['Administrator'], private_post)


def test_all_public_subforums_can_be_deleted_without_breaking_private_conversations(forum):
    service, db, users = forum
    for category in service.categories(users['Administrator']):
        service.category_admin.delete(users['Administrator'], category.id, category.revision)
    assert service.categories(users['Alice']) == []
    service.conversations.create(users['Alice'], 'Still private', 'Private message', (users['Bob'],))
    db.close()
    db.connect()
    assert service.categories(users['Alice']) == []
    assert not any(category.id == PRIVATE_CATEGORY_ID for category in service.categories(users['Administrator']))
    for operation in (
        lambda: service.category_admin.get(users['Administrator'], PRIVATE_CATEGORY_ID),
        lambda: service.category_admin.delete(users['Administrator'], PRIVATE_CATEGORY_ID, 0),
        lambda: service.create_topic(users['Alice'], PRIVATE_CATEGORY_ID, 'Forged public topic', 'Message'),
    ):
        with pytest.raises(ForumError, match='forum-error-missing'):
            operation()


def test_category_limit_and_invalid_move_destinations(forum):
    service, _, users = forum
    admin = service.category_admin
    with patch('server.forum.categories.MAX_CATEGORIES', 3):
        with pytest.raises(ForumError, match='category-limit'):
            admin.create(users['Administrator'], 'Too many')
    assert MAX_CATEGORIES >= 3
    for destination in ('general', PRIVATE_CATEGORY_ID, 'missing'):
        with pytest.raises(ForumError):
            admin.delete(users['Administrator'], 'general', 0, destination=destination)
    assert service.repository.has_category('general')


def test_deletion_rechecks_topics_created_after_opening_confirmation(forum):
    service, _, users = forum
    category_id = service.category_admin.create(users['Administrator'], 'Previously empty')
    topic, post = service.create_topic(users['Alice'], category_id, 'New topic', 'New message')
    with pytest.raises(ForumError, match='category-destination'):
        service.category_admin.delete(users['Administrator'], category_id, 0)
    assert service.repository.has_category(category_id)
    assert service.post(users['Alice'], post).topic_id == topic


def legacy_six(path):
    db = Database(path)
    db._conn = db._open_connection(str(path), timeout=30)
    db._conn.execute('PRAGMA foreign_keys = ON')
    with db._transaction(immediate=True) as cursor:
        db._create_tables_in_transaction(cursor, forum_version=6)
        cursor.execute(f'PRAGMA application_id = {Database.APPLICATION_ID}')
        cursor.execute('PRAGMA user_version = 6')
    owner = db.create_user('Legacy Owner', 'retained-hash')
    recipient = db.create_user('Legacy Recipient', 'hash')
    db.approve_user(owner.username)
    db.approve_user(recipient.username)
    service = ForumService(ForumRepository(db))
    with patch('server.forum.conversations.PRIVATE_CATEGORY_ID', 'general'):
        topic, post = service.conversations.create(owner.uuid, 'Private retained', 'Retained body', (recipient.uuid,))
    db.adjust_wallet_balance(owner.uuid, 123)
    db.close()
    return owner.uuid, topic, post


def test_v6_migration_preserves_existing_data_and_separates_private_storage(tmp_path):
    path = tmp_path / 'legacy.db'
    owner, topic, post = legacy_six(path)
    db = Database(path)
    backups = tmp_path / 'backups'
    db.connect(migration_backup_dir=backups)
    try:
        service = ForumService(ForumRepository(db))
        assert db.get_wallet(owner).balance == 373
        assert service.post(owner, post).body == 'Retained body'
        assert service.topic(owner, topic).category_id == PRIVATE_CATEGORY_ID
        assert [category.id for category in service.categories(owner)] == ['general', 'help', 'ideas']
        assert db._conn.execute('PRAGMA user_version').fetchone()[0] == 7
        with sqlite3.connect(next(backups.glob('*.sqlite3'))) as snapshot:
            assert snapshot.execute('PRAGMA user_version').fetchone()[0] == 6
            assert snapshot.execute('SELECT category_id FROM forum_topics').fetchone()[0] == 'general'
    finally:
        db.close()


def test_v7_migration_rolls_back_metadata_and_private_move_and_reuses_backup(tmp_path, monkeypatch):
    path = tmp_path / 'legacy.db'
    legacy_six(path)
    original = database_module.create_forum_schema

    def fail_after_schema(cursor, **kwargs):
        original(cursor, **kwargs)
        raise sqlite3.OperationalError('injected category migration fault')

    monkeypatch.setattr(database_module, 'create_forum_schema', fail_after_schema)
    db = Database(path)
    backups = tmp_path / 'backups'
    with pytest.raises(sqlite3.OperationalError, match='injected category migration fault'):
        db.connect(migration_backup_dir=backups)
    with sqlite3.connect(path) as snapshot:
        assert snapshot.execute('PRAGMA user_version').fetchone()[0] == 6
        assert snapshot.execute('SELECT category_id FROM forum_topics').fetchone()[0] == 'general'
        assert [row[1] for row in snapshot.execute('PRAGMA table_info(forum_categories)')] == ['id', 'position']
    monkeypatch.setattr(database_module, 'create_forum_schema', original)
    db.connect(migration_backup_dir=backups)
    db.close()
    assert len(list(backups.glob('*.sqlite3'))) == 1


def test_migration_does_not_recreate_deleted_default_subforums(tmp_path):
    path = tmp_path / 'legacy.db'
    legacy_six(path)
    with sqlite3.connect(path) as snapshot:
        snapshot.execute("DELETE FROM forum_categories WHERE id = 'ideas'")
    db = Database(path)
    db.connect()
    try:
        assert not ForumRepository(db).has_category('ideas')
        assert db._conn.execute('PRAGMA foreign_key_check').fetchall() == []
    finally:
        db.close()


def test_current_schema_rejects_missing_internal_category_without_repair(tmp_path):
    path = tmp_path / 'drift.db'
    db = Database(path)
    db.connect()
    db._conn.execute('DELETE FROM forum_categories WHERE id = ?', (PRIVATE_CATEGORY_ID,))
    db.close()
    with pytest.raises(sqlite3.DatabaseError, match='internal private forum category'):
        db.connect()
    with sqlite3.connect(path) as snapshot:
        assert not snapshot.execute('SELECT 1 FROM forum_categories WHERE id = ?', (PRIVATE_CATEGORY_ID,)).fetchone()


@pytest.mark.asyncio
@pytest.mark.parametrize('client_type', ['web', 'python'])
async def test_category_management_over_real_socket_and_live_reader_refresh(tmp_path, client_type):
    server = Server(host='127.0.0.1', port=0, db_path=str(tmp_path / 'socket.db'))
    await server.start()
    try:
        auth = AuthManager(server.db)
        for name in ('Staff', 'Reader'):
            assert auth.register(name, 'TestPassword123', locale='es', email=f'{name}@example.test') == 'ok'
            server.db.approve_user(name)
        server.db.update_user_trust_level('Reader', 1)
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

        async with connect(f'ws://127.0.0.1:{port}') as staff, connect(f'ws://127.0.0.1:{port}') as reader:
            for ws, name in ((staff, 'Staff'), (reader, 'Reader')):
                await ws.send(json.dumps({'type': 'authorize', 'client': client_type, 'version': VERSION,
                                          'username': name, 'password': 'TestPassword123'}))
                await receive(ws, lambda p: p.get('menu_id') == 'main_menu')
                home = await choose(ws, 'main_menu', 'forum', nav.HOME)
                assert ('manage_categories' in [item['id'] for item in home['items']]) is (name == 'Staff')
            await choose(staff, nav.HOME, 'manage_categories', nav.CATEGORIES)
            await choose(staff, nav.CATEGORIES, 'create_category', nav.CATEGORY_EDITOR)
            await staff.send(json.dumps({'type': 'menu', 'menu_id': nav.CATEGORY_EDITOR, 'selection_id': 'edit_category_name'}))
            prompt = await receive(staff, lambda p: p.get('type') == 'request_input' and p.get('input_id') == nav.CATEGORY_NAME_INPUT)
            assert not prompt['multiline']
            await staff.send(json.dumps({'type': 'editbox', 'input_id': nav.CATEGORY_NAME_INPUT, 'text': 'Noticias nuevas'}))
            await receive(staff, lambda p: p.get('menu_id') == nav.CATEGORY_EDITOR)
            saved = await choose(staff, nav.CATEGORY_EDITOR, 'save_category', nav.CATEGORIES)
            row = next(item for item in saved['items'] if 'Noticias nuevas' in item['text'])
            category_id = row['id'].removeprefix('edit_category:')
            updated = await receive(reader, lambda p: p.get('menu_id') == nav.HOME and any('Noticias nuevas' in i['text'] for i in p['items']))
            assert 'manage_categories' not in [item['id'] for item in updated['items']]
            await choose(staff, nav.CATEGORIES, row['id'], nav.CATEGORY_EDITOR)
            await staff.send(json.dumps({'type': 'menu', 'menu_id': nav.CATEGORY_EDITOR, 'selection_id': 'edit_category_description'}))
            description_prompt = await receive(staff, lambda p: p.get('input_id') == nav.CATEGORY_DESCRIPTION_INPUT)
            assert description_prompt['multiline']
            description = 'Anuncios para toda la comunidad.'
            await staff.send(json.dumps({'type': 'editbox', 'input_id': nav.CATEGORY_DESCRIPTION_INPUT, 'text': description}))
            await receive(staff, lambda p: p.get('menu_id') == nav.CATEGORY_EDITOR)
            await choose(staff, nav.CATEGORY_EDITOR, 'save_category', nav.CATEGORIES)
            await choose(staff, nav.CATEGORIES, row['id'], nav.CATEGORY_EDITOR)
            prompt = await choose(staff, nav.CATEGORY_EDITOR, 'delete_category', nav.CATEGORY_DELETE)
            assert [item['id'] for item in prompt['items']] == ['confirmation_prompt', 'yes', 'no']
            await choose(staff, nav.CATEGORY_DELETE, 'no', nav.CATEGORY_EDITOR)
            assert server.forum_manager.service.repository.has_category(category_id)
            # A topic created after cancellation changes deletion into a move.
            service = server.forum_manager.service
            owner = server.db.get_user('Reader').uuid
            topic, post = service.create_topic(owner, category_id, 'Tema conservado', 'Mensaje conservado')
            topics = await choose(reader, nav.HOME, f'category:{category_id}', nav.TOPICS)
            assert topics['items'][0]['id'] == f'topic:{topic}'
            assert not any(description in item['text'] for item in topics['items'])
            await receive(reader, lambda p: p.get('type') == 'speak' and description in p.get('text', ''))
            await choose(staff, nav.CATEGORY_EDITOR, 'delete_category', nav.CATEGORY_DESTINATION)
            prompt = await choose(staff, nav.CATEGORY_DESTINATION, 'move_category:ideas', nav.CATEGORY_DELETE)
            assert 'Ideas y sugerencias' in prompt['items'][0]['text']
            await choose(staff, nav.CATEGORY_DELETE, 'yes', nav.CATEGORIES)
            assert not server.forum_manager.service.repository.has_category(category_id)
            assert service.topic(owner, topic).category_id == 'ideas'
            assert service.post(owner, post).body == 'Mensaje conservado'
            refreshed = await receive(reader, lambda p: p.get('menu_id') == nav.HOME)
            assert f'category:{category_id}' not in [item['id'] for item in refreshed['items']]
            await choose(reader, nav.HOME, 'back', 'main_menu')
    finally:
        await server.stop()
