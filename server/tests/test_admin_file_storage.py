"""Developer menus, persistent policy, HTTP enforcement and storage changes."""

import asyncio
from io import BytesIO
from types import SimpleNamespace
import threading

from aiohttp import ClientSession
import pytest

from ..administration.files import FILES_MENU, LIMITS_MENU, LIMIT_INPUT, STORAGE_MENU, STORAGE_CONFIRM
from ..core.server import Server
from ..forum.file_settings import MIB, SETTINGS_KEY, check_storage, probe_storage
from ..forum.models import Draft, ForumError
from ..forum.storage import LocalObjectStorage
from ..messages.localization import Localization
from .test_admin_navigation import _make_admin_server, _select, _menu_item_ids, _current_menu
from .test_forum_media_http import media_server, ready_file


@pytest.fixture
def admin_files(tmp_path, monkeypatch):
    monkeypatch.setenv('PLAYAURAL_FORUM_STORAGE', 'local')
    server, developer = _make_admin_server(tmp_path)
    server.db.create_user('Other Developer', 'hash', trust_level=3)
    server.db.approve_user('Other Developer')
    yield server, developer
    server.db.close()


async def open_files(server, user):
    await _select(server, user, 'main_menu', 'administration')
    await _select(server, user, 'admin_menu', 'admin_system')
    await _select(server, user, 'admin_system_menu', 'file_storage')
    assert _current_menu(server, user.username) == FILES_MENU


async def submit_limit(server, user, value, *, input_id=LIMIT_INPUT, cancelled=False):
    await server._handle_editbox(SimpleNamespace(username=user.username),
                                 {'type': 'editbox', 'input_id': input_id, 'text': value, 'cancelled': cancelled})


async def test_menu_limits_toggles_persist_and_back_restores_focus(admin_files):
    server, user = admin_files
    settings = server.forum_manager.service.files
    await open_files(server, user)
    assert 'status' in _menu_item_ids(user, FILES_MENU)
    assert next(row for row in user.get_current_menu_items(FILES_MENU) if row.id == 'status').read_only
    await _select(server, user, FILES_MENU, 'require_approval')
    await _select(server, user, FILES_MENU, 'uploads_enabled')
    assert settings.policy().require_approval and not settings.policy().uploads_enabled
    await _select(server, user, FILES_MENU, 'limits')
    await _select(server, user, LIMITS_MENU, 'max_file_mib')
    await submit_limit(server, user, '8', input_id='forged')
    assert settings.policy().max_file_mib == 128
    await submit_limit(server, user, '8')
    assert settings.policy().max_file_mib == 8
    assert _current_menu(server, user.username) == LIMITS_MENU
    await _select(server, user, LIMITS_MENU, 'pending_mib')
    await submit_limit(server, user, '4')  # Cannot be smaller than the file limit.
    assert settings.policy().pending_mib == 256
    assert LIMIT_INPUT in user.editboxes
    await submit_limit(server, user, '16')
    await _select(server, user, LIMITS_MENU, 'back')
    assert user.menus[FILES_MENU]['selection_id'] == 'limits'
    await _select(server, user, FILES_MENU, 'back')
    assert user.menus['admin_system_menu']['selection_id'] == 'file_storage'
    expected = settings.policy()
    server.db.close()
    restarted = Server(db_path=server.db.db_path)
    restarted.db.connect()
    try:
        restarted._load_persistent_server_settings()
        assert restarted.forum_manager.service.files.policy() == expected
    finally:
        restarted.db.close()


@pytest.mark.parametrize('level', [1, 2])
async def test_stale_developer_session_cannot_write_or_restore_settings(admin_files, level):
    server, user = admin_files
    await open_files(server, user)
    server.db.update_user_trust_level(user.username, level)
    expected = server.forum_manager.service.files.policy()
    await _select(server, user, FILES_MENU, 'uploads_enabled')
    assert server.forum_manager.service.files.policy() == expected
    server._restore_frame(user, {'menu': STORAGE_MENU}, [])
    assert _current_menu(server, user.username) not in {FILES_MENU, STORAGE_MENU}
    with pytest.raises(ForumError, match='dev-only-action'):
        server.forum_manager.service.files.update(user.uuid, expected=expected, uploads_enabled=False)


async def test_cancel_and_concurrent_limit_change_do_not_overwrite_settings(admin_files):
    server, user = admin_files
    settings = server.forum_manager.service.files
    await open_files(server, user)
    await _select(server, user, FILES_MENU, 'limits')
    await _select(server, user, LIMITS_MENU, 'max_file_mib')
    settings.update(user.uuid, expected=settings.policy(), max_file_mib=16)
    await submit_limit(server, user, '8')
    assert settings.policy().max_file_mib == 16
    await submit_limit(server, user, '', cancelled=True)
    assert _current_menu(server, user.username) == LIMITS_MENU
    assert LIMIT_INPUT not in user.editboxes


