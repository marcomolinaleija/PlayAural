"""Final quota/idle check immediately before the production stack is stopped."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from codex_quota import read_quota


def idle_status(root, now=None):
    path = Path(root) / 'data/maintenance-status.json'
    if path.is_symlink():
        raise RuntimeError('Maintenance status must be a regular private file')
    status = json.loads(path.read_text())
    age = (time.time() if now is None else now) - status['observed_at']
    if not 0 <= age <= 30:
        raise RuntimeError('Runtime maintenance status is stale; deployment deferred')
    if type(status.get('table_count')) is not int or status['table_count'] != 0:
        raise RuntimeError('People are still at tables; deployment deferred')
    return status


def verify(root):
    quota = read_quota(env=dict(os.environ, CODEX_HOME=str(Path(root) / 'auto/agent-home')))
    if not quota['allowed']:
        raise RuntimeError('Codex reserve reached; deployment deferred')
    with Path(__file__).with_name('auth_release_probe.py').open('rb') as probe:
        result = subprocess.run(['docker', 'exec', '-i', 'playaural-game-1', '/app/server/.venv/bin/python', '-'],
                                stdin=probe, capture_output=True, check=True, text=False, timeout=75)
    print(result.stdout.decode('utf-8'), end='')
    if os.environ.get('PLAYAURAL_BOOTSTRAP_IDLE') == '1':
        current = (Path(root) / 'current.env').read_text()
        if 'RELEASE_ID=49a80c60117152c70107d0a58a62b30398e1db1c\n' not in current:
            raise RuntimeError('Bootstrap is restricted to the original legacy release')
        print('Operator bootstrap of legacy release; subsequent deployments require fresh runtime counts')
    else:
        idle_status(root)
    print('Final quota and deployment gate passed')


if __name__ == '__main__':
    try:
        verify(Path(sys.argv[1]))
    except (RuntimeError, OSError, ValueError, KeyError, TimeoutError, subprocess.SubprocessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(75)
