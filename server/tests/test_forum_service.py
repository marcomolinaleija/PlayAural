"""Native forum rules, privacy, persistence and transaction boundaries."""

import sqlite3

import pytest

from ..forum.models import ForumError, MAX_BODY_LENGTH, MAX_WRITES_PER_WINDOW
from ..forum.repository import ForumRepository
from ..forum.service import ForumService
from ..forum.text import reading_chunks
from ..persistence.database import Database


@pytest.fixture
def forum(tmp_path):
    db = Database(str(tmp_path / "forum.db"))
    db.connect()
    users = {}
    for name in ("Alice", "Bob", "Carol", "Moderator"):
        users[name] = db.create_user(name, "hash")
        db.approve_user(name)
    db.update_user_trust_level("Moderator", 2)
    clock = [1_800_000_000]
    service = ForumService(ForumRepository(db), clock=lambda: clock[0])
    yield service, db, users, clock
    db.close()


def test_topics_replies_search_bookmarks_and_read_progress(forum):
    service, db, users, clock = forum
    alice, bob = users["Alice"].uuid, users["Bob"].uuid
    topic, first = service.create_topic(alice, "general", "Welcome 👋", "First message")
    second = service.reply(bob, topic, "A reply with café and 100% support")
    assert service.topic(bob, topic).unread_count == 2
    service.posts(bob, topic)  # A list of previews is not a read receipt.
    assert service.topic(bob, topic).unread_count == 2
    service.post(bob, first, mark_read=True)
    assert service.repository.resume_post(bob, topic) == second
    service.post(bob, second, mark_read=True)
    service.post(bob, first, mark_read=True)  # Older pages cannot move backwards.
    assert service.topic(bob, topic).unread_count == 0
    assert service.topics(bob, view="unread").total == 0
    service.bookmark(bob, topic, True)
    assert service.topics(bob, view="saved").items[0].id == topic
    assert service.topics(alice, view="saved").total == 0
    assert service.topics(bob, view="search", query="CAFÉ").items[0].id == topic
    assert service.topics(bob, view="search", query="100%").total == 1
    assert service.topics(bob, view="search", query="__").total == 0
    db.close()
    db.connect()
    assert service.topic(bob, topic).bookmarked
    assert service.topic(bob, topic).unread_count == 0
    assert service.posts(bob, topic).total == 2


def test_blocking_filters_lists_messages_counts_search_and_forged_writes(forum):
    service, db, users, _ = forum
    alice, bob, carol = (users[name].uuid for name in ("Alice", "Bob", "Carol"))
    private_to_pair, first = service.create_topic(alice, "general", "Alice discussion", "Alice message")
    shared, _ = service.create_topic(carol, "help", "Shared discussion", "A question")
    blocked_reply = service.reply(alice, shared, "secretword")
    assert db.block_user(bob, alice) == "blocked"
    for viewer, target in ((bob, private_to_pair), (alice, private_to_pair)):
        if viewer == alice:
            continue  # An author can always see their own public discussion.
        with pytest.raises(ForumError, match="forum-error-missing"):
            service.topic(viewer, target)
    assert service.topics(bob).total == 1
    assert service.categories(bob)[0].topic_count == 0
    assert service.posts(bob, shared).total == 1
    assert service.topic(bob, shared).unread_count == 1
    assert service.topics(bob, view="search", query="secretword").total == 0
    for operation in (
        lambda: service.post(bob, first), lambda: service.post(bob, blocked_reply),
        lambda: service.reply(bob, private_to_pair, "forged reply"),
        lambda: service.bookmark(bob, private_to_pair, True),
    ):
        with pytest.raises(ForumError, match="forum-error-missing"):
            operation()
    # The opposite direction must filter Bob's posts as well.
    bobs_reply = service.reply(bob, shared, "Bob reply")
    with pytest.raises(ForumError, match="forum-error-missing"):
        service.post(alice, bobs_reply)


def test_edits_use_owner_time_window_revision_and_authoritative_role(forum):
    service, db, users, clock = forum
    alice, bob, mod = (users[name].uuid for name in ("Alice", "Bob", "Moderator"))
    topic, post = service.create_topic(alice, "ideas", "An idea", "Original")
    with pytest.raises(ForumError, match="forum-error-edit-permission"):
        service.edit(bob, post, "Unauthorized", 0)
    service.edit(alice, post, "Updated", 0)
    with pytest.raises(ForumError, match="forum-error-conflict"):
        service.edit(alice, post, "Stale update", 0)
    assert service.post(alice, post).body == "Updated"
    clock[0] += 1801
    with pytest.raises(ForumError, match="forum-error-edit-permission"):
        service.edit(alice, post, "Too late", 1)
    service.edit(mod, post, "Moderator update", 1)
    service.moderate(mod, topic, "closed", True)
    with pytest.raises(ForumError, match="forum-error-closed"):
        service.reply(bob, topic, "Late reply")
    service.moderate(mod, topic, "pinned", True)
    service.moderate(mod, topic, "hidden", True, post)
    assert service.post(bob, post).body == ""
    assert service.topics(bob, view="search", query="Moderator update").total == 0
    service.moderate(mod, topic, "hidden", False, post)
    assert service.post(bob, post).body == "Moderator update"
    assert db._conn.execute("SELECT COUNT(*) FROM forum_moderation_events").fetchone()[0] == 4
    db.update_user_trust_level("Moderator", 1)
    with pytest.raises(ForumError, match="forum-error-moderator"):
        service.moderate(mod, topic, "closed", False)