async def test_upload_limits_are_enforced_by_service_and_approval_persists(admin_files):
    server, user = admin_files
    service = server.forum_manager.service
    record = server.db.create_user('Uploader', 'hash')
    server.db.approve_user('Uploader')
    service.files.update(user.uuid, expected=service.files.policy(), max_file_mib=1, pending_mib=1,
                         require_approval=True)
    with pytest.raises(ForumError, match='forum-error-limite-carga'):
        service.attachments.reserve(record.uuid, 'too-large.txt', MIB + 1)
    row = service.attachments.reserve(record.uuid, 'one.txt', MIB)
    assert row['approval'] == 'unsubmitted'
    with pytest.raises(ForumError, match='forum-error-cuota-carga'):
        service.attachments.reserve(record.uuid, 'two.txt', 1)


async def test_disabled_uploads_preserve_published_http_downloads_and_drafts(media_server, tmp_path):
    server, media, users = media_server
    service = server.forum_manager.service
    user = users['Alice']
    server.db.update_user_trust_level('Alice', 3)
    attachment = await ready_file(server, media, user, tmp_path)
    category = service.categories(user.uuid)[0].id
    topic, post = service.create_topic(user.uuid, category, 'File', 'Body', attachment_ids=(attachment,))
    reservation = service.attachments.reserve(user.uuid, 'pending.txt', 8)
    headers = {'Authorization': 'Bearer ' + media.credentials(user)['token']}
    service.files.update(user.uuid, expected=service.files.policy(), uploads_enabled=False)
    media.on_reserve = lambda actor, payload: service.attachments.reserve(actor.uuid, payload['name'], payload['size'])
    server.forum_manager.media = media
    with pytest.raises(ForumError, match='forum-error-cargas-desactivadas'):
        server.forum_manager.media_ui.choose(user, Draft(kind='reply', topic_id=topic))
    async with ClientSession() as client:
        async with client.post(media.base_url + '/uploads', headers=headers, json={'name': 'x.txt', 'size': 8}) as response:
            assert response.status == 503
        async with client.put(media.base_url + '/uploads/' + reservation['id'], headers=headers, data=b'12345678') as response:
            assert response.status == 503
        async with client.get(media.base_url + '/files/' + attachment, headers={**headers, 'Range': 'bytes=0-3'}) as response:
            assert response.status == 206 and await response.read() == b'0123'
    assert service.attachments._row(reservation['id'])['state'] == 'uploading'
    assert service.post(user.uuid, post).body == 'Body'


async def test_approved_upload_already_processing_can_complete_after_disabling(media_server, tmp_path):
    server, media, users = media_server
    service = server.forum_manager.service
    server.db.update_user_trust_level('Alice', 3)
    row = service.attachments.reserve(users['Alice'].uuid, 'file.txt', 4)
    service.attachments.processing(users['Alice'].uuid, row['id'])
    service.files.update(users['Alice'].uuid, expected=service.files.policy(), uploads_enabled=False)
    source = tmp_path / 'source'
    source.write_bytes(b'text')
    processed = media.worker.processor.process(source, tmp_path / 'prepared')
    media.storage.put(row['object_key'], processed.path, processed.mime)
    service.attachments.complete(users['Alice'].uuid, row['id'], processed)
    assert service.attachments.get(users['Alice'].uuid, row['id'])['state'] == 'ready'


async def test_enabling_needs_live_service_and_successful_probe(admin_files, monkeypatch):
    server, user = admin_files
    settings = server.forum_manager.service.files
    await open_files(server, user)
    await _select(server, user, FILES_MENU, 'uploads_enabled')
    await _select(server, user, FILES_MENU, 'uploads_enabled')
    assert not settings.policy().uploads_enabled
    server.forum_manager.media = SimpleNamespace(site=object(), _closing=False)
    async def failure(*args):
        raise OSError('credential secret must never be sent to a client')
    monkeypatch.setattr('server.administration.files.check_storage', failure)
    await _select(server, user, FILES_MENU, 'uploads_enabled')
    assert not settings.policy().uploads_enabled
    assert not any('credential secret' in str(message.data) for message in user.messages)
    monkeypatch.setattr('server.administration.files.check_storage', check_storage)
    await _select(server, user, FILES_MENU, 'uploads_enabled')
    assert settings.policy().uploads_enabled
    assert not list((server._forum_media_directory / 'objects').rglob('content'))


