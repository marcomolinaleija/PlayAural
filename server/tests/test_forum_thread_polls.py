"""Compact poll fields and one independent, permission-checked thread ballot."""

import asyncio
import json
import sqlite3
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from websockets.asyncio.client import connect

from ..auth.auth import AuthManager
from ..core.server import Server, VERSION
from ..forum import navigation as nav
from ..forum.models import Draft, ForumError
from ..forum.polls import PollConfig
from ..forum.repository import ForumRepository
from ..forum.service import ForumService
from ..persistence import database as database_module
from ..persistence.database import Database
from ..users.network_user import NetworkUser


@pytest.fixture
def forum(tmp_path):
    server = Server(db_path=str(tmp_path / 'thread-polls.db'))
    server.db.connect()
    users = {}
    for name, level in (('Alice', 1), ('Bob', 1), ('Staff', 3)):
        account = server.db.create_user(name, 'hash', locale='es', trust_level=level, approved=True)
        user = NetworkUser(name, 'es', SimpleNamespace(username=name, authenticated=True, retired=False),
                           uuid=account.uuid, approved=True, trust_level=level)
        server._users[name] = users[name] = user
        server._show_main_menu(user)
        user.get_queued_messages()
    now = [1_800_000_000]
    service = server.forum_manager.service
    service.clock = lambda: now[0]
    yield server, service, users, now
    server.db.close()


def menu(user, menu_id):
    return [p for p in user.get_queued_messages() if p.get('menu_id') == menu_id][-1]


def test_editor_has_one_editable_field_per_value_and_complete_multiline_options(forum):
    server, _, users, _ = forum
    user = users['Alice']
    options = ('A' * 160, 'B' * 160)
    draft = Draft('topic', category_id='general', title='Kept title', body='Kept body',
                  poll=asdict(PollConfig('A question', options)))
    server._nav_push(user, server.forum_manager.composer.show, draft)
    packet = menu(user, nav.COMPOSER)
    assert sum(row['id'] == 'poll' for row in packet['items']) == 1
    assert not any(row['id'].startswith('poll_preview') for row in packet['items'])
    server.forum_manager.handle_menu(user, 'poll', server._user_states[user.username])
    packet = menu(user, nav.POLL_EDITOR)
    assert [row['id'] for row in packet['items'][:2]] == ['question', 'options']
    assert packet['items'][0]['text'] == 'Pregunta: A question'
    assert packet['items'][1]['text'].startswith('Opciones: ') and len(packet['items'][1]['text']) < 180
    assert not any(row.get('read_only') for row in packet['items'])
    server.forum_manager.handle_menu(user, 'options', server._user_states[user.username])
    prompt = next(p for p in user.get_queued_messages() if p.get('type') == 'request_input')
    assert prompt['multiline'] and prompt['default_value'] == '\n'.join(options)
    state = server._user_states[user.username]
    server.forum_manager.handle_input(user, {'input_id':nav.POLL_OPTIONS_INPUT, 'cancelled':True}, state)
    server._nav_back(user)
    assert server._user_states[user.username]['forum_draft']['body'] == 'Kept body'


def test_one_thread_poll_is_pinned_on_every_page_without_creating_posts(forum):
    server, service, users, now = forum
    alice, bob = users['Alice'], users['Bob']
    topic, post = service.create_topic(alice.uuid, 'general', 'Topic', 'Opening',
                                      poll=PollConfig('Message question', ('A', 'B'), results='always'))
    for i in range(9):
        now[0] += 61
        service.reply(alice.uuid, topic, f'Comment {i}')
    before = service.topic(bob.uuid, topic).post_count
    service.thread_polls.create(alice.uuid, topic, PollConfig('General question', ('Yes', 'No')))
    assert service.topic(bob.uuid, topic).post_count == before
    for page in (1, 2):
        server.forum_manager.views.thread(bob, topic, page)
        rows = menu(bob, nav.THREAD)['items']
        assert rows[0]['id'] == 'thread_poll' and rows[1]['id'].startswith('post:')
        assert 'General question' in rows[0]['text']
    with pytest.raises(ForumError, match='forum-error-thread-poll-exists'):
        service.thread_polls.create(alice.uuid, topic, PollConfig('Second', ('One', 'Two')))
    poll = service.thread_polls.get(bob.uuid, topic)
    service.thread_polls.vote(bob.uuid, topic, (poll['options'][0]['id'],))
    assert service.thread_polls.get(bob.uuid, topic)['voters'] == 1
    assert service.polls.get(bob.uuid, post)['voters'] == 0


