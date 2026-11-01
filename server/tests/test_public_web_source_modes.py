import importlib.util
import os
from pathlib import Path

import pytest


SOURCE = Path(__file__).resolve().parents[2] / 'deployment/marco-vps/prepare_public_web_source.py'
SPEC = importlib.util.spec_from_file_location('public_web_source_modes', SOURCE)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def make_sources(root):
    for name in ('web_client/index.html', 'web_client/nested/app.js', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'deployment/marco-vps/nginx.conf', 'private/config.json'):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('preserved content')
        path.chmod(0o600)
    (root / 'web_client').chmod(0o700)
    (root / 'web_client/nested').chmod(0o700)


@pytest.mark.skipif(os.name == 'nt', reason='Linux image input permissions')
def test_private_extraction_becomes_readable_only_for_public_image_inputs(tmp_path):
    make_sources(tmp_path)
    module.prepare(tmp_path)
    for name in ('web_client/index.html', 'web_client/nested/app.js', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'deployment/marco-vps/nginx.conf'):
        path = tmp_path / name
        assert path.stat().st_mode & 0o777 == 0o644
        assert path.read_text() == 'preserved content'
    assert (tmp_path / 'web_client/nested').stat().st_mode & 0o777 == 0o755
    assert (tmp_path / 'private/config.json').stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name == 'nt', reason='Linux symlink safety')
def test_public_tree_never_follows_symlinks_into_private_files(tmp_path):
    make_sources(tmp_path)
    (tmp_path / 'web_client/link').symlink_to(tmp_path / 'private/config.json')
    module.prepare(tmp_path)
    assert (tmp_path / 'private/config.json').stat().st_mode & 0o777 == 0o600
    nginx = tmp_path / 'deployment/marco-vps/nginx.conf'
    nginx.unlink()
    nginx.symlink_to(tmp_path / 'private/config.json')
    with pytest.raises(ValueError):
        module.prepare(tmp_path)
    assert (tmp_path / 'private/config.json').stat().st_mode & 0o777 == 0o600
