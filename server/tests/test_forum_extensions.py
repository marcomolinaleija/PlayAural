"""Private admission, non-disclosure and atomic poll publication/ballots."""

import sqlite3

import pytest

from ..forum.models import ForumError
from ..forum.polls import PollConfig
from ..forum.repository import ForumRepository
from ..forum.service import ForumService
from ..persistence.database import Database


@pytest.fixture
def forum(tmp_path):
    db = Database(str(tmp_path / 'forum.db'))
    db.connect()
    users = {}
    for name in ('Alice', 'Bob', 'Carol', 'Moderator'):
        users[name] = db.create_user(name, 'hash', locale='es').uuid
        db.approve_user(name)
    db.update_user_trust_level('Moderator', 2)
    clock = [1_800_000_000]
    service = ForumService(ForumRepository(db), clock=lambda: clock[0])
    yield service, db, users, clock
    db.close()


def private_pair(forum):
    service, _, users, _ = forum
    topic, post = service.conversations.create(users['Alice'], 'Private title', 'Private secretword', (users['Bob'],))
    invitation = service.conversations.invitations(users['Bob'])[0]['id']
    return topic, post, invitation


def test_private_metadata_and_content_require_accepted_membership_even_for_admin(forum):
    service, db, users, _ = forum
    topic, post, invitation = private_pair(forum)
    for viewer in users.values():
        assert service.topics(viewer).total == 0
        assert service.topics(viewer, view='search', query='secretword').total == 0
        assert all(category.topic_count == 0 for category in service.categories(viewer))
        if viewer == users['Alice']:
            continue
        for read in (lambda: service.topic(viewer, topic), lambda: service.post(viewer, post),
                     lambda: service.reply(viewer, topic, 'Forged private reply'),
                     lambda: service.bookmark(viewer, topic, True),
                     lambda: service.conversations.members(viewer, topic)):
            with pytest.raises(ForumError, match='forum-error-missing'):
                read()
        assert service.repository.posts(viewer, topic).total == 0
        assert service.repository.resume_post(viewer, topic) == 0
        assert service.topics(viewer, view='private').total == 0
    with pytest.raises(ForumError):
        service.conversations.respond(users['Carol'], invitation, accept=True)
    service.conversations.respond(users['Bob'], invitation, accept=True)
    assert service.post(users['Bob'], post).body == 'Private secretword'
    assert service.topics(users['Bob'], view='private').items[0].is_private
    assert service.conversations.invitations(users['Bob']) == []
    with pytest.raises(ForumError):
        service.conversations.respond(users['Bob'], invitation, accept=True)
    db.close()
    db.connect()
    assert service.post(users['Bob'], post).topic_id == topic


@pytest.mark.parametrize('departure', ['leave', 'remove'])
def test_personal_saved_includes_private_discussions_only_while_admitted(forum, departure):
    service, db, users, _ = forum
    topic, _, invitation = private_pair(forum)
    public, _ = service.create_topic(users['Carol'], 'general', 'Public title', 'Public message')
    service.conversations.respond(users['Bob'], invitation, accept=True)
    service.bookmark(users['Bob'], topic, True)
    service.bookmark(users['Bob'], public, True)
    saved = service.topics(users['Bob'], view='saved')
    assert {item.id: bool(item.is_private) for item in saved.items} == {topic: True, public: False}
    for outsider in ('Carol', 'Moderator'):
        # A stale or forged bookmark must never grant admission.
        db._conn.execute('INSERT INTO forum_bookmarks VALUES (?, ?)', (users[outsider], topic))
        assert service.topics(users[outsider], view='saved').total == 0
    for view in ('recent', 'unread', 'search', 'category'):
        assert topic not in {item.id for item in service.topics(
            users['Bob'], view=view, query='Private', category_id='general').items}
    if departure == 'leave':
        service.conversations.leave(users['Bob'], topic)
    else:
        service.conversations.remove(users['Alice'], topic, users['Bob'])
    assert [item.id for item in service.topics(users['Bob'], view='saved').items] == [public]
    assert not db._conn.execute('SELECT 1 FROM forum_bookmarks WHERE user_uuid = ? AND topic_id = ?',
                               (users['Bob'], topic)).fetchone()


