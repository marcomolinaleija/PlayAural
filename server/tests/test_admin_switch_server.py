"""Tests for the administration switch-server feature."""

import asyncio
from types import SimpleNamespace
import pytest

from ..core.server import Server
from ..users.test_user import MockUser


def _make_admin_server(tmp_path):
    server = Server(
        db_path=tmp_path / "admin_switch.sqlite",
        database_backup_dir=tmp_path / "backups",
    )
    server._db.connect()
    record = server._db.create_user("Admin", "hash", trust_level=3)
    server._db.approve_user("Admin")
    admin = MockUser("Admin", uuid=record.uuid)
    admin.trust_level = 3
    server._users[admin.username] = admin
    server._show_main_menu(admin)
    return server, admin


async def _select(server: Server, user: MockUser, menu_id: str, selection_id: str) -> None:
    await server._handle_menu(
        SimpleNamespace(username=user.username),
        {
            "type": "menu",
            "menu_id": menu_id,
            "selection_id": selection_id,
        },
    )


@pytest.mark.asyncio
async def test_admin_menu_includes_switch_server_for_admins(tmp_path):
    server, admin = _make_admin_server(tmp_path)
    server.admin_manager._show_admin_menu(admin)

    assert "admin_menu" in admin.menus
    item_ids = [item.id for item in admin.menus["admin_menu"]["items"]]
    assert "switch_server" in item_ids


@pytest.mark.asyncio
async def test_switch_server_retires_session_and_sends_packet(tmp_path):
    server, admin = _make_admin_server(tmp_path)
    server.admin_manager._show_admin_menu(admin)

    # Mock connection on user
    sent_packets = []

    async def mock_send(packet):
        sent_packets.append(packet)

    async def mock_close(*args, **kwargs):
        pass

    mock_client = SimpleNamespace(
        username=admin.username,
        authenticated=True,
        send=mock_send,
        close=mock_close,
    )
    admin.connection = mock_client

    await _select(server, admin, "admin_menu", "switch_server")

    # Connection should receive switch_server packet
    assert any(pkt.get("type") == "switch_server" for pkt in sent_packets)
    # User should be retired from server active users
    assert "Admin" not in server._users
