"""Forum notices remain actionable, bounded and subject to current access."""

import asyncio
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from websockets.asyncio.client import connect

from ..auth.auth import AuthManager
from ..core.server import Server, VERSION
from ..forum import navigation as nav
from ..forum.models import Draft, ForumError
from ..forum.notifications import MAX_NOTIFICATIONS, RETENTION_SECONDS, mention_names
from ..forum.polls import PollConfig
from ..forum.repository import ForumRepository
from ..forum.service import ForumService
from ..persistence import database as database_module
from ..persistence.database import Database
from ..users.network_user import NetworkUser


@pytest.fixture
def forum(tmp_path):
    server = Server(db_path=str(tmp_path / 'notices.db'))
    server.db.connect()
    users = {}
    for name, locale, level in (('Alice', 'es', 3), ('Bob', 'en', 1), ('Carol', 'es', 1), ('Ana López', 'es', 1)):
        account = server.db.create_user(name, 'hash', locale=locale, trust_level=level)
        server.db.approve_user(name)
        user = NetworkUser(name, locale, SimpleNamespace(username=name, authenticated=True, retired=False),
                           uuid=account.uuid, approved=True, trust_level=level)
        server._users[name] = users[name] = user
        server._show_main_menu(user)
        user.get_queued_messages()
    now = [1_800_000_000]
    server.forum_manager.service.clock = lambda: now[0]
    yield server, server.forum_manager.service, users, now
    server.db.close()


def private(forum):
    _, service, users, _ = forum
    alice, bob = users['Alice'].uuid, users['Bob'].uuid
    topic, _ = service.conversations.create(alice, 'Secret title', 'Opening', (bob,))
    invite = service.conversations.invitations(bob)[0]['id']
    service.conversations.respond(bob, invite, accept=True)
    return topic


def test_mentions_parse_unicode_spaces_boundaries_and_literal_escape():
    assert mention_names(r'@Bob, @{Ana López}; @BOB. mail@Bob.com \@Carol @@Carol') == ('Bob', 'Ana López')


def test_private_replies_notify_only_accepted_members_and_prioritize_mentions(forum):
    _, service, users, _ = forum
    alice, bob, carol = (users[n].uuid for n in ('Alice', 'Bob', 'Carol'))
    topic = private(forum)
    service.conversations.invite(alice, topic, carol)
    first = service.reply(alice, topic, 'A new private message')
    second = service.reply(alice, topic, '@Bob and @BOB, please read this')
    pending = service.notifications.pending(bob)
    assert [(n['post_id'], n['kind']) for n in pending] == [(second, 'mention'), (first, 'private')]
    assert not service.notifications.pending(alice)
    assert not service.notifications.pending(carol)
    assert not service.notifications.pending(users['Ana López'].uuid)


def test_public_mentions_cross_languages_and_do_not_subscribe_bookmarks(forum):
    _, service, users, _ = forum
    alice, bob, ana = (users[n].uuid for n in ('Alice', 'Bob', 'Ana López'))
    topic, post = service.create_topic(alice, 'vi:general', 'Vietnamese community', '@{ANA LÓPEZ} and @bob')
    assert service.notifications.pending(ana)[0]['post_id'] == post
    assert service.notifications.pending(bob)[0]['post_id'] == post
    assert service.languages.current(bob) == 'en'
    service.bookmark(bob, topic, True)
    service.reply(alice, topic, 'Ordinary public activity')
    assert len(service.notifications.pending(bob)) == 1


@pytest.mark.parametrize('body,error', [('@MissingUser', 'forum-error-mention-user'),
    (' '.join(f'@Person{i}' for i in range(11)), 'forum-error-mention-limit')])
def test_invalid_mentions_roll_back_post_poll_and_notifications(forum, body, error):
    server, service, users, _ = forum
    with pytest.raises(ForumError, match=error):
        service.create_topic(users['Alice'].uuid, 'general', 'Not committed', '@Bob ' + body,
                             poll=PollConfig('Question', ('One', 'Two')))
    for table in ('forum_topics', 'forum_posts', 'forum_polls', 'forum_notifications', 'forum_mentions'):
        assert server.db._conn.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0] == 0


