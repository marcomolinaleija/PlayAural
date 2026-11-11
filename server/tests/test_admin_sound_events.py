"""Tests for administrator sound events configuration."""

from types import SimpleNamespace
import pytest

from ..core.server import Server
from ..core.sound_events import AVAILABLE_SOUND_ASSETS, SOUND_EVENTS
from ..administration.manager import (
    ADMIN_SOUND_EVENTS_MENU,
    ADMIN_SOUND_PICKER_MENU,
)
from ..messages.localization import Localization
from ..users.roles import ADMIN_TRUST_LEVEL, DEVELOPER_TRUST_LEVEL, USER_TRUST_LEVEL
from ..users.test_user import MockUser


def _current_menu(server: Server, username: str) -> str:
    return server._user_states.get(username, {}).get("menu", "")


async def _select(server: Server, user: MockUser, menu_id: str, selection_id: str) -> None:
    await server._handle_menu(
        SimpleNamespace(username=user.username),
        {
            "type": "menu",
            "menu_id": menu_id,
            "selection_id": selection_id,
        },
    )


@pytest.fixture
def admin_room():
    server = Server(db_path=":memory:")
    server._db.connect()
    server._db.create_user("AdminUser", "hash")
    server._db.create_user("DevUser", "hash")
    server._db.create_user("RegularUser", "hash")
    admin_rec = server._db.get_user("AdminUser")
    dev_rec = server._db.get_user("DevUser")
    reg_rec = server._db.get_user("RegularUser")

    admin = MockUser("AdminUser", uuid=admin_rec.uuid, locale="es")
    admin.trust_level = ADMIN_TRUST_LEVEL
    dev = MockUser("DevUser", uuid=dev_rec.uuid, locale="es")
    dev.trust_level = DEVELOPER_TRUST_LEVEL
    regular = MockUser("RegularUser", uuid=reg_rec.uuid, locale="es")
    regular.trust_level = USER_TRUST_LEVEL

    server._users = {
        admin.username: admin,
        dev.username: dev,
        regular.username: regular,
    }
    yield server, admin, dev, regular
    server._db.close()


@pytest.mark.asyncio
async def test_admin_sound_settings_menu_permissions(admin_room):
    server, admin, dev, regular = admin_room

    # Admin sees admin_server_content in admin_menu and sound_settings in admin_server_content_menu
    server.admin_manager._show_admin_menu(admin)
    items = [i.id for i in admin.get_current_menu_items("admin_menu")]
    assert "admin_server_content" in items
    server.admin_manager._show_admin_server_content_menu(admin)
    content_items = [i.id for i in admin.get_current_menu_items("admin_server_content_menu")]
    assert "sound_settings" in content_items

    # Developer also sees sound_settings in admin_server_content_menu
    server.admin_manager._show_admin_menu(dev)
    items_dev = [i.id for i in dev.get_current_menu_items("admin_menu")]
    assert "admin_server_content" in items_dev
    server.admin_manager._show_admin_server_content_menu(dev)
    content_items_dev = [i.id for i in dev.get_current_menu_items("admin_server_content_menu")]
    assert "sound_settings" in content_items_dev

    # Regular user cannot open sound settings
    server.admin_manager._show_sound_events_menu(regular)
    assert _current_menu(server, regular.username) != ADMIN_SOUND_EVENTS_MENU
    assert any("admin-only-action" in s for s in regular.get_spoken_messages())


@pytest.mark.asyncio
async def test_sound_events_menu_display_and_navigation(admin_room):
    server, admin, _, _ = admin_room

    server._show_main_menu(admin)
    server.admin_manager._show_admin_menu(admin)
    await _select(server, admin, "admin_menu", "admin_server_content")
    await _select(server, admin, "admin_server_content_menu", "sound_settings")

    assert _current_menu(server, admin.username) == ADMIN_SOUND_EVENTS_MENU
    items = admin.get_current_menu_items(ADMIN_SOUND_EVENTS_MENU)
    item_ids = [i.id for i in items]

    for event_id in SOUND_EVENTS:
        assert event_id in item_ids

    assert "back" in item_ids

    # Back navigates back to admin_server_content_menu
    await _select(server, admin, ADMIN_SOUND_EVENTS_MENU, "back")
    assert _current_menu(server, admin.username) == "admin_server_content_menu"


