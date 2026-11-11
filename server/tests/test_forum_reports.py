"""Public reports share moderation, retain evidence and never expose private data."""

import asyncio
import json
import sqlite3
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from websockets.asyncio.client import connect

from ..core.server import Server, VERSION
from ..auth.auth import AuthManager
from ..forum import navigation as nav
from ..forum.models import ForumError
from ..forum.reporting import ForumReportEvidence, ReportTarget, capture_public_report
from ..moderation.reports import AutomatedSpamEvidence
from ..persistence.database import Database
from ..users.network_user import NetworkUser


@pytest.fixture
def forum(tmp_path):
    server = Server(db_path=str(tmp_path / 'reports.db'))
    server.db.connect()
    users = {}
    for name, level in (('Staff', 3), ('Alice', 1), ('Bob', 1)):
        account = server.db.create_user(name, 'hash', trust_level=level, locale='es')
        server.db.approve_user(name)
        user = NetworkUser(name, 'es', SimpleNamespace(username=name, retired=False, authenticated=True),
                           uuid=account.uuid, approved=True, trust_level=level)
        users[name] = user
        server._users[name] = user
        server._show_main_menu(user)
        user.get_queued_messages()
    yield server, server.forum_manager.service, users
    server.db.close()


def submit(server, actor, target, **kwargs):
    return server.db.submit_moderation_report(reporter_uuid=actor.uuid, reporter_username=actor.username,
                                              forum_target=target, reason_code='harassment', **kwargs)


@pytest.mark.parametrize('kind', ['thread', 'post'])
def test_public_report_retains_exact_snapshot_and_uses_existing_review_queue(forum, kind):
    server, service, users = forum
    topic, post = service.create_topic(users['Alice'].uuid, 'general', 'Título original', 'Mensaje original')
    original = capture_public_report(service, users['Bob'].uuid, kind, topic if kind == 'thread' else post)
    result = submit(server, users['Bob'], original.target, details='Por favor revisen esto')
    assert result.outcome == 'created'
    service.edit(users['Alice'].uuid, post, 'Nuevo mensaje', 0)
    report = server.db.get_moderation_report(result.report_id)
    assert report.context_code == 'forum' and report.origin_code == 'manual' and report.status == 'open'
    assert report.context_anchor_message_id is None and report.channel_code is None
    assert ForumReportEvidence.from_json(report.evidence_json) == original
    assert report.reported_uuid == users['Alice'].uuid and report.reporter_uuid == users['Bob'].uuid
    assert report.details == 'Por favor revisen esto'
    assert server.db.count_moderation_reports(status='open') == 1
    assert not service.post(users['Bob'].uuid, post).hidden
    assert server.db.get_active_ban('Alice') is None
    staff = users['Staff']
    server.admin_manager._show_moderation_report_detail_menu(staff, result.report_id)
    menu = next(p for p in staff.get_queued_messages() if p.get('items'))
    rows = {row['id']: row['text'] for row in menu['items']}
    assert 'Mensaje original' in rows['forum_evidence_body:0']
    assert 'Título original' in rows['forum_evidence']
    assert 'Foro público' in rows['report_channel']
    assert 'view_context' not in rows and 'view_target_history' not in rows
    assert 'view_forum_current' in rows and 'set_status_reviewed' in rows


def test_evidence_survives_author_reporter_and_content_deletion_then_explicit_cleanup(forum):
    server, service, users = forum
    topic, post = service.create_topic(users['Alice'].uuid, 'general', 'Evidence', 'Keep this')
    target = capture_public_report(service, users['Bob'].uuid, 'post', post).target
    result = submit(server, users['Bob'], target)
    before = server.db.get_moderation_report(result.report_id)
    assert server.db.delete_user('Alice')
    assert server.db.delete_user('Bob')
    with server.db._transaction(immediate=True) as cursor:
        cursor.execute('DELETE FROM forum_topics WHERE id = ?', (topic,))
    assert server.db.get_moderation_report(result.report_id) == before
    assert server.db.set_moderation_report_status(result.report_id, 'reviewed',
        reviewer_uuid=users['Staff'].uuid, reviewer_username='Staff')
    server.db.clear_closed_moderation_reports()
    assert server.db.get_moderation_report(result.report_id) is None
    assert server.db._conn.execute('SELECT COUNT(*) FROM forum_report_targets').fetchone()[0] == 0