def test_edit_notifies_new_targets_once_and_removes_obsolete_mentions(forum):
    _, service, users, _ = forum
    alice, bob, carol = (users[n].uuid for n in ('Alice', 'Bob', 'Carol'))
    _, post = service.create_topic(alice, 'general', 'Topic', 'Hello @Bob')
    service.edit(alice, post, 'Changed wording, @Bob', 0)
    assert len(service.notifications.pending(bob)) == 1
    service.edit(alice, post, 'Mention removed', 1)
    assert not service.notifications.pending(bob)
    service.edit(alice, post, 'Hello again @Bob and @Carol', 2)
    assert not service.notifications.pending(bob)
    assert len(service.notifications.pending(carol)) == 1
    service.post(carol, post, mark_read=True)
    service.edit(alice, post, '@Carol stays mentioned', 3)
    assert not service.notifications.pending(carol)


def test_edits_cannot_bypass_lifetime_mention_limit(forum):
    server, service, users, _ = forum
    for i in range(11):
        account = server.db.create_user(f'Person{i}', 'hash')
        server.db.approve_user(account.username)
    _, post = service.create_topic(users['Alice'].uuid, 'general', 'Topic', ' '.join(f'@Person{i}' for i in range(10)))
    service.edit(users['Alice'].uuid, post, 'Removed mentions', 0)
    with pytest.raises(ForumError, match='forum-error-mention-limit'):
        service.edit(users['Alice'].uuid, post, 'New @Person10', 1)
    assert service.post(users['Alice'].uuid, post).body == 'Removed mentions'


def test_pagination_settings_and_cross_language_destination_use_shared_menus(forum):
    server, service, users, now = forum
    alice, bob = users['Alice'], users['Bob']
    topic, _ = service.create_topic(alice.uuid, 'general', 'Spanish topic', 'Opening')
    for i in range(18):
        now[0] += 61
        service.reply(alice.uuid, topic, f'Message {i} @Bob')
    manager = server.forum_manager
    server._nav_push(bob, manager.home)
    manager.handle_menu(bob, 'notifications', server._user_states[bob.username])
    rows = [p for p in bob.get_queued_messages() if p.get('menu_id') == nav.NOTIFICATIONS][-1]['items']
    assert len([row for row in rows if row['id'].startswith('notice:')]) == 15
    assert not rows[-1]['id'].startswith('notice:')
    manager.handle_menu(bob, 'page_next', server._user_states[bob.username])
    assert server._user_states[bob.username]['forum_page'] == 2
    rows = [p for p in bob.get_queued_messages() if p.get('menu_id') == nav.NOTIFICATIONS][-1]['items']
    target = next(row['id'] for row in rows if row['id'].startswith('notice:'))
    manager.handle_menu(bob, target, server._user_states[bob.username])
    assert server._user_states[bob.username]['menu'] == nav.BODY_READER
    assert service.languages.current(bob.uuid) == 'en'
    manager.reader.close(bob, server._user_states[bob.username])
    server._nav_back(bob)
    server._nav_back(bob)
    manager.handle_menu(bob, 'notification_settings', server._user_states[bob.username])
    assert server._user_states[bob.username]['menu'] == nav.NOTIFICATION_SETTINGS
    manager.handle_menu(bob, 'mention_alerts', server._user_states[bob.username])
    assert not service.notifications.settings(bob.uuid)['mention_alerts']


def test_moderator_edit_does_not_impersonate_author_with_new_mentions(forum):
    _, service, users, _ = forum
    _, post = service.create_topic(users['Bob'].uuid, 'general', 'Topic', 'Original')
    service.edit(users['Alice'].uuid, post, 'Moderated @Carol', 0)
    assert not service.notifications.pending(users['Carol'].uuid)


@pytest.mark.parametrize('direction', ['recipient', 'author'])
def test_blocks_suppress_new_notices_and_discard_pending_notices_permanently(forum, direction):
    server, service, users, _ = forum
    alice, bob = users['Alice'].uuid, users['Bob'].uuid
    _, post = service.create_topic(alice, 'general', 'Topic', 'Hello @Bob')
    assert service.notifications.pending(bob)
    blocker, blocked = (bob, alice) if direction == 'recipient' else (alice, bob)
    assert server.db.block_user(blocker, blocked) == 'blocked'
    assert not service.notifications.pending(bob)
    server.db.unblock_user(blocker, blocked)
    assert not service.notifications.pending(bob)
    service.edit(alice, post, 'Repeated @Bob', 0)
    assert not service.notifications.pending(bob)
    server.db.block_user(blocker, blocked)
    service.create_topic(alice, 'help', 'Another topic', 'New @Bob')
    assert not service.notifications.pending(bob)