def test_admission_rechecks_blocks_expiration_and_moderation(forum):
    service, db, users, clock = forum
    topic, _, invitation = private_pair(forum)
    db.block_user(users['Alice'], users['Bob'])
    assert service.conversations.invitations(users['Bob']) == []
    with pytest.raises(ForumError, match='forum-error-private-contact'):
        service.conversations.respond(users['Bob'], invitation, accept=True)
    assert service.topics(users['Bob'], view='private').total == 0
    with pytest.raises(ForumError):
        service.conversations.create(users['Bob'], 'Blocked', 'Blocked body', (users['Alice'],))
    assert db._conn.execute('SELECT COUNT(*) FROM forum_topics').fetchone()[0] == 1
    clock[0] += 8 * 86400
    with pytest.raises(ForumError, match='forum-error-missing'):
        service.conversations.respond(users['Bob'], invitation, accept=True)


def test_group_block_filters_pair_messages_without_evicting_other_members(forum):
    service, db, users, _ = forum
    topic, first, invitation = private_pair(forum)
    service.conversations.respond(users['Bob'], invitation, accept=True)
    invite = service.conversations.invite(users['Alice'], topic, users['Carol'])
    service.conversations.respond(users['Carol'], invite, accept=True)
    bobs_post = service.reply(users['Bob'], topic, 'Bob secret')
    db.block_user(users['Alice'], users['Bob'])
    assert len(service.conversations.members(users['Bob'], topic)) == 3
    assert service.topic(users['Bob'], topic).is_private
    with pytest.raises(ForumError):
        service.post(users['Bob'], first)
    assert service.post(users['Carol'], first).body
    assert service.post(users['Carol'], bobs_post).body
    assert service.posts(users['Bob'], topic).total == 1


def test_leave_revokes_access_transfers_owner_and_last_member_deletes_private_topic(forum):
    service, db, users, _ = forum
    topic, post, invitation = private_pair(forum)
    service.conversations.respond(users['Bob'], invitation, accept=True)
    pending = service.conversations.invite(users['Alice'], topic, users['Carol'])
    service.conversations.leave(users['Alice'], topic)
    assert service.conversations.owner(users['Bob'], topic)
    with pytest.raises(ForumError):
        service.post(users['Alice'], post)
    with pytest.raises(ForumError):
        service.conversations.respond(users['Carol'], pending, accept=True)
    assert service.topics(users['Carol']).total == 0
    service.conversations.leave(users['Bob'], topic)
    assert db._conn.execute('SELECT COUNT(*) FROM forum_topics').fetchone()[0] == 0
    assert not db._conn.execute('PRAGMA foreign_key_check').fetchall()


def test_account_deletion_preserves_private_acl_and_transfers_owner(forum):
    service, db, users, _ = forum
    topic, post, invitation = private_pair(forum)
    service.conversations.respond(users['Bob'], invitation, accept=True)
    db.delete_user('Alice')
    assert service.conversations.owner(users['Bob'], topic)
    assert service.post(users['Bob'], post).author_uuid is None
    with pytest.raises(ForumError):
        service.post(users['Moderator'], post)
    db.delete_user('Bob')
    assert db._conn.execute('SELECT COUNT(*) FROM forum_topics').fetchone()[0] == 0


def test_private_group_owner_can_hide_but_admin_status_does_not_grant_access_or_edit(forum):
    service, _, users, _ = forum
    topic, first, invitation = private_pair(forum)
    service.conversations.respond(users['Bob'], invitation, accept=True)
    post = service.reply(users['Bob'], topic, 'A reply')
    service.moderate(users['Alice'], topic, 'hidden', True, post)
    assert service.post(users['Bob'], post).hidden
    invite = service.conversations.invite(users['Alice'], topic, users['Moderator'])
    service.conversations.respond(users['Moderator'], invite, accept=True)
    assert not service.can_edit(users['Moderator'], service.post(users['Moderator'], first))
    with pytest.raises(ForumError, match='forum-error-moderator'):
        service.moderate(users['Moderator'], topic, 'closed', True)


def make_poll(forum, **kwargs):
    service, _, users, _ = forum
    return service.create_topic(users['Alice'], 'ideas', 'Poll topic', 'Discuss this choice',
                                poll=PollConfig('Choose a game', ('Chess', 'Pig', 'Uno'), **kwargs))


def test_poll_publication_is_atomic_and_validates_options(forum):
    service, db, users, _ = forum
    for config in (PollConfig('Question', ('One',)), PollConfig('Question', ('Same', 'SAME')),
                   PollConfig('Question', ('A', 'B'), closes_at=0)):
        with pytest.raises(ForumError):
            service.create_topic(users['Alice'], 'ideas', 'Invalid', 'Body', poll=config)
        assert db._conn.execute('SELECT COUNT(*) FROM forum_topics').fetchone()[0] == 0


