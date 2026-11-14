"""Whole backups include object bytes; expiry never destroys published media."""

import asyncio
import hashlib
from pathlib import Path
import sqlite3
import zipfile

import pytest

from ..core.server import Server
from ..forum.media_http import ForumMediaHTTP
from ..forum.media_processing import MediaProcessor
from ..forum.models import ForumError


@pytest.fixture
def media(tmp_path):
    server = Server(db_path=str(tmp_path / 'forum.db'), database_backup_dir=tmp_path / 'backups',
                    forum_media_dir=tmp_path / 'media')
    server.db.connect()
    user = server.db.create_user('Owner', 'hash', locale='es')
    server.db.approve_user(user.username)
    other = server.db.create_user('Participant', 'hash', locale='es')
    server.db.approve_user(other.username)
    transport = ForumMediaHTTP(server, base_url='http://127.0.0.1:8001', directory=tmp_path / 'media')
    server.forum_manager.media = transport
    clock = [1800000000]
    server.forum_manager.service.clock = lambda: clock[0]
    yield server, transport, user.uuid, other.uuid, clock
    server.db.close()


def prepare(media, tmp_path, text='Private object bytes'):
    server, transport, owner, _, _ = media
    service = server.forum_manager.service
    source = tmp_path / 'source.txt'
    source.write_text(text, encoding='utf-8')
    row = service.attachments.reserve(owner, 'notes.txt', source.stat().st_size)
    service.attachments.processing(owner, row['id'])
    processed = MediaProcessor().process(source, tmp_path / row['id'])
    transport.storage.put(row['object_key'], processed.path, processed.mime)
    service.attachments.complete(owner, row['id'], processed)
    return row


async def test_verified_manual_backup_is_standalone_and_preserves_private_acl(media, tmp_path):
    server, transport, owner, participant, _ = media
    service = server.forum_manager.service
    row = prepare(media, tmp_path)
    topic, _ = service.conversations.create(owner, 'Private file', 'Body', (participant,), attachment_ids=(row['id'],))
    invite = service.conversations.invitations(participant)[0]['id']
    service.conversations.respond(participant, invite, accept=True)
    backup = await server.maintenance_manager.back_up_database(requested_by='Owner')
    assert backup.path.exists() and backup.archive_path.exists() and backup.archive_size_bytes > 0
    manifest = transport.backups.verify(backup.archive_path, backup.path)
    assert [item['key'] for item in manifest['objects']] == [row['object_key']]
    with zipfile.ZipFile(backup.archive_path) as archive:
        assert archive.read('objects/' + row['object_key']) == b'Private object bytes'
        restored = tmp_path / 'restored.sqlite3'
        restored.write_bytes(archive.read('database.sqlite3'))
    with sqlite3.connect(restored) as connection:
        assert connection.execute('SELECT COUNT(*) FROM forum_private_members WHERE topic_id = ?', (topic,)).fetchone()[0] == 2
    # Live deletion neither mutates the frozen snapshot nor collects its file.
    service.conversations.leave(owner, topic)
    service.conversations.leave(participant, topic)
    assert await transport.lifecycle.collect() == 0
    assert transport.backups.verify(backup.archive_path, backup.path) == manifest
    assert transport.storage.path(row['object_key']).exists()


@pytest.mark.parametrize('corrupt', [False, True])
async def test_disabling_media_http_keeps_complete_backups_required(media, tmp_path, corrupt):
    server, transport, owner, _, _ = media
    row = prepare(media, tmp_path)
    server.forum_manager.service.create_topic(owner, 'general', 'File', 'Body', attachment_ids=(row['id'],))
    server.forum_manager.media = None
    if corrupt:
        transport.storage.path(row['object_key']).write_bytes(b'corrupted')
        with pytest.raises(ValueError, match='checksum'):
            await server.maintenance_manager.back_up_database(requested_by='Owner')
        assert not list((tmp_path / 'backups').glob('*.forum.zip'))
    else:
        backup = await server.maintenance_manager.back_up_database(requested_by='Owner')
        manifest = transport.backups.verify(backup.archive_path, backup.path)
        assert manifest['objects'][0]['key'] == row['object_key']
    assert server.db._conn is not None and not server.maintenance_manager.is_active