@pytest.mark.parametrize('interruption', ['demotion', 'navigation', 'handover'])
async def test_probe_does_not_authorize_late_writes(admin_files, monkeypatch, interruption):
    server, user = admin_files
    settings = server.forum_manager.service.files
    settings.update(user.uuid, expected=settings.policy(), uploads_enabled=False)
    server.forum_manager.media = SimpleNamespace(site=object(), _closing=False)
    entered, finish = asyncio.Event(), asyncio.Event()
    async def wait(*args):
        entered.set()
        await finish.wait()
    monkeypatch.setattr('server.administration.files.check_storage', wait)
    await open_files(server, user)
    pending = asyncio.create_task(_select(server, user, FILES_MENU, 'uploads_enabled'))
    await entered.wait()
    if interruption == 'demotion':
        server.db.update_user_trust_level(user.username, 2)
    elif interruption == 'navigation':
        server._nav_back(user)
    else:
        server._users[user.username] = SimpleNamespace()
    finish.set()
    await pending
    assert not settings.policy().uploads_enabled
    assert not server.maintenance_manager._tracked_work


async def test_provider_change_blocks_all_attachments_and_stale_confirmation(admin_files, monkeypatch):
    server, user = admin_files
    service = server.forum_manager.service
    async def success(*args):
        pass
    monkeypatch.setattr('server.administration.files.check_storage', success)
    await open_files(server, user)
    await _select(server, user, FILES_MENU, 'storage')
    await _select(server, user, STORAGE_MENU, 's3')
    row = service.attachments.reserve(user.uuid, 'pending.txt', 1)
    await _select(server, user, STORAGE_CONFIRM, 'yes')
    assert service.files.policy().backend == 'local'
    service.attachments.discard(user.uuid, row['id'])
    await _select(server, user, STORAGE_CONFIRM, 'yes')
    assert service.files.policy().backend == 'local'  # Retired metadata is still protected.
    await _select(server, user, STORAGE_CONFIRM, 'no')
    # A different operator changing policy invalidates the confirmation snapshot.
    await _select(server, user, STORAGE_MENU, 's3')
    service.files.update(user.uuid, expected=service.files.policy(), require_approval=True)
    await _select(server, user, STORAGE_CONFIRM, 'yes')
    assert service.files.policy().backend == 'local'


async def test_provider_selection_freezes_uploads_applies_on_restart_and_preserves_backups(admin_files, monkeypatch):
    server, user = admin_files
    settings = server.forum_manager.service.files
    async def success(*args):
        pass
    monkeypatch.setattr('server.administration.files.check_storage', success)
    await open_files(server, user)
    await _select(server, user, FILES_MENU, 'storage')
    await _select(server, user, STORAGE_MENU, 's3')
    await _select(server, user, STORAGE_CONFIRM, 'yes')
    assert settings.policy().backend == 's3' and not settings.policy().uploads_enabled
    assert settings.active_backend == 'local'
    with pytest.raises(ForumError, match='forum-error-cargas-desactivadas'):
        server.forum_manager.service.attachments.reserve(user.uuid, 'pending.txt', 1)
    server.db.close()
    restarted = Server(db_path=server.db.db_path)
    restarted.db.connect()
    try:
        restarted._load_persistent_server_settings()
        assert restarted.forum_manager.service.files.active_backend == 's3'
        assert not restarted.forum_manager.service.files.policy().uploads_enabled
        # HTTP can remain disabled while backup workers use the selected store.
        calls = []
        monkeypatch.setattr('server.core.maintenance.configured_storage',
                            lambda directory, **kwargs: calls.append(kwargs) or LocalObjectStorage(directory))
        snapshot = restarted.db.backup_database(server._forum_media_directory / 'backups', purpose='manual')
        completed = await asyncio.to_thread(restarted.maintenance_manager._complete_forum_snapshot, snapshot)
        assert completed.archive_path.exists()
        assert calls == [{'backend': 's3'}]
    finally:
        restarted.db.close()


def test_local_probe_preserves_existing_objects_and_cleans_up_on_failure(tmp_path, monkeypatch):
    objects = LocalObjectStorage(tmp_path / 'objects')
    source = tmp_path / 'original'
    source.write_bytes(b'keep')
    key = 'a' * 32 + '/content'
    objects.put(key, source, 'text/plain')
    probe_storage(tmp_path, 'local')
    assert objects.path(key).read_bytes() == b'keep'
    assert list((tmp_path / 'objects').rglob('content')) == [objects.path(key)]
    deleted = []
    bad = SimpleNamespace(put=lambda *args: None, open=lambda *args: BytesIO(b'wrong'), delete=deleted.append)
    monkeypatch.setattr('server.forum.file_settings.configured_storage', lambda *args, **kwargs: bad)
    with pytest.raises(OSError, match='mismatch'):
        probe_storage(tmp_path, 's3')
    assert len(deleted) == 1 and deleted[0] != key


