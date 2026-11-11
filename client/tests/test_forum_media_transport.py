"""Real authenticated desktop HTTP and the native codec's loopback bridge."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import pytest
import requests

from forum_media_transport import NativeMediaRelay, media_endpoint, media_file_url, save_file


@pytest.fixture
def source():
    state = {'allowed': True, 'requests': []}
    content = b'0123456789abcdef'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_GET(self):
            state['requests'].append(dict(self.headers))
            if not state['allowed'] or self.headers.get('Authorization') != 'Bearer example-credential':
                self.send_error(401)
                return
            start, end = 0, len(content) - 1
            partial = self.headers.get('Range')
            if partial:
                first, last = partial.removeprefix('bytes=').split('-')
                start, end = int(first), int(last) if last else end
            self.send_response(206 if partial else 200)
            self.send_header('Content-Length', str(end - start + 1))
            self.send_header('Content-Type', 'audio/mpeg')
            self.send_header('Accept-Ranges', 'bytes')
            if partial:
                self.send_header('Content-Range', f'bytes {start}-{end}/{len(content)}')
            self.end_headers()
            self.wfile.write(content[start:end + 1])
    http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=http.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{http.server_port}/forum-media'
    attachment_id = '0286290b-cb37-49d5-9bb8-00fda578c757'
    packet = {'base_url': base, 'token': 'example-credential', 'attachment': {
        'id': attachment_id, 'kind': 'audio', 'name': 'test.mp3', 'size': len(content)},
        'url': f'{base}/files/{attachment_id}'}
    yield packet, state
    http.shutdown()
    http.server_close()


def test_desktop_rejects_url_credentials_token_queries_and_nonlocal_plaintext():
    for base in ('file:///forum-media', 'http://remote.example/forum-media',
                 'https://user:password@example.test/forum-media', 'https://example.test/forum-media?token=secret'):
        with pytest.raises(ValueError):
            media_endpoint({'base_url': base, 'token': 'token'})


def test_relay_streams_with_authorization_and_rechecks_each_seek(source):
    packet, state = source
    relay = NativeMediaRelay(packet)
    try:
        assert relay.url.startswith('http://127.0.0.1:') and packet['token'] not in relay.url
        response = requests.get(relay.url, headers={'Range': 'bytes=3-7'}, timeout=5)
        assert response.status_code == 206 and response.content == b'34567'
        assert response.headers['Content-Range'] == 'bytes 3-7/16'
        assert response.headers['Cache-Control'] == 'private, no-store'
        assert state['requests'][-1]['Authorization'] == 'Bearer example-credential'
        assert requests.get(relay.url.rsplit('/', 1)[0] + '/other', timeout=5).status_code == 404
        state['allowed'] = False
        assert requests.get(relay.url, headers={'Range': 'bytes=8-'}, timeout=5).status_code == 403
    finally:
        relay.close()


def test_desktop_download_replaces_destination_only_after_complete_authorized_file(source, tmp_path):
    packet, state = source
    destination = tmp_path / 'saved.mp3'
    destination.write_bytes(b'old content')
    save_file(packet, destination, threading.Event())
    assert destination.read_bytes() == b'0123456789abcdef'
    packet['attachment']['size'] += 1
    with pytest.raises(ValueError, match='Incomplete'):
        save_file(packet, destination, threading.Event())
    assert destination.read_bytes() == b'0123456789abcdef'
    assert not list(tmp_path.glob('.playaural-download-*'))
    state['allowed'] = False
    with pytest.raises(ValueError):
        save_file(packet, destination, threading.Event())
    assert destination.read_bytes() == b'0123456789abcdef'


def test_desktop_never_accepts_an_arbitrary_file_or_upload_endpoint(source):
    packet, _ = source
    assert media_file_url(packet) == packet['url']
    with pytest.raises(ValueError):
        media_file_url({**packet, 'url': packet['url'] + '?token=credential'})
