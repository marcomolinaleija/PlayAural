"""Keep the trusted coordinator monotonic when an older app job finishes."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile


COMMIT = re.compile(r'^[0-9a-f]{40}$')


def controller_is_newer(root, candidate):
    root = Path(root)
    if not COMMIT.fullmatch(candidate):
        raise ValueError('Controller revisions must be full source commits')
    receipt = root / 'auto/controller-source.json'
    if not receipt.exists():
        return False
    installed = json.loads(receipt.read_text())['source_commit']
    if not COMMIT.fullmatch(installed):
        raise ValueError('Invalid installed controller revision')
    if candidate == installed:
        return False
    for older, newer, answer in ((candidate, installed, True), (installed, candidate, False)):
        result = subprocess.run(['git', '-C', str(root / 'source'), 'merge-base', '--is-ancestor', older, newer], capture_output=True)
        if result.returncode == 0:
            return answer
        if result.returncode != 1:
            raise RuntimeError('Could not establish controller revision ancestry')
    raise RuntimeError('Unrelated controller histories require review')


def record_controller(root, commit):
    if not COMMIT.fullmatch(commit):
        raise ValueError('Controller revisions must be full source commits')
    path = Path(root) / 'auto/controller-source.json'
    descriptor, temporary = tempfile.mkstemp(prefix='.controller-source-', dir=path.parent)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
        json.dump({'source_commit': commit}, output)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