def test_validation_and_persistent_send_limits(forum):
    service, db, users, clock = forum
    alice = users["Alice"].uuid
    with pytest.raises(ForumError, match="forum-error-title-empty"):
        service.create_topic(alice, "general", " ", "body")
    with pytest.raises(ForumError, match="forum-error-body-length"):
        service.create_topic(alice, "general", "Title", "a" * (MAX_BODY_LENGTH + 1))
    with pytest.raises(ForumError, match="forum-error-text-controls"):
        service.create_topic(alice, "general", "Title", "spoof\u202etext")
    topic, _ = service.create_topic(alice, "general", "Title", "Body")
    with pytest.raises(ForumError, match="forum-error-duplicate"):
        service.reply(alice, topic, "BODY")
    for index in range(MAX_WRITES_PER_WINDOW - 1):
        service.reply(alice, topic, f"Reply {index}")
    db.close()
    db.connect()
    with pytest.raises(ForumError, match="forum-error-rate"):
        service.reply(alice, topic, "Cannot bypass with a reconnect or restart")
    clock[0] += 61
    service.reply(alice, topic, "Now allowed")
    assert service.posts(alice, topic).total == MAX_WRITES_PER_WINDOW + 1


def test_topic_and_first_post_are_atomic(forum, monkeypatch):
    service, db, users, _ = forum
    def fail(*args):
        raise sqlite3.OperationalError("injected write fault")
    monkeypatch.setattr(service.repository, "create_post", fail)
    with pytest.raises(sqlite3.OperationalError, match="injected"):
        service.create_topic(users["Alice"].uuid, "general", "No partial topic", "Body")
    assert db._conn.execute("SELECT COUNT(*) FROM forum_topics").fetchone()[0] == 0


def test_account_deletion_anonymizes_authorship_erases_personal_state_and_keeps_discussion(forum):
    service, db, users, _ = forum
    alice, bob, mod = (users[name].uuid for name in ("Alice", "Bob", "Moderator"))
    topic, post = service.create_topic(alice, "general", "Retained topic", "Public content")
    service.reply(bob, topic, "Retained reply")
    service.bookmark(alice, topic, True)
    service.post(alice, post, mark_read=True)
    service.moderate(mod, topic, "pinned", True)
    assert db.delete_user("Alice")
    assert service.topic(bob, topic).author_uuid is None
    assert service.topic(bob, topic).author_name == ""
    assert service.post(bob, post).author_name == ""
    for table in ("forum_read_positions", "forum_bookmarks"):
        assert db._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert service.posts(bob, topic).total == 2
    assert db.delete_user("Moderator")
    assert db._conn.execute("SELECT actor_uuid FROM forum_moderation_events").fetchone()[0] is None
    assert not db._conn.execute("PRAGMA foreign_key_check").fetchall()


def test_sql_pagination_is_bounded_and_resume_respects_visible_posts(forum):
    service, db, users, clock = forum
    alice, bob = users["Alice"].uuid, users["Bob"].uuid
    for index in range(18):
        clock[0] += 61
        topic, post = service.create_topic(alice, "general", f"Topic {index}", f"Body {index}")
    assert len(service.topics(bob).items) == 15
    assert len(service.topics(bob, page=2).items) == 3
    assert service.topics(bob, page=900).page == 2
    for index in range(10):
        clock[0] += 61
        service.reply(alice, topic, f"Message {index}")
    page = service.posts(bob, topic)
    assert len(page.items) == 8 and page.total_pages == 2
    service.post(bob, page.items[-1].id, mark_read=True)
    assert service.repository.post_page(bob, topic, service.repository.resume_post(bob, topic)) == 2


def test_many_short_lines_cannot_create_an_unbounded_reading_menu():
    text = "a\n" * 4000
    chunks = reading_chunks(text)
    assert len(chunks) <= 32
    assert max(map(len, chunks)) <= 500
    assert " ".join(" ".join(chunks).split()) == " ".join(text.split())


def test_search_accepts_valid_text_whose_unicode_normalization_expands(forum):
    service, _, users, _ = forum
    query = "ﬃ" * 100
    service.create_topic(users["Alice"].uuid, "general", "Ligatures", query)
    assert service.topics(users["Bob"].uuid, view="search", query=query).total == 1
