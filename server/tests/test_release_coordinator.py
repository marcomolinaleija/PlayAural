import importlib.util
import json
from pathlib import Path
import sys
import time

import pytest


pytest.importorskip('fcntl', reason='The unattended coordinator runs on Linux')
SCRIPTS = Path(__file__).resolve().parents[2] / 'deployment/marco-vps'
sys.path.insert(0, str(SCRIPTS))
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
    monkeypatch.setattr(module, 'read_quota', lambda: {'allowed': False, 'remaining_percent': 2})
    job = {'id': 'test', 'phase': 'await_idle'}
    assert not controller.quota(job)
    assert job['quota_deferred']
    assert json.loads(controller.state_path.read_text())['phase'] == 'await_idle'


@pytest.mark.parametrize('age,count', [(31, 0), (-5, 0), (0, 1), (0, True)])
def test_stale_future_and_occupied_status_cannot_authorize_a_restart(tmp_path, age, count):
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data/maintenance-status.json').write_text(json.dumps({'observed_at': 1000 - age, 'table_count': count}))
    with pytest.raises(RuntimeError):
        module.idle_status(tmp_path, now=1000)