def test_no_thread_poll_has_no_placeholder_and_creation_requires_thread_management(forum):
    server, service, users, _ = forum
    topic, _ = service.create_topic(users['Alice'].uuid, 'general', 'Topic', 'Body')
    for name, allowed in (('Alice', True), ('Bob', False), ('Staff', True)):
        user = users[name]
        server.forum_manager.views.thread(user, topic)
        ids = [row['id'] for row in menu(user, nav.THREAD)['items']]
        assert ids[0].startswith('post:') and 'thread_poll' not in ids
        assert ('create_thread_poll' in ids) is allowed
    with pytest.raises(ForumError, match='forum-error-edit-permission'):
        service.thread_polls.create(users['Bob'].uuid, topic, PollConfig('Denied', ('A', 'B')))
    service.moderate(users['Staff'].uuid, topic, 'closed', True)
    assert not service.thread_polls.can_create(users['Alice'].uuid, topic)


def test_private_poll_membership_and_bilateral_blocks_are_rechecked(forum):
    server, service, users, _ = forum
    alice, bob, staff = (users[name].uuid for name in ('Alice', 'Bob', 'Staff'))
    topic, _ = service.conversations.create(alice, 'Private', 'Opening', (bob,))
    service.thread_polls.create(alice, topic, PollConfig('Secret question', ('One', 'Two')))
    for outsider in (bob, staff):
        with pytest.raises(ForumError, match='forum-error-missing'):
            service.thread_polls.get(outsider, topic)
        with pytest.raises(ForumError, match='forum-error-missing'):
            service.thread_polls.create(outsider, topic, PollConfig('Forged', ('A', 'B')))
    service.conversations.respond(bob, service.conversations.invitations(bob)[0]['id'], accept=True)
    poll = service.thread_polls.get(bob, topic)
    server.db.block_user(bob, alice)
    with pytest.raises(ForumError, match='forum-error-missing'):
        service.thread_polls.vote(bob, topic, (poll['options'][0]['id'],))
    server.forum_manager.views.thread(users['Bob'], topic)
    assert 'thread_poll' not in [r['id'] for r in menu(users['Bob'], nav.THREAD)['items']]
    server.db.unblock_user(bob, alice)
    service.conversations.remove(alice, topic, bob)
    with pytest.raises(ForumError, match='forum-error-missing'):
        service.thread_polls.get(bob, topic)


