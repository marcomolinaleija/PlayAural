"""Release exports contain data-only catalogs, credits and working registrations."""

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

import pytest

from ..translations.catalog import default_catalog, read_web_object
from ..translations.exporter import export_bundle


def test_real_catalog_export_covers_all_five_domains_and_checksums(tmp_path):
    catalog = default_catalog()
    choices = [('server', 'back', 'Retour'), ('windows', 'common-error', 'Erreur'),
               ('web', 'app-title', 'PlayAural Web FR'), ('android', 'app-title', 'PlayAural Mobile FR'),
               ('documentation', 'document', 'Règles de test.')]
    entries = []
    for domain, key, value in choices:
        unit = next(unit for unit in catalog.units.values() if unit.domain == domain and unit.key == key
                    and (domain != 'documentation' or unit.path == 'community_rules.md'))
        entries.append({'language': 'fr', 'unit_id': unit.id, 'domain': domain, 'path': unit.path,
                        'key': key, 'value': value, 'source_hash': unit.source_hash, 'revision': 1})
    data = {'languages': {'fr': {'name': 'French', 'native_name': 'Français', 'contributors': ['Contributor']}}, 'entries': entries}
    destination = export_bundle(data, catalog, tmp_path / 'all-domains.zip')
    with zipfile.ZipFile(destination) as archive:
        manifest = json.loads(archive.read('translation-manifest.json'))
        assert len(manifest['entries']) == 5
        for path, metadata in manifest['files'].items():
            assert hashlib.sha256(archive.read(path)).hexdigest() == metadata['sha256']
            assert len(archive.read(path)) == metadata['bytes']
            assert '..' not in Path(path).parts
        assert read_web_object(archive.read('web_client/locales/fr.js').decode())['app-title'] == 'PlayAural Web FR'
        assert json.loads(archive.read('mobile_client/locales/fr/client.json'))['app-title'] == 'PlayAural Mobile FR'
        assert archive.read('server/documentation/content/fr/community_rules.md').decode() == 'Règles de test.'
        for path in manifest['files']:
            target = tmp_path / 'stage' / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(path))
    # The actual mobile registry must compile, including default direction on
    # existing metadata whose source JSON does not spell it out.
    compiler = catalog.root / 'mobile_client/node_modules/typescript/lib/tsc.js'
    node = shutil.which('node')
    if node and compiler.exists():
        for source in (catalog.root / 'mobile_client/locales').glob('*/client.json'):
            target = tmp_path / 'stage/mobile_client/locales' / source.parent.name / 'client.json'
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copyfile(source, target)
        registry = tmp_path / 'stage/mobile_client/src/i18n/localeCatalogs.ts'
        result = subprocess.run([node, str(compiler), '--noEmit', '--resolveJsonModule', '--esModuleInterop',
                                 '--skipLibCheck', '--module', 'commonjs', '--target', 'es2020', str(registry)],
                                capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stdout + result.stderr
