"""Tests for the admin grant coins feature."""

from types import SimpleNamespace
import pytest

from ..core.server import Server
from ..administration.manager import (
    GRANT_COINS_AMOUNT_MENU,
    GRANT_COINS_INPUT,
    GRANT_COINS_MENU,
    GRANT_COINS_PRESET_AMOUNTS,
)
from ..messages.localization import Localization
from ..users.roles import ADMIN_TRUST_LEVEL, USER_TRUST_LEVEL
from ..users.test_user import MockUser


@pytest.fixture
def admin_server(tmp_path):
    server = Server(
        db_path=tmp_path / "grant_coins_test.sqlite",
        database_backup_dir=tmp_path / "backups",
    )
    server._db.connect()

    admin_rec = server._db.create_user("AdminUser", "hash", trust_level=ADMIN_TRUST_LEVEL)
    server._db.approve_user("AdminUser")

    admin = MockUser("AdminUser", uuid=admin_rec.uuid, locale="es")
    admin.trust_level = ADMIN_TRUST_LEVEL
    admin.queue_protocol_packet = lambda packet: None

    server._users = {admin.username: admin}
    server._connections = {admin.username: SimpleNamespace(remote_address="127.0.0.1")}
    server._show_main_menu(admin)

    yield server, admin
    server._db.close()


def _create_approved_user(server: Server, username: str, trust_level: int = USER_TRUST_LEVEL):
    record = server._db.create_user(username, "hash", trust_level=trust_level)
    server._db.approve_user(username)
    return record


async def _select(server: Server, user: MockUser, menu_id: str, selection_id: str) -> None:
    await server._handle_menu(
        SimpleNamespace(username=user.username),
        {
            "type": "menu",
            "menu_id": menu_id,
            "selection_id": selection_id,
        },
    )


async def _submit_input(server: Server, user: MockUser, input_id: str, value: str) -> None:
    await server._handle_editbox(
        SimpleNamespace(username=user.username),
        {
            "type": "editbox",
            "input_id": input_id,
            "text": value,
        },
    )


@pytest.mark.asyncio
async def test_admin_menu_has_grant_coins_item(admin_server):
    server, admin = admin_server
    server.admin_manager._show_admin_menu(admin)

    items = admin.get_current_menu_items("admin_menu") or []
    grant_item = next((i for i in items if i.id == "grant_coins"), None)
    assert grant_item is not None
    assert Localization.get("es", "admin-grant-coins") in grant_item.text


@pytest.mark.asyncio
async def test_grant_coins_empty_users_speaks_error(admin_server):
    server, admin = admin_server
    # Unapprove or remove all users so total approved is 0
    server._db._conn.execute("UPDATE users SET approved = 0")
    server._db._conn.commit()

    server.admin_manager._show_admin_menu(admin)
    admin.clear_messages()
    await _select(server, admin, "admin_menu", "grant_coins")

    assert server._user_states[admin.username]["menu"] == "admin_menu"
    assert Localization.get("es", "admin-grant-coins-no-users") in admin.get_spoken_messages()


@pytest.mark.asyncio
async def test_grant_coins_menu_lists_and_searches_users(admin_server):
    server, admin = admin_server
    _create_approved_user(server, "Alice")
    _create_approved_user(server, "Bob")
    _create_approved_user(server, "Charlie")

    server.admin_manager._show_admin_menu(admin)
    await _select(server, admin, "admin_menu", "grant_coins")

    assert server._user_states[admin.username]["menu"] == GRANT_COINS_MENU
    item_ids = [item.id for item in admin.get_current_menu_items(GRANT_COINS_MENU) or []]
    assert "grant_coins_Alice" in item_ids
    assert "grant_coins_Bob" in item_ids
    assert "grant_coins_Charlie" in item_ids

    # Search for "Bob"
    await _select(server, admin, GRANT_COINS_MENU, "search")
    assert server._user_states[admin.username]["menu"] == "admin_target_search_input"
    await _submit_input(server, admin, "admin_target_search_input", "Bob")

    assert server._user_states[admin.username]["menu"] == GRANT_COINS_MENU
    filtered_ids = [item.id for item in admin.get_current_menu_items(GRANT_COINS_MENU) or []]
    assert "grant_coins_Bob" in filtered_ids
    assert "grant_coins_Alice" not in filtered_ids
    assert "grant_coins_Charlie" not in filtered_ids


