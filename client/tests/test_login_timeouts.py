"""Slow authorization, cancellation and saved desktop connection policy."""

import asyncio
from contextlib import suppress
import json
from pathlib import Path
import sys
import threading
from types import SimpleNamespace

import pytest
import websockets
import wx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config_manager import ConfigManager
from connection_policy import LoginAttempt, authorize, login_timeout, normalize_login_timeout
from localization import Localization
from network_manager import NetworkManager
from ui import login_dialog as login_module
from ui.login_dialog import LoginDialog
from ui.main_window import MainWindow
from ui.options_dialog import ClientOptionsDialog


@pytest.mark.parametrize('value', [None, False, '60', 30.0, 0, -1, 31, 999])
def test_invalid_saved_timeouts_use_the_safe_default(value):
    assert normalize_login_timeout(value) == 30


def test_timeout_choice_is_local_persistent_and_migrates_old_config(tmp_path):
    config = ConfigManager(base_path=tmp_path)
    assert login_timeout(config) == 30
    config.set_client_option('network/login_timeout_seconds', 60, create_mode=True)
    assert login_timeout(ConfigManager(base_path=tmp_path)) == 60


@pytest.mark.asyncio
@pytest.mark.parametrize('entry', ['dialog', 'main'])
async def test_sign_in_accepts_a_real_response_after_the_old_five_second_limit(monkeypatch, entry):
    received, authenticated = asyncio.Event(), asyncio.Event()
    async def handler(ws):
        assert json.loads(await ws.recv())['type'] == 'authorize'
        received.set()
        await asyncio.sleep(5.1)
        await ws.send(json.dumps({'type':'authorize_success', 'username':'Alice'}))
        await ws.wait_closed()
    async with websockets.serve(handler, '127.0.0.1', 0) as server:
        url = f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}'
        if entry == 'dialog':
            window = SimpleNamespace(server_url=url, config_manager=None)
            result = await LoginDialog._async_test(window, 'Alice', 'test-password')
            assert result['type'] == 'authorize_success'
        else:
            lost = []
            window = SimpleNamespace(config_manager=None, IsShown=lambda:True,
                on_authorize_success=lambda packet:authenticated.set(),
                on_connection_lost=lambda:lost.append('lost'), on_connection_timeout=lambda:lost.append('timeout'))
            network = NetworkManager(window)
            network.loop = asyncio.get_running_loop()
            network.connecting = True
            monkeypatch.setattr(wx, 'CallAfter', lambda callback, *args:callback(*args))
            task = asyncio.create_task(network._connect_and_listen(url, 'Alice', 'test-password', 'test', 0, 30))
            network._connect_task = task
            await asyncio.wait_for(received.wait(), 2)
            assert network.connecting and not network.connected
            await asyncio.wait_for(authenticated.wait(), 8)
            assert network.connected and not network.connecting
            network.disconnect()
            with suppress(asyncio.CancelledError):
                await task
            assert not lost


@pytest.mark.asyncio
async def test_nonterminal_packets_do_not_complete_or_extend_authorization_deadline():
    class Socket:
        async def send(self, packet):
            pass
        async def recv(self):
            await asyncio.sleep(0.005)
            return json.dumps({'type':'update_locale', 'locale':'en'})
    packets = []
    with pytest.raises(asyncio.TimeoutError):
        await authorize(Socket(), {'type':'authorize'}, 0.04, packets.append)
    assert packets


def test_background_login_can_cancel_before_a_socket_exists_without_any_result_callback():
    entered, cleaned = threading.Event(), threading.Event()
    results = []
    async def operation():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()
    attempt = LoginAttempt(operation, results.append)
    attempt.start()
    assert entered.wait(2)
    attempt.cancel()
    attempt.thread.join(2)
    assert cleaned.is_set() and not attempt.thread.is_alive() and not results


