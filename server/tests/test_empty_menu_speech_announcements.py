from __future__ import annotations

import pytest

from ..core.server import Server
from ..games.crazyeights.game import CrazyEightsGame
from ..games.freetable.game import FreeTable
from ..messages.localization import Localization
from ..users.roles import ADMIN_TRUST_LEVEL, USER_TRUST_LEVEL
from ..users.test_user import MockUser


def _setup_server():
    server = Server(db_path=":memory:")
    server._db.connect()
    return server


@pytest.mark.asyncio
async def test_saved_tables_empty_announcement_keeps_user_in_main_menu():
    server = _setup_server()
    rec = server._db.create_user("Alice", "hash", trust_level=USER_TRUST_LEVEL)
    server._db.approve_user("Alice")
    alice = MockUser("Alice", uuid=rec.uuid)
    alice.queue_protocol_packet = lambda packet: None
    server._users[alice.username] = alice

    # Show main menu
    server._show_main_menu(alice)
    assert server._user_states[alice.username]["menu"] == "main_menu"
    alice.clear_messages()

    # Select saved_tables with 0 saves
    await server._handle_main_menu_selection(alice, "saved_tables")

    # Menu did not change
    assert server._user_states[alice.username]["menu"] == "main_menu"
    assert "saved_tables_menu" not in alice.menus

    # Announcement spoken
    expected_text = Localization.get(alice.locale, "no-saved-tables")
    spoken = [m.data.get("text") for m in alice.messages if m.type == "speak"]
    assert any(expected_text in t for t in spoken)

    # Now add a saved table and confirm it opens the menu
    server._db.save_user_table(
        username=alice.username,
        save_name="Test Save",
        game_type="crazyeights",
        game_json="{}",
        members_json="[]",
        table_state_json="{}",
    )
    alice.clear_messages()
    await server._handle_main_menu_selection(alice, "saved_tables")
    assert server._user_states[alice.username]["menu"] == "saved_tables_menu"
    assert "saved_tables_menu" in alice.menus


@pytest.mark.asyncio
async def test_friends_hub_empty_submenus_speak_without_opening_menus():
    server = _setup_server()
    rec = server._db.create_user("Alice", "hash", trust_level=USER_TRUST_LEVEL)
    server._db.approve_user("Alice")
    alice = MockUser("Alice", uuid=rec.uuid)
    alice.queue_protocol_packet = lambda packet: None
    server._users[alice.username] = alice

    server._show_friends_hub_menu(alice)
    assert server._user_states[alice.username]["menu"] == "friends_hub_menu"

    # 1. my_friends when 0 friends
    alice.clear_messages()
    await server._handle_friends_hub_selection(alice, "my_friends")
    assert server._user_states[alice.username]["menu"] == "friends_hub_menu"
    assert "friends_list_menu" not in alice.menus
    assert any(
        Localization.get(alice.locale, "friends-list-empty") in m.data.get("text", "")
        for m in alice.messages if m.type == "speak"
    )

    # 2. pending_requests when 0 pending requests
    alice.clear_messages()
    await server._handle_friends_hub_selection(alice, "pending_requests")
    assert server._user_states[alice.username]["menu"] == "friends_hub_menu"
    assert "friend_requests_menu" not in alice.menus
    assert any(
        Localization.get(alice.locale, "no-pending-requests") in m.data.get("text", "")
        for m in alice.messages if m.type == "speak"
    )

    # 3. sent_requests when 0 sent requests
    alice.clear_messages()
    await server._handle_friends_hub_selection(alice, "sent_requests")
    assert server._user_states[alice.username]["menu"] == "friends_hub_menu"
    assert "sent_friend_requests_menu" not in alice.menus
    assert any(
        Localization.get(alice.locale, "no-sent-requests") in m.data.get("text", "")
        for m in alice.messages if m.type == "speak"
    )

    # 4. blocked_users when 0 blocked users
    alice.clear_messages()
    await server._handle_friends_hub_selection(alice, "blocked_users")
    assert server._user_states[alice.username]["menu"] == "friends_hub_menu"
    assert "blocked_users_menu" not in alice.menus
    assert any(
        Localization.get(alice.locale, "friends-blocked-empty") in m.data.get("text", "")
        for m in alice.messages if m.type == "speak"
    )