def test_deleted_author_public_content_remains_reportable_without_inventing_identity(forum):
    server, service, users = forum
    _, post = service.create_topic(users['Alice'].uuid, 'general', 'Retained', 'Retained body')
    server.db.delete_user('Alice')
    target = capture_public_report(service, users['Bob'].uuid, 'post', post).target
    result = submit(server, users['Bob'], target)
    report = server.db.get_moderation_report(result.report_id)
    assert report.reported_uuid == '' and report.reported_username == ''
    assert ForumReportEvidence.from_json(report.evidence_json).author_uuid is None


def test_duplicate_version_is_suppressed_but_other_posts_and_revisions_are_independent(forum):
    server, service, users = forum
    topic, post = service.create_topic(users['Alice'].uuid, 'general', 'Topic', 'First')
    other = service.reply(users['Alice'].uuid, topic, 'Second')
    actor = users['Bob']
    target = capture_public_report(service, actor.uuid, 'post', post).target
    assert submit(server, actor, target).outcome == 'created'
    assert submit(server, actor, target).outcome == 'duplicate'
    assert submit(server, actor, capture_public_report(service, actor.uuid, 'post', other).target).outcome == 'created'
    service.edit(users['Alice'].uuid, post, 'Edited first', 0)
    with pytest.raises(ForumError, match='forum-report-changed'):
        submit(server, actor, target)
    assert submit(server, actor, replace(target, revision=1)).outcome == 'created'
    assert server.db.count_moderation_reports() == 3


@pytest.mark.parametrize('violation', ['private', 'hidden', 'blocked', 'reverse_blocked', 'self', 'unapproved', 'banned', 'missing'])
def test_submission_rechecks_public_access_even_with_previously_valid_target(forum, violation):
    server, service, users = forum
    author, actor = users['Alice'], users['Bob']
    topic, post = service.create_topic(author.uuid, 'general', 'Topic', 'Body')
    target = capture_public_report(service, actor.uuid, 'post', post).target
    if violation == 'private':
        topic, post = service.conversations.create(author.uuid, 'Private', 'Secret', (actor.uuid,))
        invite = service.conversations.invitations(actor.uuid)[0]['id']
        service.conversations.respond(actor.uuid, invite, accept=True)
        assert service.post(actor.uuid, post).body == 'Secret'
        target = ReportTarget('post', post, 0)
    elif violation == 'hidden':
        service.moderate(users['Staff'].uuid, topic, 'hidden', True, post)
    elif violation == 'blocked':
        server.db.block_user(actor.uuid, author.uuid)
    elif violation == 'reverse_blocked':
        server.db.block_user(author.uuid, actor.uuid)
    elif violation == 'self':
        actor = author
    elif violation == 'unapproved':
        server.db._conn.execute('UPDATE users SET approved = 0 WHERE uuid = ?', (actor.uuid,))
        server.db._conn.commit()
    elif violation == 'banned':
        server.db.ban_user('Bob', 'Staff', 'Test', None)
    else:
        target = replace(target, id=999999)
    with pytest.raises(ForumError):
        submit(server, actor, target)
    assert server.db.count_moderation_reports() == 0


def test_muted_accounts_can_report_and_share_manual_chat_quota(forum):
    server, service, users = forum
    actor, author = users['Bob'], users['Alice']
    server.db.mute_user('Bob', 'Staff', 'Test', None)
    server.db.submit_moderation_report(reporter_uuid=actor.uuid, reporter_username='Bob',
        reported_uuid=author.uuid, reported_username='Alice', reason_code='spam')
    topic, post = service.create_topic(author.uuid, 'general', 'Topic', 'First')
    for index in range(4):
        if index:
            post = service.reply(author.uuid, topic, f'Message {index}')
        assert submit(server, actor, capture_public_report(service, actor.uuid, 'post', post).target).outcome == 'created'
    post = service.reply(author.uuid, topic, 'Limited')
    assert submit(server, actor, capture_public_report(service, actor.uuid, 'post', post).target).outcome == 'reporter_limit'
    assert server.db.count_moderation_reports() == 5