def test_ballot_replaces_atomically_and_hidden_results_never_reach_client(forum, monkeypatch):
    service, db, users, _ = forum
    _, post = make_poll(forum)
    poll = service.polls.get(users['Bob'], post)
    options = [option['id'] for option in poll['options']]
    assert not poll['results_visible'] and 'voters' not in poll
    assert all('votes' not in option for option in poll['options'])
    with pytest.raises(ForumError):
        service.polls.vote(users['Bob'], post, options[:2])
    with pytest.raises(ForumError):
        service.polls.vote(users['Bob'], post, [True])
    service.polls.vote(users['Bob'], post, [options[0]])
    service.polls.vote(users['Bob'], post, [options[1]])
    poll = service.polls.get(users['Bob'], post)
    assert poll['selected'] == (options[1],) and poll['voters'] == 1
    assert [option['votes'] for option in poll['options']] == [0, 1, 0]
    assert not service.polls.get(users['Carol'], post)['results_visible']
    # An invalid replacement cannot erase the existing ballot.
    with pytest.raises(ForumError):
        service.polls.vote(users['Bob'], post, [999999])
    assert service.polls.get(users['Bob'], post)['selected'] == (options[1],)
    service.polls.vote(users['Bob'], post, [])
    assert not service.polls.get(users['Bob'], post)['results_visible']
    # Withdrawing the last vote cannot unlock question/option edits.
    with pytest.raises(ForumError, match='forum-error-poll-started'):
        service.polls.edit(users['Alice'], post, PollConfig('Changed', ('A', 'B')))
    db.close()
    db.connect()
    assert service.polls.get(users['Alice'], post)['started']


def test_multiple_fixed_votes_expiry_and_closed_results(forum):
    service, _, users, clock = forum
    _, post = make_poll(forum, multiple=True, change_vote=False, results='after_close', closes_at=clock[0] + 60)
    options = [option['id'] for option in service.polls.get(users['Bob'], post)['options']]
    service.polls.vote(users['Bob'], post, options[:2])
    service.polls.vote(users['Bob'], post, options[:2])  # Retry is idempotent.
    assert not service.polls.get(users['Bob'], post)['results_visible']
    with pytest.raises(ForumError, match='forum-error-poll-fixed-vote'):
        service.polls.vote(users['Bob'], post, [options[2]])
    clock[0] += 60
    poll = service.polls.get(users['Carol'], post)
    assert poll['closed'] and poll['voters'] == 1
    assert [option['votes'] for option in poll['options']] == [1, 1, 0]
    with pytest.raises(ForumError, match='forum-error-poll-closed'):
        service.polls.vote(users['Carol'], post, [options[0]])


def test_private_poll_uses_membership_and_hidden_post_authorization(forum):
    service, _, users, _ = forum
    topic, post = service.conversations.create(users['Alice'], 'Private poll', 'Body', (users['Bob'],),
                                              poll=PollConfig('Question', ('A', 'B')))
    option = service.polls.get(users['Alice'], post)['options'][0]['id']
    for viewer in (users['Bob'], users['Moderator']):
        with pytest.raises(ForumError):
            service.polls.vote(viewer, post, [option])
        with pytest.raises(ForumError):
            service.polls.get(viewer, post)
    invite = service.conversations.invitations(users['Bob'])[0]['id']
    service.conversations.respond(users['Bob'], invite, accept=True)
    service.polls.vote(users['Bob'], post, [option])
    service.moderate(users['Alice'], topic, 'hidden', True, post)
    with pytest.raises(ForumError):
        service.polls.get(users['Bob'], post)
    service.conversations.leave(users['Bob'], topic)
    with pytest.raises(ForumError):
        service.polls.vote(users['Bob'], post, [option])


def test_poll_choices_cannot_belong_to_another_poll_and_user_deletion_erases_ballots(forum):
    service, db, users, clock = forum
    _, first = make_poll(forum, results='always')
    clock[0] += 61
    _, second = make_poll(forum, results='always')
    other_option = service.polls.get(users['Bob'], second)['options'][0]['id']
    with pytest.raises(ForumError):
        service.polls.vote(users['Bob'], first, [other_option])
    with pytest.raises(sqlite3.IntegrityError):
        with service.repository.atomic():
            db._conn.execute('INSERT INTO forum_poll_votes VALUES (?, ?, ?, ?)', (first, other_option, users['Bob'], clock[0]))
    service.polls.vote(users['Bob'], second, [other_option])
    db.delete_user('Bob')
    assert service.polls.get(users['Alice'], second)['voters'] == 0
    assert service.polls.get(users['Alice'], second)['started']