@pytest.mark.asyncio
async def test_my_stats_empty_announcement_keeps_user_in_personal_options():
    server = _setup_server()
    rec = server._db.create_user("Alice", "hash", trust_level=USER_TRUST_LEVEL)
    server._db.approve_user("Alice")
    alice = MockUser("Alice", uuid=rec.uuid)
    alice.queue_protocol_packet = lambda packet: None
    server._users[alice.username] = alice

    server._show_personal_options_menu(alice)
    assert server._user_states[alice.username]["menu"] == "personal_options_menu"
    alice.clear_messages()

    await server._handle_personal_options_selection(alice, "my_stats")
    assert server._user_states[alice.username]["menu"] == "personal_options_menu"
    assert "my_stats_menu" not in alice.menus
    assert any(
        Localization.get(alice.locale, "my-stats-no-games") in m.data.get("text", "")
        for m in alice.messages if m.type == "speak"
    )


@pytest.mark.asyncio
async def test_host_management_empty_submenus_speak_without_changing_menu():
    server = _setup_server()
    rec = server._db.create_user("Alice", "hash", trust_level=USER_TRUST_LEVEL)
    server._db.approve_user("Alice")
    alice = MockUser("Alice", uuid=rec.uuid)
    alice.queue_protocol_packet = lambda packet: None
    server._users[alice.username] = alice

    table = server._tables.create_table("crazyeights", alice.username, alice)
    game = CrazyEightsGame()
    table.game = game
    game._table = table
    game.initialize_lobby(alice.username, alice)

    server._show_host_management_menu(alice, table)
    state = server._user_states[alice.username]
    assert state["menu"] == "host_management_menu"

    # 1. invite_friend (Alice has no friends)
    alice.clear_messages()
    await server._handle_host_management_selection(alice, "invite_friend", state)
    assert server._user_states[alice.username]["menu"] == "host_management_menu"
    assert "host_invite_menu" not in alice.menus
    assert any(
        Localization.get(alice.locale, "host-invite-no-friends") in m.data.get("text", "")
        for m in alice.messages if m.type == "speak"
    )

    # 2. pass_host (only Alice is in table)
    alice.clear_messages()
    await server._handle_host_management_selection(alice, "pass_host", state)
    assert server._user_states[alice.username]["menu"] == "host_management_menu"
    assert "host_pass_menu" not in alice.menus
    assert any(
        Localization.get(alice.locale, "host-pass-no-candidates") in m.data.get("text", "")
        for m in alice.messages if m.type == "speak"
    )

    # 3. kick_player (no other users in table)
    alice.clear_messages()
    await server._handle_host_management_selection(alice, "kick_player", state)
    assert server._user_states[alice.username]["menu"] == "host_management_menu"
    assert "host_kick_menu" not in alice.menus
    assert any(
        Localization.get(alice.locale, "host-kick-no-candidates") in m.data.get("text", "")
        for m in alice.messages if m.type == "speak"
    )

    # 4. kick_ban_player
    alice.clear_messages()
    await server._handle_host_management_selection(alice, "kick_ban_player", state)
    assert server._user_states[alice.username]["menu"] == "host_management_menu"
    assert "host_kick_ban_menu" not in alice.menus
    assert any(
        Localization.get(alice.locale, "host-kick-no-candidates") in m.data.get("text", "")
        for m in alice.messages if m.type == "speak"
    )

    # 5. manage_voice (no other members)
    alice.clear_messages()
    await server._handle_host_management_selection(alice, "manage_voice", state)
    assert server._user_states[alice.username]["menu"] == "host_management_menu"
    assert "host_voice_management_menu" not in alice.menus
    assert any(
        Localization.get(alice.locale, "voice-host-management-no-members") in m.data.get("text", "")
        for m in alice.messages if m.type == "speak"
    )

    # 6. player_substitution (waiting lobby -> game not playing, no substitution seats)
    alice.clear_messages()
    await server._handle_host_management_selection(alice, "player_substitution", state)
    assert server._user_states[alice.username]["menu"] == "host_management_menu"
    assert "host_substitution_seat_menu" not in alice.menus
    assert any(
        Localization.get(alice.locale, "player-substitution-no-seats") in m.data.get("text", "")
        for m in alice.messages if m.type == "speak"
    )


