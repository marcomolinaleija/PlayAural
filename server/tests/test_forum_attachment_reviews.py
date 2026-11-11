"""Review requires publish consent and never grants global staff private access."""

import hashlib
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from ..forum.media_processing import ProcessedMedia
from ..forum.composer import ForumComposer
from ..forum.models import Draft, ForumError
from ..forum.polls import PollConfig
from ..forum.repository import ForumRepository
from ..forum.service import ForumService
from ..persistence.database import Database


@pytest.fixture
def forum(tmp_path):
    db = Database(str(tmp_path / 'forum.db'))
    db.connect()
    users = {}
    for name in ('Owner', 'Participant', 'Moderator'):
        users[name] = db.create_user(name, 'hash').uuid
        db.approve_user(name)
    db.update_user_trust_level('Moderator', 2)
    service = ForumService(ForumRepository(db), clock=lambda: 1800000000)
    service.attachments.require_approval = True
    yield service, db, users, tmp_path
    db.close()


def ready(forum, owner, *, topic_id=0, private=False):
    service, _, _, tmp_path = forum
    row = service.attachments.reserve(owner, 'notes.txt', 4, topic_id=topic_id, private=private)
    service.attachments.processing(owner, row['id'])
    service.attachments.complete(owner, row['id'], ProcessedMedia(tmp_path / 'source', 'text/plain', 'file', '.txt', 4, hashlib.sha256(b'test').hexdigest()))
    return row['id']


def test_staff_cannot_read_or_review_a_draft_file_before_publish_consent(forum):
    service, db, users, _ = forum
    attachment = ready(forum, users['Owner'])
    assert service.attachments.get(users['Owner'], attachment)['approval'] == 'unsubmitted'
    assert service.attachment_reviews.pending(users['Moderator']).total == 0
    with pytest.raises(ForumError):
        service.attachments.get(users['Moderator'], attachment)
    with pytest.raises(ForumError):
        service.attachment_reviews.review(users['Moderator'], attachment, approve=True)
    with pytest.raises(ForumError, match='forum-error-media-not-ready'):
        service.create_topic(users['Owner'], 'general', 'Not approved', 'Body', attachment_ids=(attachment,))
    assert not db._conn.execute('SELECT 1 FROM forum_posts').fetchone()
    assert service.attachment_reviews.request(users['Owner'], (attachment,))
    assert service.attachment_reviews.pending(users['Moderator']).items[0]['id'] == attachment
    assert service.attachments.get(users['Moderator'], attachment)['approval'] == 'pending'
    service.attachment_reviews.review(users['Moderator'], attachment, approve=True)
    assert not service.attachment_reviews.request(users['Owner'], (attachment,))
    _, post = service.create_topic(users['Owner'], 'general', 'Approved', 'Body', attachment_ids=(attachment,))
    assert service.attachments.get(users['Participant'], attachment)['post_id'] == post
    assert db._conn.execute('SELECT decision FROM forum_attachment_reviews').fetchone()[0] == 'approved'


def test_rejection_preserves_owner_preview_and_role_changes_are_rechecked(forum):
    service, db, users, _ = forum
    attachment = ready(forum, users['Owner'])
    service.attachment_reviews.request(users['Owner'], (attachment,))
    db.update_user_trust_level('Moderator', 1)
    with pytest.raises(ForumError):
        service.attachment_reviews.review(users['Moderator'], attachment, approve=True)
    db.update_user_trust_level('Moderator', 2)
    service.attachment_reviews.review(users['Moderator'], attachment, approve=False)
    assert service.attachments.get(users['Owner'], attachment)['approval'] == 'rejected'
    with pytest.raises(ForumError):
        service.attachments.get(users['Moderator'], attachment)
    with pytest.raises(ForumError, match='forum-error-media-not-ready'):
        service.attachment_reviews.request(users['Owner'], (attachment,))


def test_incomplete_poll_keeps_files_unsubmitted_when_publish_cannot_succeed(forum):
    service, db, users, _ = forum
    attachment = ready(forum, users['Owner'])
    draft = Draft('topic', category_id='general', title='Vote', body='Pick a game',
                  poll=asdict(PollConfig('', ('One answer',))), attachment_ids=(attachment,))
    composer = ForumComposer(None, service, None)
    with pytest.raises(ForumError, match='forum-error-poll-options'):
        composer.publish(SimpleNamespace(uuid=users['Owner']), draft)
    assert service.attachments.get(users['Owner'], attachment)['approval'] == 'unsubmitted'
    assert service.attachment_reviews.pending(users['Moderator']).total == 0
    assert not db._conn.execute('SELECT 1 FROM forum_posts').fetchone()


def test_private_file_is_reviewed_by_current_group_owner_and_never_by_uninvited_staff(forum):
    service, _, users, _ = forum
    topic, _ = service.conversations.create(users['Owner'], 'Private', 'Body', (users['Participant'],))
    invite = service.conversations.invitations(users['Participant'])[0]['id']
    service.conversations.respond(users['Participant'], invite, accept=True)
    attachment = ready(forum, users['Participant'], topic_id=topic)
    service.attachment_reviews.request(users['Participant'], (attachment,))
    assert service.attachment_reviews.pending(users['Moderator']).total == 0
    with pytest.raises(ForumError):
        service.attachments.get(users['Moderator'], attachment)
    assert service.attachment_reviews.pending(users['Owner'], topic_id=topic).items[0]['id'] == attachment
    assert service.attachments.get(users['Owner'], attachment)['approval'] == 'pending'
    service.attachment_reviews.review(users['Owner'], attachment, approve=True)
    service.reply(users['Participant'], topic, 'A file', attachment_ids=(attachment,))
    assert service.attachments.get(users['Owner'], attachment)['published']


def test_group_owner_and_moderators_can_publish_own_files_without_self_review(forum):
    service, _, users, _ = forum
    moderator_file = ready(forum, users['Moderator'])
    private_file = ready(forum, users['Owner'], private=True)
    assert service.attachments.get(users['Moderator'], moderator_file)['approval'] == 'approved'
    assert service.attachments.get(users['Owner'], private_file)['approval'] == 'approved'
    with pytest.raises(ForumError, match='forum-error-media-owner'):
        service.create_topic(users['Owner'], 'general', 'Public', 'Body', attachment_ids=(private_file,))


def test_leaving_cancels_private_unpublished_uploads_and_revokes_review_access(forum):
    service, db, users, _ = forum
    topic, _ = service.conversations.create(users['Owner'], 'Private', 'Body', (users['Participant'],))
    invite = service.conversations.invitations(users['Participant'])[0]['id']
    service.conversations.respond(users['Participant'], invite, accept=True)
    attachment = ready(forum, users['Participant'], topic_id=topic)
    service.attachment_reviews.request(users['Participant'], (attachment,))
    service.conversations.remove(users['Owner'], topic, users['Participant'])
    assert service.attachment_reviews.pending(users['Owner'], topic_id=topic).total == 0
    with pytest.raises(ForumError):
        service.attachments.get(users['Owner'], attachment)
    assert db._conn.execute('SELECT state FROM forum_attachments WHERE id = ?', (attachment,)).fetchone()[0] == 'retired'