@pytest.mark.asyncio
async def test_grant_coins_amount_menu_layout(admin_server):
    server, admin = admin_server
    alice_rec = _create_approved_user(server, "Alice")
    wallet = server._db.get_wallet(alice_rec.uuid)

    server.admin_manager._show_grant_coins_amount_menu(admin, "Alice")
    assert server._user_states[admin.username]["menu"] == GRANT_COINS_AMOUNT_MENU
    items = admin.get_current_menu_items(GRANT_COINS_AMOUNT_MENU) or []
    item_ids = [item.id for item in items]

    assert item_ids[0] == "target_balance"
    assert items[0].read_only is True
    assert str(wallet.balance) in items[0].text

    for amount in GRANT_COINS_PRESET_AMOUNTS:
        assert f"amount_{amount}" in item_ids

    assert "amount_custom" in item_ids
    assert "back" in item_ids


@pytest.mark.asyncio
async def test_grant_coins_preset_amount_success_online_recipient(admin_server):
    server, admin = admin_server
    alice_rec = _create_approved_user(server, "Alice")
    alice = MockUser("Alice", uuid=alice_rec.uuid, locale="es")
    server._users["Alice"] = alice

    initial_balance = server._db.get_wallet(alice_rec.uuid).balance

    server.admin_manager._show_grant_coins_amount_menu(admin, "Alice")
    admin.clear_messages()
    alice.clear_messages()

    await _select(server, admin, GRANT_COINS_AMOUNT_MENU, "amount_500")

    # DB wallet updated
    new_balance = server._db.get_wallet(alice_rec.uuid).balance
    assert new_balance == initial_balance + 500

    # Admin received sound and announcement
    assert "coins_grant.ogg" in admin.get_sounds_played()
    admin_spoken = " ".join(admin.get_spoken_messages())
    assert "500" in admin_spoken
    assert str(new_balance) in admin_spoken
    assert "Alice" in admin_spoken

    # Online recipient received sound and notification
    assert "coins_grant.ogg" in alice.get_sounds_played()
    alice_spoken = " ".join(alice.get_spoken_messages())
    assert "500" in alice_spoken
    assert str(new_balance) in alice_spoken

    # Admin returned to admin root with focus on grant_coins
    assert server._user_states[admin.username]["menu"] == "admin_menu"
    assert server._user_states[admin.username].get("_last_selection_id") == "grant_coins"


@pytest.mark.asyncio
async def test_grant_coins_preset_amount_success_offline_recipient(admin_server):
    server, admin = admin_server
    bob_rec = _create_approved_user(server, "Bob")
    initial_balance = server._db.get_wallet(bob_rec.uuid).balance

    server.admin_manager._show_grant_coins_amount_menu(admin, "Bob")
    admin.clear_messages()

    await _select(server, admin, GRANT_COINS_AMOUNT_MENU, "amount_1000")

    new_balance = server._db.get_wallet(bob_rec.uuid).balance
    assert new_balance == initial_balance + 1000
    assert "coins_grant.ogg" in admin.get_sounds_played()
    assert server._user_states[admin.username]["menu"] == "admin_menu"


@pytest.mark.asyncio
async def test_grant_coins_self_no_duplicate_audio(admin_server):
    server, admin = admin_server
    initial_balance = server._db.get_wallet(admin.uuid).balance

    server.admin_manager._show_grant_coins_amount_menu(admin, admin.username)
    admin.clear_messages()

    await _select(server, admin, GRANT_COINS_AMOUNT_MENU, "amount_100")

    new_balance = server._db.get_wallet(admin.uuid).balance
    assert new_balance == initial_balance + 100

    # Only one play_sound message, not duplicated
    assert admin.get_sounds_played() == ["coins_grant.ogg"]
    assert server._user_states[admin.username]["menu"] == "admin_menu"


@pytest.mark.asyncio
async def test_grant_coins_custom_amount_success(admin_server):
    server, admin = admin_server
    charlie_rec = _create_approved_user(server, "Charlie")
    initial_balance = server._db.get_wallet(charlie_rec.uuid).balance

    server.admin_manager._show_grant_coins_amount_menu(admin, "Charlie")
    await _select(server, admin, GRANT_COINS_AMOUNT_MENU, "amount_custom")

    assert server._user_states[admin.username]["menu"] == GRANT_COINS_INPUT
    assert "grant_coins_custom_amount" in admin.editboxes

    admin.clear_messages()
    await _submit_input(server, admin, "grant_coins_custom_amount", "7777")

    new_balance = server._db.get_wallet(charlie_rec.uuid).balance
    assert new_balance == initial_balance + 7777
    assert "coins_grant.ogg" in admin.get_sounds_played()
    assert server._user_states[admin.username]["menu"] == "admin_menu"