def test_revision_freeze_withdrawal_deadline_and_closed_topic(forum):
    _, service, users, now = forum
    alice, bob = users['Alice'].uuid, users['Bob'].uuid
    topic, _ = service.create_topic(alice, 'general', 'Topic', 'Opening')
    service.thread_polls.create(alice, topic, PollConfig('Question', ('A', 'B')))
    service.thread_polls.edit(alice, topic, PollConfig('Changed', ('C', 'D')), revision=0)
    with pytest.raises(ForumError, match='forum-error-conflict'):
        service.thread_polls.edit(alice, topic, PollConfig('Stale', ('A', 'B')), revision=0)
    poll = service.thread_polls.get(bob, topic)
    service.thread_polls.vote(bob, topic, (poll['options'][0]['id'],))
    service.thread_polls.vote(bob, topic, ())
    with pytest.raises(ForumError, match='forum-error-poll-started'):
        service.thread_polls.edit(alice, topic, PollConfig('Frozen', ('A', 'B')), revision=1)
    service.moderate(users['Staff'].uuid, topic, 'closed', True)
    with pytest.raises(ForumError, match='forum-error-poll-closed'):
        service.thread_polls.vote(bob, topic, (poll['options'][0]['id'],))
    service.moderate(users['Staff'].uuid, topic, 'closed', False)
    service.thread_polls.close(alice, topic)
    assert service.thread_polls.get(bob, topic)['closed']
    with pytest.raises(ForumError, match='forum-error-poll-closed'):
        service.thread_polls.vote(bob, topic, (poll['options'][0]['id'],))
    now[0] += 61
    other, _ = service.create_topic(alice, 'general', 'Deadline', 'Another body')
    service.thread_polls.create(alice, other, PollConfig('Deadline', ('A', 'B'), closes_at=now[0] + 10))
    now[0] += 10
    assert service.thread_polls.get(bob, other)['closed']


def test_thread_editor_save_discard_and_existing_boolean_fields(forum):
    server, service, users, _ = forum
    alice = users['Alice']
    topic, _ = service.create_topic(alice.uuid, 'general', 'Topic', 'Body')
    manager = server.forum_manager
    server._nav_push(alice, manager.views.thread, topic)
    manager.handle_menu(alice, 'create_thread_poll', server._user_states[alice.username])
    manager.handle_menu(alice, 'question', server._user_states[alice.username])
    manager.handle_input(alice, {'input_id':nav.POLL_QUESTION_INPUT, 'text':'General question'}, server._user_states[alice.username])
    manager.handle_menu(alice, 'options', server._user_states[alice.username])
    manager.handle_input(alice, {'input_id':nav.POLL_OPTIONS_INPUT, 'text':'One\nTwo'}, server._user_states[alice.username])
    manager.handle_menu(alice, 'back', server._user_states[alice.username])
    assert server._user_states[alice.username]['menu'] == nav.DISCARD
    manager.handle_menu(alice, 'no', server._user_states[alice.username])
    manager.handle_menu(alice, 'save_thread_poll', server._user_states[alice.username])
    assert server._user_states[alice.username]['menu'] == nav.THREAD
    assert service.thread_polls.get(alice.uuid, topic)['question'] == 'General question'
    manager.handle_menu(alice, 'thread_poll', server._user_states[alice.username])
    manager.handle_menu(alice, 'edit', server._user_states[alice.username])
    manager.handle_menu(alice, 'save_thread_poll', server._user_states[alice.username])
    assert server._user_states[alice.username]['menu'] == nav.POLL
    manager.handle_menu(alice, 'edit', server._user_states[alice.username])
    manager.handle_menu(alice, 'back', server._user_states[alice.username])
    assert server._user_states[alice.username]['menu'] == nav.POLL  # Unchanged edit needs no confirmation.


