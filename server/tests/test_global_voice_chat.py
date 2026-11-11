import asyncio
from pathlib import Path
from types import SimpleNamespace
import pytest

from ..auth.voice_rate_limit import VoiceRateLimiter
from ..core.server import Server
from ..administration.manager import AdministrationManager, DEVELOPER_TRUST_LEVEL, ADMIN_MODERATION_MENU
from ..messages.localization import Localization
from ..persistence.database import MuteRecord
from ..tables.manager import TableManager
from ..users.test_user import MockUser
from ..voice import VoiceService


class RecordingConnection:
    def __init__(self, username: str = ""):
        self.username = username
        self.sent: list[dict] = []

    async def send(self, packet: dict) -> None:
        self.sent.append(packet)


class DummyDb:
    def __init__(self):
        self.mutes: dict[str, MuteRecord] = {}
        self.users: dict[str, SimpleNamespace] = {}
        self.server_settings: dict[str, bool] = {}
        self.social_blocks: dict[str, set[str]] = {}

    def get_active_mute(self, username: str):
        return self.mutes.get(username)

    def unmute_user(self, username: str):
        return self.mutes.pop(username, None) is not None

    def mute_user(self, username: str, admin_username: str, reason: str, expires_at: str | None = None):
        record = MuteRecord(
            id=len(self.mutes) + 1,
            username=username,
            admin_username=admin_username,
            reason=reason,
            issued_at="now",
            expires_at=expires_at,
        )
        self.mutes[username] = record
        return record

    def get_user(self, username: str):
        return self.users.get(username)

    def get_boolean_server_setting(self, key: str, default: bool = True) -> bool:
        return self.server_settings.get(key, default)

    def set_boolean_server_setting(self, key: str, value: bool) -> None:
        self.server_settings[key] = value

    def get_socially_blocked_ids(self, uuid: str) -> set[str]:
        return self.social_blocks.get(uuid, set())

    def count_moderation_reports(self, *args, **kwargs) -> int:
        return 0

    def count_global_chat_messages(self, *args, **kwargs) -> int:
        return 0


def _make_server() -> Server:
    Localization.init(Path(__file__).resolve().parents[1] / "locales")
    Localization.preload_bundles()
    server = Server.__new__(Server)
    server._tables = TableManager()
    server._tables._server = server
    server._db = DummyDb()
    server._users = {}
    server._user_states = {}
    server._voice = VoiceService(
        enabled=True,
        public_url="wss://voice.example.com",
        api_key="test-key",
        api_secret="test-secret",
        room_prefix="pa",
        token_ttl_seconds=300,
    )
    server._voice_context_resolvers = {
        "table": server._resolve_table_voice_context,
        "global": server._resolve_global_voice_context,
    }
    server._voice_presence_by_user = {}
    server._voice_join_authorizations_by_user = {}
    server._next_voice_join_authorization_expiry = None
    server._voice_rate_limiter = VoiceRateLimiter()
    server._global_chat_sending_enabled = True
    server._global_voice_chat_enabled = True
    server.admin_manager = AdministrationManager(server)
    return server


@pytest.mark.asyncio
async def test_main_menu_includes_global_voice_chat_and_opens_menu():
    server = _make_server()
    user = MockUser("Alice", uuid="uuid-alice")
    user.connection = RecordingConnection("Alice")
    server._users["Alice"] = user

    server._show_main_menu(user)
    items = user.get_current_menu_items("main_menu")
    action_ids = [item.id for item in items]
    assert "global_voice_chat" in action_ids

    # Select global_voice_chat
    await server._handle_main_menu_selection(user, "global_voice_chat")
    assert server._user_states["Alice"]["menu"] == "global_voice_chat_menu"

    menu_items = user.get_current_menu_items("global_voice_chat_menu")
    voice_ids = [item.id for item in menu_items]
    assert "connect_voice" in voice_ids
    assert "participants_heading" in voice_ids
    assert "no_participants" in voice_ids
    assert "back" in voice_ids


@pytest.mark.asyncio
async def test_global_voice_chat_join_and_leave_lifecycle():
    server = _make_server()
    alice = MockUser("Alice", uuid="uuid-alice")
    alice.connection = RecordingConnection("Alice")
    server._users["Alice"] = alice

    server._show_global_voice_chat_menu(alice)

    # 1. Alice clicks connect_voice
    await server._handle_global_voice_chat_selection(alice, "connect_voice")
    # Server should send voice_join_info with server_requested=True
    assert len(alice.connection.sent) == 1
    join_packet = alice.connection.sent[-1]
    assert join_packet["type"] == "voice_join_info"
    assert join_packet["scope"] == "global"
    assert join_packet["context_id"] == "lobby"
    assert join_packet["server_requested"] is True

    # 2. Alice's client sends voice_presence state=connected
    await server._handle_voice_presence(
        alice.connection,
        {
            "type": "voice_presence",
            "state": "connected",
            "scope": "global",
            "context_id": "lobby",
        },
    )
    await asyncio.sleep(0)

    # Alice should be recorded in presence
    assert server._voice_presence_by_user["Alice"] == {
        "scope": "global",
        "context_id": "lobby",
    }
    # Join sound played
    assert "voice_join.ogg" in alice.get_sounds_played()

    # Menu refreshed and now shows disconnect_voice and Alice in participants
    menu_items = alice.get_current_menu_items("global_voice_chat_menu")
    menu_ids = [item.id for item in menu_items]
    assert "disconnect_voice" in menu_ids
    assert "voice_participant_Alice" in menu_ids

    # 3. Alice clicks disconnect_voice
    await server._handle_global_voice_chat_selection(alice, "disconnect_voice")
    await asyncio.sleep(0)
    assert "Alice" not in server._voice_presence_by_user
    # Leave sound played
    assert "voice_leave.ogg" in alice.get_sounds_played()
    # Context closed packet sent to client
    assert alice.connection.sent[-1]["type"] == "voice_context_closed"


