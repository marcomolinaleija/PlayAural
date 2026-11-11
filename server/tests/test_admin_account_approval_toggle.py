"""Tests for account approval toggle setting in administration menu."""

from types import SimpleNamespace
import pytest

from ..core.server import Server, ACCOUNT_APPROVAL_REQUIRED_SETTING_KEY
from ..auth.auth import AuthManager
from ..messages.localization import Localization
from ..users.roles import ADMIN_TRUST_LEVEL, USER_TRUST_LEVEL
from ..users.test_user import MockUser


class DummyClientConnection:
    def __init__(self, ip: str = "127.0.0.1"):
        self.ip_address = ip
        self.sent_packets: list[dict] = []
        self.closed = False

    async def send(self, packet: dict) -> None:
        self.sent_packets.append(packet)

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def admin_server():
    server = Server(db_path=":memory:")
    server._db.connect()
    server._auth = AuthManager(server._db)
    server._db.create_user("AdminUser", "hash")
    admin_rec = server._db.get_user("AdminUser")

    admin = MockUser("AdminUser", uuid=admin_rec.uuid, locale="es")
    admin.trust_level = ADMIN_TRUST_LEVEL
    admin.queue_protocol_packet = lambda packet: None

    server._users = {admin.username: admin}
    server._connections = {admin.username: SimpleNamespace(remote_address="127.0.0.1")}
    yield server, admin
    server._db.close()


@pytest.mark.asyncio
async def test_account_approval_toggle_in_admin_menu(admin_server):
    server, admin = admin_server

    # Default is False (Desactivado)
    assert not server.account_approval_required
    assert not server._db.get_boolean_server_setting(
        ACCOUNT_APPROVAL_REQUIRED_SETTING_KEY, default=False
    )

    server.admin_manager._show_admin_users_menu(admin)
    items = admin.get_current_menu_items("admin_users_menu")
    toggle_item = next((i for i in items if i.id == "toggle_account_approval"), None)
    assert toggle_item is not None
    assert Localization.get("es", "option-off") in toggle_item.text

    # Toggle to True
    admin.clear_messages()
    await server.admin_manager._handle_admin_submenu_selection(
        admin, "toggle_account_approval", "admin_users_menu"
    )
    assert server.account_approval_required
    assert server._db.get_boolean_server_setting(
        ACCOUNT_APPROVAL_REQUIRED_SETTING_KEY, default=False
    )

    # Spoken feedback and sound
    spoken = admin.get_spoken_messages()
    assert any(Localization.get("es", "option-on") in s for s in spoken)
    sounds = [m.data.get("asset") for m in admin.messages if m.type == "play_sound"]
    assert "menuenter.ogg" in sounds

    # Menu reflects new state
    items = admin.get_current_menu_items("admin_users_menu")
    toggle_item = next(i for i in items if i.id == "toggle_account_approval")
    assert Localization.get("es", "option-on") in toggle_item.text

    # Toggle back to False
    admin.clear_messages()
    await server.admin_manager._handle_admin_submenu_selection(
        admin, "toggle_account_approval", "admin_users_menu"
    )
    assert not server.account_approval_required
    assert not server._db.get_boolean_server_setting(
        ACCOUNT_APPROVAL_REQUIRED_SETTING_KEY, default=True
    )


@pytest.mark.asyncio
async def test_registration_flow_respects_approval_toggle(admin_server):
    server, admin = admin_server

    # 1. When approval is required (True)
    server.set_account_approval_required(True)

    client1 = DummyClientConnection()
    admin.clear_messages()
    await server._handle_register(
        client1,
        {
            "username": "PendingUser1",
            "password": "Password123",
            "email": "pending1@example.com",
            "locale": "es",
        },
    )

    # Client receives success with pending approval text
    assert len(client1.sent_packets) == 1
    resp = client1.sent_packets[0]
    assert resp["type"] == "register_response"
    assert resp["status"] == "success"
    assert Localization.get("es", "auth-registration-pending-approval") in resp["text"]

    # Admin was notified with accountrequest.ogg
    admin_sounds = [m.data.get("asset") for m in admin.messages if m.type == "play_sound"]
    assert "accountrequest.ogg" in admin_sounds

    # User in DB is not approved
    user_rec = server._db.get_user("PendingUser1")
    assert user_rec is not None
    assert not user_rec.approved

    # 2. When approval is NOT required (False)
    server.set_account_approval_required(False)

    client2 = DummyClientConnection()
    await server._handle_register(
        client2,
        {
            "username": "AutoApprovedUser",
            "password": "Password123",
            "email": "auto@example.com",
            "locale": "es",
        },
    )

    assert len(client2.sent_packets) == 1
    resp2 = client2.sent_packets[0]
    assert resp2["type"] == "register_response"
    assert resp2["status"] == "success"
    assert Localization.get("es", "auth-registration-success") in resp2["text"]

    user_rec2 = server._db.get_user("AutoApprovedUser")
    assert user_rec2 is not None
    assert user_rec2.approved