async def test_corrupt_object_fails_backup_without_publishing_partial_archive_or_freezing_database(media, tmp_path):
    server, transport, owner, _, _ = media
    row = prepare(media, tmp_path)
    server.forum_manager.service.create_topic(owner, 'general', 'File', 'Body', attachment_ids=(row['id'],))
    transport.storage.path(row['object_key']).write_bytes(b'corrupted')
    with pytest.raises(ValueError, match='checksum'):
        await server.maintenance_manager.back_up_database(requested_by='Owner')
    assert server.db._conn is not None and not server.maintenance_manager.is_active
    assert not list((tmp_path / 'backups').glob('*.forum.zip'))
    assert not list((tmp_path / 'backups').glob('*.partial'))
    assert server.forum_manager.service.topics(owner).total == 1


async def test_expiry_retires_unpublished_files_and_keeps_published_objects_forever(media, tmp_path):
    server, transport, owner, _, clock = media
    published = prepare(media, tmp_path, 'Published')
    service = server.forum_manager.service
    service.create_topic(owner, 'general', 'Published file', 'Body', attachment_ids=(published['id'],))
    pending = prepare(media, tmp_path, 'Unpublished')
    assert await transport.lifecycle.collect() == 0
    clock[0] += 86401
    assert await transport.lifecycle.collect() == 1
    assert not transport.storage.path(pending['object_key']).exists()
    assert transport.storage.path(published['object_key']).exists()
    with pytest.raises(ForumError):
        service.attachments.get(owner, pending['id'])


async def test_restart_discards_interrupted_staging_without_touching_unknown_or_published_files(media, tmp_path):
    server, transport, owner, _, _ = media
    row = server.forum_manager.service.attachments.reserve(owner, 'interrupted.mp3', 10)
    server.forum_manager.service.attachments.processing(owner, row['id'])
    abandoned = transport.staging / 'upload-interrupted'
    abandoned.mkdir()
    (abandoned / 'source').write_bytes(b'partial')
    unknown = transport.staging / 'operator-notes.txt'
    unknown.write_text('Keep', encoding='utf-8')
    await transport.lifecycle.recover()
    assert not abandoned.exists() and unknown.exists()
    assert server.db._conn.execute('SELECT state FROM forum_attachments WHERE id = ?', (row['id'],)).fetchone()[0] == 'failed'


async def test_active_worker_objects_are_never_collected_mid_processing(media, tmp_path):
    _, transport, owner, _, clock = media
    row = prepare(media, tmp_path)
    transport.worker._active_ids.add(row['id'])
    clock[0] += 86401
    assert await transport.lifecycle.collect() == 0
    assert transport.storage.path(row['object_key']).exists()
    transport.worker._active_ids.remove(row['id'])
    assert await transport.lifecycle.collect() == 1


@pytest.mark.parametrize('operation,method', [('compact_database', 'compact_database'), ('clean_storage', 'clean_storage')])
@pytest.mark.parametrize('http_enabled', [False, True])
async def test_complete_safety_backup_is_required_before_storage_mutation(media, tmp_path, monkeypatch, operation, method, http_enabled):
    server, transport, owner, _, _ = media
    row = prepare(media, tmp_path)
    server.forum_manager.service.create_topic(owner, 'general', 'File', 'Body', attachment_ids=(row['id'],))
    transport.storage.path(row['object_key']).write_bytes(b'corrupted')
    if not http_enabled:
        server.forum_manager.media = None
    def forbidden(*args, **kwargs):
        pytest.fail('Storage mutation ran before its object backup was verified')
    monkeypatch.setattr(type(server.db), method, forbidden)
    with pytest.raises(ValueError, match='checksum'):
        await getattr(server.maintenance_manager, operation)(requested_by='Owner')
    assert server.db._conn is not None and server.forum_manager.service.topics(owner).total == 1


async def test_removing_participant_revokes_file_access_and_read_state_immediately(media, tmp_path):
    server, _, owner, participant, _ = media
    service = server.forum_manager.service
    row = prepare(media, tmp_path)
    topic, post = service.conversations.create(owner, 'Private file', 'Body', (participant,), attachment_ids=(row['id'],))
    invitation = service.conversations.invitations(participant)[0]['id']
    service.conversations.respond(participant, invitation, accept=True)
    service.post(participant, post, mark_read=True)
    service.bookmark(participant, topic, True)
    with pytest.raises(ForumError, match='forum-error-private-owner'):
        service.conversations.remove(participant, topic, owner)
    service.conversations.remove(owner, topic, participant)
    with pytest.raises(ForumError):
        service.attachments.get(participant, row['id'])
    assert server.db._conn.execute('SELECT COUNT(*) FROM forum_read_positions WHERE user_uuid = ?', (participant,)).fetchone()[0] == 0
    assert service.topic(owner, topic).post_count == 1
