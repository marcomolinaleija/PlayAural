import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

from ..tables.table import Table
from ..users.preferences import UserPreferences
from ..users.test_user import MockUser
from ..messages.localization import Localization
from ..games.pig.game import PigGame
from ..core.server import Server
from ..tables.manager import TableManager
from ..administration.manager import AdministrationManager, DEVELOPER_TRUST_LEVEL
from ..auth.voice_rate_limit import VoiceRateLimiter
from ..voice import VoiceService


LOCALES_DIR = Path(__file__).resolve().parents[1] / "locales"


@pytest.fixture(autouse=True)
def init_localization():
    Localization.init(LOCALES_DIR)


class RecordingConnection:
    def __init__(self, username: str = ""):
        self.username = username
        self.sent: list[dict] = []

    async def send(self, packet: dict) -> None:
        self.sent.append(packet)


class DummyDb:
    def __init__(self):
        self.server_settings: dict[str, bool] = {}
        self.social_blocks: dict[str, set[str]] = {}

    def get_boolean_server_setting(self, key: str, default: bool = True) -> bool:
        return self.server_settings.get(key, default)

    def set_boolean_server_setting(self, key: str, value: bool) -> None:
        self.server_settings[key] = value

    def get_socially_blocked_ids(self, uuid: str) -> set[str]:
        return self.social_blocks.get(uuid, set())


def _make_server() -> Server:
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
    server.global_voice_quality = "high"
    server.admin_manager = AdministrationManager(server)
    return server


def _table_with_game() -> tuple[Table, MockUser, MockUser, MockUser]:
    alice = MockUser("Alice", uuid="uuid-alice")
    bob = MockUser("Bob", uuid="uuid-bob")
    charlie = MockUser("Charlie", uuid="uuid-charlie")
    table = Table(table_id="table-test", game_type="pig", host="Alice")
    assert table.add_member("Alice", alice)
    assert table.add_member("Bob", bob)
    assert table.add_member("Charlie", charlie)
    return table, alice, bob, charlie


def test_table_voice_quality_defaults_and_validation() -> None:
    table = Table(table_id="t1", game_type="pig", host="Alice")
    assert table.voice_spatial_audio is True
    assert table.voice_quality == "high"

    assert table.set_voice_spatial_audio(False) is True
    assert table.voice_spatial_audio is False

    assert table.set_voice_quality("standard") is True
    assert table.voice_quality == "standard"

    assert table.set_voice_quality("invalid") is False
    assert table.voice_quality == "standard"

    assert table.set_voice_spatial_audio("not-a-bool") is False
    assert table.voice_spatial_audio is False


def test_table_voice_quality_checkpoint_persistence() -> None:
    table, _alice, _bob, _charlie = _table_with_game()
    table.set_voice_spatial_audio(False)
    table.set_voice_quality("standard")

    manual_json = table.serialize_saved_state(include_checkpoint_state=False)
    manual_data = json.loads(manual_json)
    assert "voice_spatial_audio" not in manual_data["properties"]
    assert "voice_quality" not in manual_data["properties"]

    checkpoint_json = table.serialize_saved_state(include_checkpoint_state=True)
    checkpoint_data = json.loads(checkpoint_json)
    assert checkpoint_data["properties"]["voice_spatial_audio"] is False
    assert checkpoint_data["properties"]["voice_quality"] == "standard"

    restored = Table(table_id="t-restored", game_type="pig", host="Alice")
    restored.restore_saved_state(
        Table.deserialize_saved_state(checkpoint_json, include_checkpoint_state=True)
    )
    assert restored.voice_spatial_audio is False
    assert restored.voice_quality == "standard"


def test_calculate_voice_pans_relative_to_listener() -> None:
    table, alice, bob, charlie = _table_with_game()
    # Before game start (in table lobby with 3 seated members):
    pans_lobby = table.calculate_voice_pans("uuid-alice")
    assert "uuid-alice" not in pans_lobby
    assert pans_lobby["uuid-bob"] > 0.5
    assert pans_lobby["uuid-charlie"] < -0.5

    # Start pig game with 3 players
    game = PigGame()
    game.add_player("Alice", alice)
    game.add_player("Bob", bob)
    game.add_player("Charlie", charlie)
    table.game = game

    # With spatial audio enabled:
    pans = table.calculate_voice_pans("uuid-alice")
    assert "uuid-alice" not in pans
    assert pans["uuid-bob"] > 0.5  # To the right
    assert pans["uuid-charlie"] < -0.5  # To the left

    # When spatial audio is disabled, pans are empty dict
    table.set_voice_spatial_audio(False)
    pans_disabled = table.calculate_voice_pans("uuid-alice")
    assert pans_disabled == {}


