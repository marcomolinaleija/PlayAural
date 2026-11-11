"""Actual media normalization, storage adapters and post-based file access."""

from io import BytesIO
from pathlib import Path
import shutil
import subprocess
import wave

from PIL import Image
import pytest

from ..forum.media_processing import MediaProcessor
from ..forum.models import ForumError
from ..forum.repository import ForumRepository
from ..forum.service import ForumService
from ..forum.storage import LocalObjectStorage, S3ObjectStorage
from ..persistence.database import Database


@pytest.fixture
def forum(tmp_path):
    db = Database(str(tmp_path / 'forum.db'))
    db.connect()
    users = {}
    for name in ('Alice', 'Bob', 'Moderator'):
        users[name] = db.create_user(name, 'hash', locale='es').uuid
        db.approve_user(name)
    db.update_user_trust_level('Moderator', 2)
    clock = [1_800_000_000]
    service = ForumService(ForumRepository(db), clock=lambda: clock[0])
    yield service, db, users, clock
    db.close()


def ready_attachment(forum, tmp_path):
    service, _, users, _ = forum
    source = tmp_path / 'source.txt'
    source.write_text('An attached text file.', encoding='utf-8')
    reservation = service.attachments.reserve(users['Alice'], 'source.txt', source.stat().st_size)
    service.attachments.processing(users['Alice'], reservation['id'])
    media = MediaProcessor().process(source, tmp_path / reservation['id'])
    storage = LocalObjectStorage(tmp_path / 'objects')
    storage.put(reservation['object_key'], media.path, media.mime)
    service.attachments.complete(users['Alice'], reservation['id'], media)
    return reservation['id'], storage


def test_local_objects_are_private_opaque_immutable_and_path_bounded(tmp_path):
    storage = LocalObjectStorage(tmp_path / 'objects')
    source = tmp_path / 'source'
    source.write_bytes(b'content')
    key = 'a' * 32 + '/content'
    storage.put(key, source, 'application/octet-stream')
    with storage.open(key, start=2) as stream:
        assert stream.read() == b'ntent'
    source.write_bytes(b'replacement')
    with pytest.raises(FileExistsError):
        storage.put(key, source, 'application/octet-stream')
    for invalid in ('../source', '/source', 'a' * 32 + '/../../source', 'a' * 32 + '/content.html'):
        with pytest.raises(ValueError):
            storage.path(invalid)
    assert storage.path(key).read_bytes() == b'content'
    storage.delete(key)
    assert not storage.path(key).exists()


def test_s3_adapter_never_publishes_objects_and_supports_byte_ranges(tmp_path):
    calls = []
    class Client:
        def put_object(self, **kwargs):
            calls.append(('put', {**kwargs, 'Body': kwargs['Body'].read()}))
        def get_object(self, **kwargs):
            calls.append(('get', kwargs))
            return {'Body': BytesIO(b'partial')}
        def delete_object(self, **kwargs):
            calls.append(('delete', kwargs))
    source = tmp_path / 'source'
    source.write_bytes(b'private')
    storage = S3ObjectStorage('private-forum', client=Client())
    key = 'b' * 32 + '/content'
    storage.put(key, source, 'text/plain')
    with storage.open(key, start=2, end=5) as stream:
        assert stream.read() == b'partial'
    storage.delete(key)
    assert calls[0][1]['Body'] == b'private'
    assert 'ACL' not in calls[0][1]
    assert calls[1][1]['Range'] == 'bytes=2-5'
    assert all(call[1]['Bucket'] == 'private-forum' for call in calls)


def test_images_are_decoded_reencoded_strip_metadata_and_get_thumbnails(tmp_path):
    source = tmp_path / 'fake.mp3'
    image = Image.new('RGB', (700, 200), 'blue')
    exif = Image.Exif()
    exif[270] = 'Private metadata'
    image.save(source, format='JPEG', exif=exif)
    result = MediaProcessor().process(source, tmp_path / 'prepared')
    assert result.kind == 'image' and result.mime == 'image/jpeg'
    assert (result.width, result.height) == (700, 200)
    assert result.thumbnail.exists() and len(result.sha256) == 64
    with Image.open(result.path) as normalized:
        assert not normalized.getexif()
    with Image.open(result.thumbnail) as thumbnail:
        assert thumbnail.width <= 480 and thumbnail.height <= 480