def test_private_mentions_never_admit_outsiders_and_removal_revokes_pending_notices(forum):
    _, service, users, _ = forum
    alice, bob, carol = (users[n].uuid for n in ('Alice', 'Bob', 'Carol'))
    topic = private(forum)
    service.reply(alice, topic, 'Hello @Bob and @Carol')
    assert not service.notifications.pending(carol)
    service.notifications.set_muted(bob, topic, True)
    service.conversations.remove(alice, topic, bob)
    assert not service.notifications.pending(bob)
    assert not service.notifications.muted(bob, topic)
    service.conversations.invite(alice, topic, bob)
    service.conversations.respond(bob, service.conversations.invitations(bob)[0]['id'], accept=True)
    assert not service.notifications.pending(bob)


def test_hidden_or_deleted_messages_and_deleted_accounts_cannot_leak_notifications(forum):
    server, service, users, _ = forum
    alice, bob = users['Alice'].uuid, users['Bob'].uuid
    topic, post = service.create_topic(alice, 'general', 'Hidden title', 'Hello @Bob')
    service.moderate(alice, topic, 'hidden', True, post)
    assert not service.notifications.pending(bob)
    service.moderate(alice, topic, 'hidden', False, post)
    assert service.notifications.pending(bob)
    with server.db._transaction(immediate=True) as cursor:
        cursor.execute('DELETE FROM forum_posts WHERE id = ?', (post,))
    assert not service.notifications.pending(bob)
    assert not server.db._conn.execute('SELECT * FROM forum_mentions').fetchall()


def test_pending_notices_survive_restart_and_spoken_delivery_does_not_read_messages(forum):
    server, service, users, _ = forum
    alice, bob = users['Alice'], users['Bob']
    topic = private(forum)
    post = service.reply(alice.uuid, topic, 'New private reply')
    before = service.topic(bob.uuid, topic).unread_count
    server.db.close()
    server.db.connect()
    server.forum_manager.notifications.deliver(bob)
    assert any(p.get('key') == 'forum-notification-summary' for p in bob.get_queued_messages())
    assert service.topic(bob.uuid, topic).unread_count == before
    assert service.notifications.pending(bob.uuid)[0]['announced'] == 1
    server.forum_manager.notifications.deliver(bob)
    assert not bob.get_queued_messages()
    service.post(bob.uuid, post, mark_read=True)
    assert not service.notifications.pending(bob.uuid)


def test_live_private_activity_coalesces_but_mention_has_one_distinct_alert(forum):
    server, service, users, _ = forum
    alice, bob = users['Alice'], users['Bob']
    topic = private(forum)
    for body in ('First reply', 'Second reply'):
        post = service.reply(alice.uuid, topic, body)
        server.forum_manager.notifications.deliver_post(post)
    assert [p.get('key') for p in bob.get_queued_messages()] == ['forum-notification-private']
    grouped = server.forum_manager.notifications.grouped(bob)
    assert len(grouped) == 1 and grouped[0]['count'] == 2
    post = service.reply(alice.uuid, topic, 'Attention @Bob')
    server.forum_manager.notifications.deliver_post(post)
    assert [p.get('key') for p in bob.get_queued_messages()] == ['forum-notification-mention']
    server.forum_manager.notifications.deliver_post(post)
    assert not bob.get_queued_messages()


def test_reading_thread_and_muting_suppress_speech_but_keep_inbox_and_unread(forum):
    server, service, users, _ = forum
    alice, bob = users['Alice'], users['Bob']
    topic = private(forum)
    server.forum_manager.views.thread(bob, topic)
    bob.get_queued_messages()
    post = service.reply(alice.uuid, topic, 'While reading @Bob')
    server.forum_manager.notifications.deliver_post(post)
    assert not bob.get_queued_messages()
    assert service.notifications.pending(bob.uuid)
    server._show_main_menu(bob)
    bob.get_queued_messages()
    service.notifications.set_muted(bob.uuid, topic, True)
    post = service.reply(alice.uuid, topic, 'Muted @Bob')
    server.forum_manager.notifications.deliver_post(post)
    assert not bob.get_queued_messages()
    assert len(service.notifications.pending(bob.uuid)) == 2
    service.notifications.set_setting(bob.uuid, 'private_alerts', False)
    service.notifications.set_setting(bob.uuid, 'mention_alerts', False)
    server.db.close()
    server.db.connect()
    assert not any(service.notifications.settings(bob.uuid).values())
    assert service.notifications.muted(bob.uuid, topic)


