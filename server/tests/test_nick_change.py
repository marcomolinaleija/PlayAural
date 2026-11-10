"""Tests for the user nick change, 90/30-day cooldown, coin bypass/reduction, and admin approval flow."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest

from server.auth.auth import AuthManager
from server.core.server import Server
from server.administration.manager import (
    ADMIN_NICK_CHANGES_MENU,
    ADMIN_NICK_CHANGE_ACTIONS_MENU,
    ADMIN_NICK_REJECT_REASON_INPUT,
    ADMIN_NICK_REJECT_REFUND_MENU,
    ADMIN_USERS_MENU,
)
from server.users.roles import ADMIN_TRUST_LEVEL


class DummyConnection:
    def __init__(self, username: str):
        self.username = username
        self.address = "127.0.0.1:50000"

    async def send(self, packet: dict) -> None:
        pass


def _make_connected_user(server: Server, username: str, password: str = "Secret123!", *, trust_level: int = 1, locale: str = "es"):
    from server.users.network_user import NetworkUser

    auth = server._auth or AuthManager(server._db)
    server._auth = auth
    pwd_hash = auth.hash_password(password)
    record = server._db.create_user(
        username,
        pwd_hash,
        locale=locale,
        trust_level=trust_level,
        approved=True,
    )
    conn = DummyConnection(username)
    net_user = NetworkUser(
        username=record.username,
        locale=locale,
        connection=conn,
        uuid=record.uuid,
        trust_level=trust_level,
        approved=True,
    )
    server._users[record.username] = net_user
    return net_user, record


@pytest.mark.asyncio
async def test_first_nick_change_with_password_and_admin_approval(tmp_path) -> None:
    db_file = tmp_path / "nick_change.db"
    server = Server(db_path=str(db_file))
    server._db.connect()
    try:
        user, record = _make_connected_user(server, "jugador1", "ClaveSegura1!")
        admin, _ = _make_connected_user(
            server, "admin1", "AdminPass1!", trust_level=ADMIN_TRUST_LEVEL
        )

        # 1. Open profile menu and verify username item is clickable (`edit_nick`)
        server._show_profile_menu(user)
        profile_items = user._current_menus["profile_menu"]["items"]
        nick_item = next(
            (i for i in profile_items if isinstance(i, dict) and i.get("id") == "edit_nick"),
            None,
        )
        assert nick_item is not None

        # 2. Click username in profile -> opens nick_change_menu with free change option
        await server._handle_profile_selection(user, "edit_nick")
        assert server._user_states[user.username]["menu"] == "nick_change_menu"
        nick_menu_items = user._current_menus["nick_change_menu"]["items"]
        item_ids = [i.get("id") for i in nick_menu_items if isinstance(i, dict)]
        assert "change_nick" in item_ids

        # 3. Select change_nick -> opens nick_new_input editbox
        await server._handle_nick_change_menu_selection(
            user, "change_nick", server._user_states[user.username]
        )
        assert server._user_states[user.username]["menu"] == "nick_new_input"

        # 4. Enter desired new nick -> prompts for password confirmation
        await server._handle_editbox(
            SimpleNamespace(username=user.username),
            {"input_id": "nick_new_input", "text": "Campeon99"},
        )
        assert server._user_states[user.username]["menu"] == "nick_password_input"
        assert server._user_states[user.username]["pending_new_nick"] == "Campeon99"

        # 5. Wrong password rejects submission without creating a request
        await server._handle_editbox(
            SimpleNamespace(username=user.username),
            {"input_id": "nick_password_input", "text": "ClaveIncorrecta"},
        )
        assert server._db.count_pending_nick_requests() == 0
        assert server._user_states[user.username]["menu"] == "nick_change_menu"

        # 6. Re-submit with valid password -> creates pending request
        await server._handle_nick_change_menu_selection(
            user, "change_nick", server._user_states[user.username]
        )
        await server._handle_editbox(
            SimpleNamespace(username=user.username),
            {"input_id": "nick_new_input", "text": "Campeon99"},
        )
        await server._handle_editbox(
            SimpleNamespace(username=user.username),
            {"input_id": "nick_password_input", "text": "ClaveSegura1!"},
        )
        assert server._db.count_pending_nick_requests() == 1
        pending = server._db.get_user_pending_nick_request(record.uuid)
        assert pending is not None
        assert pending.requested_username == "Campeon99"
        assert pending.coins_paid == 0
        admin_queued = admin.get_queued_messages()
        assert any(
            p.get("type") == "audio" and p.get("asset") == "accountrequest.ogg"
            for p in admin_queued
        )

        # 7. Admin opens Users submenu -> "Cambios pendientes" -> approves request
        server.admin_manager._show_admin_users_menu(admin)
        admin_user_items = admin._current_menus[ADMIN_USERS_MENU]["items"]
        assert any(
            isinstance(i, dict) and i.get("id") == "pending_nick_changes"
            for i in admin_user_items
        )

        await server.admin_manager._handle_admin_menu_selection(
            admin, "pending_nick_changes"
        )
        assert server._user_states[admin.username]["menu"] == ADMIN_NICK_CHANGES_MENU

        await server.admin_manager._handle_pending_nick_changes_selection(
            admin,
            f"nick_req_{pending.id}",
            server._user_states[admin.username],
        )
        assert (
            server._user_states[admin.username]["menu"]
            == ADMIN_NICK_CHANGE_ACTIONS_MENU
        )

        user.get_queued_messages()
        await server.admin_manager._handle_pending_nick_change_actions_selection(
            admin, "approve", server._user_states[admin.username]
        )

        # 8. Verify username renamed in DB and live runtime, notification sound & reconnect message sent, and 90-day cooldown started
        user_queued = user.get_queued_messages()
        assert any(
            p.get("type") == "audio" and p.get("asset") == "accountapprove.ogg"
            for p in user_queued
        )
        assert any(
            p.get("type") == "speak"
            and "aprobado por un administrador" in p.get("text", "")
            and "reconectado con el nuevo nick" in p.get("text", "")
            for p in user_queued
        )
        assert any(
            p.get("type") == "username_updated" and p.get("username") == "Campeon99"
            for p in user_queued
        )
        assert user.username == "Campeon99"
        assert "Campeon99" in server._users
        assert "jugador1" not in server._users
        updated_record = server._db.get_user_by_uuid(record.uuid)
        assert updated_record is not None
        assert updated_record.username == "Campeon99"

        remaining = server._db.get_nick_cooldown_remaining(record.uuid)
        assert remaining.total_seconds() > 89 * 86400
    finally:
        server._db.close()


@pytest.mark.asyncio
async def test_cooldown_static_counter_and_coin_reduction_and_bypass(tmp_path) -> None:
    db_file = tmp_path / "nick_cooldown.db"
    server = Server(db_path=str(db_file))
    server._db.connect()
    try:
        user, record = _make_connected_user(server, "viajero", "MiClave123!")
        admin, _ = _make_connected_user(
            server, "admin1", "AdminPass1!", trust_level=ADMIN_TRUST_LEVEL
        )

        # Simulate a nick change approved 20 days ago (70 days remaining on 90-day limit)
        twenty_days_ago = (
            datetime.now(timezone.utc) - timedelta(days=20, hours=2)
        ).isoformat(timespec="microseconds")
        with server._db._transaction(immediate=True) as cursor:
            from server.persistence.database import NickChangeState

            server._db._set_nick_change_state_in_tx(
                cursor,
                NickChangeState(
                    user_uuid=record.uuid,
                    last_changed_at_utc=twenty_days_ago,
                    cooldown_reduced=False,
                ),
            )

        # Open nick_change_menu: counter should be at the top and static until reopened
        server._nav_push(user, server._show_nick_change_menu)
        state = server._user_states[user.username]
        snap1 = dict(state["cooldown_snapshot"])
        assert snap1["active"] is True
        assert snap1["days"] == 69

        items = user._current_menus["nick_change_menu"]["items"]
        assert items[0]["id"] == "nick_cooldown_counter"
        item_ids = [i.get("id") for i in items if isinstance(i, dict)]
        assert "bypass_cooldown" in item_ids
        assert "reduce_cooldown" in item_ids

        # Simulate time passing in DB, but _restore_frame keeps the static snapshot
        forty_days_ago = (
            datetime.now(timezone.utc) - timedelta(days=40)
        ).isoformat(timespec="microseconds")
        with server._db._transaction(immediate=True) as cursor:
            server._db._set_nick_change_state_in_tx(
                cursor,
                NickChangeState(
                    user_uuid=record.uuid,
                    last_changed_at_utc=forty_days_ago,
                    cooldown_reduced=False,
                ),
            )
        server._restore_frame(user, state, [])
        assert server._user_states[user.username]["cooldown_snapshot"]["days"] == 69

        # Re-opening the section updates the counter snapshot (now ~50 days left)
        server._show_nick_change_menu(user)
        assert server._user_states[user.username]["cooldown_snapshot"]["days"] in (49, 50)

        # Give user 50,000 coins and test 15,000-coin reduction (90 -> 30 days)
        # Since 40 days have already elapsed since last change, reducing to 30 days
        # immediately satisfies the cooldown!
        server._db.adjust_wallet_balance(record.uuid, 50000)
        await server._handle_nick_change_menu_selection(
            user, "reduce_cooldown", server._user_states[user.username]
        )
        assert server._user_states[user.username]["menu"] == "nick_reduce_confirm_menu"
        await server._handle_nick_reduce_confirm_selection(
            user, "yes", server._user_states[user.username]
        )
        assert server._db.get_wallet(record.uuid).balance == 50250 - 15000
        # Because 40 days > 30 days, the menu now unlocks free change!
        assert server._user_states[user.username]["menu"] == "nick_change_menu"
        unlocked_ids = [
            i.get("id")
            for i in user._current_menus["nick_change_menu"]["items"]
            if isinstance(i, dict)
        ]
        assert "change_nick" in unlocked_ids
    finally:
        server._db.close()


@pytest.mark.asyncio
async def test_paid_bypass_rejection_with_and_without_refund_and_collision_warning(
    tmp_path,
) -> None:
    db_file = tmp_path / "nick_reject.db"
    server = Server(db_path=str(db_file))
    server._db.connect()
    try:
        user, record = _make_connected_user(server, "alfa", "ClaveAlfa1!")
        other_user, _ = _make_connected_user(server, "omega", "ClaveOmega1!")
        admin, _ = _make_connected_user(
            server, "admin1", "AdminPass1!", trust_level=ADMIN_TRUST_LEVEL
        )

        # Put `alfa` on active cooldown (changed 1 day ago) and give 60,000 coins
        one_day_ago = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(
            timespec="microseconds"
        )
        with server._db._transaction(immediate=True) as cursor:
            from server.persistence.database import NickChangeState

            server._db._set_nick_change_state_in_tx(
                cursor,
                NickChangeState(
                    user_uuid=record.uuid,
                    last_changed_at_utc=one_day_ago,
                    cooldown_reduced=False,
                ),
            )
        server._db.adjust_wallet_balance(record.uuid, 60000)
        initial_balance = server._db.get_wallet(record.uuid).balance

        # 1. User buys 30,000-coin bypass and requests "omega" (colliding with existing user)
        server._show_nick_change_menu(user)
        await server._handle_nick_change_menu_selection(
            user, "bypass_cooldown", server._user_states[user.username]
        )
        await server._handle_editbox(
            SimpleNamespace(username=user.username),
            {"input_id": "nick_new_input", "text": "omega"},
        )
        await server._handle_editbox(
            SimpleNamespace(username=user.username),
            {"input_id": "nick_password_input", "text": "ClaveAlfa1!"},
        )

        assert server._db.get_wallet(record.uuid).balance == initial_balance - 30000
        req = server._db.get_user_pending_nick_request(record.uuid)
        assert req is not None
        assert req.coins_paid == 30000

        # 2. Admin inspects request -> sees collision warning row
        server.admin_manager._show_pending_nick_change_actions_menu(admin, req.id)
        detail_items = admin._current_menus[ADMIN_NICK_CHANGE_ACTIONS_MENU]["items"]
        detail_ids = [i.get("id") for i in detail_items if isinstance(i, dict)]
        assert "nick_detail_collision" in detail_ids

        # 3. Admin rejects with reason and chooses to REFUND the 30,000 coins
        await server.admin_manager._handle_pending_nick_change_actions_selection(
            admin, "reject", server._user_states[admin.username]
        )
        assert (
            server._user_states[admin.username]["menu"]
            == ADMIN_NICK_REJECT_REASON_INPUT
        )
        await server.admin_manager.handle_input(
            admin,
            {
                "input_id": ADMIN_NICK_REJECT_REASON_INPUT,
                "text": "El nick ya pertenece a otro jugador activo",
            },
            server._user_states[admin.username],
        )
        assert (
            server._user_states[admin.username]["menu"]
            == ADMIN_NICK_REJECT_REFUND_MENU
        )
        user.get_queued_messages()
        await server.admin_manager._handle_pending_nick_reject_refund_selection(
            admin, "reject_refund", server._user_states[admin.username]
        )

        # Verify 30,000 coins were refunded and rejection sound played
        user_reject_queued = user.get_queued_messages()
        assert any(
            p.get("type") == "audio" and p.get("asset") == "accountdeni.ogg"
            for p in user_reject_queued
        )
        assert server._db.get_wallet(record.uuid).balance == initial_balance
        resolved_req = server._db.get_nick_change_request(req.id)
        assert resolved_req is not None
        assert resolved_req.status == "rejected"
        assert resolved_req.refunded is True
        assert resolved_req.reject_reason == "El nick ya pertenece a otro jugador activo"

        # 4. Now test rejecting a paid request WITHOUT refund
        server._show_nick_change_menu(user)
        await server._handle_nick_change_menu_selection(
            user, "bypass_cooldown", server._user_states[user.username]
        )
        await server._handle_editbox(
            SimpleNamespace(username=user.username),
            {"input_id": "nick_new_input", "text": "AlfaNuevo"},
        )
        await server._handle_editbox(
            SimpleNamespace(username=user.username),
            {"input_id": "nick_password_input", "text": "ClaveAlfa1!"},
        )
        req2 = server._db.get_user_pending_nick_request(record.uuid)
        assert req2 is not None
        assert server._db.get_wallet(record.uuid).balance == initial_balance - 30000

        server.admin_manager._show_pending_nick_change_actions_menu(admin, req2.id)
        await server.admin_manager._handle_pending_nick_change_actions_selection(
            admin, "reject", server._user_states[admin.username]
        )
        await server.admin_manager.handle_input(
            admin,
            {
                "input_id": ADMIN_NICK_REJECT_REASON_INPUT,
                "text": "Solicitud no autorizada",
            },
            server._user_states[admin.username],
        )
        await server.admin_manager._handle_pending_nick_reject_refund_selection(
            admin, "reject_no_refund", server._user_states[admin.username]
        )

        assert server._db.get_wallet(record.uuid).balance == initial_balance - 30000
        resolved_req2 = server._db.get_nick_change_request(req2.id)
        assert resolved_req2 is not None
        assert resolved_req2.status == "rejected"
        assert resolved_req2.refunded is False
    finally:
        server._db.close()
