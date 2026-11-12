"""Desktop connection deadlines and cancellable background sign-in work."""

import asyncio
import json
import threading

LOGIN_TIMEOUT_SECONDS = (30, 60)
DEFAULT_LOGIN_TIMEOUT_SECONDS = 30
LOGIN_TIMEOUT_OPTION = 'network/login_timeout_seconds'


def normalize_login_timeout(value):
    return value if type(value) is int and value in LOGIN_TIMEOUT_SECONDS else DEFAULT_LOGIN_TIMEOUT_SECONDS


def login_timeout(config_manager):
    value = config_manager.get_client_option(LOGIN_TIMEOUT_OPTION, DEFAULT_LOGIN_TIMEOUT_SECONDS) if config_manager else None
    return normalize_login_timeout(value)


async def authorize(websocket, packet, timeout, on_packet=None):
    # One deadline covers sending credentials and waiting for the terminal
    # response. Other packets never reset it or falsely complete sign-in.
    async with asyncio.timeout(timeout):
        await websocket.send(json.dumps(packet))
        while True:
            try:
                response = json.loads(await websocket.recv())
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(response, dict):
                continue
            if response.get('type') in {'authorize_success', 'login_failed'}:
                return response
            if on_packet:
                on_packet(response)


class LoginAttempt:
    """Cancel opening/authentication without blocking the wx event loop."""

    def __init__(self, operation, on_result):
        self.operation, self.on_result = operation, on_result
        self.cancelled = threading.Event()
        self.lock = threading.Lock()
        self.loop = self.task = None

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def cancel(self):
        self.cancelled.set()
        with self.lock:
            if self.loop and self.task:
                try:
                    self.loop.call_soon_threadsafe(self.task.cancel)
                except RuntimeError:
                    pass

    def _run(self):
        try:
            result = asyncio.run(self._operation())
        except asyncio.CancelledError:
            return
        except Exception:
            result = 'connection_error'
        if not self.cancelled.is_set():
            self.on_result(result)

    async def _operation(self):
        with self.lock:
            self.loop, self.task = asyncio.get_running_loop(), asyncio.current_task()
        try:
            if self.cancelled.is_set():
                raise asyncio.CancelledError
            return await self.operation()
        finally:
            with self.lock:
                self.loop = self.task = None
