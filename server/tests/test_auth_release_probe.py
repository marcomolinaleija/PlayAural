import importlib.util
from pathlib import Path

import pytest


SOURCE = Path(__file__).resolve().parents[2] / 'deployment/marco-vps/auth_release_probe.py'
SPEC = importlib.util.spec_from_file_location('auth_release_probe_tested', SOURCE)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def fixture():
    artifact = {'url': 'https://play.example/approved/PlayAural.zip', 'sha256': 'a' * 64, 'build_id': 'b' * 40}
    manifest = {'version': 'same', 'targets': {'windows': {'application': artifact}}}
    packet = {'type': 'authorize_success', 'preferences': {}, 'version': 'same',
              'update_info': {'version': 'same', 'available': True, 'target': 'windows',
                              'url': artifact['url'], 'hash': artifact['sha256'], 'build_id': artifact['build_id']}}
    return packet, manifest


def test_probe_accepts_only_update_bootstrap_for_the_approved_artifact():
    packet, manifest = fixture()
    module.validate_release(packet, manifest, 'windows')


@pytest.mark.parametrize('field,value', [('url', 'https://other.example/wrong.zip'), ('hash', 'c' * 64), ('build_id', 'c' * 40), ('version', 'wrong')])
def test_probe_rejects_wrong_native_artifacts(field, value):
    packet, manifest = fixture()
    packet['update_info'][field] = value
    with pytest.raises(RuntimeError):
        module.validate_release(packet, manifest, 'windows')


def test_probe_rejects_a_normal_live_session_or_authentication_failure():
    for changes in ({'preferences': {'some_preference': True}}, {'type': 'login_failed'}):
        packet, manifest = fixture()
        packet.update(changes)
        with pytest.raises(RuntimeError):
            module.validate_release(packet, manifest, 'windows')