def test_empty_inbox_only_speaks_and_never_changes_menu_or_return_stack(forum):
    server, _, users, _ = forum
    bob = users['Bob']
    server._nav_push(bob, server.forum_manager.home)
    bob.get_queued_messages()
    state = server._user_states[bob.username]
    before = dict(state)
    server.forum_manager.handle_menu(bob, 'notifications', state)
    assert server._user_states[bob.username] is state and state == before
    assert [p.get('key') for p in bob.get_queued_messages()] == ['forum-notifications-empty']
    server._nav_back(bob)
    assert server._user_states[bob.username]['menu'] == 'main_menu'


def test_inbox_opens_exact_full_message_and_returns_to_home_when_consumed(forum):
    server, service, users, _ = forum
    bob = users['Bob']
    _, post = service.create_topic(users['Alice'].uuid, 'general', 'Destination', 'Hello @Bob\nFull body')
    manager = server.forum_manager
    server._nav_push(bob, manager.home)
    manager.handle_menu(bob, 'notifications', server._user_states[bob.username])
    assert server._user_states[bob.username]['menu'] == nav.NOTIFICATIONS
    manager.handle_menu(bob, f'notice:{post}', server._user_states[bob.username])
    state = server._user_states[bob.username]
    assert state['menu'] == nav.BODY_READER and state['forum_post'] == post
    assert any(p.get('read_only') and p.get('default_value') == 'Hello @Bob\nFull body' for p in bob.get_queued_messages())
    manager.reader.close(bob, state)
    server._nav_back(bob)
    assert server._user_states[bob.username]['menu'] == nav.HOME
    assert any(p.get('key') == 'forum-notifications-empty' for p in bob.get_queued_messages())
    server._nav_back(bob)
    assert server._user_states[bob.username]['menu'] == 'main_menu'


def test_stale_notice_refresh_and_disabled_forum_never_render_empty_inbox(forum):
    server, service, users, _ = forum
    alice, bob = users['Alice'], users['Bob']
    topic, post = service.create_topic(alice.uuid, 'general', 'Topic', 'Hello @Bob')
    manager = server.forum_manager
    server._nav_push(bob, manager.home)
    manager.handle_menu(bob, 'notifications', server._user_states[bob.username])
    bob.get_queued_messages()
    service.moderate(alice.uuid, topic, 'hidden', True, post)
    manager.handle_menu(bob, f'notice:{post}', server._user_states[bob.username])
    packets = bob.get_queued_messages()
    assert not any(p.get('menu_id') == nav.NOTIFICATIONS or p.get('type') == 'request_input' for p in packets)
    assert server._user_states[bob.username]['menu'] == nav.HOME
    server.set_forum_enabled(False)
    manager.handle_menu(bob, 'notifications', server._user_states[bob.username])
    assert server._user_states[bob.username]['menu'] == nav.HOME


def test_retention_and_account_limit_bound_offline_queue(forum):
    server, service, users, now = forum
    alice, bob = users['Alice'].uuid, users['Bob'].uuid
    topic, _ = service.create_topic(alice, 'general', 'Topic', 'Start')
    account = server.db.get_user('Alice')
    with service.repository.atomic():
        for i in range(MAX_NOTIFICATIONS + 20):
            post = service.repository.create_post(account, topic, f'Message {i}', now[0] + i)
            server.db._conn.execute('''INSERT INTO forum_notifications(user_uuid, post_id, kind, created_at)
                VALUES (?, ?, 'mention', ?)''', (bob, post, now[0] + i))
    assert len(service.notifications.pending(bob)) == MAX_NOTIFICATIONS
    now[0] += RETENTION_SECONDS + MAX_NOTIFICATIONS + 21
    assert not service.notifications.pending(bob)


