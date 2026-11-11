"""Authenticated forum binary transport, independent of wx and game audio."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import secrets
import tempfile
import threading
from urllib.parse import urlsplit
from uuid import UUID

import requests

MAX_BYTES = 128 * 1024 * 1024
CHUNK = 256 * 1024


class MediaUserError(ValueError):
    pass


def media_endpoint(packet: dict) -> str:
    base = packet.get('base_url', '')
    if not isinstance(base, str) or len(base) > 2048:
        raise ValueError('Invalid media endpoint')
    parsed = urlsplit(base)
    if (parsed.scheme not in {'https', 'http'} or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path != '/forum-media'
            or parsed.scheme == 'http' and parsed.hostname not in {'127.0.0.1', 'localhost', '::1'}):
        raise ValueError('Invalid media endpoint')
    token = packet.get('token')
    if not isinstance(token, str) or not 1 <= len(token) <= 100 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ValueError('Invalid media credential')
    return base


def media_file_url(packet: dict) -> str:
    base = media_endpoint(packet)
    attachment_id = packet.get('attachment', {}).get('id', '')
    if str(UUID(attachment_id)) != attachment_id:
        raise ValueError('Invalid attachment')
    expected = f'{base}/files/{attachment_id}'
    if packet.get('url') != expected:
        raise ValueError('Unexpected media URL')
    return expected


def request(packet, method: str, url: str, **kwargs):
    response = requests.request(method, url, headers={'Authorization': 'Bearer ' + packet['token'],
                                **kwargs.pop('headers', {})}, timeout=(10, 60), allow_redirects=False, **kwargs)
    if response.status_code not in {200, 201, 202, 206}:
        try:
            message = response.json().get('message', '')
        except (ValueError, AttributeError):
            message = ''
        response.close()
        if isinstance(message, str) and 0 < len(message) <= 1024:
            raise MediaUserError(message)
        raise ValueError('Forum binary request rejected')
    return response


def upload_file(packet: dict, path: Path, cancelled: threading.Event) -> None:
    base = media_endpoint(packet)
    size = path.stat().st_size
    if not 0 < size <= MAX_BYTES:
        raise MediaUserError(packet['labels'].get('size_error', packet['labels']['error']))
    if cancelled.is_set():
        return
    with request(packet, 'POST', base + '/uploads', json={'draft_token': packet['draft_token'], 'name': path.name, 'size': size}) as response:
        reservation = response.json()
    attachment_id = reservation['id']
    if str(UUID(attachment_id)) != attachment_id or reservation['upload_url'] != f'{base}/uploads/{attachment_id}':
        raise ValueError('Unexpected upload endpoint')
    if cancelled.is_set():
        return
    with path.open('rb') as stream:
        with request(packet, 'PUT', reservation['upload_url'], data=stream, headers={'Content-Length': str(size)}):
            pass


def content_bytes(packet: dict) -> bytes:
    url = media_file_url(packet)
    chunks, total = [], 0
    with request(packet, 'GET', url, stream=True) as response:
        for chunk in response.iter_content(CHUNK):
            total += len(chunk)
            if total > MAX_BYTES:
                raise ValueError('Media exceeds size limit')
            chunks.append(chunk)
    return b''.join(chunks)


def caption_bytes(packet: dict) -> bytes:
    expected = media_file_url(packet) + '/captions'
    if packet.get('captions_url') != expected:
        raise ValueError('Unexpected captions URL')
    with request(packet, 'GET', expected, stream=True) as response:
        chunks, total = [], 0
        for chunk in response.iter_content(CHUNK):
            total += len(chunk)
            if total > 2 * 1024 * 1024:
                raise ValueError('Captions exceed size limit')
            chunks.append(chunk)
        return b''.join(chunks)


def save_file(packet: dict, destination: Path, cancelled: threading.Event) -> None:
    url = media_file_url(packet)
    fd, temporary = tempfile.mkstemp(prefix='.playaural-download-', dir=destination.parent)
    try:
        total = 0
        with os.fdopen(fd, 'wb') as target, request(packet, 'GET', url, stream=True) as response:
            for chunk in response.iter_content(CHUNK):
                if cancelled.is_set():
                    return
                total += len(chunk)
                if total > MAX_BYTES:
                    raise ValueError('Media exceeds size limit')
                target.write(chunk)
            if total != packet['attachment']['size']:
                raise ValueError('Incomplete download')
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


class NativeMediaRelay:
    """An ephemeral loopback bridge for native codecs without HTTP auth headers.

    The random local path is not a remote capability: every upstream request
    still rechecks the owning session and the post's current permissions.
    """

    def __init__(self, packet: dict):
        self.packet = packet
        self.upstream = media_file_url(packet)
        suffix = '.mp3' if packet['attachment']['kind'] == 'audio' else '.mp4'
        self.path = '/' + secrets.token_urlsafe(32) + '/media' + suffix
        self.stopped = threading.Event()
        relay = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                self.transfer(False)

            def do_HEAD(self):
                self.transfer(True)

            def transfer(self, head):
                if self.path != relay.path or relay.stopped.is_set():
                    self.send_error(404)
                    return
                headers_sent = False
                try:
                    headers = {'Range': self.headers['Range']} if 'Range' in self.headers else {}
                    with request(relay.packet, 'HEAD' if head else 'GET', relay.upstream, headers=headers, stream=True) as response:
                        self.send_response(response.status_code)
                        for name in ('Content-Type', 'Content-Length', 'Content-Range', 'Accept-Ranges'):
                            if name in response.headers:
                                self.send_header(name, response.headers[name])
                        self.send_header('Cache-Control', 'private, no-store')
                        self.end_headers()
                        headers_sent = True
                        if not head:
                            for chunk in response.iter_content(CHUNK):
                                if relay.stopped.is_set():
                                    break
                                self.wfile.write(chunk)
                except (OSError, ValueError, requests.RequestException):
                    if not headers_sent:
                        self.send_error(403)
                    self.close_connection = True

        self.http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.http.daemon_threads = True
        self.thread = threading.Thread(target=self.http.serve_forever, kwargs={'poll_interval': 0.1}, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.http.server_port}{self.path}'

    def close(self) -> None:
        if not self.stopped.is_set():
            self.stopped.set()
            self.http.shutdown()
            self.http.server_close()
