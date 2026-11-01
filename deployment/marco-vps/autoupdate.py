"""Durable VPS coordinator. Builders/agents never receive production credentials."""
import argparse
import ast
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import signal
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile

from agent_runner import BUILDER, container_status, integration_prompt, start_agent
from codex_quota import read_quota
from controller_revision import controller_is_newer
from deployment_gate import idle_status
from github_release import GitHub, REPOSITORY, extract_windows_artifact, sha256


SCRIPTS = Path(__file__).resolve().parent
SHA = re.compile(r'^[0-9a-f]{40}$')
STOP_REQUESTED = False


def request_stop(signum, frame):
    global STOP_REQUESTED
    STOP_REQUESTED = True


def atomic_json(path, value):
    path = Path(path)
    descriptor, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    temporary = Path(name)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
        json.dump(value, output, indent=2)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def constants(path):
    values = {}
    for node in ast.parse(Path(path).read_text(encoding='utf-8')).body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    values[target.id] = node.value.value
    return values


class Coordinator:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.auto = self.root / 'auto'
        self.repository = self.auto / 'repository'
        self.api = GitHub(self.auto / 'credentials/github.token')
        self.state_path = self.auto / 'state.json'
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else None

    def save(self, job):
        job['updated_at'] = time.time()
        atomic_json(self.state_path, job)
        atomic_json(self.job_dir(job) / 'state.json', job)
        self.state = job

    def job_dir(self, job):
        return self.auto / 'jobs' / job['id']

    def git(self, *arguments, check=True):
        environment = dict(os.environ, GIT_NO_REPLACE_OBJECTS='1', GIT_TERMINAL_PROMPT='0',
                           GIT_ASKPASS=str(self.auto / 'credentials/askpass'), GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null')
        environment['GIT_SSH_COMMAND'] = shlex.join(['ssh', '-i', str(self.auto / 'credentials/repository_ed25519'),
                                                   '-o', 'IdentitiesOnly=yes', '-o', 'StrictHostKeyChecking=yes',
                                                   '-o', 'UserKnownHostsFile=' + str(self.auto / 'credentials/known_hosts')])
        result = subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', '-c', 'core.fsmonitor=false',
                                 '-C', str(self.repository), *arguments], capture_output=True, text=True, env=environment)
        if check and result.returncode:
            raise RuntimeError('Git operation failed: ' + arguments[0] + '\n' + result.stderr[-2000:])
        return result

    def head(self, ref='HEAD'):
        value = self.git('rev-parse', ref).stdout.strip()
        if not SHA.fullmatch(value):
            raise ValueError('Expected a full Git commit')
        return value

    def ancestor(self, older, newer):
        result = self.git('merge-base', '--is-ancestor', older, newer, check=False)
        if result.returncode not in (0, 1):
            raise RuntimeError('Could not verify Git ancestry')
        return result.returncode == 0

    def quota(self, job):
        try:
            quota = read_quota(env=dict(os.environ, CODEX_HOME=str(self.auto / 'agent-home')))
        except Exception as error:
            # A reader failure must also stop an already-running model process.
            quota = {'allowed': False, 'remaining_percent': None, 'error': type(error).__name__}
        atomic_json(self.auto / 'quota.json', quota)
        job['quota_checked_at'] = time.time()
        if not quota['allowed']:
            job['quota_deferred'] = True
            job['last_error'] = ('Codex usage unavailable' if quota.get('error') else 'Codex reserve reached') + '; candidate preserved and production unchanged'
            self.save(job)
            return False
        job.pop('quota_deferred', None)
        return True

    def current_release(self):
        values = dict(line.split('=', 1) for line in (self.root / 'current.env').read_text().splitlines() if '=' in line)
        return values['RELEASE_ID']

    def create_job(self, bootstrap=False):
        if self.git('status', '--porcelain').stdout.strip():
            raise RuntimeError('Unowned dirty candidate tree; preserving it for inspection')
        self.git('fetch', 'origin')
        if self.git('remote', 'get-url', 'upstream', check=False).returncode:
            self.git('remote', 'add', 'upstream', 'https://github.com/Daoductrung/PlayAural.git')
        self.git('fetch', 'upstream', 'main')
        base = self.head('origin/main')
        upstream = self.head('upstream/main')
        develop = self.head('origin/develop')
        release = self.current_release() != base
        if not release and self.ancestor(upstream, develop) and self.ancestor(base, develop):
            return None
        identifier = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
        job = {'id': identifier, 'phase': 'ci' if release else 'agent',
               'kind': 'release' if release else 'integration',
               'base': base if release else develop, 'main': base, 'upstream': upstream,
               'branch': 'main' if release else 'feature/upstream-' + identifier,
               'created_at': time.time(), 'agent_attempt': 0,
               'bootstrap': bootstrap, 'previous_release': self.current_release()}
        if release:
            job['candidate'] = base
        job['git_config_sha256'] = sha256(self.repository / '.git/config')
        self.job_dir(job).mkdir(mode=0o700)
        if not release:
            self.git('checkout', '-b', job['branch'], develop)
        self.save(job)
        return job

    def repair(self, job, reason, log=''):
        if job.get('kind') == 'release':
            (self.job_dir(job) / 'failure.log').write_text(log[-40000:], encoding='utf-8')
            job.update(phase='deferred', last_error=reason + '; fix develop or a hotfix and merge into main before retrying')
            self.save(job)
            return False
        if job.get('repair_count', 0) >= 2:
            job.update(phase='deferred', last_error=reason)
            self.save(job)
            return False
        (self.job_dir(job) / 'failure.log').write_text(log[-40000:], encoding='utf-8')
        if 'promotion_unit' in job:
            job['promotion_attempt'] = job.get('promotion_attempt', 0) + 1
        job['promotion_failures'] = 0
        job.update(phase='agent', correction=reason + '\nRead /results/failure.log for the bounded failure log.',
                   agent_attempt=job['agent_attempt'] + 1, previous_candidate=job.get('candidate'), repair_count=job.get('repair_count', 0) + 1)
        for key in ('candidate', 'windows_run', 'windows_requested_at', 'windows_dispatch_ref', 'windows_downloaded',
                    'android_container', 'android_code', 'published', 'promotion_unit'):
            job.pop(key, None)
        self.save(job)
        return True

    def agent(self, job):
        name = 'playaural-update-agent-' + job['id'].lower() + '-' + str(job['agent_attempt'])
        status = container_status(name)
        if status is None:
            self.check_agent_files(job)
            if not self.quota(job):
                return False
            start_agent(self.root, self.repository, self.job_dir(job), name,
                        integration_prompt(job['upstream'], job['base'], job.get('correction', ''),
                                           main=job.get('main') if job.get('kind') == 'integration' else None))
            self.save(job)
            return False
        if status['Running']:
            if time.time() - job.get('quota_checked_at', 0) >= 60 and not self.quota(job):
                subprocess.run(['docker', 'stop', '--signal', 'SIGINT', '--time', '30', name], check=False, capture_output=True)
                stopped = container_status(name)
                if stopped is not None and not stopped['Running']:
                    job['agent_attempt'] += 1
                self.save(job)
            return False
        self.check_agent_files(job)
        log = subprocess.check_output(['docker', 'logs', name], stderr=subprocess.STDOUT, text=True)
        (self.job_dir(job) / f"agent-{job['agent_attempt']}.jsonl").write_text(log, encoding='utf-8')
        if status['ExitCode'] != 0:
            return self.repair(job, 'Integration agent stopped before producing a verified result', log)
        result = json.loads((self.job_dir(job) / 'result.json').read_text())
        if result.get('decision') != 'ready':
            job.update(phase='deferred', last_error=result.get('summary', 'Agent requested deferral'))
            self.save(job)
            return False
        if self.git('status', '--porcelain').stdout.strip():
            return self.repair(job, 'Agent left uncommitted changes; review and finish the candidate', log)
        candidate = self.head()
        if not self.ancestor(job['base'], candidate) or not self.ancestor(job['upstream'], candidate):
            return self.repair(job, 'Candidate does not preserve both approved fork and upstream history', log)
        if job.get('kind') == 'integration' and not self.ancestor(job['main'], candidate):
            return self.repair(job, 'Integration must also preserve approved main history', log)
        protected = self.git('diff', '--name-only', job['base'], candidate, '--', 'deployment/marco-vps', '.github/workflows/marco*').stdout.strip()
        if protected:
            job.update(phase='deferred', last_error='Integration changes trusted controller files: ' + protected)
            self.save(job)
            return False
        if job.get('previous_candidate') == candidate:
            job.update(phase='deferred', last_error='Repair did not change the failing candidate')
            self.save(job)
            return False
        self.git('push', 'origin', 'HEAD:refs/heads/' + job['branch'])
        if candidate != job['base'] and job.get('kind') != 'integration':
            existing = self.api.repo('pulls?' + urllib.parse.urlencode({'head': REPOSITORY.split('/')[0] + ':' + job['branch'], 'state': 'open'}))
            pr = existing[0] if existing else self.api.repo('pulls', 'POST', {
                'title': 'Actualizar PlayAural desde upstream ' + job['upstream'][:8],
                'head': job['branch'], 'base': 'main',
                'body': 'Integración automática preparada por el agente aislado del VPS.\n\n' + result['summary'] + '\n\nEl controlador exige CI completo y artefactos verificados antes de desplegar.'})
            job['pull_request'] = pr['html_url']
        job.update(candidate=candidate, phase='ci', summary=result['summary'])
        self.save(job)
        return True

    def check_agent_files(self, job):
        if sha256(self.repository / '.git/config') != job['git_config_sha256']:
            raise RuntimeError('Agent changed protected Git configuration')
        for directory, folders, files in os.walk(self.job_dir(job), followlinks=False):
            for name in folders + files:
                path = Path(directory) / name
                mode = path.lstat()
                if stat.S_ISLNK(mode.st_mode) or not (stat.S_ISREG(mode.st_mode) or stat.S_ISDIR(mode.st_mode)):
                    raise RuntimeError('Unsafe file in isolated agent results')
                if stat.S_ISREG(mode.st_mode) and mode.st_nlink != 1:
                    raise RuntimeError('Hard-linked agent results are not allowed')

    def ci(self, job):
        query = urllib.parse.urlencode({'head_sha': job['candidate'], 'per_page': 30})
        runs = self.api.repo('actions/workflows/marco-ci.yml/runs?' + query)['workflow_runs']
        if not runs:
            return False
        run = runs[0]
        job['ci_run'] = run['id']
        if run['status'] != 'completed':
            self.save(job)
            return False
        if run['conclusion'] != 'success':
            archive = self.job_dir(job) / f"ci-{run['id']}.zip"
            self.api.download(f"/repos/{REPOSITORY}/actions/runs/{run['id']}/logs", archive, limit=100 * 1024**2)
            with zipfile.ZipFile(archive) as logs:
                failure_log = '\n'.join(logs.read(name).decode('utf-8', 'replace')[-10000:] for name in logs.namelist() if not name.endswith('/'))
            return self.repair(job, 'CI rejected candidate ' + job['candidate'], failure_log)
        self.git('fetch', 'origin')
        main = self.head('origin/main')
        if job.get('kind') == 'integration':
            develop = self.head('origin/develop')
            if not self.ancestor(main, job['candidate']):
                job['main'] = main
                job['base'] = develop
                return self.repair(job, 'Main advanced. Merge the new main and develop bases as well as upstream, preserving all three histories.')
            if develop != job['candidate']:
                if develop != job['base']:
                    job['base'] = develop
                    job['main'] = main
                    return self.repair(job, 'Develop advanced. Merge the new develop and main bases as well as upstream, preserving all three histories.')
                self.git('push', 'origin', job['candidate'] + ':refs/heads/develop')
            job.update(phase='done', completed_at=time.time(), last_error='', integrated_ref='develop')
            self.save(job)
            print('Upstream integration verified on develop; production unchanged: ' + job['candidate'])
            return False
        if job.get('kind') == 'release':
            if not self.ancestor(job['candidate'], main):
                return self.repair(job, 'The approved release no longer belongs to main')
            job['phase'] = 'windows'
            self.save(job)
            return True
        if main != job['candidate']:
            if main != job['base']:
                job['base'] = main
                return self.repair(job, 'Fork main advanced. Merge the new approved fork base as well as upstream, preserve both histories, and commit the refreshed integration.')
            self.git('push', 'origin', job['candidate'] + ':refs/heads/main')
        job['phase'] = 'windows'
        self.save(job)
        return True

    def windows(self, job):
        if 'windows_run' not in job:
            if 'windows_requested_at' not in job:
                job['windows_requested_at'] = time.time()
                self.save(job)
                self.api.repo('actions/workflows/marco-windows-release.yml/dispatches', 'POST', {
                    'ref': job['branch'], 'inputs': {'source_ref': job['candidate']}})
            query = urllib.parse.urlencode({'head_sha': job['candidate'], 'event': 'workflow_dispatch', 'per_page': 30})
            runs = self.api.repo('actions/workflows/marco-windows-release.yml/runs?' + query)['workflow_runs']
            matching = [run for run in runs if datetime.fromisoformat(run['created_at'].replace('Z', '+00:00')).timestamp() >= job['windows_requested_at'] - 5]
            if not matching:
                if time.time() - job['windows_requested_at'] > 600:
                    job.pop('windows_requested_at')
                    self.save(job)
                return False
            job['windows_run'] = matching[0]['id']
            self.save(job)
        run = self.api.repo(f"actions/runs/{job['windows_run']}")
        if run['status'] != 'completed':
            return False
        if run['conclusion'] != 'success':
            return self.repair(job, 'Windows release build failed; fix runtime source or defer if trusted tooling must change', json.dumps(run))
        artifacts = self.api.repo(f"actions/runs/{job['windows_run']}/artifacts")['artifacts']
        artifact = next(item for item in artifacts if item['name'].startswith('windows-') and not item['expired'])
        archive = self.job_dir(job) / 'windows-artifact.zip'
        self.api.download(f"/repos/{REPOSITORY}/actions/artifacts/{artifact['id']}/zip", archive)
        metadata = extract_windows_artifact(archive, self.job_dir(job) / 'windows', job['candidate'])
        job.update(phase='android', windows_metadata=metadata)
        self.save(job)
        return True

    def android(self, job):
        if 'android_code' not in job:
            manifest = json.loads((self.root / 'config/releases.json').read_text())
            counter_path = self.auto / 'android-counter.json'
            counter = json.loads(counter_path.read_text()) if counter_path.exists() else {'last': 0}
            code = max(counter['last'], manifest.get('android_version_code', 0)) + 1
            atomic_json(counter_path, {'last': code})
            job['android_code'] = code
            job['android_container'] = 'playaural-update-android-' + job['id'].lower() + '-' + str(job['agent_attempt'])
            self.save(job)
        name = job['android_container']
        status = container_status(name)
        code = self.root / 'build/android-source'
        if status is None:
            if shutil.disk_usage(self.root).free < 20 * 1024**3:
                raise RuntimeError('Android builder needs 20 GiB free; current production retained')
            if subprocess.check_output(['git', '-C', str(code), 'status', '--porcelain'], text=True).strip():
                raise RuntimeError('Android build checkout has unowned tracked changes')
            subprocess.run(['git', '-C', str(code), 'fetch', 'origin'], check=True, capture_output=True)
            subprocess.run(['git', '-C', str(code), 'checkout', '--detach', job['candidate']], check=True, capture_output=True)
            command = ['docker', 'run', '-d', '--name', name, '--user', '0', '--cpus', '3', '--memory', '8g',
                       '--memory-swap', '8g', '--pids-limit', '1024', '-v', f'{code}:/workspace',
                       '-v', 'playaural-android-sdk:/home/circleci/android-sdk', '-v', 'playaural-android-gradle:/root/.gradle',
                       '-e', 'PLAYAURAL_ANDROID_VERSION_CODE=' + str(job['android_code']), '-w', '/workspace',
                       BUILDER, 'bash', '/workspace/deployment/marco-vps/build-android.sh']
            subprocess.run(command, check=True, capture_output=True)
            return False
        if status['Running']:
            return False
        log = subprocess.check_output(['docker', 'logs', name], stderr=subprocess.STDOUT, text=True)
        (self.job_dir(job) / 'android-build.log').write_text(log, encoding='utf-8')
        if status['ExitCode'] != 0:
            return self.repair(job, 'Android build failed; review /results/failure.log and fix runtime source', log)
        if subprocess.check_output(['git', '-C', str(code), 'status', '--porcelain'], text=True).strip():
            raise RuntimeError('Android build modified tracked sources; package is not reproducible')
        job['phase'] = 'sign'
        self.save(job)
        return True

    def sign(self, job):
        output = self.job_dir(job) / 'signed'
        output.mkdir(mode=0o700, exist_ok=True)
        code = self.root / 'build/android-source'
        command = ['docker', 'run', '--rm', '--network', 'none', '--user', '0', '--cpus', '2', '--memory', '2g',
                   '-v', f'{code}:/workspace:ro', '-v', f'{output}:/signed',
                   '-v', 'playaural-android-sdk:/home/circleci/android-sdk:ro',
                   '-v', f'{SCRIPTS}/sign_android.py:/sign_android.py:ro',
                   '-v', f'{self.root}/config/playaural-marco.jks:/signing/key.jks:ro',
                   '-v', f'{self.root}/config/signing.json:/signing/config.json:ro', BUILDER,
                   'python3', '/sign_android.py', '/workspace/mobile_client/android/app/build/outputs/apk/release/app-release.apk',
                   '/signed/PlayAural.apk', '--keystore', '/signing/key.jks', '--config', '/signing/config.json',
                   '--build-tools', '/home/circleci/android-sdk/build-tools/36.0.0']
        result = subprocess.run(command, capture_output=True, text=True)
        (self.job_dir(job) / 'signing.log').write_text(result.stdout + result.stderr, encoding='utf-8')
        if (result.returncode or f"versionCode='{job['android_code']}'" not in result.stdout
                or f"versionName='{job['windows_metadata']['version']}'" not in result.stdout):
            raise RuntimeError('Android signing or version verification failed')
        expected_cert = '3657e4d8fdd4b31537eb80c327701cf65385d70b9e2caabd2bb6be5a1afc8748'
        if 'certificate SHA-256 digest: ' + expected_cert not in result.stdout:
            raise RuntimeError('Android signing certificate changed')
        with zipfile.ZipFile(output / 'PlayAural.apk') as archive:
            if archive.testzip() is not None:
                raise ValueError('APK integrity check failed')
            if job['candidate'].encode() not in archive.read('assets/PlayAural-SOURCE.txt'):
                raise ValueError('APK source notice does not match')
            bundle = archive.read('assets/index.android.bundle')
            if job['windows_metadata'].get('build_id') and job['candidate'].encode() not in bundle:
                raise ValueError('APK compiled build identity does not match')
            english = json.loads((code / 'mobile_client/locales/en/client.json').read_text())
            for key in ('chat-local', 'chat-global'):
                if english[key].encode() not in bundle:
                    raise ValueError('APK contains stale chat translations')
            if b'wss://play.marco-ml.com' not in bundle:
                raise ValueError('APK does not use this deployment')
            for abi in ('arm64-v8a', 'armeabi-v7a', 'x86', 'x86_64'):
                if not any(name.startswith('lib/' + abi + '/') for name in archive.namelist()):
                    raise ValueError('APK missing architecture ' + abi)
        job['phase'] = 'publish'
        self.save(job)
        return True

    def publish(self, job):
        source = self.root / 'build/android-source'
        expected = constants(source / 'server/core/server.py')
        metadata = job['windows_metadata']
        if metadata['version'] != expected['VERSION'] or metadata['sounds_version'] != expected['SOUNDS_VERSION']:
            raise ValueError('Native/server versions are not coordinated')
        destination = self.root / 'downloads' / job['candidate']
        staging = self.root / 'downloads' / ('.candidate-' + job['id'])
        if not destination.exists():
            if staging.is_symlink():
                raise ValueError('Staging directories cannot be symlinks')
            staging.mkdir(mode=0o755, exist_ok=True)
            staging.chmod(0o755)
            for name in ('PlayAural.zip', 'sounds.zip'):
                shutil.copy2(self.job_dir(job) / 'windows' / name, staging / name)
            shutil.copy2(self.job_dir(job) / 'signed/PlayAural.apk', staging / 'PlayAural.apk')
            with (staging / 'source.tar.gz').open('wb') as output:
                subprocess.run(['git', '-C', str(source), 'archive', '--format=tar.gz', '--prefix=PlayAural/', job['candidate']], stdout=output, check=True)
            hashes = {name: sha256(staging / name) for name in ('PlayAural.zip', 'sounds.zip', 'PlayAural.apk', 'source.tar.gz')}
            base = 'https://play.marco-ml.com/downloads/' + job['candidate']
            manifest = {'source_commit': job['candidate'], 'version': metadata['version'], 'sounds_version': metadata['sounds_version'],
                        'android_version_code': job['android_code'], 'windows_run_id': job['windows_run'], 'sha256': hashes,
                        'targets': {'windows': {'application': {'url': base + '/PlayAural.zip', 'delivery': 'windows_zip', 'sha256': hashes['PlayAural.zip']},
                                                'sounds': {'url': base + '/sounds.zip', 'delivery': 'windows_zip', 'sha256': hashes['sounds.zip']}},
                                    'android': {'application': {'url': base + '/PlayAural.apk', 'delivery': 'browser'},
                                                'sounds': {'url': base + '/PlayAural.apk', 'delivery': 'browser'}}}}
            if metadata.get('build_id'):
                if metadata['build_id'] != job['candidate']:
                    raise ValueError('Native build identity does not match approved source')
                for target in ('windows', 'android'):
                    manifest['targets'][target]['application']['build_id'] = metadata['build_id']
            (staging / 'release.json').write_text(json.dumps(manifest, indent=2) + '\n')
            (staging / 'SHA256SUMS.txt').write_text(''.join(f'{value}  {name}\n' for name, value in hashes.items()))
            for path in staging.iterdir():
                path.chmod(0o644)
                with path.open('rb') as saved:
                    os.fsync(saved.fileno())
            staging.rename(destination)
        if destination.is_symlink() or not destination.is_dir():
            raise ValueError('Release directories must be regular directories')
        manifest = json.loads((destination / 'release.json').read_text())
        if manifest['source_commit'] != job['candidate'] or manifest['android_version_code'] != job['android_code']:
            raise ValueError('Existing immutable release does not match this job')
        destination.chmod(0o755)
        for name, expected_hash in manifest['sha256'].items():
            if sha256(destination / name) != expected_hash:
                raise ValueError('Published artifact failed checksum verification')
            url = 'https://play.marco-ml.com/downloads/' + job['candidate'] + '/' + name
            if job.get('verified_downloads', {}).get(url) != expected_hash:
                downloaded = hashlib.sha256()
                with urllib.request.urlopen(url, timeout=120) as response:
                    while chunk := response.read(1024 * 1024):
                        downloaded.update(chunk)
                if downloaded.hexdigest() != expected_hash:
                    raise ValueError('Public HTTPS artifact checksum mismatch')
                job.setdefault('verified_downloads', {})[url] = expected_hash
                self.save(job)
        job['phase'] = 'await_idle'
        self.save(job)
        return True

    def await_idle(self, job):
        if not self.quota(job):
            return False
        if not job.get('bootstrap'):
            try:
                idle_status(self.root)
            except (OSError, RuntimeError, ValueError, KeyError) as error:
                job['last_error'] = str(error)
                self.save(job)
                return False
        attempt = job.get('promotion_attempt', 0)
        unit = 'playaural-promote-' + job['id'].lower() + '-' + str(attempt)
        job.update(phase='promoting', promotion_unit=unit)
        self.save(job)
        return self.promoting(job)

    def unit_status(self, unit):
        result = subprocess.run(['systemctl', '--user', 'show', unit, '-p', 'LoadState', '-p', 'ActiveState', '-p', 'SubState', '-p', 'ExecMainStatus'], capture_output=True, text=True)
        return dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)

    def promoting(self, job):
        unit = job['promotion_unit']
        status = self.unit_status(unit)
        if status.get('LoadState') == 'not-found' or not status:
            if self.current_release() == job['candidate']:
                job['phase'] = 'verify'
                self.save(job)
                return True
            command = ['systemd-run', '--user', '--no-block', '--unit=' + unit, '--property=Type=oneshot', '--property=RemainAfterExit=yes',
                       '--property=TimeoutStartSec=3600', '--property=KillMode=process', '--setenv=PLAYAURAL_AUTOMATED_DEPLOYMENT=1']
            if job.get('bootstrap'):
                command.append('--setenv=PLAYAURAL_BOOTSTRAP_IDLE=1')
            command += ['bash', str(SCRIPTS / 'promote.sh'), job['candidate'], str(self.root / 'downloads' / job['candidate'] / 'release.json')]
            subprocess.run(command, check=True, capture_output=True)
            return False
        if status.get('ActiveState') in ('activating', 'reloading') or status.get('SubState') == 'running':
            return False
        if status.get('ExecMainStatus') == '75':
            job.update(phase='await_idle', promotion_attempt=job.get('promotion_attempt', 0) + 1)
            self.save(job)
            return False
        if status.get('ActiveState') == 'failed' or status.get('ExecMainStatus') != '0':
            if job.get('promotion_failures', 0) < 1:
                job.update(phase='await_idle', promotion_failures=job.get('promotion_failures', 0) + 1,
                           promotion_attempt=job.get('promotion_attempt', 0) + 1,
                           last_error='Previous promotion failed and rolled back; one bounded retry preserves the approved artifacts')
                self.save(job)
                return False
            logs = subprocess.check_output(['journalctl', '--user', '-u', unit, '-n', '250', '--no-pager'], text=True)
            return self.repair(job, 'Promotion failed and its transaction attempted rollback; inspect the bounded log', logs)
        job['phase'] = 'verify'
        self.save(job)
        return True

    def verify(self, job):
        if self.current_release() != job['candidate']:
            raise RuntimeError('Active release does not match the promoted candidate')
        active = json.loads((self.root / 'config/releases.json').read_text())
        if active['source_commit'] != job['candidate']:
            raise RuntimeError('Active native manifest does not match the promoted source')
        state = subprocess.check_output(['docker', 'inspect', '--format', '{{json .State}}', 'playaural-game-1'], text=True)
        state = json.loads(state)
        if not state['Running'] or state.get('Health', {}).get('Status') != 'healthy':
            return False
        for container, expected_image in (('playaural-game-1', 'playaural-game:'), ('playaural-web-1', 'playaural-web:')):
            image = subprocess.check_output(['docker', 'inspect', '--format', '{{.Config.Image}}', container], text=True).strip()
            if image != expected_image + job['candidate']:
                raise RuntimeError('Runtime image does not match the approved source')
        with urllib.request.urlopen('https://play.marco-ml.com/health', timeout=20) as response:
            if response.status != 200:
                raise RuntimeError('Public web health check failed')
        with urllib.request.urlopen('https://play.marco-ml.com/downloads/' + job['candidate'] + '/release.json', timeout=20) as response:
            if json.load(response)['source_commit'] != job['candidate']:
                raise RuntimeError('Public native manifest is not the approved release')
        version = active['version']
        revision = job['candidate']
        html = f'''<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>PlayAural Marco: descargas</title><style>body{{font:18px/1.6 system-ui;max-width:48rem;margin:3rem auto;padding:1rem;background:#101620;color:#f2f5fa}}a{{color:#9bd4ff}}li{{margin:1rem 0}}</style><main><h1>PlayAural Marco</h1><p><a href="/">Jugar desde el navegador</a></p><p>Versión {version}. Compilada desde las fuentes verificadas de esta instancia.</p><ul><li><a href="{revision}/PlayAural.zip">Windows de 64 bits: ZIP portátil</a>. Extrae la carpeta completa y ejecuta PlayAural.exe.</li><li><a href="{revision}/PlayAural.apk">Android: APK</a>. Instálalo sobre PlayAural Marco para conservar sus datos. Android solicita confirmar la instalación.</li></ul><p><a href="{revision}/source.tar.gz">Código fuente de esta entrega</a> · <a href="{revision}/SHA256SUMS.txt">Sumas SHA-256</a> · <a href="/licenses/LICENSE">Licencia GPL</a> · <a href="/licenses/THIRD_PARTY_NOTICES.md">Avisos de terceros</a></p><p>Las actualizaciones de servidor y descargas se preparan automáticamente. Los clientes de esta entrega detectan también las correcciones que conservan el número de versión. Android solicita confirmar la instalación de cada APK.</p></main></html>'''
        index = self.root / 'downloads/.index-auto.next'
        index.write_text(html, encoding='utf-8')
        index.chmod(0o644)
        index.replace(self.root / 'downloads/index.html')
        source_link = self.root / 'downloads/.source-auto.next'
        if source_link.is_symlink():
            source_link.unlink()
        source_link.symlink_to(revision + '/source.tar.gz')
        source_link.replace(self.root / 'downloads/source.tar.gz')
        if controller_is_newer(self.root, revision):
            subprocess.run(['systemctl', '--user', 'enable', '--now', 'playaural-update.timer', 'playaural-update-resume.timer'], check=True)
        else:
            installer = self.root / 'releases' / revision / 'deployment/marco-vps/install_autoupdate.py'
            subprocess.run(['python3', str(installer), '--root', str(self.root), '--enable', '--source-commit', revision], check=True)
        subprocess.run(['systemctl', '--user', 'start', '--no-block', 'playaural-b2-upload.service'], check=True)
        job.update(phase='done', completed_at=time.time(), last_error='')
        self.save(job)
        print('Coordinated release verified: ' + revision)
        return False

    def advance(self, job):
        return getattr(self, job['phase'])(job)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path('/home/marco/apps/playaural'))
    parser.add_argument('--resume-only', action='store_true')
    parser.add_argument('--run-through', action='store_true')
    parser.add_argument('--bootstrap', action='store_true', help='Operator-only first migration of legacy release 49a80c60')
    parser.add_argument('--status', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    coordinator = Coordinator(args.root)
    if args.status:
        print(json.dumps(coordinator.state, indent=2))
        return
    with (coordinator.auto / 'controller.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        job = coordinator.state
        if job and job['phase'] == 'deferred' and job.get('kind') == 'release' and not args.resume_only:
            coordinator.git('fetch', 'origin')
            if coordinator.head('origin/main') != job['candidate']:
                job = None
        if not job or job['phase'] == 'done':
            if args.resume_only:
                return
            job = coordinator.create_job(bootstrap=args.bootstrap)
        if not job or job['phase'] == 'deferred':
            return
        deadline = time.monotonic() + 3 * 3600
        while not STOP_REQUESTED and time.monotonic() < deadline:
            try:
                changed = coordinator.advance(job)
            except (OSError, RuntimeError, ValueError, KeyError, StopIteration, subprocess.SubprocessError) as error:
                job['last_error'] = type(error).__name__ + ': ' + str(error)
                coordinator.save(job)
                print('Candidate preserved; retry pending: ' + job['last_error'], file=sys.stderr)
                return
            if job['phase'] in ('done', 'deferred'):
                return
            if job.get('quota_deferred'):
                return
            if not changed:
                if not args.run_through:
                    return
                time.sleep(15)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    main()
