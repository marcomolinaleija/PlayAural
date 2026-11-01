import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest


pytest.importorskip('fcntl', reason='The unattended coordinator runs on Linux')
SCRIPTS = Path(__file__).resolve().parents[2] / 'deployment/marco-vps'
sys.path.insert(0, str(SCRIPTS))
from controller_revision import record_controller

SPEC = importlib.util.spec_from_file_location('autoupdate_tested', SCRIPTS / 'autoupdate.py')
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_resuming_a_live_windows_run_does_not_dispatch_a_second_build(tmp_path):
    (tmp_path / 'auto').mkdir()
    controller = module.Coordinator(tmp_path)
    calls = []
    class API:
        def repo(self, path):
            calls.append(path)
            return {'status': 'in_progress'}
    controller.api = API()
    job = {'id': 'test', 'phase': 'windows', 'windows_run': 123}
    assert controller.windows(job) is False
    assert calls == ['actions/runs/123']
    assert job['windows_run'] == 123


def test_resuming_a_live_agent_observes_its_container_without_restarting(tmp_path, monkeypatch):
    (tmp_path / 'auto').mkdir()
    controller = module.Coordinator(tmp_path)
    monkeypatch.setattr(module, 'container_status', lambda name: {'Running': True})
    monkeypatch.setattr(module, 'start_agent', lambda *args: pytest.fail('duplicated live agent'))
    job = {'id': 'test', 'phase': 'agent', 'agent_attempt': 0, 'quota_checked_at': time.time()}
    assert controller.agent(job) is False
    assert job['phase'] == 'agent'


def test_atomic_state_never_follows_a_preplanted_temporary_symlink(tmp_path):
    private = tmp_path / 'private'
    private.write_text('preserved')
    path = tmp_path / 'state.json'
    path.with_name('.state.json.next').symlink_to(private)
    module.atomic_json(path, {'phase': 'await_idle'})
    assert private.read_text() == 'preserved'
    assert json.loads(path.read_text())['phase'] == 'await_idle'


def test_quota_reserve_preserves_phase_and_stops_advancement(tmp_path, monkeypatch):
    (tmp_path / 'auto/jobs/test').mkdir(parents=True)
    controller = module.Coordinator(tmp_path)
    monkeypatch.setattr(module, 'read_quota', lambda **kwargs: {'allowed': False, 'remaining_percent': 2})
    job = {'id': 'test', 'phase': 'await_idle'}
    assert not controller.quota(job)
    assert job['quota_deferred']
    assert json.loads(controller.state_path.read_text())['phase'] == 'await_idle'


def test_unknown_quota_stops_an_already_running_agent_and_preserves_work(tmp_path, monkeypatch):
    (tmp_path / 'auto/jobs/test').mkdir(parents=True)
    controller = module.Coordinator(tmp_path)
    states = iter([{'Running': True}, {'Running': False}])
    monkeypatch.setattr(module, 'container_status', lambda name: next(states))
    def unavailable(**kwargs):
        raise TimeoutError('usage endpoint unavailable')
    monkeypatch.setattr(module, 'read_quota', unavailable)
    commands = []
    monkeypatch.setattr(module.subprocess, 'run', lambda command, **kwargs: commands.append(command) or SimpleNamespace(returncode=0))
    job = {'id': 'test', 'phase': 'agent', 'agent_attempt': 0, 'candidate': 'a' * 40, 'quota_checked_at': 0}
    assert controller.agent(job) is False
    assert len(commands) == 1
    assert commands[0][:6] == ['docker', 'stop', '--signal', 'SIGINT', '--time', '30']
    assert job['quota_deferred']
    assert job['candidate'] == 'a' * 40
    assert job['phase'] == 'agent'
    assert job['agent_attempt'] == 1
    assert json.loads((tmp_path / 'auto/quota.json').read_text())['allowed'] is False


def test_publication_is_traversable_under_private_umask_and_resume_repairs_permissions(tmp_path, monkeypatch):
    root = tmp_path
    job_dir = root / 'auto/jobs/test'
    for directory in (job_dir / 'windows', job_dir / 'signed', root / 'downloads', root / 'build/android-source/server/core'):
        directory.mkdir(parents=True, exist_ok=True)
    (job_dir / 'windows/PlayAural.zip').write_bytes(b'windows fixture')
    (job_dir / 'windows/sounds.zip').write_bytes(b'sounds fixture')
    (job_dir / 'signed/PlayAural.apk').write_bytes(b'apk fixture')
    (root / 'build/android-source/server/core/server.py').write_text('VERSION = "test"\nSOUNDS_VERSION = "13"\n')
    controller = module.Coordinator(root)
    job = {'id': 'test', 'phase': 'publish', 'candidate': 'a' * 40, 'android_code': 10503003, 'windows_run': 123,
           'windows_metadata': {'version': 'test', 'sounds_version': '13'}}
    monkeypatch.setattr(module.subprocess, 'run', lambda command, **kwargs: kwargs['stdout'].write(b'source fixture'))
    monkeypatch.setattr(module.urllib.request, 'urlopen', lambda url, **kwargs: io.BytesIO((root / 'downloads' / job['candidate'] / Path(urlsplit(url).path).name).read_bytes()))
    previous = os.umask(0o077)
    try:
        assert controller.publish(job)
    finally:
        os.umask(previous)
    destination = root / 'downloads' / job['candidate']
    assert destination.stat().st_mode & 0o777 == 0o755
    hashes = json.loads((destination / 'release.json').read_text())['sha256']
    destination.chmod(0o700)
    assert controller.publish(job)
    assert destination.stat().st_mode & 0o777 == 0o755
    assert hashes == json.loads((destination / 'release.json').read_text())['sha256']


def test_older_completed_app_job_cannot_downgrade_a_newer_controller(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (tmp_path / 'auto').mkdir()
    def git(*args):
        return subprocess.check_output(['git', '-C', str(source), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', *args], text=True).strip()
    git('init', '-q')
    git('commit', '--allow-empty', '-qm', 'first')
    first = git('rev-parse', 'HEAD')
    git('commit', '--allow-empty', '-qm', 'second')
    second = git('rev-parse', 'HEAD')
    record_controller(tmp_path, second)
    assert module.controller_is_newer(tmp_path, first)
    assert not module.controller_is_newer(tmp_path, second)
    record_controller(tmp_path, first)
    assert not module.controller_is_newer(tmp_path, second)
    git('checkout', '--orphan', 'unrelated')
    git('commit', '--allow-empty', '-qm', 'unrelated')
    with pytest.raises(RuntimeError, match='Unrelated'):
        module.controller_is_newer(tmp_path, git('rev-parse', 'HEAD'))


@pytest.mark.parametrize('age,count', [(31, 0), (-5, 0), (0, 1), (0, True)])
def test_stale_future_and_occupied_status_cannot_authorize_a_restart(tmp_path, age, count):
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data/maintenance-status.json').write_text(json.dumps({'observed_at': 1000 - age, 'table_count': count}))
    with pytest.raises(RuntimeError):
        module.idle_status(tmp_path, now=1000)
