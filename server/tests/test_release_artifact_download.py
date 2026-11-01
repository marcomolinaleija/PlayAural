import importlib.util
import json
from pathlib import Path
import zipfile

import pytest


SOURCE = Path(__file__).resolve().parents[2] / 'deployment/marco-vps/github_release.py'
SPEC = importlib.util.spec_from_file_location('github_release_tested', SOURCE)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)
COMMIT = 'a' * 40


def artifact(tmp_path, *, wrong_commit=False, tampered=False, extra=None):
    desktop = tmp_path / 'PlayAural.zip'
    with zipfile.ZipFile(desktop, 'w') as archive:
        for name in ('PlayAural.exe', 'updater.exe', 'LICENSE', 'THIRD_PARTY_NOTICES.md'):
            archive.writestr('PlayAural/' + name, b'fixture')
        archive.writestr('PlayAural/SOURCE.txt', COMMIT)
    sounds = tmp_path / 'sounds.zip'
    with zipfile.ZipFile(sounds, 'w') as archive:
        archive.writestr('sounds/version.txt', '13')
    metadata = {'source_commit': 'b' * 40 if wrong_commit else COMMIT,
                'sha256': {'PlayAural.zip': '0' * 64 if tampered else module.sha256(desktop), 'sounds.zip': module.sha256(sounds)}}
    outer = tmp_path / 'artifact.zip'
    with zipfile.ZipFile(outer, 'w') as archive:
        archive.write(desktop, 'PlayAural.zip')
        archive.write(sounds, 'sounds.zip')
        archive.writestr('windows-release.json', json.dumps(metadata))
        archive.writestr('SHA256SUMS.txt', 'fixture')
        if extra:
            archive.writestr(extra, 'do not extract')
    return outer


def test_verified_windows_archive_retains_exact_source_and_checksums(tmp_path):
    metadata = module.extract_windows_artifact(artifact(tmp_path), tmp_path / 'out', COMMIT)
    assert metadata['source_commit'] == COMMIT


@pytest.mark.parametrize('options', [{'wrong_commit': True}, {'tampered': True}, {'extra': '../escape'}, {'extra': '/absolute'}])
def test_source_mismatch_tampering_and_extra_paths_are_rejected(tmp_path, options):
    with pytest.raises(ValueError):
        module.extract_windows_artifact(artifact(tmp_path, **options), tmp_path / 'out', COMMIT)
    assert not (tmp_path / 'escape').exists()