def test_image_transparency_is_preserved_and_corruption_rejected(tmp_path):
    source = tmp_path / 'transparent.png'
    Image.new('RGBA', (32, 32), (0, 0, 0, 0)).save(source)
    result = MediaProcessor().process(source, tmp_path / 'prepared')
    assert result.mime == 'image/png'
    with Image.open(result.path) as image:
        assert image.getpixel((0, 0))[3] == 0
    source.write_bytes(b'\x89PNG\r\n\x1a\ncorrupt')
    with pytest.raises(ForumError, match='forum-error-media-type'):
        MediaProcessor().process(source, tmp_path / 'corrupt')


def test_text_markup_is_download_only_and_unknown_binary_is_rejected(tmp_path):
    source = tmp_path / 'test.svg'
    source.write_text('<script>alert(1)</script>', encoding='utf-8')
    result = MediaProcessor().process(source, tmp_path / 'prepared')
    assert result.kind == 'file' and result.mime == 'text/plain' and result.suffix == '.txt'
    source.write_bytes(b'\x00executable data')
    with pytest.raises(ForumError, match='forum-error-media-type'):
        MediaProcessor().process(source, tmp_path / 'invalid')


def test_real_audio_is_normalized_to_mp3_and_requires_local_processing_tools(tmp_path):
    source = tmp_path / 'audio.wav'
    with wave.open(str(source), 'wb') as stream:
        stream.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        stream.writeframes(b'\x00\x00' * 8000)
    processor = MediaProcessor()
    if not processor.ffmpeg or not processor.ffprobe:
        pytest.skip('FFmpeg and FFprobe integration requires the deployment media tools')
    result = processor.process(source, tmp_path / 'prepared')
    assert result.kind == 'audio' and result.mime == 'audio/mpeg'
    assert 0.4 <= result.duration <= 0.6 and result.size > 0
    processor.ffmpeg = None
    with pytest.raises(ForumError, match='forum-error-media-unavailable'):
        processor.process(source, tmp_path / 'unavailable')


def test_real_video_is_playable_mp4_with_a_thumbnail(tmp_path):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg and FFprobe integration requires the deployment media tools')
    source = tmp_path / 'video.webm'
    subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i',
                    'color=c=blue:s=160x120:d=0.5', '-c:v', 'libvpx', str(source)], check=True,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), stdin=subprocess.DEVNULL)
    result = MediaProcessor().process(source, tmp_path / 'prepared')
    assert result.kind == 'video' and result.mime == 'video/mp4'
    assert result.thumbnail.exists() and (result.width, result.height) == (160, 120)


