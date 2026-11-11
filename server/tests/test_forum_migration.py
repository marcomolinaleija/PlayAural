"""Forum schema upgrades preserve existing accounts and recover on failure."""

import sqlite3
from unittest.mock import patch

import pytest

from ..forum.models import ForumError
from ..forum.polls import PollConfig
from ..forum.repository import ForumRepository
from ..forum.service import ForumService
from ..persistence.database import Database
from ..persistence import database as database_module


def version_three_database(path):
    """Build the actual pre-forum contract, without any forum tables."""
    db = Database(str(path))
    db._conn = db._open_connection(str(path), timeout=30)
    db._conn.execute("PRAGMA foreign_keys = ON")
    with db._transaction(immediate=True) as cursor:
        db._create_tables_in_transaction(cursor, include_forum=False, forum_version=3)
        cursor.execute(f"PRAGMA application_id = {Database.APPLICATION_ID}")
        cursor.execute("PRAGMA user_version = 3")
    user = db.create_user("Existing User", "retained-hash", email="existing@example.com", locale='es')
    db.approve_user(user.username)
    db.close()
    return user


def test_v3_upgrade_creates_verified_backup_and_preserves_existing_rows(tmp_path):
    path = tmp_path / "v3.db"
    backups = tmp_path / "backups"
    user = version_three_database(path)
    db = Database(str(path))
    db.connect(migration_backup_dir=backups)
    try:
        retained = db.get_user_by_uuid(user.uuid)
        assert retained.username == user.username and retained.password_hash == "retained-hash"
        assert db._conn.execute("PRAGMA user_version").fetchone()[0] == Database.CURRENT_SCHEMA_VERSION
        service = ForumService(ForumRepository(db))
        topic, post = service.create_topic(user.uuid, "general", "First native discussion", "A fresh forum")
        assert service.post(user.uuid, post).topic_id == topic
        snapshots = list(backups.glob("*.sqlite3"))
        assert len(snapshots) == 1
        with db._open_connection(snapshots[0], timeout=30) as snapshot:
            assert snapshot.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert snapshot.execute("PRAGMA user_version").fetchone()[0] == 3
            assert snapshot.execute("SELECT uuid FROM users").fetchone()[0] == user.uuid
            assert snapshot.execute("SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'forum_%'").fetchone()[0] == 0
        backup = db.backup_database(tmp_path / "forum-backups")
        with sqlite3.connect(backup.path) as snapshot:
            assert snapshot.execute("SELECT body FROM forum_posts").fetchone()[0] == "A fresh forum"
    finally:
        db.close()


def test_failed_forum_migration_rolls_back_and_retains_pre_migration_backup(tmp_path, monkeypatch):
    path = tmp_path / "v3.db"
    user = version_three_database(path)
    original = database_module.create_forum_schema
    def fail_after_creation(cursor, **kwargs):
        original(cursor, **kwargs)
        raise sqlite3.OperationalError("injected migration fault")
    monkeypatch.setattr(database_module, "create_forum_schema", fail_after_creation)
    db = Database(str(path))
    with pytest.raises(sqlite3.OperationalError, match="injected migration fault"):
        db.connect(migration_backup_dir=tmp_path / "backups")
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 3
        assert connection.execute("SELECT uuid FROM users").fetchone()[0] == user.uuid
        assert connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'forum_%'").fetchone()[0] == 0
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 1
    monkeypatch.setattr(database_module, "create_forum_schema", original)
    db.connect(migration_backup_dir=tmp_path / "backups")
    db.close()
    assert len(list((tmp_path / "backups").glob("*.sqlite3"))) == 1


def test_current_schema_rejects_forum_index_drift_without_repair(tmp_path):
    path = tmp_path / "current.db"
    db = Database(str(path))
    db.connect()
    db._conn.execute("DROP INDEX idx_forum_posts_topic")
    db.close()
    with pytest.raises(sqlite3.DatabaseError):
        db.connect()
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE name = 'idx_forum_posts_topic'").fetchone() is None


