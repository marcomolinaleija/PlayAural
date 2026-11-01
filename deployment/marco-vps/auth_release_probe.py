"""Check native authentication through TLS without owning an account session."""
import asyncio
import json
from pathlib import Path

from websockets.asyncio.client import connect


def validate_release(packet, manifest, target):
    if packet.get('type') != 'authorize_success' or packet.get('preferences') != {}:
        raise RuntimeError('Managed update-only authentication failed')
    expected = manifest['targets'][target]['application']
    info = packet.get('update_info', {})
    if packet.get('version') != manifest['version'] or info.get('version') != manifest['version']:
        raise RuntimeError('Native protocol version does not match the release')
    if not info.get('available') or info.get('target') != target or info.get('url') != expected['url']:
        raise RuntimeError('Native delivery does not match the release')
    if expected.get('sha256') and info.get('hash') != expected['sha256']:
        raise RuntimeError('Native checksum does not match the release')
    if info.get('build_id', '') != expected.get('build_id', ''):
        raise RuntimeError('Native source identity does not match the release')


async def main():
    credentials = json.loads(Path('/config/operator.json').read_text())
    manifest = json.loads(Path('/config/releases.json').read_text())
    for client, target in (('python', 'windows'), ('mobile', 'android')):
        async with connect('wss://play.marco-ml.com/ws', open_timeout=15) as socket:
            await socket.send(json.dumps({'type': 'authorize', 'client': client, 'release_platform': target,
                                         'version': '__maintenance_update_only__',
                                         'username': credentials['username'], 'password': credentials['password']}))
            packet = json.loads(await asyncio.wait_for(socket.recv(), timeout=15))
            validate_release(packet, manifest, target)
            await socket.send(json.dumps({'type': 'ping'}))
            try:
                await asyncio.wait_for(socket.recv(), timeout=0.25)
            except asyncio.TimeoutError:
                pass
            else:
                raise RuntimeError('Maintenance connection unexpectedly owns a live session')
    print(json.dumps({'authenticated_update_probe': True, 'targets': ['windows', 'android'], 'version': manifest['version']}))


if __name__ == '__main__':
    asyncio.run(main())