@pytest.mark.asyncio
async def test_admin_account_approval_and_reports_empty_announcements():
    server = _setup_server()
    rec = server._db.create_user("AdminUser", "hash", trust_level=ADMIN_TRUST_LEVEL)
    server._db.approve_user("AdminUser")
    admin = MockUser("AdminUser", uuid=rec.uuid)
    admin.trust_level = ADMIN_TRUST_LEVEL
    admin.queue_protocol_packet = lambda packet: None
    server._users[admin.username] = admin

    # 1. Account approval with 0 pending users
    server.admin_manager._show_admin_menu(admin)
    assert server._user_states[admin.username]["menu"] == "admin_menu"
    admin.clear_messages()

    await server.admin_manager._handle_admin_menu_selection(admin, "account_approval")
    assert server._user_states[admin.username]["menu"] == "admin_menu"
    assert "account_approval_menu" not in admin.menus
    assert any(
        Localization.get(admin.locale, "no-pending-accounts") in m.data.get("text", "")
        for m in admin.messages if m.type == "speak"
    )

    # 2. Moderation reports with 0 reports
    server.admin_manager._show_moderation_menu(admin)
    assert server._user_states[admin.username]["menu"] == "admin_moderation_menu"

    for report_filter in ("reports_open", "reports_closed", "reports_all"):
        admin.clear_messages()
        await server.admin_manager._handle_moderation_selection(admin, report_filter)
        assert server._user_states[admin.username]["menu"] == "admin_moderation_menu"
        assert "admin_moderation_reports_menu" not in admin.menus
        assert any(
            Localization.get(admin.locale, "admin-moderation-no-reports") in m.data.get("text", "")
            for m in admin.messages if m.type == "speak"
        )


@pytest.mark.asyncio
async def test_detailed_scores_empty_announces_without_status_box():
    server = _setup_server()
    rec = server._db.create_user("Alice", "hash", trust_level=USER_TRUST_LEVEL)
    server._db.approve_user("Alice")
    alice = MockUser("Alice", uuid=rec.uuid)
    alice.queue_protocol_packet = lambda packet: None

    game = FreeTable()
    game.initialize_lobby(alice.username, alice)
    player = game.players[0]

    alice.clear_messages()
    game._action_check_scores_detailed(player, "check_scores_detailed")

    # FreeTable does not support scores; verifies it speaks instead of opening a status box
    assert "status_box" not in alice.menus
    assert any(
        Localization.get(alice.locale, "no-scores-available") in m.data.get("text", "")
        for m in alice.messages if m.type == "speak"
    )


@pytest.mark.asyncio
async def test_leaderboard_types_empty_selection_announces():
    server = _setup_server()
    rec = server._db.create_user("Alice", "hash", trust_level=USER_TRUST_LEVEL)
    server._db.approve_user("Alice")
    alice = MockUser("Alice", uuid=rec.uuid)
    alice.queue_protocol_packet = lambda packet: None
    server._users[alice.username] = alice

    server._show_leaderboard_types_menu(alice, "crazyeights")
    state = server._user_states[alice.username]
    assert state["menu"] == "leaderboard_types_menu"

    alice.clear_messages()
    # crazyeights has no stats yet
    await server._handle_leaderboard_types_selection(alice, "type_wins", state)
    assert server._user_states[alice.username]["menu"] == "leaderboard_types_menu"
    assert "game_leaderboard" not in alice.menus
    assert any(
        Localization.get(alice.locale, "leaderboard-no-data") in m.data.get("text", "")
        for m in alice.messages if m.type == "speak"
    )

    alice.clear_messages()
    await server._handle_leaderboard_types_selection(alice, "type_rating", state)
    assert server._user_states[alice.username]["menu"] == "leaderboard_types_menu"
    assert "game_leaderboard" not in alice.menus
    assert any(
        Localization.get(alice.locale, "leaderboard-no-ratings") in m.data.get("text", "")
        for m in alice.messages if m.type == "speak"
    )

