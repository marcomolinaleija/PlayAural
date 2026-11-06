"""Forum schema upgrades preserve existing accounts and recover on failure."""

import sqlite3

import pytest

from ..forum.models import ForumError
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
        db._create_tables_in_transaction(cursor, include_forum=False)
        cursor.execute(f"PRAGMA application_id = {Database.APPLICATION_ID}")
        cursor.execute("PRAGMA user_version = 3")
    user = db.create_user("Existing User", "retained-hash", email="existing@example.com")
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
        assert db._conn.execute("PRAGMA user_version").fetchone()[0] == 4
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
    def fail_after_creation(cursor):
        original(cursor)
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


def test_unapproved_banned_and_muted_accounts_cannot_bypass_forum_rules(tmp_path):
    db = Database(str(tmp_path / "auth.db"))
    db.connect()
    try:
        user = db.create_user("Pending", "hash")
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
