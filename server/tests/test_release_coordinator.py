import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
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


def test_failed_promotion_retries_approved_artifacts_once_without_rebuilding(tmp_path, monkeypatch):
    (tmp_path / 'auto/jobs/test').mkdir(parents=True)
    controller = module.Coordinator(tmp_path)
    monkeypatch.setattr(controller, 'unit_status', lambda name: {'LoadState': 'loaded', 'ActiveState': 'failed', 'ExecMainStatus': '1'})
    monkeypatch.setattr(controller, 'repair', lambda *args: pytest.fail('premature agent repair'))
    job = {'id': 'test', 'phase': 'promoting', 'promotion_unit': 'test-unit', 'candidate': 'a' * 40,
           'windows_run': 123, 'android_code': 10503003, 'agent_attempt': 0}
    assert controller.promoting(job) is False
    assert job['phase'] == 'await_idle'
    assert job['promotion_failures'] == 1
    assert job['promotion_attempt'] == 1
    assert job['candidate'] == 'a' * 40 and job['windows_run'] == 123 and job['android_code'] == 10503003


def test_repaired_candidate_gets_a_new_promotion_handle(tmp_path):
    (tmp_path / 'auto/jobs/test').mkdir(parents=True)
    controller = module.Coordinator(tmp_path)
    job = {'id': 'test', 'phase': 'promoting', 'promotion_unit': 'previous-unit', 'promotion_attempt': 1,
           'promotion_failures': 1, 'candidate': 'a' * 40, 'agent_attempt': 0}
    assert controller.repair(job, 'repair the candidate')
    assert job['phase'] == 'agent'
    assert 'promotion_unit' not in job
    assert job['promotion_attempt'] == 2
    assert job['promotion_failures'] == 0


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


@pytest.mark.skipif(shutil.which('git') is None, reason='Real Git ancestry is verified in CI; the minimal game image has no Git')
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


@pytest.fixture
def git_flow(tmp_path):
    if shutil.which('git') is None:
        pytest.skip('Real Git flow requires Git')
    def git(directory, *args):
        return subprocess.check_output(
            ['git', '-C', str(directory), '-c', 'user.name=Test',
             '-c', 'user.email=test@example.invalid', *args], text=True,
            stderr=subprocess.PIPE).strip()
    upstream = tmp_path / 'upstream'
    upstream.mkdir()
    git(upstream, 'init', '-q', '--initial-branch=main')
    git(upstream, 'commit', '--allow-empty', '-qm', 'base')
    base = git(upstream, 'rev-parse', 'HEAD')
    remote = tmp_path / 'fork.git'
    subprocess.run(['git', 'clone', '--bare', str(upstream), str(remote)], check=True, capture_output=True)
    root = tmp_path / 'runtime'
    repository = root / 'auto/repository'
    repository.parent.mkdir(parents=True)
    (root / 'auto/jobs').mkdir()
    subprocess.run(['git', 'clone', str(remote), str(repository)], check=True, capture_output=True)
    git(repository, 'remote', 'add', 'upstream', str(upstream))
    git(repository, 'push', 'origin', 'HEAD:refs/heads/develop')
    (root / 'current.env').write_text('RELEASE_ID=' + base + '\n')
    controller = module.Coordinator(root)
    return SimpleNamespace(controller=controller, git=git, upstream=upstream,
                           remote=remote, repository=repository, root=root, base=base)


def successful_ci(controller):
    class API:
        def repo(self, path):
            assert path.startswith('actions/workflows/marco-ci.yml/runs?')
            return {'workflow_runs': [{'id': 123, 'status': 'completed', 'conclusion': 'success'}]}
    controller.api = API()


def test_unreleased_develop_changes_do_not_start_a_release(git_flow):
    flow = git_flow
    flow.git(flow.repository, 'checkout', '-b', 'feature/pending')
    flow.git(flow.repository, 'commit', '--allow-empty', '-qm', 'unfinished feature')
    flow.git(flow.repository, 'push', 'origin', 'HEAD:refs/heads/develop')
    assert flow.controller.create_job() is None
    assert flow.controller.current_release() == flow.base
    assert not flow.controller.state_path.exists()


def test_upstream_integration_only_advances_develop_after_ci(git_flow):
    flow = git_flow
    flow.git(flow.upstream, 'commit', '--allow-empty', '-qm', 'upstream change')
    job = flow.controller.create_job()
    assert job['kind'] == 'integration' and job['phase'] == 'agent'
    assert job['branch'].startswith('feature/upstream-')
    flow.git(flow.repository, 'merge', '--no-ff', 'upstream/main', '-m', 'integrate upstream')
    job.update(candidate=flow.git(flow.repository, 'rev-parse', 'HEAD'), phase='ci')
    successful_ci(flow.controller)
    assert flow.controller.ci(job) is False
    assert job['phase'] == 'done' and job['integrated_ref'] == 'develop'
    assert flow.git(flow.remote, 'rev-parse', 'main') == flow.base
    assert flow.git(flow.remote, 'rev-parse', 'develop') == job['candidate']
    assert flow.controller.current_release() == flow.base
    assert not any(key in job for key in ('windows_run', 'android_code', 'promotion_unit'))
    assert flow.controller.create_job() is None


