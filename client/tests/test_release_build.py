import json
from pathlib import Path
import sys

import pytest


CLIENT_DIR = Path(__file__).resolve().parents[1]
if str(CLIENT_DIR) not in sys.path:
    sys.path.insert(0, str(CLIENT_DIR))

import client_info
from release_build import application_update_required, get_build_id


def test_packaged_identity_is_a_valid_full_source_commit(tmp_path):
    record = tmp_path / 'release-build.json'
    record.write_text(json.dumps({'source_commit': 'a' * 40}))
    assert get_build_id(record) == 'a' * 40
    for invalid in ({'source_commit': '../elsewhere'}, {'source_commit': 42}, [], {'source_commit': 'a' * 39}):
        record.write_text(json.dumps(invalid))
        assert get_build_id(record) == ''


@pytest.mark.parametrize('current,expected,needs_update', [('a' * 40, 'a' * 40, False), ('a' * 40, 'b' * 40, True), ('', 'a' * 40, True)])
def test_same_protocol_packaged_corrections_trigger_update(current, expected, needs_update):
    assert application_update_required({'version': 'same', 'build_id': expected}, 'same', current_build=current, packaged=True) is needs_update


def test_protocol_version_check_remains_exact_and_source_runs_do_not_require_packaged_identity():
    assert application_update_required({'version': 'different'}, 'same', current_build='', packaged=False)
    assert not application_update_required({'version': 'same', 'build_id': 'a' * 40}, 'same', current_build='', packaged=False)
    assert not application_update_required({'version': 'same', 'build_id': 'not-a-source-commit'}, 'same', current_build='a' * 40, packaged=True)


def test_desktop_auth_reports_the_packaged_source(monkeypatch):
    monkeypatch.setattr(client_info, 'get_build_id', lambda: 'a' * 40)
    assert client_info.client_auth_metadata()['build_id'] == 'a' * 40