def test_atomic_failure_leaves_no_case_or_deduplication_record(forum):
    server, service, users = forum
    _, post = service.create_topic(users['Alice'].uuid, 'general', 'Topic', 'Body')
    target = capture_public_report(service, users['Bob'].uuid, 'post', post).target
    server.db._conn.execute("CREATE TEMP TRIGGER fail_report BEFORE INSERT ON forum_report_targets BEGIN SELECT RAISE(ABORT, 'failure'); END")
    with pytest.raises(sqlite3.IntegrityError):
        submit(server, users['Bob'], target)
    assert server.db.count_moderation_reports() == 0
    assert not server.db._conn.in_transaction


def test_reports_only_appear_for_eligible_public_content_and_respect_forum_switch(forum):
    server, service, users = forum
    manager = server.forum_manager
    author, actor = users['Alice'], users['Bob']
    topic, post = service.create_topic(author.uuid, 'general', 'Public', 'Body')
    for user, permitted in ((actor, True), (author, False)):
        manager.views.post(user, post)
        menu = next(p for p in user.get_queued_messages() if p.get('menu_id') == nav.POST)
        assert ('report_post' in [row['id'] for row in menu['items']]) == permitted
    state = server._user_states[actor.username]
    server._forum_enabled = False
    manager.handle_menu(actor, 'report_post', state)
    assert server._user_states[actor.username]['menu'] == nav.POST
    assert server.db.count_moderation_reports() == 0


async def test_private_content_has_no_report_actions_even_for_staff_members(forum):
    server, service, users = forum
    author, actor = users['Alice'], users['Staff']
    topic, post = service.conversations.create(author.uuid, 'Private', 'Secret', (actor.uuid,))
    invite = service.conversations.invitations(actor.uuid)[0]['id']
    service.conversations.respond(actor.uuid, invite, accept=True)
    for show, target, menu_id in ((server.forum_manager.views.thread, topic, nav.THREAD),
                                  (server.forum_manager.views.post, post, nav.POST)):
        show(actor, target)
        menu = next(p for p in actor.get_queued_messages() if p.get('menu_id') == menu_id)
        assert not any(row['id'].startswith('report_') for row in menu['items'])
        with pytest.raises(ForumError):
            capture_public_report(service, actor.uuid, 'thread' if menu_id == nav.THREAD else 'post', target)


def test_suspended_report_confirmation_cannot_resume_consent(forum):
    server, service, users = forum
    _, post = service.create_topic(users['Alice'].uuid, 'general', 'Public', 'Body')
    actor = users['Bob']
    evidence = capture_public_report(service, actor.uuid, 'post', post)
    draft = {'kind': 'post', 'id': post, 'revision': evidence.revision, 'reason': 'spam', 'details': ''}
    server.forum_manager.reports.confirm(actor, draft)
    frame = dict(server._user_states[actor.username])
    server.forum_manager.restore(actor, frame)
    assert server._user_states[actor.username]['menu'] == nav.HOME
    assert server.db.count_moderation_reports() == 0


async def test_staff_can_review_snapshot_while_forum_off_but_cannot_open_live_content(forum):
    server, service, users = forum
    _, post = service.create_topic(users['Alice'].uuid, 'general', 'Public', 'Historical body')
    target = capture_public_report(service, users['Bob'].uuid, 'post', post).target
    result = submit(server, users['Bob'], target)
    server._forum_enabled = False
    staff = users['Staff']
    admin = server.admin_manager
    admin._show_moderation_report_detail_menu(staff, result.report_id)
    state = server._user_states[staff.username]
    await admin._handle_moderation_report_detail_selection(staff, 'view_forum_current', state)
    assert server._user_states[staff.username]['menu'] == state['menu']
    await admin._handle_moderation_report_detail_selection(staff, 'set_status_reviewed', state)
    assert server.db.get_moderation_report(result.report_id).status == 'reviewed'


@pytest.mark.parametrize('value', ['{}', '[]', 'null', 'broken', '{"version":2}', '{"version":1}'])
def test_bad_evidence_is_safe_to_review(value):
    assert ForumReportEvidence.from_json(value) is None


def test_forum_is_not_an_automated_spam_scope():
    with pytest.raises(ValueError):
        AutomatedSpamEvidence('forum', 'rate_limited', 1, 1, 0, 30, 'text').to_json()


