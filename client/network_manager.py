"""Network manager for WebSocket communication with server."""

import asyncio
import json
import threading
import traceback
import wx
import websockets
from client_info import client_auth_metadata
from ssl_utils import make_ssl_context
from connection_policy import authorize, login_timeout


class NetworkManager:
    """Manages WebSocket connection to PlayAural server."""

    def __init__(self, main_window):
        """
        Initialize network manager.

        Args:
            main_window: Reference to MainWindow for callbacks
        """
        self.main_window = main_window
        self.ws = None
        self.connected = False
        self.connecting = False
        self.username = None
        self.thread = None
        self.loop = None
        self.should_stop = False
        self._connect_task = None
        self._attempt_id = 0

    def is_connecting(self):
        """Check if a connection attempt is in progress."""
        return self.connecting or bool(self.thread and self.thread.is_alive() and not self.connected)

    def connect(self, server_url, username, password, client_version="0.0.0"):
        """
        Connect to server.
        
        Args:
            server_url: WebSocket URL (e.g., "wss://playaural.ddt.one")
            username: Username for authorization
            password: Password for authorization
            client_version: Version string of the client
        """
        try:
            # Pending and closing attempts finish in the background. Never
            # block wx or overlap transports just because a retry timer fired.
            if self.thread and self.thread.is_alive():
                return False

            self.username = username
            self.should_stop = False
            self.connecting = True
            self._attempt_id += 1
            timeout = login_timeout(getattr(self.main_window, 'config_manager', None))

            # Start async thread
            self.thread = threading.Thread(
                target=self._run_async_loop,
                args=(server_url, username, password, client_version, self._attempt_id, timeout),
                daemon=True,
            )
            self.thread.start()

            return True
        except Exception:
            traceback.print_exc()
            self.connecting = False
            return False

    def _run_async_loop(self, server_url, username, password, client_version, attempt_id, timeout):
        """Run the async event loop in a thread."""
        try:
            # Create new event loop for this thread
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)

            # Run the connection coroutine
            self._connect_task = self.loop.create_task(
                self._connect_and_listen(server_url, username, password, client_version, attempt_id, timeout))
            self.loop.run_until_complete(self._connect_task)
        except asyncio.CancelledError:
            pass
        except Exception:
            traceback.print_exc()
        finally:
            self.connecting = False
            self._connect_task = None
            if self.loop and self.loop.is_running():
                 self.loop.close()
            elif self.loop:
                 self.loop.close()

    async def _connect_and_listen(self, server_url, username, password, client_version, attempt_id, timeout):
        """Connect to server and listen for messages."""
        timed_out = False
        rejected = False
        try:
            if self.should_stop:
                return
            async with websockets.connect(
                server_url,
                ssl=make_ssl_context(server_url),
                ping_interval=20,
                ping_timeout=timeout,
                open_timeout=timeout,
                close_timeout=2,
            ) as websocket:
                self.ws = websocket
                response = await authorize(websocket, {
                            **client_auth_metadata(),
                            "type": "authorize",
                            "username": username,
                            "password": password,
                            "version": client_version,
                        }, timeout, lambda packet: wx.CallAfter(self._handle_packet, packet, attempt_id))
                if self.should_stop:
                    return
                rejected = response['type'] == 'login_failed'
                if not rejected:
                    self.connected = True
                    self.connecting = False
                wx.CallAfter(self._handle_packet, response, attempt_id)
                if rejected:
                    return

                # Listen for messages
                while not self.should_stop:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                        packet = json.loads(message)

                        # Forward to main thread (skip if shutting down)
                        if not self.should_stop:
                            wx.CallAfter(self._handle_packet, packet, attempt_id)
                    except asyncio.TimeoutError:
                        # Timeout is normal, just continue
                        continue
                    except websockets.exceptions.ConnectionClosed:
                        break
                    except (json.JSONDecodeError, ValueError, KeyError):
                        # Malformed packet — discard and keep listening
                        continue

        except asyncio.TimeoutError:
            timed_out = True
        except (ConnectionRefusedError, OSError) as e:
            # Common connection errors - log briefly, don't spam traceback
            print(f"Connection attempt failed: {e}")
        except websockets.exceptions.InvalidStatus as e:
            # Server rejected connection (e.g. 503 Service Unavailable)
            print(f"Server rejected connection: {e}")
        except Exception:
            traceback.print_exc()
        finally:
            self.connected = False
            self.ws = None
            # Only call on_connection_lost if we're not in the middle of stopping
            # (to avoid race conditions during reconnection)
            if not self.should_stop and not rejected:
                wx.CallAfter(self._connection_ended, attempt_id, timed_out)

    def _connection_ended(self, attempt_id, timed_out):
        if attempt_id != self._attempt_id or self.should_stop:
            return
        try:
            if not self.main_window.IsShown():
                return
        except RuntimeError:
            return
        if timed_out:
            self.main_window.on_connection_timeout()
        else:
            self.main_window.on_connection_lost()

    def disconnect(self):
        """Disconnect from server."""
        self.should_stop = True
        self.connected = False

        # Cancel DNS/open/authentication/listening, including before ws exists.
        if self._connect_task and self.loop:
            try:
                self.loop.call_soon_threadsafe(self._connect_task.cancel)
            except Exception:
                pass  # Ignore errors during cleanup

    def send_packet(self, packet):
        """
        Send packet to server.

        Args:
            packet: Dictionary to send as JSON
        """
        if not self.connected or not self.ws or not self.loop:
            return False

        try:
            message = json.dumps(packet)

            # Schedule send in the async loop
            asyncio.run_coroutine_threadsafe(self.ws.send(message), self.loop)
            return True
        except Exception:
            traceback.print_exc()
            self.connected = False
            # Only trigger reconnect if this isn't an intentional disconnect
            if not self.should_stop:
                wx.CallAfter(self.main_window.on_connection_lost)
            return False

    def _handle_packet(self, packet, attempt_id=None):
        """
        Handle incoming packet from server (called in main thread).

        Args:
            packet: Dictionary received from server
        """
        if self.should_stop or (attempt_id is not None and attempt_id != self._attempt_id):
            return
        # Guard against delivery to a window that was destroyed between the
        # wx.CallAfter dispatch and the main-thread execution of this callback.
        try:
            if not self.main_window or not self.main_window.IsShown():
                return
        except RuntimeError:
            return  # Underlying C++ wx object already deleted

        packet_type = packet.get("type")

        if packet_type == "update_locale":
             self.main_window.on_update_locale(packet)
        elif packet_type == "authorize_success":
            canonical_username = packet.get("username")
            if isinstance(canonical_username, str) and canonical_username:
                self.username = canonical_username
            self.main_window.on_authorize_success(packet)
        elif packet_type == "speak":
            self.main_window.on_server_speak(packet)
        elif packet_type == "audio":
            self.main_window.on_server_audio(packet)
        elif packet_type == 'forum_file_picker':
            self.main_window.forum_media.choose(packet)
        elif packet_type == 'forum_open_media':
            self.main_window.forum_media.open(packet)
        elif packet_type == 'forum_media_session':
            pass
        elif packet_type == "menu":
            self.main_window.on_server_menu(packet)
        elif packet_type == "request_input":
            self.main_window.on_server_request_input(packet)
        elif packet_type == 'translation_draft':
            self.main_window.on_translation_draft(packet)
        elif packet_type == "remove_editbox":
            self.main_window.on_server_remove_editbox(packet)
        elif packet_type == "clear_ui":
            self.main_window.on_server_clear_ui(packet)
        elif packet_type == "game_list":
            self.main_window.on_server_game_list(packet)
        elif packet_type == "disconnect":
            self.main_window.on_server_disconnect(packet)
        elif packet_type == "login_failed":
            self.main_window.on_login_failed(packet)
        elif packet_type == "update_options_lists":
            self.main_window.on_update_options_lists(packet)
        elif packet_type == "open_client_options":
            self.main_window.on_open_client_options(packet)
        elif packet_type == "open_server_options":
            self.main_window.on_open_server_options(packet)
        elif packet_type == "table_create":
            self.main_window.on_table_create(packet)
        elif packet_type == "chat":
            self.main_window.on_receive_chat(packet)
        elif packet_type == "force_exit":
             self.main_window.on_force_exit(packet)
        elif packet_type == "switch_server":
             self.main_window.on_switch_server(packet)
        elif packet_type == "update_preference":
             self.main_window.on_update_preference(packet)
        elif packet_type == "pong":
            self.main_window.on_server_pong(packet)
        elif packet_type == "voice_join_info":
            self.main_window.on_voice_join_info(packet)
        elif packet_type == "voice_join_error":
            self.main_window.on_voice_join_error(packet)
        elif packet_type == "voice_leave_ack":
            self.main_window.on_voice_leave_ack(packet)
        elif packet_type == "voice_context_closed":
            self.main_window.on_voice_context_closed(packet)
        elif packet_type == "voice_settings":
            self.main_window.on_voice_settings(packet)
        elif packet_type == "voice_pans":
            self.main_window.on_voice_pans(packet)
        elif packet_type == "table_context":
            self.main_window.on_table_context(packet)
        elif packet_type == "username_updated":
            self.main_window.on_username_updated(packet)
