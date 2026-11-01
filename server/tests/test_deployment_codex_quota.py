import importlib.util
from pathlib import Path
import sys

import pytest


SOURCE = Path(__file__).resolve().parents[2] / 'deployment/marco-vps/codex_quota.py'
SPEC = importlib.util.spec_from_file_location('codex_quota', SOURCE)
quota = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quota)


@pytest.mark.parametrize('used,allowed', [(0, True), (96, True), (97, False), (98, False), (100, False)])
def test_quota_preserves_three_percent_reserve(used, allowed):
    assert quota.quota_status({'rateLimits': {'primary': {'usedPercent': used}}})['allowed'] is allowed


def test_secondary_window_can_stop_work_even_with_primary_capacity():
    result = {'rateLimitsByLimitId': {'codex': {'primary': {'usedPercent': 10}, 'secondary': {'usedPercent': 99}}}}
    assert quota.quota_status(result)['remaining_percent'] == 1
    assert not quota.quota_status(result)['allowed']


@pytest.mark.parametrize('result', [{}, {'rateLimits': {}}, {'rateLimits': {'primary': {'usedPercent': None}}}, {'rateLimits': {'primary': {'usedPercent': True}}}, {'rateLimits': {'primary': {'usedPercent': -1}}}])
def test_missing_or_malformed_usage_does_not_authorize_work(result):
    with pytest.raises(RuntimeError):
        quota.quota_status(result)


@pytest.mark.skipif(sys.platform == 'win32', reason='The VPS usage reader polls Linux subprocess pipes')
def test_usage_reader_uses_initialized_rpc_before_reading_limits(tmp_path):
    fake = tmp_path / 'rpc.py'
    fake.write_text('''import json,sys
request=json.loads(sys.stdin.readline())
assert request['method']=='initialize'
print(json.dumps({'id':1,'result':{}}),flush=True)
assert json.loads(sys.stdin.readline())['method']=='initialized'
request=json.loads(sys.stdin.readline())
assert request['method']=='account/rateLimits/read'
print(json.dumps({'id':2,'result':{'rateLimits':{'primary':{'usedPercent':98}}}}),flush=True)
sys.stdin.read()
''')
    assert quota.read_quota([sys.executable, str(fake)], timeout=5)['allowed'] is False