def legacy_seven(path):
    db = Database(path)
    db._conn = db._open_connection(str(path), timeout=30)
    db._conn.execute('PRAGMA foreign_keys = ON')
    with db._transaction(immediate=True) as cursor:
        db._create_tables_in_transaction(cursor, forum_version=7)
        cursor.execute(f'PRAGMA application_id = {Database.APPLICATION_ID}')
        cursor.execute('PRAGMA user_version = 7')
    users = [db.create_user(name, 'hash', locale='es') for name in ('Alice', 'Bob')]
    for user in users:
        db.approve_user(user.username)
    manual = db.submit_moderation_report(reporter_uuid=users[1].uuid, reporter_username='Bob',
        reported_uuid=users[0].uuid, reported_username='Alice', reason_code='spam')
    automatic = db.submit_automated_spam_report(reported_uuid=users[0].uuid, reported_username='Alice',
        evidence=AutomatedSpamEvidence('global', 'rate_limited', 1, 1, 0, 30, 'sample'), channel_code='en')
    snapshots = [db.get_moderation_report(result.report_id) for result in (manual, automatic)]
    with db._transaction(immediate=True) as cursor:
        cursor.execute("UPDATE sqlite_sequence SET seq = 999 WHERE name = 'moderation_reports'")
    db.close()
    return users, snapshots