def test_embedded_text_captions_survive_normalization_and_have_a_webvtt_variant(tmp_path):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg and FFprobe integration requires the deployment media tools')
    subtitles = tmp_path / 'captions.srt'
    subtitles.write_text('1\n00:00:00,000 --> 00:00:01,000\nWelcome to PlayAural\n', encoding='utf-8')
    source = tmp_path / 'captioned.mkv'
    subprocess.run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i',
                    'color=c=blue:s=160x120:d=1', '-i', str(subtitles), '-c:v', 'libx264', '-c:s', 'srt', str(source)],
                   check=True, stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    result = MediaProcessor().process(source, tmp_path / 'prepared')
    assert result.captions and result.captions.read_text(encoding='utf-8').startswith('WEBVTT')
    assert 'Welcome to PlayAural' in result.captions.read_text(encoding='utf-8')
    inspection = subprocess.run([shutil.which('ffprobe'), '-v', 'error', '-select_streams', 's', '-show_entries',
                                 'stream=codec_name', '-of', 'csv=p=0', str(result.path)], check=True, capture_output=True,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert b'mov_text' in inspection.stdout


def test_unpublished_file_is_owner_only_and_cannot_be_stolen_or_reused(forum, tmp_path):
    service, db, users, _ = forum
    attachment, _ = ready_attachment(forum, tmp_path)
    assert service.attachments.get(users['Alice'], attachment)['kind'] == 'file'
    with pytest.raises(ForumError):
        service.attachments.get(users['Bob'], attachment)
    with pytest.raises(ForumError, match='forum-error-media-owner'):
        service.create_topic(users['Bob'], 'general', 'Stealing file', 'Body', attachment_ids=(attachment,))
    assert not db._conn.execute('SELECT 1 FROM forum_topics').fetchone()
    _, post = service.create_topic(users['Alice'], 'general', 'Public file', 'Body', attachment_ids=(attachment,))
    assert service.attachments.for_post(users['Bob'], post)[0]['id'] == attachment
    with pytest.raises(ForumError, match='forum-error-media-owner'):
        service.create_topic(users['Alice'], 'general', 'Reusing file', 'Another body', attachment_ids=(attachment,))
    assert db._conn.execute('SELECT COUNT(*) FROM forum_posts').fetchone()[0] == 1


def test_file_access_tracks_hidden_posts_blocks_and_current_private_membership(forum, tmp_path):
    service, db, users, _ = forum
    attachment, _ = ready_attachment(forum, tmp_path)
    topic, post = service.conversations.create(users['Alice'], 'Private file', 'Body', (users['Bob'],), attachment_ids=(attachment,))
    with pytest.raises(ForumError):
        service.attachments.get(users['Bob'], attachment)
    with pytest.raises(ForumError):
        service.attachments.get(users['Moderator'], attachment)
    invite = service.conversations.invitations(users['Bob'])[0]['id']
    service.conversations.respond(users['Bob'], invite, accept=True)
    assert service.attachments.get(users['Bob'], attachment)['post_id'] == post
    service.moderate(users['Alice'], topic, 'hidden', True, post)
    with pytest.raises(ForumError):
        service.attachments.get(users['Alice'], attachment)
    service.moderate(users['Alice'], topic, 'hidden', False, post)
    db.block_user(users['Bob'], users['Alice'])
    with pytest.raises(ForumError):
        service.attachments.get(users['Bob'], attachment)
    service.conversations.leave(users['Bob'], topic)
    with pytest.raises(ForumError):
        service.attachments.get(users['Bob'], attachment)
    service.conversations.leave(users['Alice'], topic)
    # Deleting the post cannot reclassify its file as an owner's draft.
    with pytest.raises(ForumError):
        service.attachments.get(users['Alice'], attachment)
    assert service.attachments.expired() == []


def test_failed_publication_keeps_ready_upload_and_expiry_never_collects_published_files(forum, tmp_path):
    service, db, users, clock = forum
    attachment, storage = ready_attachment(forum, tmp_path)
    pending = service.attachments.reserve(users['Alice'], 'not-ready.jpg', 100)
    with pytest.raises(ForumError, match='forum-error-media-not-ready'):
        service.create_topic(users['Alice'], 'general', 'Not ready', 'Body', attachment_ids=(attachment, pending['id']))
    assert not service.attachments.get(users['Alice'], attachment)['published']
    assert not db._conn.execute('SELECT 1 FROM forum_posts').fetchone()
    _, post = service.create_topic(users['Alice'], 'general', 'Ready', 'Body', attachment_ids=(attachment,))
    clock[0] += 86401
    assert [row['id'] for row in service.attachments.expired()] == [pending['id']]
    assert service.attachments.get(users['Alice'], attachment)['published']
    db.delete_user('Alice')
    assert service.attachments.get(users['Bob'], attachment)['post_id'] == post
    assert storage.path(service.attachments.get(users['Bob'], attachment)['object_key']).exists()
