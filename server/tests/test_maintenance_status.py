import importlib.util
import json
import os
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'core/maintenance_status.py'
SPEC = importlib.util.spec_from_file_location('maintenance_status', SOURCE)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
MaintenanceStatus = module.MaintenanceStatus


def test_status_is_private_anonymous_and_throttled(tmp_path):
    path = tmp_path / 'status.json'
    status = MaintenanceStatus(path)
    status.publish(table_count=2, version='test')
    first = path.read_bytes()
    assert json.loads(first)['table_count'] == 2
    assert set(json.loads(first)) == {'observed_at', 'table_count', 'version', 'pid'}
    if os.name != 'nt':
        assert path.stat().st_mode & 0o777 == 0o600
    status.publish(table_count=0, version='next')
    assert path.read_bytes() == first
    status.next_write = 0
    status.publish(table_count=0, version='next')
    assert json.loads(path.read_text())['table_count'] == 0
    assert not list(tmp_path.glob('.maintenance-status-*'))


def test_status_disabled_or_unavailable_never_breaks_gameplay(tmp_path):
    MaintenanceStatus().publish(table_count=0, version='test')
    MaintenanceStatus(tmp_path / 'missing/status.json').publish(table_count=0, version='test')
    assert not (tmp_path / 'missing').exists()