@pytest.mark.parametrize('reordered_columns', [False, True])
def test_v8_migration_preserves_manual_and_automatic_reports_sequence_and_verified_backup(tmp_path, reordered_columns):
    from ..forum.repository import ForumRepository
    from ..forum.service import ForumService
    path = tmp_path / 'legacy.db'
    users, reports = legacy_seven(path)
    if reordered_columns:
        with sqlite3.connect(path) as connection:
            ddl = connection.execute("SELECT sql FROM sqlite_master WHERE name = 'moderation_reports'").fetchone()[0]
            indexes = [row[0] for row in connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'moderation_reports' AND sql IS NOT NULL")]
            columns = ', '.join(row[1] for row in connection.execute('PRAGMA table_info(moderation_reports)'))
            connection.execute('ALTER TABLE moderation_reports RENAME TO previous_reports')
            connection.execute(ddl.replace('reporter_uuid TEXT NOT NULL, reporter_username TEXT NOT NULL',
                                           'reporter_username TEXT NOT NULL, reporter_uuid TEXT NOT NULL'))
            connection.execute(f'INSERT INTO moderation_reports ({columns}) SELECT {columns} FROM previous_reports')
            connection.execute('DROP TABLE previous_reports')
            for statement in indexes:
                connection.execute(statement)
            connection.execute("UPDATE sqlite_sequence SET seq = 999 WHERE name = 'moderation_reports'")
    db = Database(path)
    db.connect(migration_backup_dir=tmp_path / 'backups')
    try:
        assert [db.get_moderation_report(report.id) for report in reports] == reports
        service = ForumService(ForumRepository(db))
        _, post = service.create_topic(users[0].uuid, 'general', 'Migrated', 'Body')
        result = db.submit_moderation_report(reporter_uuid=users[1].uuid, reporter_username='Bob',
            reason_code='spam', forum_target=capture_public_report(service, users[1].uuid, 'post', post).target)
        assert result.report_id == 1000
        backup = next((tmp_path / 'backups').glob('*.sqlite3'))
        with db._open_connection(str(backup), timeout=30) as snapshot:
            assert snapshot.execute('PRAGMA user_version').fetchone()[0] == 7
            assert snapshot.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            assert snapshot.execute('SELECT COUNT(*) FROM moderation_reports').fetchone()[0] == 2
    finally:
        db.close()
    db.connect()
    db.close()


def test_v8_migration_failure_rolls_back_reports_and_reuses_backup(tmp_path, monkeypatch):
    from ..persistence import database as database_module
    path = tmp_path / 'legacy.db'
    _, reports = legacy_seven(path)
    original = database_module.create_forum_schema
    def fail(cursor, **kwargs):
        original(cursor, **kwargs)
        raise sqlite3.DatabaseError('Injected migration failure')
    monkeypatch.setattr(database_module, 'create_forum_schema', fail)
    with pytest.raises(sqlite3.DatabaseError):
        Database(path).connect(migration_backup_dir=tmp_path / 'backups')
    with sqlite3.connect(path) as snapshot:
        assert snapshot.execute('PRAGMA user_version').fetchone()[0] == 7
        assert snapshot.execute('SELECT COUNT(*) FROM moderation_reports').fetchone()[0] == 2
        assert snapshot.execute("SELECT 1 FROM sqlite_master WHERE name = 'forum_report_targets'").fetchone() is None
    monkeypatch.setattr(database_module, 'create_forum_schema', original)
    db = Database(path)
    db.connect(migration_backup_dir=tmp_path / 'backups')
    try:
        assert [db.get_moderation_report(report.id) for report in reports] == reports
        assert len(list((tmp_path / 'backups').glob('*.sqlite3'))) == 1
    finally:
        db.close()


@pytest.mark.parametrize('client_type', ['python', 'web'])
async def test_report_flow_over_socket_reason_details_confirmation_and_staff_review(tmp_path, client_type):
    server = Server(host='127.0.0.1', port=0, db_path=str(tmp_path / 'socket.db'))
    await server.start()
    try:
        auth = AuthManager(server.db)
        for name in ('Staff', 'Author', 'Reporter'):
            assert auth.register(name, 'TestPassword123', locale='es', email=f'{name}@example.test') == 'ok'
            server.db.approve_user(name)
        service = server.forum_manager.service
        topic, post = service.create_topic(server.db.get_user('Author').uuid, 'general', 'Tema público', 'Mensaje para revisar')
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
                'username': 'Reporter', 'password': 'TestPassword123'}))
            await receive(ws, lambda p: p.get('menu_id') == 'main_menu')
            await choose(ws, 'main_menu', 'forum', nav.HOME)
            await choose(ws, nav.HOME, 'category:general', nav.TOPICS)
            thread = await choose(ws, nav.TOPICS, f'topic:{topic}', nav.THREAD)
            assert thread['items'][0]['id'] == f'post:{post}'
            assert 'report_thread' in [row['id'] for row in thread['items']]
            await choose(ws, nav.THREAD, f'post:{post}', nav.POST)
            form = await choose(ws, nav.POST, 'report_post', nav.REPORT)
            assert [row['id'] for row in form['items']] == ['report_content', 'reason', 'details', 'submit', 'back']
            await choose(ws, nav.REPORT, 'reason', nav.REPORT_REASON)
            form = await choose(ws, nav.REPORT_REASON, 'reason:harassment', nav.REPORT)
            assert 'Motivo:' in next(row['text'] for row in form['items'] if row['id'] == 'reason')
            await ws.send(json.dumps({'type': 'menu', 'menu_id': nav.REPORT, 'selection_id': 'details'}))
            prompt = await receive(ws, lambda p: p.get('type') == 'request_input' and p.get('input_id') == nav.REPORT_DETAILS_INPUT)
            assert prompt['multiline'] and prompt['max_length'] == 500
            await ws.send(json.dumps({'type': 'editbox', 'input_id': nav.REPORT_DETAILS_INPUT, 'text': 'Explicación breve'}))
            await receive(ws, lambda p: p.get('menu_id') == nav.REPORT)
            confirmation = await choose(ws, nav.REPORT, 'submit', nav.REPORT_CONFIRM)
            assert [row['id'] for row in confirmation['items']] == ['confirmation_prompt', 'yes', 'no']
            assert server.db.count_moderation_reports() == 0
            await choose(ws, nav.REPORT_CONFIRM, 'no', nav.REPORT)
            assert server.db.count_moderation_reports() == 0
            await choose(ws, nav.REPORT, 'submit', nav.REPORT_CONFIRM)
            server._notify_new_moderation_report = Mock()
            await choose(ws, nav.REPORT_CONFIRM, 'yes', nav.POST)
            assert server.db.count_moderation_reports(status='open') == 1
            report = server.db.get_moderation_report(1)
            assert report.details == 'Explicación breve' and report.reason_code == 'harassment'
            assert ForumReportEvidence.from_json(report.evidence_json).body == 'Mensaje para revisar'
            assert server._notify_new_moderation_report.call_count == 1
            # A repeat submission is acknowledged without another case or alert.
            await choose(ws, nav.POST, 'report_post', nav.REPORT)
            await choose(ws, nav.REPORT, 'reason', nav.REPORT_REASON)
            await choose(ws, nav.REPORT_REASON, 'reason:spam', nav.REPORT)
            await choose(ws, nav.REPORT, 'submit', nav.REPORT_CONFIRM)
            await choose(ws, nav.REPORT_CONFIRM, 'yes', nav.POST)
            assert server.db.count_moderation_reports() == 1
            assert server._notify_new_moderation_report.call_count == 1
    finally:
        await server.stop()
