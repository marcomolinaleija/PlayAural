"""Install only this app's trusted coordinator and user-level timers."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tomllib

from github_release import GitHub
from controller_revision import controller_is_newer, record_controller

PAYLOAD = ('autoupdate.py', 'agent_runner.py', 'codex_quota.py', 'deployment_gate.py', 'controller_revision.py',
           'github_release.py', 'sign_android.py', 'promote.sh', 'rollback.sh', 'install_autoupdate.py',
           'prepare_public_web_source.py')
UNITS = ('playaural-update.service', 'playaural-update.timer',
         'playaural-update-resume.service', 'playaural-update-resume.timer')


def install(root, source, *, enable=False, source_commit):
    os.umask(0o077)
    root, source = Path(root).resolve(), Path(source).resolve()
    if controller_is_newer(root, source_commit):
        if enable:
            subprocess.run(['systemctl', '--user', 'enable', '--now', 'playaural-update.timer', 'playaural-update-resume.timer'], check=True)
        print('Kept the newer trusted coordinator')
        return
    for directory in ('auto', 'auto/jobs', 'auto/credentials', 'auto/agent-home', 'ops/autoupdate'):
        path = root / directory
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o700)
    token = root / 'auto/credentials/github.token'
    if not token.is_file():
        raise RuntimeError('Install the private GitHub credential before enabling the coordinator')
    token.chmod(0o600)
    api = GitHub(token)
    key = root / 'auto/credentials/repository_ed25519'
    if not key.exists():
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', 'PlayAural VPS updater', '-f', str(key)], check=True)
    key.chmod(0o600)
    public = key.with_suffix('.pub').read_text().strip()
    identity = ' '.join(public.split()[:2])
    existing_keys = api.repo('keys')
    if not any(' '.join(item['key'].split()[:2]) == identity for item in existing_keys):
        api.repo('keys', 'POST', {'title': 'PlayAural VPS automatic updates', 'key': public, 'read_only': False})
    known_hosts = root / 'auto/credentials/known_hosts'
    known_hosts.write_text(''.join('github.com ' + value + '\n' for value in api.api('/meta')['ssh_keys']))
    known_hosts.chmod(0o600)
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
    subprocess.run(['git', '-C', str(repository), 'remote', 'set-url', 'origin', 'git@github.com:marcomolinaleija/PlayAural.git'], check=True)
    subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
    record_controller(root, source_commit)
    if enable:
        subprocess.run(['systemctl', '--user', 'enable', '--now', 'playaural-update.timer', 'playaural-update-resume.timer'], check=True)
    print('Trusted PlayAural coordinator installed' + (' and timers enabled' if enable else '; timers not enabled by this command'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('/home/marco/apps/playaural'))
    parser.add_argument('--enable', action='store_true')
    parser.add_argument('--source-commit', required=True)
    args = parser.parse_args()
    install(args.root, Path(__file__).resolve().parent, enable=args.enable, source_commit=args.source_commit)