def test_main_release_is_pinned_without_merging_pending_upstream(git_flow, monkeypatch):
    flow = git_flow
    flow.git(flow.repository, 'commit', '--allow-empty', '-qm', 'approved release')
    approved = flow.git(flow.repository, 'rev-parse', 'HEAD')
    flow.git(flow.repository, 'push', 'origin', 'HEAD:refs/heads/main')
    flow.git(flow.upstream, 'commit', '--allow-empty', '-qm', 'not approved for production')
    monkeypatch.setattr(module, 'start_agent', lambda *args: pytest.fail('A release must not edit main'))
    job = flow.controller.create_job()
    assert job['kind'] == 'release' and job['phase'] == 'ci'
    assert job['candidate'] == approved and job['branch'] == 'main'
    successful_ci(flow.controller)
    assert flow.controller.ci(job) is True
    assert job['phase'] == 'windows'
    assert flow.git(flow.remote, 'rev-parse', 'main') == approved
    assert flow.git(flow.remote, 'rev-parse', 'develop') == flow.base
    assert not flow.controller.ancestor(job['upstream'], approved)


@pytest.mark.parametrize('branch', ['main', 'develop'])
def test_integration_preserves_concurrent_main_and_develop_changes(git_flow, branch):
    flow = git_flow
    flow.git(flow.upstream, 'commit', '--allow-empty', '-qm', 'upstream change')
    job = flow.controller.create_job()
    flow.git(flow.repository, 'merge', '--no-ff', 'upstream/main', '-m', 'integrate upstream')
    job.update(candidate=flow.git(flow.repository, 'rev-parse', 'HEAD'), phase='ci')
    tree = flow.git(flow.repository, 'rev-parse', flow.base + '^{tree}')
    concurrent = flow.git(flow.repository, 'commit-tree', tree, '-p', flow.base, '-m', 'concurrent change')
    flow.git(flow.repository, 'push', 'origin', concurrent + ':refs/heads/' + branch)
    successful_ci(flow.controller)
    assert flow.controller.ci(job) is True
    assert job['phase'] == 'agent'
    assert flow.git(flow.remote, 'rev-parse', branch) == concurrent
    assert job['main' if branch == 'main' else 'base'] == concurrent
    assert flow.controller.current_release() == flow.base


def test_failed_release_defers_without_creating_an_integration_agent(git_flow):
    flow = git_flow
    flow.git(flow.repository, 'commit', '--allow-empty', '-qm', 'approved release')
    flow.git(flow.repository, 'push', 'origin', 'HEAD:refs/heads/main')
    job = flow.controller.create_job()
    assert flow.controller.repair(job, 'build failed', 'failure details') is False
    assert job['phase'] == 'deferred'
    assert flow.git(flow.remote, 'rev-parse', 'main') == job['candidate']
    assert flow.controller.current_release() == flow.base
    assert (flow.controller.job_dir(job) / 'failure.log').read_text() == 'failure details'


def test_deferred_release_restarts_only_after_main_is_corrected(git_flow, monkeypatch):
    flow = git_flow
    flow.git(flow.repository, 'commit', '--allow-empty', '-qm', 'failed release')
    flow.git(flow.repository, 'push', 'origin', 'HEAD:refs/heads/main')
    failed = flow.controller.create_job()
    flow.controller.repair(failed, 'build failed')
    monkeypatch.setattr(module, 'Coordinator', lambda root: flow.controller)
    monkeypatch.setattr(sys, 'argv', ['autoupdate.py', '--root', str(flow.root)])
    advanced = []
    def advance(job):
        advanced.append(job['candidate'])
        job['phase'] = 'done'
        flow.controller.save(job)
        return False
    monkeypatch.setattr(flow.controller, 'advance', advance)
    module.main()
    assert not advanced
    flow.git(flow.repository, 'commit', '--allow-empty', '-qm', 'corrected release')
    corrected = flow.git(flow.repository, 'rev-parse', 'HEAD')
    flow.git(flow.repository, 'push', 'origin', 'HEAD:refs/heads/main')
    module.main()
    assert advanced == [corrected]


def test_git_flow_agent_prompt_identifies_all_histories_and_develop_target():
    prompt = module.integration_prompt('upstream-sha', 'develop-sha', main='main-sha')
    assert 'integration into develop' in prompt
    assert 'main-sha' in prompt
    assert 'Never merge develop into main' in prompt