@pytest.mark.asyncio
async def test_grant_coins_custom_amount_validation_non_numeric(admin_server):
    server, admin = admin_server
    charlie_rec = _create_approved_user(server, "Charlie")
    initial_balance = server._db.get_wallet(charlie_rec.uuid).balance

    server.admin_manager._show_grant_coins_amount_menu(admin, "Charlie")
    await _select(server, admin, GRANT_COINS_AMOUNT_MENU, "amount_custom")

    admin.clear_messages()
    await _submit_input(server, admin, "grant_coins_custom_amount", "not_a_number")

    # Balance unmutated
    assert server._db.get_wallet(charlie_rec.uuid).balance == initial_balance
    assert Localization.get("es", "admin-grant-coins-error-invalid") in admin.get_spoken_messages()
    # Restored to amount menu
    assert server._user_states[admin.username]["menu"] == GRANT_COINS_AMOUNT_MENU


@pytest.mark.asyncio
async def test_grant_coins_custom_amount_validation_negative_and_zero(admin_server):
    server, admin = admin_server
    charlie_rec = _create_approved_user(server, "Charlie")
    initial_balance = server._db.get_wallet(charlie_rec.uuid).balance

    for invalid_val in ("0", "-100"):
        server.admin_manager._show_grant_coins_amount_menu(admin, "Charlie")
        await _select(server, admin, GRANT_COINS_AMOUNT_MENU, "amount_custom")

        admin.clear_messages()
        await _submit_input(server, admin, "grant_coins_custom_amount", invalid_val)

        assert server._db.get_wallet(charlie_rec.uuid).balance == initial_balance
        assert Localization.get("es", "admin-grant-coins-error-positive") in admin.get_spoken_messages()
        assert server._user_states[admin.username]["menu"] == GRANT_COINS_AMOUNT_MENU


@pytest.mark.asyncio
async def test_grant_coins_custom_amount_cancel_restores_parent(admin_server):
    server, admin = admin_server
    _create_approved_user(server, "Charlie")

    server.admin_manager._show_grant_coins_amount_menu(admin, "Charlie")
    await _select(server, admin, GRANT_COINS_AMOUNT_MENU, "amount_custom")

    await _submit_input(server, admin, "grant_coins_custom_amount", "")
    assert server._user_states[admin.username]["menu"] == GRANT_COINS_AMOUNT_MENU


@pytest.mark.asyncio
async def test_grant_coins_navigation_back_stack(admin_server):
    server, admin = admin_server
    _create_approved_user(server, "Alice")

    server.admin_manager._show_admin_menu(admin)
    await _select(server, admin, "admin_menu", "grant_coins")
    assert server._user_states[admin.username]["menu"] == GRANT_COINS_MENU

    await _select(server, admin, GRANT_COINS_MENU, "grant_coins_Alice")
    assert server._user_states[admin.username]["menu"] == GRANT_COINS_AMOUNT_MENU

    # Back from amount menu -> grant_coins_menu
    await _select(server, admin, GRANT_COINS_AMOUNT_MENU, "back")
    assert server._user_states[admin.username]["menu"] == GRANT_COINS_MENU

    # Back from grant_coins_menu -> admin_menu
    await _select(server, admin, GRANT_COINS_MENU, "back")
    assert server._user_states[admin.username]["menu"] == "admin_menu"


@pytest.mark.asyncio
async def test_non_admin_cannot_access_grant_coins(admin_server):
    server, _ = admin_server
    user_rec = _create_approved_user(server, "NormalUser", trust_level=USER_TRUST_LEVEL)
    normal_user = MockUser("NormalUser", uuid=user_rec.uuid, locale="es")
    normal_user.trust_level = USER_TRUST_LEVEL
    server._users["NormalUser"] = normal_user

    # Attempt to call _grant_coins_to_user directly
    await server.admin_manager._grant_coins_to_user(normal_user, "NormalUser", 500)
    assert Localization.get("es", "not-admin-anymore") in normal_user.get_spoken_messages()

    # Attempt to submit input to grant_coins_input
    server._user_states[normal_user.username] = {
        "menu": GRANT_COINS_INPUT,
        "target_username": "NormalUser",
    }
    normal_user.clear_messages()
    await _submit_input(server, normal_user, "grant_coins_custom_amount", "500")
    assert Localization.get("es", "not-admin-anymore") in normal_user.get_spoken_messages()