@pytest.mark.asyncio
async def test_sound_picker_menu_structure_and_preview_sound(admin_room):
    server, admin, _, _ = admin_room

    server.admin_manager._show_admin_menu(admin)
    await _select(server, admin, "admin_menu", "admin_server_content")
    await _select(server, admin, "admin_server_content_menu", "sound_settings")

    # Select table_created event
    await _select(server, admin, ADMIN_SOUND_EVENTS_MENU, "table_created")
    assert _current_menu(server, admin.username) == ADMIN_SOUND_PICKER_MENU

    items = admin.get_current_menu_items(ADMIN_SOUND_PICKER_MENU)
    sound_items = [i for i in items if i.id != "back"]

    # Every sound item must have its sound attribute set for automatic preview
    assert len(sound_items) == len(AVAILABLE_SOUND_ASSETS)
    for item in sound_items:
        assert item.sound == item.id
        assert item.id in AVAILABLE_SOUND_ASSETS

    # Default sound is table_created.ogg and has current tag
    current_item = next(i for i in sound_items if i.id == "table_created.ogg")
    assert Localization.get("es", "current-selection") in current_item.text
    assert Localization.get("es", "default-selection") in current_item.text

    # Back / Cancel returns without changing
    await _select(server, admin, ADMIN_SOUND_PICKER_MENU, "back")
    assert _current_menu(server, admin.username) == ADMIN_SOUND_EVENTS_MENU
    assert server.get_sound_for_event("table_created") == "table_created.ogg"


@pytest.mark.asyncio
async def test_sound_picker_selection_and_persistence(admin_room):
    server, admin, _, _ = admin_room

    server.admin_manager._show_admin_menu(admin)
    await _select(server, admin, "admin_menu", "admin_server_content")
    await _select(server, admin, "admin_server_content_menu", "sound_settings")
    await _select(server, admin, ADMIN_SOUND_EVENTS_MENU, "table_created")

    # Select a new sound (e.g. gamewin.ogg)
    admin.clear_messages()
    await _select(server, admin, ADMIN_SOUND_PICKER_MENU, "gamewin.ogg")

    # Returned to events menu
    assert _current_menu(server, admin.username) == ADMIN_SOUND_EVENTS_MENU
    assert server.get_sound_for_event("table_created") == "gamewin.ogg"

    # Spoken feedback and sound confirmation
    spoken = admin.get_spoken_messages()
    assert any("gamewin.ogg" in s for s in spoken)
    sound_cmds = [m for m in admin.messages if m.type == "play_sound"]
    assert any(m.data.get("asset") == "gamewin.ogg" for m in sound_cmds)

    # Events menu row reflects new sound
    items = admin.get_current_menu_items(ADMIN_SOUND_EVENTS_MENU)
    row = next(i for i in items if i.id == "table_created")
    assert "gamewin.ogg" in row.text

    # Persistence verification: clear memory cache and reload from database
    server._sound_event_mappings.clear()
    server._load_sound_event_mappings()
    assert server.get_sound_for_event("table_created") == "gamewin.ogg"


@pytest.mark.asyncio
async def test_event_sounds_trigger_configured_asset(admin_room):
    server, admin, _, _ = admin_room

    # Change private_message and friend_request sounds
    server.set_sound_for_event("private_message", "notify1.ogg")
    server.set_sound_for_event("friend_request", "online.ogg")

    expected_pm = server.get_sound_for_event("private_message")
    expected_friend = server.get_sound_for_event("friend_request")
    assert expected_pm == "notify1.ogg"
    assert expected_friend == "online.ogg"

    # Setup target user in DB and make admin and target friends
    server._db.create_user("TargetUser", "hash")
    target_rec = server._db.get_user("TargetUser")
    target = MockUser("TargetUser", uuid=target_rec.uuid, locale="es")
    server._users[target.username] = target

    server._db.send_friend_request(admin.uuid, target.uuid)
    server._db.accept_friend_request(admin.uuid, target.uuid)

    admin.clear_messages()
    target.clear_messages()
    await server._deliver_private_message(admin, target.username, "Hola")

    target_sounds = [m.data.get("asset") for m in target.messages if m.type == "play_sound"]
    assert expected_pm in target_sounds

    # Verify friend request plays the configured sound
    server._db.create_user("OtherUser", "hash")
    other_rec = server._db.get_user("OtherUser")
    other = MockUser("OtherUser", uuid=other_rec.uuid, locale="es")
    server._users[other.username] = other

    other.clear_messages()
    server._send_friend_request_to_record(admin, other_rec)
    other_sounds = [m.data.get("asset") for m in other.messages if m.type == "play_sound"]
    assert expected_friend in other_sounds