def test_composer_dispatches_only_committed_posts_to_online_recipient(forum):
    server, _, users, _ = forum
    alice, bob = users['Alice'], users['Bob']
    manager = server.forum_manager
    server._nav_push(alice, manager.home)
    server._nav_push(alice, manager.composer.show, Draft('topic', category_id='general', title='Live', body='Hello @Bob'))
    manager.handle_menu(alice, 'publish', server._user_states[alice.username])
    packets = bob.get_queued_messages()
    assert [p.get('key') for p in packets] == ['forum-notification-mention']
    assert 'Alice' in packets[0]['text'] and 'Live' in packets[0]['text']
    assert 'mentioned' in packets[0]['text']  # Recipient's English locale.


def test_deleted_accounts_erase_notices_and_owned_settings_without_removing_public_posts(forum):
    server, service, users, _ = forum
    alice, bob = users['Alice'].uuid, users['Bob'].uuid
    topic, post = service.create_topic(alice, 'general', 'Retained public topic', 'Hello @Bob')
    service.notifications.set_setting(alice, 'mention_alerts', False)
    service.notifications.set_muted(alice, topic, True)
    assert server.db.delete_user('Alice')
    assert not service.notifications.pending(bob)
    assert not server.db._conn.execute('SELECT * FROM forum_notifications').fetchall()
    assert service.post(bob, post).author_uuid is None
    for table in ('forum_notification_settings', 'forum_muted_topics'):
        assert not server.db._conn.execute(f'SELECT * FROM {table}').fetchall()


def legacy_ten(path):
    db = Database(path)
    db._conn = db._open_connection(str(path), timeout=30)
    db._conn.execute('PRAGMA foreign_keys = ON')
    with db._transaction(immediate=True) as cursor:
        db._create_tables_in_transaction(cursor, forum_version=10)
        cursor.execute(f'PRAGMA application_id = {Database.APPLICATION_ID}')
        cursor.execute('PRAGMA user_version = 10')
    alice = db.create_user('Legacy Author', 'retained-hash', locale='es')
    bob = db.create_user('Legacy Reader', 'hash', locale='en')
    for account in (alice, bob):
        db.approve_user(account.username)
    service = ForumService(ForumRepository(db))
    service.notifications = Mock()  # Historical data predates notice/mention tables.
    topic, post = service.create_topic(alice.uuid, 'general', 'Retained', 'x' * 64000,
                                      poll=PollConfig('Retained poll', ('Yes', 'No')))
    service.bookmark(bob.uuid, topic, True)
    service.post(bob.uuid, post, mark_read=True)
    db.close()
    return alice.uuid, bob.uuid, topic, post


def test_v10_migration_preserves_content_and_creates_verified_backup_and_no_retroactive_alerts(tmp_path):
    path = tmp_path / 'legacy.db'
    alice, bob, topic, post = legacy_ten(path)
    db = Database(path)
    db.connect(migration_backup_dir=tmp_path / 'backups')
    try:
        service = ForumService(ForumRepository(db))
        assert service.post(bob, post).body == 'x' * 64000
        assert service.topic(bob, topic).bookmarked and service.topic(bob, topic).unread_count == 0
        assert service.polls.get(bob, post)['question'] == 'Retained poll'
        assert not service.notifications.pending(bob)
        assert db._conn.execute('PRAGMA user_version').fetchone()[0] == 11
        assert not db._conn.execute('PRAGMA foreign_key_check').fetchall()
        backup = next((tmp_path / 'backups').glob('*.sqlite3'))
        with db._open_connection(str(backup), timeout=30) as old:
            assert old.execute('PRAGMA user_version').fetchone()[0] == 10
            assert old.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert old.execute('SELECT body FROM forum_posts WHERE id = ?', (post,)).fetchone()[0] == 'x' * 64000
        assert service.reply(alice, topic, 'Hello @{Legacy Reader}') > post
        assert service.notifications.pending(bob)
    finally:
        db.close()


