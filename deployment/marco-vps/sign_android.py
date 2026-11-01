"""Sign in a network-isolated SDK container; never log keystore passwords."""
import argparse
import json
import os
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('apk', type=Path)
parser.add_argument('output', type=Path)
parser.add_argument('--keystore', required=True, type=Path)
parser.add_argument('--config', required=True, type=Path)
parser.add_argument('--build-tools', required=True, type=Path)
args = parser.parse_args()
signing = json.loads(args.config.read_text())
environment = dict(os.environ, PLAYAURAL_SIGNING_PASSWORD=signing['password'])
aligned = Path('/tmp/playaural-aligned.apk')

def run(tool, *arguments, **kwargs):
    return subprocess.run([str(args.build_tools / tool), *map(str, arguments)],
                          check=True, env=environment, **kwargs)

run('zipalign', '-P', '16', '-f', '4', args.apk, aligned)
run('apksigner', 'sign', '--ks', args.keystore, '--ks-key-alias', signing['alias'],
    '--ks-pass', 'env:PLAYAURAL_SIGNING_PASSWORD', '--key-pass', 'env:PLAYAURAL_SIGNING_PASSWORD',
    '--out', args.output, aligned)
run('apksigner', 'verify', '--verbose', '--print-certs', args.output)
run('zipalign', '-c', '-P', '16', '4', args.output)
badging = run('aapt', 'dump', 'badging', args.output, capture_output=True, text=True).stdout
assert "package: name='com.marcoml.playaural'" in badging
for line in badging.splitlines():
    if line.startswith(('package:', 'application-label:', 'native-code:')):
        print(line)