def version_four_database(path):
    db = Database(str(path))
    db._conn = db._open_connection(str(path), timeout=30)
    db._conn.execute('PRAGMA foreign_keys = ON')
    with db._transaction(immediate=True) as cursor:
        db._create_tables_in_transaction(cursor, forum_version=4)
        cursor.execute('DROP TABLE user_wallets')
        cursor.execute(f'PRAGMA application_id = {Database.APPLICATION_ID}')
        cursor.execute('PRAGMA user_version = 4')
    user = db.create_user('Forum Veteran', 'retained-hash', locale='es')
    db.approve_user(user.username)
    # The actual v4 repository had no private membership tables.
    with db._transaction(immediate=True):
        topic, post = ForumRepository(db).create_topic(user, 'general', 'Existing topic', 'Existing body', 1800000000)
        ForumRepository(db).bookmark(user.uuid, topic, True)
    db.close()
    return user, topic, post


def test_v4_upgrade_preserves_public_forum_and_creates_private_extensions(tmp_path):
    path = tmp_path / 'v4.db'
    user, topic, post = version_four_database(path)
    db = Database(str(path))
    db.connect(migration_backup_dir=tmp_path / 'backups')
    try:
        service = ForumService(ForumRepository(db))
        retained = service.topic(user.uuid, topic)
        assert retained.bookmarked and not retained.is_private
        assert service.post(user.uuid, post).body == 'Existing body'
        assert service.topics(user.uuid, view='private').total == 0
        with sqlite3.connect(next((tmp_path / 'backups').glob('*.sqlite3'))) as snapshot:
            assert snapshot.execute('PRAGMA user_version').fetchone()[0] == 4
            assert snapshot.execute('SELECT COUNT(*) FROM forum_posts').fetchone()[0] == 1
            assert not snapshot.execute("SELECT 1 FROM sqlite_master WHERE name = 'forum_private_topics'").fetchone()
    finally:
        db.close()


def test_v4_schema_drift_is_rejected_before_migration(tmp_path):
    path = tmp_path / 'v4-drift.db'
    version_four_database(path)
    with sqlite3.connect(path) as connection:
        connection.execute('DROP INDEX idx_forum_posts_topic')
    db = Database(str(path))
    with pytest.raises(sqlite3.DatabaseError):
        db.connect(migration_backup_dir=tmp_path / 'backups')
    with sqlite3.connect(path) as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 4
        assert not connection.execute("SELECT 1 FROM sqlite_master WHERE name = 'forum_private_topics'").fetchone()


def test_unapproved_banned_and_muted_accounts_cannot_bypass_forum_rules(tmp_path):
    db = Database(str(tmp_path / "auth.db"))
    db.connect()
    try:
        user = db.create_user("Pending", "hash", locale='es')
        service = ForumService(ForumRepository(db))
        with pytest.raises(ForumError, match="forum-error-account"):
            service.create_topic(user.uuid, "general", "Title", "Body")
        db.approve_user(user.username)
        topic, _ = service.create_topic(user.uuid, "general", "Title", "Body")
        db.mute_user(user.username, "Moderator", "Muted", None)
        assert service.topic(user.uuid, topic).id == topic
        with pytest.raises(ForumError, match="forum-error-muted"):
            service.reply(user.uuid, topic, "Muted post")
        db.ban_user(user.username, "Moderator", "Banned", None)
        with pytest.raises(ForumError, match="forum-error-account"):
            service.topics(user.uuid)
    finally:
        db.close()


def historical_branch_database(path, *, version, forum):
    """The two branches used v4 independently, before their merge into v6."""
    db = Database(str(path))
    db._conn = db._open_connection(str(path), timeout=30)
    db._conn.execute('PRAGMA foreign_keys = ON')
    with db._transaction(immediate=True) as cursor:
        db._create_tables_in_transaction(cursor, include_forum=forum, forum_version=version)
        if forum:
            cursor.execute('DROP TABLE user_wallets')
        cursor.execute(f'PRAGMA application_id = {Database.APPLICATION_ID}')
        cursor.execute(f'PRAGMA user_version = {version}')
    owner = db.create_user('Historical Owner', 'retained-hash', locale='es')
    recipient = db.create_user('Historical Recipient', 'second-hash', locale='es')
    db.approve_user(owner.username)
    db.approve_user(recipient.username)
    post = None
    if not forum:
        db.adjust_wallet_balance(owner.uuid, 713, is_win=True)
        db.adjust_wallet_balance(owner.uuid, -19, is_bet=True)
    elif version == 5:
        service = ForumService(ForumRepository(db))
        # Historical private discussions used the public general category.
        with patch('server.forum.conversations.PRIVATE_CATEGORY_ID', 'general'):
            topic, post = service.conversations.create(
                owner.uuid, 'Retained private topic', 'Retained private message', (recipient.uuid,),
                poll=PollConfig('Retained question', ('One', 'Two')),
            )
        invitation = service.conversations.invitations(recipient.uuid)[0]['id']
        service.conversations.respond(recipient.uuid, invitation, accept=True)
        option = service.polls.get(recipient.uuid, post)['options'][0]['id']
        service.polls.vote(recipient.uuid, post, (option,))
        service.bookmark(recipient.uuid, topic, True)
    db.close()
    return owner, recipient, post