def test_failed_v11_migration_rolls_back_and_keeps_backup(tmp_path, monkeypatch):
    path = tmp_path / 'legacy.db'
    _, _, _, post = legacy_ten(path)
    original = database_module.create_forum_schema
    def fail(cursor, **kwargs):
        original(cursor, **kwargs)
        if kwargs.get('version', 11) >= 11:
            raise sqlite3.OperationalError('Injected notification migration fault')
    monkeypatch.setattr(database_module, 'create_forum_schema', fail)
    with pytest.raises(sqlite3.DatabaseError):
        Database(path).connect(migration_backup_dir=tmp_path / 'backups')
    with sqlite3.connect(path) as old:
        assert old.execute('PRAGMA user_version').fetchone()[0] == 10
        assert old.execute('SELECT length(body) FROM forum_posts WHERE id = ?', (post,)).fetchone()[0] == 64000
        assert not old.execute("SELECT name FROM sqlite_master WHERE name = 'forum_notifications'").fetchall()
    assert len(list((tmp_path / 'backups').glob('*.sqlite3'))) == 1
    monkeypatch.setattr(database_module, 'create_forum_schema', original)
    db = Database(path)
    db.connect(migration_backup_dir=tmp_path / 'backups')
    db.close()


@pytest.mark.parametrize('client_type', ['python', 'web'])
async def test_live_and_offline_notices_and_exact_reader_over_real_websocket(tmp_path, client_type):
    server = Server(host='127.0.0.1', port=0, db_path=str(tmp_path / 'socket.db'))
    await server.start()
    try:
        auth = AuthManager(server.db)
        for name in ('Alice', 'Bob'):
            assert auth.register(name, 'ForumPassword123', locale='es', email=f'{name}@example.com') == 'ok'
            server.db.approve_user(name)
        manager, service = server.forum_manager, server.forum_manager.service
        alice_id, bob_id = (server.db.get_user(n).uuid for n in ('Alice', 'Bob'))
        topic, _ = service.conversations.create(alice_id, 'Private socket test', 'Opening', (bob_id,))
        service.conversations.respond(bob_id, service.conversations.invitations(bob_id)[0]['id'], accept=True)
        _, offline = service.create_topic(alice_id, 'general', 'Offline mention', 'Offline @Bob')
        port = server._ws_server._server.sockets[0].getsockname()[1]
        async def receive(ws, predicate):
            async with asyncio.timeout(15):
                while True:
                    packet = json.loads(await ws.recv())
                    if predicate(packet):
                        return packet
        async with connect(f'ws://127.0.0.1:{port}') as alice, connect(f'ws://127.0.0.1:{port}') as bob:
            for ws, name in ((alice, 'Alice'), (bob, 'Bob')):
                await ws.send(json.dumps({'type':'authorize','client':client_type,'version':VERSION,
                                          'username':name,'password':'ForumPassword123'}))
                login_packets = []
                await receive(ws, lambda p: (login_packets.append(p) or p.get('menu_id') == 'main_menu'))
                if name == 'Bob':
                    assert any(p.get('key') == 'forum-notification-summary' for p in login_packets)
            alice_user = server._users['Alice']
            server._nav_push(alice_user, manager.composer.show, Draft('reply', topic_id=topic, body='Live private reply'))
            await receive(alice, lambda p: p.get('menu_id') == nav.COMPOSER)
            await alice.send(json.dumps({'type':'menu','menu_id':nav.COMPOSER,'selection_id':'publish'}))
            live = await receive(bob, lambda p: p.get('key') == 'forum-notification-private')
            assert 'Alice' in live['text'] and 'Private socket test' in live['text']
            assert len(service.notifications.pending(bob_id)) == 2
            await bob.send(json.dumps({'type':'keybind','key':'f','control':True,'shift':True}))
            await receive(bob, lambda p: p.get('menu_id') == nav.HOME)
            await bob.send(json.dumps({'type':'menu','menu_id':nav.HOME,'selection_id':'notifications'}))
            inbox = await receive(bob, lambda p: p.get('menu_id') == nav.NOTIFICATIONS)
            assert f'notice:{offline}' in [row['id'] for row in inbox['items']]
            await bob.send(json.dumps({'type':'menu','menu_id':nav.NOTIFICATIONS,'selection_id':f'notice:{offline}'}))
            reader = await receive(bob, lambda p: p.get('input_id') == nav.BODY_READER and p.get('type') == 'request_input')
            assert reader['read_only'] and reader['multiline'] and reader['default_value'] == 'Offline @Bob'
            assert len(service.notifications.pending(bob_id)) == 1
    finally:
        await server.stop()