@pytest.mark.asyncio
async def test_global_voice_chat_multi_user_audio_and_tts():
    server = _make_server()
    alice = MockUser("Alice", uuid="uuid-alice")
    bob = MockUser("Bob", uuid="uuid-bob")
    alice.connection = RecordingConnection("Alice")
    bob.connection = RecordingConnection("Bob")
    server._users["Alice"] = alice
    server._users["Bob"] = bob

    # Alice connects to global voice
    await server.force_voice_context_join("Alice", scope="global", context_id="lobby")
    await server._handle_voice_presence(
        alice.connection,
        {"type": "voice_presence", "state": "connected", "scope": "global", "context_id": "lobby"},
    )
    await asyncio.sleep(0)

    assert "voice_join.ogg" in alice.get_sounds_played()

    # Bob connects to global voice
    await server.force_voice_context_join("Bob", scope="global", context_id="lobby")
    await server._handle_voice_presence(
        bob.connection,
        {"type": "voice_presence", "state": "connected", "scope": "global", "context_id": "lobby"},
    )
    await asyncio.sleep(0)

    # Both Alice and Bob should hear voice_join.ogg for Bob's join
    assert bob.get_sounds_played().count("voice_join.ogg") == 1
    assert alice.get_sounds_played().count("voice_join.ogg") == 2

    # Bob disconnects
    await server.force_voice_context_leave("Bob", scope="global", context_id="lobby")
    await asyncio.sleep(0)
    assert "voice_leave.ogg" in alice.get_sounds_played()
    assert "voice_leave.ogg" in bob.get_sounds_played()


@pytest.mark.asyncio
async def test_admin_toggle_global_voice_chat_and_disconnect_active():
    server = _make_server()
    admin = MockUser("Dev", uuid="uuid-dev")
    admin.trust_level = DEVELOPER_TRUST_LEVEL
    admin.connection = RecordingConnection("Dev")
    alice = MockUser("Alice", uuid="uuid-alice")
    alice.connection = RecordingConnection("Alice")
    server._users["Dev"] = admin
    server._users["Alice"] = alice

    # Alice connects to global voice
    await server.force_voice_context_join("Alice", scope="global", context_id="lobby")
    await server._handle_voice_presence(
        alice.connection,
        {"type": "voice_presence", "state": "connected", "scope": "global", "context_id": "lobby"},
    )
    assert "Alice" in server._voice_presence_by_user

    # Admin opens moderation menu
    server.admin_manager._show_moderation_menu(admin)
    items = admin.get_current_menu_items(ADMIN_MODERATION_MENU)
    toggle = next(i for i in items if i.id == "toggle_global_voice_chat")
    assert toggle.read_only is False
    assert "On" in toggle.text

    # Admin toggles global voice chat OFF
    await server.admin_manager._handle_moderation_selection(admin, "toggle_global_voice_chat")
    assert server.global_voice_chat_enabled is False

    # Alice should be closed/disconnected from global voice
    await asyncio.sleep(0)
    assert "Alice" not in server._voice_presence_by_user
    assert alice.connection.sent[-1]["type"] == "voice_context_closed"

    # Alice attempts to join while disabled
    server._show_global_voice_chat_menu(alice)
    disabled_items = alice.get_current_menu_items("global_voice_chat_menu")
    assert any(i.id == "voice_disabled_notice" for i in disabled_items)

    await server._handle_global_voice_chat_selection(alice, "connect_voice")
    assert alice.get_last_spoken() == "Global voice chat is currently disabled."

    # Admin toggles global voice chat back ON
    await server.admin_manager._handle_moderation_selection(admin, "toggle_global_voice_chat")
    assert server.global_voice_chat_enabled is True


@pytest.mark.asyncio
async def test_muted_user_cannot_join_global_voice():
    server = _make_server()
    bad_user = MockUser("BadUser", uuid="uuid-bad")
    bad_user.connection = RecordingConnection("BadUser")
    server._users["BadUser"] = bad_user
    server._db.mute_user("BadUser", "Dev", "voice abuse")

    server._show_global_voice_chat_menu(bad_user)
    await server._handle_global_voice_chat_selection(bad_user, "connect_voice")

    assert "BadUser" not in server._voice_presence_by_user
    assert "muted" in bad_user.get_last_spoken().lower()


@pytest.mark.asyncio
async def test_entering_table_cleans_up_global_voice():
    server = _make_server()
    alice = MockUser("Alice", uuid="uuid-alice")
    alice.connection = RecordingConnection("Alice")
    server._users["Alice"] = alice

    # Connect to global voice
    await server.force_voice_context_join("Alice", scope="global", context_id="lobby")
    await server._handle_voice_presence(
        alice.connection,
        {"type": "voice_presence", "state": "connected", "scope": "global", "context_id": "lobby"},
    )
    assert server._voice_presence_by_user.get("Alice", {}).get("scope") == "global"

    # Alice prepares for table audio (as happens when entering a table)
    server._prepare_user_for_table_audio(alice)
    await asyncio.sleep(0)

    assert "Alice" not in server._voice_presence_by_user
    assert alice.connection.sent[-1]["type"] == "voice_context_closed"
    assert alice.connection.sent[-1]["scope"] == "global"