def test_user_preferences_voice_settings() -> None:
    prefs = UserPreferences()
    assert prefs.voice_noise_suppression is True
    assert prefs.voice_spatial_audio is True
    assert prefs.voice_auto_gain is True

    serialized = prefs.to_dict()
    assert serialized["voice_noise_suppression"] is True
    assert serialized["voice_spatial_audio"] is True
    assert serialized["voice_auto_gain"] is True

    modified = UserPreferences.from_dict({
        "voice_noise_suppression": False,
        "voice_spatial_audio": False,
        "voice_auto_gain": False,
    })
    assert modified.voice_noise_suppression is False
    assert modified.voice_spatial_audio is False
    assert modified.voice_auto_gain is False


@pytest.mark.asyncio
async def test_host_voice_management_menu_and_toggles() -> None:
    server = _make_server()
    alice = MockUser("Alice", uuid="uuid-alice")
    alice.connection = RecordingConnection("Alice")
    server._users["Alice"] = alice

    table = Table(table_id="t-host-test", game_type="pig", host="Alice")
    table._server = server
    table.add_member("Alice", alice)
    server._tables._tables["t-host-test"] = table
    server._tables._username_to_table["Alice"] = "t-host-test"

    # Alice opens host voice management menu (even alone at the table)
    server._show_host_voice_management_menu(alice, table)
    menu_items = alice.get_current_menu_items("host_voice_management_menu")
    action_ids = [item.id for item in menu_items]
    assert "toggle_table_spatial_audio" in action_ids
    assert "toggle_table_voice_quality" in action_ids
    assert "members_heading" in action_ids

    # Toggle spatial audio
    assert table.voice_spatial_audio is True
    await server._handle_host_voice_management_selection(alice, "toggle_table_spatial_audio", {"table_id": table.table_id})
    assert table.voice_spatial_audio is False

    # Toggle voice quality
    assert table.voice_quality == "high"
    await server._handle_host_voice_management_selection(alice, "toggle_table_voice_quality", {"table_id": table.table_id})
    assert table.voice_quality == "standard"


@pytest.mark.asyncio
async def test_personal_voice_preferences_in_audio_submenu() -> None:
    server = _make_server()
    user = MockUser("Bob", uuid="uuid-bob")
    conn = RecordingConnection("Bob")
    user.connection = conn
    server._users["Bob"] = user

    server._save_user_preferences = lambda u: None

    server._show_audio_submenu(user)
    items = user.get_current_menu_items("options_audio_submenu")
    action_ids = [item.id for item in items]
    assert "toggle_voice_noise_suppression" in action_ids
    assert "toggle_voice_spatial_audio" in action_ids
    assert "toggle_voice_auto_gain" in action_ids

    # Toggle noise suppression
    assert user.preferences.voice_noise_suppression is True
    await server._handle_audio_submenu_selection(user, "toggle_voice_noise_suppression")
    assert user.preferences.voice_noise_suppression is False
    await asyncio.sleep(0)
    pref_packets = [p for p in conn.sent if p.get("type") == "update_preference" and p.get("key") == "audio/voice_noise_suppression"]
    assert len(pref_packets) == 1
    assert pref_packets[0]["value"] is False

    # Toggle spatial audio
    assert user.preferences.voice_spatial_audio is True
    await server._handle_audio_submenu_selection(user, "toggle_voice_spatial_audio")
    assert user.preferences.voice_spatial_audio is False

    # Toggle auto gain
    assert user.preferences.voice_auto_gain is True
    await server._handle_audio_submenu_selection(user, "toggle_voice_auto_gain")
    assert user.preferences.voice_auto_gain is False


@pytest.mark.asyncio
async def test_global_voice_chat_admin_controls() -> None:
    server = _make_server()
    dev = MockUser("Dev", uuid="uuid-dev")
    dev.trust_level = DEVELOPER_TRUST_LEVEL
    dev.connection = RecordingConnection("Dev")
    server._users["Dev"] = dev

    server.set_global_voice_chat_enabled = lambda enabled: setattr(server, "_global_voice_chat_enabled", enabled)
    type(server).global_voice_chat_enabled = property(lambda self: self._global_voice_chat_enabled)

    server._show_global_voice_chat_menu(dev)
    items = dev.get_current_menu_items("global_voice_chat_menu")
    action_ids = [item.id for item in items]
    assert "toggle_global_voice_enabled" in action_ids
    assert "toggle_global_voice_quality" in action_ids

    # Toggle enabled
    await server._handle_global_voice_chat_selection(dev, "toggle_global_voice_enabled")
    assert server.global_voice_chat_enabled is False

    # Toggle quality
    assert server.global_voice_quality == "high"
    await server._handle_global_voice_chat_selection(dev, "toggle_global_voice_quality")
    assert server.global_voice_quality == "standard"