@pytest.mark.parametrize(('version', 'forum'), [(4, False), (5, True)])
def test_branch_schema_upgrade_preserves_wallets_or_private_forum(tmp_path, version, forum):
    path = tmp_path / 'historical.db'
    owner, recipient, post = historical_branch_database(path, version=version, forum=forum)
    backups = tmp_path / 'backups'
    db = Database(str(path))
    db.connect(migration_backup_dir=backups)
    try:
        assert db.get_user_by_uuid(owner.uuid).password_hash == 'retained-hash'
        assert db._conn.execute('PRAGMA user_version').fetchone()[0] == Database.CURRENT_SCHEMA_VERSION
        wallet = db.get_wallet(owner.uuid)
        assert wallet.balance == (250 if forum else 944)
        assert wallet.total_won == (0 if forum else 713)
        assert wallet.total_bet == (0 if forum else 19)
        service = ForumService(ForumRepository(db))
        if forum:
            assert service.post(recipient.uuid, post).body == 'Retained private message'
            assert service.polls.get(recipient.uuid, post)['voters'] == 1
            assert service.topics(recipient.uuid, view='saved').total == 1
            assert service.topics(recipient.uuid).total == 0
        else:
            assert service.topics(owner.uuid).total == 0
    finally:
        db.close()
    snapshots = list(backups.glob('*.sqlite3'))
    assert len(snapshots) == 1
    with sqlite3.connect(snapshots[0]) as snapshot:
        assert snapshot.execute('PRAGMA user_version').fetchone()[0] == version
        assert bool(snapshot.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'user_wallets'"
        ).fetchone()) is not forum
    # Reopening the combined schema must not run another migration.
    db.connect(migration_backup_dir=backups)
    db.close()
    assert list(backups.glob('*.sqlite3')) == snapshots


@pytest.mark.parametrize(('version', 'forum', 'index'), [
    (4, False, 'idx_user_wallets_balance'),
    (5, True, 'idx_forum_posts_topic'),
])
def test_branch_schema_drift_fails_before_backup_or_mutation(tmp_path, version, forum, index):
    path = tmp_path / 'drift.db'
    historical_branch_database(path, version=version, forum=forum)
    with sqlite3.connect(path) as connection:
        connection.execute(f'DROP INDEX {index}')
    before = path.read_bytes()
    with pytest.raises(sqlite3.DatabaseError):
        Database(str(path)).connect(migration_backup_dir=tmp_path / 'backups')
    assert path.read_bytes() == before
    assert not list((tmp_path / 'backups').glob('*.sqlite3'))


def test_failed_combined_migration_preserves_v5_and_reuses_backup(tmp_path, monkeypatch):
    path = tmp_path / 'v5.db'
    owner, recipient, post = historical_branch_database(path, version=5, forum=True)
    original = database_module.create_forum_schema

    def fail_after_wallet_creation(cursor, **kwargs):
        original(cursor, **kwargs)
        raise sqlite3.OperationalError('injected combined migration fault')

    monkeypatch.setattr(database_module, 'create_forum_schema', fail_after_wallet_creation)
    db = Database(str(path))
    backups = tmp_path / 'backups'
    with pytest.raises(sqlite3.OperationalError, match='injected combined migration fault'):
        db.connect(migration_backup_dir=backups)
    with sqlite3.connect(path) as connection:
        assert connection.execute('PRAGMA user_version').fetchone()[0] == 5
        assert not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'user_wallets'"
        ).fetchone()
        assert connection.execute('SELECT COUNT(*) FROM forum_poll_votes').fetchone()[0] == 1
    monkeypatch.setattr(database_module, 'create_forum_schema', original)
    db.connect(migration_backup_dir=backups)
    try:
        assert db.get_user_by_uuid(owner.uuid)
        assert ForumService(ForumRepository(db)).post(recipient.uuid, post)
    finally:
        db.close()
    assert len(list(backups.glob('*.sqlite3'))) == 1
