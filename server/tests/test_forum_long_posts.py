"""64,000-character posts survive transport, editing, reporting and migration."""

import asyncio
import json
import sqlite3
from unittest.mock import Mock

import pytest
from websockets.asyncio.client import connect

from ..auth.auth import AuthManager
from ..core.server import Server, VERSION
from ..forum import navigation as nav, schema as forum_schema
from ..forum.media_processing import MediaProcessor
from ..forum.models import ForumError, MAX_BODY_LENGTH
from ..forum.polls import PollConfig
from ..forum.reporting import ForumReportEvidence, capture_public_report
from ..forum.repository import ForumRepository
from ..forum.service import ForumService
from ..persistence.database import Database


def snapshot(db):
    tables = [row[0] for row in db._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'forum_%' ORDER BY name")]
    # Compare the v9 content; v11 adds four empty, separately tested tables.
    return {table: [tuple(row) for row in db._conn.execute(f'SELECT * FROM {table} ORDER BY rowid')]
            for table in tables + ['moderation_reports'] if table not in {
                'forum_mentions', 'forum_notifications', 'forum_notification_settings', 'forum_muted_topics'}}


def legacy_nine(path, tmp_path):
    db = Database(path)
    db._conn = db._open_connection(str(path), timeout=30)
    db._conn.execute('PRAGMA foreign_keys = ON')
    with db._transaction(immediate=True) as cursor:
        db._create_tables_in_transaction(cursor, forum_version=9)
        cursor.execute(f'PRAGMA application_id = {Database.APPLICATION_ID}')
        cursor.execute('PRAGMA user_version = 9')
    alice = db.create_user('Alice', 'hash', locale='es', trust_level=3).uuid
    bob = db.create_user('Bob', 'hash', locale='es').uuid
    for name in ('Alice', 'Bob'):
        db.approve_user(name)
    service = ForumService(ForumRepository(db), clock=lambda: 1_800_000_000)
    service.notifications = Mock()  # Seed the historical layout without v11 features.
    source = tmp_path / 'notes.txt'
    source.write_text('Retained attachment', encoding='utf-8')
    attachment = service.attachments.reserve(alice, 'notes.txt', source.stat().st_size)
    service.attachments.processing(alice, attachment['id'])
    processed = MediaProcessor().process(source, tmp_path / 'prepared')
    service.attachments.complete(alice, attachment['id'], processed)
    topic, post = service.create_topic(alice, 'general', 'Retained topic', 'x' * 8000,
        attachment_ids=(attachment['id'],), poll=PollConfig('Retained poll', ('Yes', 'No')))
    option = service.polls.get(bob, post)['options'][0]['id']
    service.polls.vote(bob, post, (option,))
    service.bookmark(bob, topic, True)
    service.post(bob, post, mark_read=True)
    service.moderate(alice, topic, 'hidden', True, post)
    service.moderate(alice, topic, 'hidden', False, post)
    service.languages.select(bob, 'en')
    private, private_post = service.conversations.create(alice, 'Private', 'Private body', (bob,))
    invite = service.conversations.invitations(bob)[0]['id']
    service.conversations.respond(bob, invite, accept=True)
    evidence = capture_public_report(service, bob, 'post', post)
    db.submit_moderation_report(reporter_uuid=bob, reporter_username='Bob', reason_code='spam', forum_target=evidence.target)
    with db._transaction(immediate=True) as cursor:
        cursor.execute("UPDATE sqlite_sequence SET seq=9999 WHERE name='forum_posts'")
    before = snapshot(db)
    db.close()
    return alice, bob, topic, post, before


def test_migration_retains_every_relation_and_post_sequence_and_enforces_new_boundary(tmp_path):
    path = tmp_path / 'legacy.db'
    alice, bob, topic, post, before = legacy_nine(path, tmp_path)
    db = Database(path)
    db.connect(migration_backup_dir=tmp_path / 'backups')
    try:
        assert snapshot(db) == before
        assert db._conn.execute('PRAGMA foreign_keys').fetchone()[0] == 1
        assert not db._conn.execute('PRAGMA foreign_key_check').fetchall()
        service = ForumService(ForumRepository(db))
        body = '🔊' * 64000
        new_post = service.reply(bob, topic, body)
        assert new_post == 10000
        assert service.post(bob, new_post).body == body
        service.edit(bob, new_post, 'é' * 64000, 0)
        target = capture_public_report(service, alice, 'post', new_post).target
        result = db.submit_moderation_report(reporter_uuid=alice, reporter_username='Alice',
            forum_target=target, reason_code='other')
        report = db.get_moderation_report(result.report_id)
        assert ForumReportEvidence.from_json(report.evidence_json).body == 'é' * 64000
        with pytest.raises(ForumError, match='forum-error-body-length'):
            service.reply(bob, topic, 'x' * 64001)
        with pytest.raises(sqlite3.IntegrityError):
            with db._transaction(immediate=True) as cursor:
                cursor.execute('UPDATE forum_posts SET body=? WHERE id=?', ('x' * 64001, new_post))
        assert service.post(bob, new_post).body == 'é' * 64000
        backup = next((tmp_path / 'backups').glob('*.sqlite3'))
        with db._open_connection(str(backup), timeout=30) as old:
            assert old.execute('PRAGMA user_version').fetchone()[0] == 9
            assert old.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert old.execute('SELECT length(body) FROM forum_posts WHERE id=?', (post,)).fetchone()[0] == 8000
    finally:
        db.close()
    db.connect()
    assert ForumService(ForumRepository(db)).post(bob, new_post).body == 'é' * 64000
    db.close()


@pytest.mark.parametrize('failure', ['after_rebuild', 'foreign_key_violation'])
def test_failed_rebuild_or_broken_reference_rolls_back_all_data_and_reuses_backup(tmp_path, monkeypatch, failure):
    path = tmp_path / 'legacy.db'
    _, _, _, post, before = legacy_nine(path, tmp_path)
    original = forum_schema.expand_posts
    def broken(cursor):
        original(cursor)
        if failure == 'after_rebuild':
            raise sqlite3.DatabaseError('Injected after post rebuild')
        cursor.execute('UPDATE forum_posts SET topic_id=999999 WHERE id=?', (post,))
    monkeypatch.setattr(forum_schema, 'expand_posts', broken)
    with pytest.raises(sqlite3.DatabaseError):
        Database(path).connect(migration_backup_dir=tmp_path / 'backups')
    old = Database(path)
    old._conn = old._open_connection(str(path), timeout=30)
    try:
        assert old._conn.execute('PRAGMA user_version').fetchone()[0] == 9
        assert snapshot(old) == before
        assert not old._conn.execute('PRAGMA foreign_key_check').fetchall()
    finally:
        old.close()
    monkeypatch.setattr(forum_schema, 'expand_posts', original)
    db = Database(path)
    db.connect(migration_backup_dir=tmp_path / 'backups')
    assert snapshot(db) == before
    assert db._conn.execute('PRAGMA foreign_keys').fetchone()[0] == 1
    assert len(list((tmp_path / 'backups').glob('*.sqlite3'))) == 1
    db.close()


@pytest.mark.parametrize('client_type', ['python', 'web'])
async def test_maximum_body_over_real_websocket_editor_reader_and_report_snapshot(tmp_path, client_type):
    server = Server(host='127.0.0.1', port=0, db_path=str(tmp_path / 'socket.db'))
    await server.start()
    try:
        auth = AuthManager(server.db)
        for name in ('Staff', 'Reader'):
            assert auth.register(name, 'TestPassword123', locale='es', email=f'{name}@example.test') == 'ok'
            server.db.approve_user(name)
        topic, first = server.forum_manager.service.create_topic(server.db.get_user('Staff').uuid, 'general', 'Long posts', 'Original')
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
                                     'username': 'Reader', 'password': 'TestPassword123'}))
            await receive(ws, lambda p: p.get('menu_id') == 'main_menu')
            await choose(ws, 'main_menu', 'forum', nav.HOME)
            await choose(ws, nav.HOME, 'category:general', nav.TOPICS)
            await choose(ws, nav.TOPICS, f'topic:{topic}', nav.THREAD)
            await choose(ws, nav.THREAD, 'reply', nav.COMPOSER)
            await ws.send(json.dumps({'type': 'menu', 'menu_id': nav.COMPOSER, 'selection_id': 'edit_body'}))
            prompt = await receive(ws, lambda p: p.get('type') == 'request_input' and p.get('input_id') == nav.BODY_INPUT)
            assert prompt['max_length'] == MAX_BODY_LENGTH == 64000
            body = '🔊' * 64000
            # Escaped surrogate pairs make this substantially larger than 64k bytes.
            await ws.send(json.dumps({'type': 'editbox', 'input_id': nav.BODY_INPUT, 'text': body}))
            draft = await receive(ws, lambda p: p.get('menu_id') == nav.COMPOSER)
            assert len(next(row['text'] for row in draft['items'] if row['id'] == 'edit_body')) < 200
            reader = await choose(ws, nav.COMPOSER, 'publish', nav.POST)
            assert len(reader['items'][0]['text']) <= 160
            await ws.send(json.dumps({'type':'menu','menu_id':nav.POST,'selection_id':'read_body'}))
            full = await receive(ws, lambda p:p.get('type') == 'request_input' and p.get('input_id') == nav.BODY_READER)
            assert full['read_only'] and full['multiline'] and full['default_value'] == body
            await ws.send(json.dumps({'type':'editbox','input_id':nav.BODY_READER,'cancelled':True}))
            await receive(ws, lambda p:p.get('menu_id') == nav.POST)
            post = server.forum_manager.service.topic(server.db.get_user('Reader').uuid, topic).last_post_id
            await choose(ws, nav.POST, 'edit', nav.COMPOSER)
            await ws.send(json.dumps({'type': 'menu', 'menu_id': nav.COMPOSER, 'selection_id': 'edit_body'}))
            prompt = await receive(ws, lambda p: p.get('type') == 'request_input' and p.get('input_id') == nav.BODY_INPUT)
            assert prompt['default_value'] == body and prompt['max_length'] == 64000
            await ws.send(json.dumps({'type':'editbox','input_id':nav.BODY_INPUT,'cancelled':True}))
            await receive(ws, lambda p:p.get('menu_id') == nav.COMPOSER)
            assert server.forum_manager.service.post(server.db.get_user('Staff').uuid, post).body == body
            evidence = capture_public_report(server.forum_manager.service, server.db.get_user('Staff').uuid, 'post', post)
            assert ForumReportEvidence.from_json(evidence.to_json()).body == body
    finally:
        await server.stop()