async def test_cancelled_probe_waits_for_thread_cleanup(tmp_path, monkeypatch):
    entered, release, cleaned = threading.Event(), threading.Event(), threading.Event()
    def probe(*args):
        entered.set()
        assert release.wait(3)
        cleaned.set()
    monkeypatch.setattr('server.forum.file_settings.probe_storage', probe)
    task = asyncio.create_task(check_storage(tmp_path, 'local'))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned.is_set()


def test_file_labels_format_in_all_installed_locales(admin_files):
    server, _user = admin_files
    for locale in Localization.get_available_languages():
        assert Localization.get(locale, 'admin-archivos-menu') != 'admin-archivos-menu'
        text = Localization.get(locale, 'forum-error-cuota-carga', cantidad=8, limite=16)
        assert '8' in text and '16' in text and '{' not in text


@pytest.mark.parametrize('value', [{'max_file_mib': True}, {'pending_mib': 1}, {'backend': []}, {'unknown': True}])
def test_invalid_persistent_policy_blocks_new_uploads(admin_files, value):
    server, user = admin_files
    server.db.set_json_server_setting(SETTINGS_KEY, value)
    with pytest.raises(ForumError, match='admin-archivos-configuracion-invalida'):
        server.forum_manager.service.attachments.reserve(user.uuid, 'file.txt', 1)


def test_corrupt_json_does_not_reenable_uploads(admin_files):
    server, user = admin_files
    settings = server.forum_manager.service.files
    settings.update(user.uuid, expected=settings.policy(), uploads_enabled=False)
    server.db._conn.execute('UPDATE server_settings SET value_json = ? WHERE setting_key = ?', ('{broken', SETTINGS_KEY))
    with pytest.raises(ForumError, match='admin-archivos-configuracion-invalida'):
        settings.require_uploads()


@pytest.mark.parametrize('backend', ['local', 's3'])
async def test_startup_uses_saved_provider_before_http_recovery(admin_files, monkeypatch, tmp_path, backend):
    server, user = admin_files
    settings = server.forum_manager.service.files
    settings.update(user.uuid, expected=settings.policy(), uploads_enabled=False)
    if backend == 's3':
        settings.select_backend(user.uuid, 's3', expected=settings.policy())
    # An obsolete environment default must not construct the wrong SDK client
    # before the database-backed selection has been loaded.
    monkeypatch.setenv('PLAYAURAL_FORUM_STORAGE', 's3' if backend == 'local' else 'local')
    monkeypatch.delenv('PLAYAURAL_FORUM_BUCKET', raising=False)
    server.db.close()
    owner_thread = threading.get_ident()
    calls = []
    adapter = LocalObjectStorage(tmp_path / 'selected-provider')
    def factory(directory, **kwargs):
        calls.append((kwargs['backend'], threading.get_ident()))
        return adapter
    monkeypatch.setattr('server.forum.media_http.configured_storage', factory)
    restarted = Server(host='127.0.0.1', port=0, db_path=server.db.db_path,
                       forum_media_url='http://127.0.0.1:0', forum_media_port=0)
    try:
        await restarted.start()
        media = restarted.forum_manager.media
        assert calls == [(backend, calls[0][1])]
        assert calls[0][1] != owner_thread
        assert media.storage is media.worker.storage is media.backups.storage is adapter
        assert restarted.forum_manager.service.files.active_backend == backend
        assert not restarted.forum_manager.service.files.policy().uploads_enabled
    finally:
        await restarted.stop()


async def test_http_transfer_already_started_finishes_after_uploads_disabled(media_server):
    server, media, users = media_server
    service = server.forum_manager.service
    server.db.update_user_trust_level('Alice', 3)
    row = service.attachments.reserve(users['Alice'].uuid, 'started.txt', 8)
    continue_upload, completed = asyncio.Event(), asyncio.Event()
    media.worker.on_complete = lambda *args: completed.set()
    async def body():
        yield b'first'
        await continue_upload.wait()
        yield b'end'
    headers = {'Authorization': 'Bearer ' + media.credentials(users['Alice'])['token'], 'Content-Length': '8'}
    async with ClientSession() as client:
        task = asyncio.create_task(client.put(media.base_url + '/uploads/' + row['id'], headers=headers, data=body()))
        try:
            async with asyncio.timeout(3):
                while row['id'] not in media._upload_ids:
                    await asyncio.sleep(0.01)
            service.files.update(users['Alice'].uuid, expected=service.files.policy(), uploads_enabled=False)
        finally:
            continue_upload.set()
        response = await task
        async with response:
            assert response.status == 202
        await asyncio.wait_for(completed.wait(), 10)
    assert service.attachments.get(users['Alice'].uuid, row['id'])['state'] == 'ready'
