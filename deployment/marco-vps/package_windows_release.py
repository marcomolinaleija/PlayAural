"""Package the isolated GitHub Windows build for the VPS release controller."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import zipfile


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def package(desktop, destination, root):
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    version = runpy.run_path(str(root / 'client/version.py'))['VERSION']
    sounds = desktop / '_internal/sounds'
    sounds_version = (sounds / 'version.txt').read_text().strip()
    for required in ('PlayAural.exe', 'updater.exe', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'SOURCE.txt'):
        if not (desktop / required).is_file():
            raise ValueError('Incomplete Windows build: ' + required)
    if commit not in (desktop / 'SOURCE.txt').read_text():
        raise ValueError('Source notice does not match the build commit')
    if json.loads((desktop / '_internal/release-build.json').read_text())['source_commit'] != commit:
        raise ValueError('Packaged Windows build identity does not match')
    destination.mkdir(parents=True, exist_ok=False)
    for name, directory, prefix in (('PlayAural.zip', desktop, 'PlayAural'), ('sounds.zip', sounds, 'sounds')):
        with zipfile.ZipFile(destination / name, 'w', zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
            for path in sorted(directory.rglob('*')):
                if path.is_symlink():
                    raise ValueError('Symlinks are not allowed in release archives')
                if path.is_file():
                    archive.write(path, prefix + '/' + path.relative_to(directory).as_posix())
        with zipfile.ZipFile(destination / name) as archive:
            if archive.testzip() is not None:
                raise ValueError('Corrupt release archive')
    result = {'source_commit': commit, 'build_id': commit, 'version': version, 'sounds_version': sounds_version,
              'sha256': {name: sha256(destination / name) for name in ('PlayAural.zip', 'sounds.zip')}}
    (destination / 'windows-release.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    (destination / 'SHA256SUMS.txt').write_text(''.join(f'{value}  {name}\n' for name, value in result['sha256'].items()), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination', type=Path)
    parser.add_argument('--desktop', type=Path, required=True)
    args = parser.parse_args()
    package(args.desktop, args.destination, Path(__file__).resolve().parents[2])