def test_v11_migration_keeps_message_poll_votes_notifications_and_reading_state(tmp_path):
    path = tmp_path / 'v11.db'
    db = Database(path)
    db._conn = db._open_connection(str(path), timeout=30)
    db._conn.execute('PRAGMA foreign_keys = ON')
    with db._transaction(immediate=True) as cursor:
        db._create_tables_in_transaction(cursor, forum_version=11)
        cursor.execute(f'PRAGMA application_id = {Database.APPLICATION_ID}')
        cursor.execute('PRAGMA user_version = 11')
    alice = db.create_user('Alice', 'hash', approved=True).uuid
    bob = db.create_user('Bob', 'hash', approved=True).uuid
    service = ForumService(ForumRepository(db))
    topic, post = service.create_topic(alice, 'general', 'Retained', 'Hello @Bob', poll=PollConfig('Old poll', ('A', 'B')))
    option = service.polls.get(bob, post)['options'][0]['id']
    service.polls.vote(bob, post, (option,))
    service.bookmark(bob, topic, True)
    tables = [r[0] for r in db._conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
    before = {name: [tuple(row) for row in db._conn.execute(f'SELECT * FROM {name} ORDER BY rowid')] for name in tables}
    db.close()
    db.connect(migration_backup_dir=tmp_path / 'backups')
    try:
        assert db._conn.execute('PRAGMA user_version').fetchone()[0] == 12
        for name, rows in before.items():
            assert [tuple(row) for row in db._conn.execute(f'SELECT * FROM {name} ORDER BY rowid')] == rows
        assert not db._conn.execute('PRAGMA foreign_key_check').fetchall()
        assert service.polls.get(bob, post)['selected'] == (option,)
        assert service.notifications.pending(bob)
        service.thread_polls.create(alice, topic, PollConfig('New general poll', ('One', 'Two')))
        with db._open_connection(str(next((tmp_path / 'backups').glob('*.sqlite3'))), timeout=30) as backup:
            assert backup.execute('PRAGMA user_version').fetchone()[0] == 11
            assert backup.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    finally:
        db.close()


def test_account_and_topic_deletion_keep_ballot_history_rules_and_cascade_owned_data(forum):
    server, service, users, _ = forum
    alice, bob, staff = (users[name].uuid for name in ('Alice', 'Bob', 'Staff'))
    topic, _ = service.create_topic(alice, 'general', 'Topic', 'Opening')
    service.thread_polls.create(alice, topic, PollConfig('General', ('A', 'B'), results='always'))
    option = service.thread_polls.get(bob, topic)['options'][0]['id']
    service.thread_polls.vote(bob, topic, (option,))
    server.db.delete_user('Bob')
    assert service.thread_polls.get(alice, topic)['voters'] == 0
    with pytest.raises(ForumError, match='forum-error-poll-started'):
        service.thread_polls.edit(alice, topic, PollConfig('Frozen', ('A', 'B')), revision=0)
    server.db.delete_user('Alice')
    assert service.thread_polls.get(staff, topic)['author_uuid'] is None
    service.thread_polls.close(staff, topic)
    with server.db._transaction(immediate=True) as cursor:
        cursor.execute('DELETE FROM forum_topics WHERE id = ?', (topic,))
    for table in ('forum_thread_polls', 'forum_thread_poll_options', 'forum_thread_poll_votes'):
        assert not server.db._conn.execute(f'SELECT * FROM {table}').fetchall()


def test_failed_v12_migration_rolls_back_and_keeps_v11_backup(tmp_path, monkeypatch):
    path = tmp_path / 'legacy.db'
    db = Database(path)
    db._conn = db._open_connection(str(path), timeout=30)
    db._conn.execute('PRAGMA foreign_keys = ON')
    with db._transaction(immediate=True) as cursor:
        db._create_tables_in_transaction(cursor, forum_version=11)
        cursor.execute(f'PRAGMA application_id = {Database.APPLICATION_ID}')
        cursor.execute('PRAGMA user_version = 11')
    account = db.create_user('Retained', 'retained-hash', approved=True)
    service = ForumService(ForumRepository(db))
    _, post = service.create_topic(account.uuid, 'general', 'Retained topic', 'Retained body')
    db.close()
    original = database_module.create_forum_schema
    def fail(cursor, **kwargs):
        original(cursor, **kwargs)
        if kwargs.get('version', 12) >= 12:
            raise sqlite3.OperationalError('Injected thread poll migration fault')
    monkeypatch.setattr(database_module, 'create_forum_schema', fail)
    with pytest.raises(sqlite3.DatabaseError):
        Database(path).connect(migration_backup_dir=tmp_path / 'backups')
    with sqlite3.connect(path) as old:
        assert old.execute('PRAGMA user_version').fetchone()[0] == 11
        assert old.execute('SELECT body FROM forum_posts WHERE id = ?', (post,)).fetchone()[0] == 'Retained body'
        assert not old.execute("SELECT 1 FROM sqlite_master WHERE name = 'forum_thread_polls'").fetchall()
    assert len(list((tmp_path / 'backups').glob('*.sqlite3'))) == 1
    monkeypatch.setattr(database_module, 'create_forum_schema', original)
    db.connect(migration_backup_dir=tmp_path / 'backups')
    db.close()


@pytest.mark.parametrize('client_type', ['python', 'web'])
async def test_general_poll_editor_and_ballot_over_real_socket(tmp_path, client_type):
    server = Server(host='127.0.0.1', port=0, db_path=str(tmp_path / 'socket.db'))
    await server.start()
    try:
        auth = AuthManager(server.db)
        for name in ('Alice', 'Bob'):
            assert auth.register(name, 'ForumPassword123', locale='es', email=f'{name}@example.com') == 'ok'
            server.db.approve_user(name)
        service = server.forum_manager.service
        alice_id, bob_id = (server.db.get_user(name).uuid for name in ('Alice', 'Bob'))
        topic, post = service.create_topic(alice_id, 'general', 'Topic', 'Body', poll=PollConfig('Message poll', ('A', 'B'), results='always'))
        port = server._ws_server._server.sockets[0].getsockname()[1]
        async def receive(ws, predicate):
            async with asyncio.timeout(15):
                while True:
                    packet = json.loads(await ws.recv())
                    if predicate(packet):
                        return packet
        async def choose(ws, surface, action, result):
            await ws.send(json.dumps({'type':'menu', 'menu_id':surface, 'selection_id':action}))
            return await receive(ws, lambda p:p.get('menu_id') == result)
        async with connect(f'ws://127.0.0.1:{port}') as alice, connect(f'ws://127.0.0.1:{port}') as bob:
            for ws, name in ((alice, 'Alice'), (bob, 'Bob')):
                await ws.send(json.dumps({'type':'authorize', 'client':client_type, 'version':VERSION,
                                          'username':name, 'password':'ForumPassword123'}))
                await receive(ws, lambda p:p.get('menu_id') == 'main_menu')
                await choose(ws, 'main_menu', 'forum', nav.HOME)
                await choose(ws, nav.HOME, 'category:general', nav.TOPICS)
                await choose(ws, nav.TOPICS, f'topic:{topic}', nav.THREAD)
            editor = await choose(alice, nav.THREAD, 'create_thread_poll', nav.POLL_EDITOR)
            assert [row['id'] for row in editor['items'][:2]] == ['question', 'options']
            for action, input_id, text in (('question', nav.POLL_QUESTION_INPUT, 'General question'),
                                           ('options', nav.POLL_OPTIONS_INPUT, 'Yes\nNo')):
                await alice.send(json.dumps({'type':'menu', 'menu_id':nav.POLL_EDITOR, 'selection_id':action}))
                await receive(alice, lambda p:p.get('type') == 'request_input' and p.get('input_id') == input_id)
                await alice.send(json.dumps({'type':'editbox', 'input_id':input_id, 'text':text}))
                await receive(alice, lambda p:p.get('menu_id') == nav.POLL_EDITOR)
            thread = await choose(alice, nav.POLL_EDITOR, 'save_thread_poll', nav.THREAD)
            assert thread['items'][0]['id'] == 'thread_poll'
            thread = await choose(bob, nav.THREAD, 'refresh', nav.THREAD)
            assert thread['items'][0]['id'] == 'thread_poll'
            ballot = await choose(bob, nav.THREAD, 'thread_poll', nav.POLL)
            choice = next(row['id'] for row in ballot['items'] if row['id'].startswith('choice:'))
            await choose(bob, nav.POLL, choice, nav.POLL)
            await choose(bob, nav.POLL, 'submit', nav.POLL)
            assert service.thread_polls.get(bob_id, topic)['voters'] == 1
            assert service.polls.get(bob_id, post)['voters'] == 0
    finally:
        await server.stop()
