"""Read documented Codex app-server limits; missing data never authorizes work."""
import json
import math
import os
import selectors
import subprocess
import time


def quota_status(result, threshold=3):
    limits = (result.get('rateLimitsByLimitId') or {}).get('codex') or result.get('rateLimits')
    if not isinstance(limits, dict):
        raise RuntimeError('Codex usage information is unavailable')
    windows = []
    for name in ('primary', 'secondary'):
        window = limits.get(name)
        if window is None:
            continue
        if not isinstance(window, dict):
            raise RuntimeError('Codex returned an invalid usage window')
        used = window.get('usedPercent')
        if isinstance(used, bool) or not isinstance(used, (int, float)) or not math.isfinite(used) or not 0 <= used <= 100:
            raise RuntimeError('Codex returned invalid usage information')
        windows.append({'window': name, 'remaining_percent': 100 - used, 'resets_at': window.get('resetsAt')})
    if not windows:
        raise RuntimeError('Codex usage windows are unavailable')
    minimum = min(window['remaining_percent'] for window in windows)
    return {'allowed': minimum > threshold, 'remaining_percent': minimum, 'threshold': threshold, 'windows': windows}


def read_quota(codex='/usr/local/bin/codex', timeout=45, env=None):
    command = codex if isinstance(codex, list) else [codex, 'app-server', '--listen', 'stdio://']
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    pending = b''
    deadline = time.monotonic() + timeout
    def send(value):
        process.stdin.write((json.dumps(value) + '\n').encode())
        process.stdin.flush()
    try:
        send({'id': 1, 'method': 'initialize', 'params': {'clientInfo': {'name': 'playaural-maintenance', 'version': '1'}, 'capabilities': {'experimentalApi': True}}})
        while time.monotonic() < deadline:
            if not selector.select(max(0, min(1, deadline - time.monotonic()))):
                if process.poll() is not None:
                    raise RuntimeError('Codex usage reader exited')
                continue
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError('Codex usage reader closed its output')
            pending += chunk
            while b'\n' in pending:
                line, pending = pending.split(b'\n', 1)
                response = json.loads(line)
                if response.get('id') == 1:
                    if 'error' in response:
                        raise RuntimeError('Codex initialization failed')
                    send({'method': 'initialized'})
                    send({'id': 2, 'method': 'account/rateLimits/read'})
                elif response.get('id') == 2:
                    if 'error' in response:
                        raise RuntimeError('Codex usage read failed')
                    return quota_status(response.get('result') or {})
        raise TimeoutError('Codex usage read timed out')
    finally:
        selector.close()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        process.stdin.close()
        process.stdout.close()


if __name__ == '__main__':
    print(json.dumps(read_quota()))
