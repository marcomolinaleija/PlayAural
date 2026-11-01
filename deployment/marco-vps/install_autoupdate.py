"""Install only this app's trusted coordinator and user-level timers."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tomllib


PAYLOAD = ('autoupdate.py', 'agent_runner.py', 'codex_quota.py', 'deployment_gate.py',
           'github_release.py', 'sign_android.py', 'promote.sh', 'rollback.sh', 'install_autoupdate.py')
UNITS = ('playaural-update.service', 'playaural-update.timer',
         'playaural-update-resume.service', 'playaural-update-resume.timer')


def install(root, source, *, enable=False):
    os.umask(0o077)
    root, source = Path(root).resolve(), Path(source).resolve()
    for directory in ('auto', 'auto/jobs', 'auto/credentials', 'auto/agent-home', 'ops/autoupdate'):
        path = root / directory
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o700)
    token = root / 'auto/credentials/github.token'
    if not token.is_file():
        raise RuntimeError('Install the private GitHub credential before enabling the coordinator')
    token.chmod(0o600)
    auth = root / 'auto/agent-home/auth.json'
    if not auth.exists():
        shutil.copy2(Path.home() / '.codex/auth.json', auth)
    auth.chmod(0o600)
    config = root / 'auto/agent-home/config.toml'
    if not config.exists():
        existing = tomllib.loads((Path.home() / '.codex/config.toml').read_text())
        config.write_text(''.join(f'{key} = {json.dumps(existing[key])}\n' for key in ('model', 'model_reasoning_effort') if key in existing))
    askpass = root / 'auto/credentials/askpass'
    askpass.write_text('#!/usr/bin/python3\nfrom pathlib import Path\nimport sys\n'
                      f"print('x-access-token' if 'username' in sys.argv[1].lower() else Path({str(token)!r}).read_text().strip())\n")
    askpass.chmod(0o700)
    for name in PAYLOAD:
        target = root / 'ops/autoupdate' / name
        temporary = target.with_name('.' + name + '.next')
        shutil.copyfile(source / name, temporary)
        temporary.chmod(0o600)
        os.replace(temporary, target)
    units = Path.home() / '.config/systemd/user'
    units.mkdir(parents=True, exist_ok=True)
    for name in UNITS:
        shutil.copyfile(source / name, units / name)
        (units / name).chmod(0o600)
    repository = root / 'auto/repository'
    if not repository.exists():
        subprocess.run(['git', 'clone', '--no-hardlinks', str(root / 'source'), str(repository)], check=True)
        subprocess.run(['git', '-C', str(repository), 'remote', 'set-url', 'origin', 'https://github.com/marcomolinaleija/PlayAural.git'], check=True)
        subprocess.run(['git', '-C', str(repository), 'fetch', 'origin'], check=True)
        subprocess.run(['git', '-C', str(repository), 'checkout', '--detach', 'origin/main'], check=True)
    for key, value in (('user.name', 'PlayAural maintenance'), ('user.email', '141619450+marcomolinaleija@users.noreply.github.com')):
        subprocess.run(['git', '-C', str(repository), 'config', key, value], check=True)
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    if enable:
        subprocess.run(['systemctl', '--user', 'enable', '--now', 'playaural-update.timer', 'playaural-update-resume.timer'], check=True)
    print('Trusted PlayAural coordinator installed' + (' and timers enabled' if enable else '; timers not enabled by this command'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('/home/marco/apps/playaural'))
    parser.add_argument('--enable', action='store_true')
    args = parser.parse_args()
    install(args.root, Path(__file__).resolve().parent, enable=args.enable)