@pytest.mark.asyncio
async def test_cancel_live_authorization_stops_worker_and_prevents_overlapping_retry(monkeypatch):
    received = asyncio.Event()
    async def handler(ws):
        await ws.recv()
        received.set()
        await ws.wait_closed()
    queued = []
    monkeypatch.setattr(wx, 'CallAfter', lambda callback, *args:queued.append((callback, args)))
    async with websockets.serve(handler, '127.0.0.1', 0) as server:
        url = f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}'
        config = SimpleNamespace(get_client_option=lambda *args:60)
        network = NetworkManager(SimpleNamespace(config_manager=config))
        assert network.connect(url, 'Alice', 'test-password')
        await asyncio.wait_for(received.wait(), 2)
        assert not network.connected and network.is_connecting()
        assert not network.connect(url, 'Alice', 'test-password')
        network.disconnect()
        await asyncio.to_thread(network.thread.join, 3)
        assert not network.thread.is_alive() and not queued


def test_stale_network_callbacks_cannot_affect_a_new_attempt():
    calls = []
    window = SimpleNamespace(IsShown=lambda:True, on_connection_lost=lambda:calls.append('lost'),
                             on_connection_timeout=lambda:calls.append('timeout'),
                             on_authorize_success=lambda packet:calls.append('authorized'))
    network = NetworkManager(window)
    network._attempt_id = 2
    network._handle_packet({'type':'authorize_success'}, 1)
    network._connection_ended(1, True)
    network._connection_ended(1, False)
    assert not calls


def test_server_requested_retry_does_not_interrupt_an_in_progress_attempt(monkeypatch):
    scheduled, actions = [], []
    monkeypatch.setattr(wx, 'CallLater', lambda delay, callback:scheduled.append((delay, callback)))
    window = SimpleNamespace(connected=False, reconnect_attempts=1,
        network=SimpleNamespace(is_connecting=lambda:True, disconnect=lambda:actions.append('disconnect')))
    MainWindow._do_reconnect(window, 'ws://localhost', 'Alice', 'test-password')
    assert scheduled and not actions and window.reconnect_attempts == 1


@pytest.mark.parametrize('connected,quitting,reconnecting', [(False,False,False), (True,False,False),
    (False,True,False), (False,False,True)])
def test_timeout_returns_to_sign_in_without_closing_a_live_or_cancelled_session(connected, quitting, reconnecting):
    exits = []
    window = SimpleNamespace(connected=connected, quitting=quitting, is_reconnecting=reconnecting,
        expecting_reconnect=False, disconnect_reason=None, _finish_local_exit=lambda:exits.append(True))
    MainWindow.on_connection_timeout(window)
    assert bool(exits) == (not connected and not quitting and not reconnecting)
    if exits:
        assert window.disconnect_reason


@pytest.fixture
def native_login(tmp_path, monkeypatch):
    app = wx.GetApp() or wx.App(False)
    old_locale = Localization.current_locale()
    Localization.init(locale='es')
    config = ConfigManager(base_path=tmp_path)
    monkeypatch.setattr(login_module, 'ConfigManager', lambda:config)
    dialog = LoginDialog()
    yield app, config, dialog
    dialog.Destroy()
    app.ProcessPendingEvents()
    Localization.init(locale=old_locale)


def test_cancel_discards_a_queued_success_without_saving_credentials(native_login):
    app, config, dialog = native_login
    async def result(*args, **kwargs):
        return {'type':'authorize_success', 'username':'Alice'}
    dialog._async_test = result
    dialog.timeout_choice.SetSelection(1)
    dialog._on_timeout_changed(None)
    assert login_timeout(config) == 60
    dialog._verify_and_login('Alice', 'test-password')
    attempt = dialog._login_attempt
    assert dialog.cancel_login_button.IsShown() and not dialog.server_choice.IsEnabled()
    attempt.thread.join(2)
    assert not attempt.thread.is_alive()
    dialog._on_cancel_login(None)
    app.ProcessPendingEvents()
    assert not config.get_server_accounts(dialog.server_id)
    assert dialog.server_choice.IsEnabled() and not dialog.cancel_login_button.IsShown()


def test_options_dialog_saves_and_restores_the_same_timeout(native_login):
    _, config, login = native_login
    dialog = ClientOptionsDialog(login, config, ['en', 'es'])
    try:
        dialog.timeout_choice.SetSelection(1)
        results = []
        dialog.EndModal = results.append
        dialog.on_save(None)
        assert login_timeout(config) == 60 and results == [wx.ID_OK]
        dialog.notebook.SetSelection(2)
        dialog._reset_current_tab_fields(config._get_default_client_options())
        assert dialog.timeout_choice.GetSelection() == 0
    finally:
        dialog.Destroy()
