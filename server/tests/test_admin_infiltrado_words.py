"""Tests for Infiltrado word pairs management in administration menu."""

from types import SimpleNamespace
import pytest
import shutil

from ..auth.auth import AuthManager
from ..core.server import Server
from ..administration.manager import (
    ADMIN_INFILTRADO_ADD_CATEGORY_INPUT,
    ADMIN_INFILTRADO_ADD_WORD1_INPUT,
    ADMIN_INFILTRADO_ADD_WORD2_INPUT,
    ADMIN_INFILTRADO_CATEGORIES_MENU,
    ADMIN_INFILTRADO_CATEGORY_DETAIL_MENU,
    ADMIN_INFILTRADO_DELETE_CATEGORY_CONFIRM_MENU,
    ADMIN_INFILTRADO_EDIT_WORD1_INPUT,
    ADMIN_INFILTRADO_EDIT_WORD2_INPUT,
    ADMIN_INFILTRADO_PAIR_DETAIL_MENU,
    ADMIN_INFILTRADO_PAIRS_LIST_MENU,
    ADMIN_INFILTRADO_RENAME_CATEGORY_INPUT,
    ADMIN_INFILTRADO_SELECT_CATEGORY_MENU,
    ADMIN_INFILTRADO_WORDS_MENU,
)
from ..games.infiltrado.words import InfiltradoWordManager
from ..messages.localization import Localization
from ..users.roles import ADMIN_TRUST_LEVEL
from ..users.test_user import MockUser


@pytest.fixture(autouse=True)
def _isolate_infiltrado_words(tmp_path):
    from ..games.infiltrado.words import InfiltradoWordManager, WORDS_JSON_PATH

    if WORDS_JSON_PATH.exists():
        tmp_words = tmp_path / "infiltrado_words.json"
        shutil.copy2(WORDS_JSON_PATH, tmp_words)
        saved_method = InfiltradoWordManager.get_json_path
        InfiltradoWordManager.get_json_path = classmethod(lambda cls: tmp_words)
        InfiltradoWordManager.reload()
        try:
            yield
        finally:
            InfiltradoWordManager.get_json_path = saved_method
            InfiltradoWordManager.reload()
    else:
        yield


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
async def test_admin_menu_shows_infiltrado_words(admin_server):
    server, admin = admin_server
    server.admin_manager._show_admin_menu(admin)

    # Check menu items sent to admin
    menu = admin.menus.get("admin_menu")
    assert menu is not None
    item_ids = [item.id if hasattr(item, "id") else item for item in menu["items"]]
    assert "manage_infiltrado_words" in item_ids


@pytest.mark.asyncio
async def test_admin_infiltrado_words_navigation(admin_server):
    server, admin = admin_server

    # Open admin menu and click manage_infiltrado_words
    server.admin_manager._show_admin_menu(admin)
    state = server.user_states.get(admin.username, {})
    await server.admin_manager.handle_menu_selection(
        admin, "manage_infiltrado_words", "admin_menu", state
    )

    current_state = server.user_states.get(admin.username, {})
    assert current_state.get("menu") == ADMIN_INFILTRADO_WORDS_MENU

    words_menu = admin.menus.get(ADMIN_INFILTRADO_WORDS_MENU)
    assert words_menu is not None
    item_ids = [item.id if hasattr(item, "id") else item for item in words_menu["items"]]
    assert "add_pair" in item_ids
    assert "list_pairs" in item_ids


@pytest.mark.asyncio
async def test_admin_infiltrado_pairs_list_pagination(admin_server):
    server, admin = admin_server

    server.admin_manager._show_infiltrado_pairs_list_menu(admin, page=1)
    current_state = server.user_states.get(admin.username, {})
    assert current_state.get("menu") == ADMIN_INFILTRADO_PAIRS_LIST_MENU
    assert current_state.get("page") == 1
    assert current_state.get("total_pages", 0) >= 3

    # Check list menu items
    pairs_menu = admin.menus.get(ADMIN_INFILTRADO_PAIRS_LIST_MENU)
    assert pairs_menu is not None
    item_ids = [item.id if hasattr(item, "id") else item for item in pairs_menu["items"]]
    assert any(str(i).startswith("pair_") for i in item_ids)


@pytest.mark.asyncio
async def test_admin_add_pair_flow(admin_server):
    server, admin = admin_server

    # Start at hub
    server.admin_manager._show_infiltrado_words_menu(admin)
    state = server.user_states.get(admin.username, {})
    await server.admin_manager.handle_menu_selection(
        admin, "add_pair", ADMIN_INFILTRADO_WORDS_MENU, state
    )

    # Now in input state 1
    input_state1 = server.user_states.get(admin.username, {})
    assert input_state1.get("menu") == ADMIN_INFILTRADO_ADD_WORD1_INPUT

    # User submits word 1
    packet1 = {"input_id": "infiltrado_add_word1", "text": "Sol"}
    handled1 = await server.admin_manager.handle_input(admin, packet1, input_state1)
    assert handled1 is True

    # Now in input state 2
    input_state2 = server.user_states.get(admin.username, {})
    assert input_state2.get("menu") == ADMIN_INFILTRADO_ADD_WORD2_INPUT
    assert input_state2.get("draft_word1") == "Sol"

    # User submits word 2
    initial_count = InfiltradoWordManager.count_pairs()
    packet2 = {"input_id": "infiltrado_add_word2", "text": "Luna"}
    handled2 = await server.admin_manager.handle_input(admin, packet2, input_state2)
    assert handled2 is True

    # Shows category selection
    sel_cat_state = server.user_states.get(admin.username, {})
    assert sel_cat_state.get("menu") == ADMIN_INFILTRADO_SELECT_CATEGORY_MENU
    assert sel_cat_state.get("draft_word1") == "Sol"
    assert sel_cat_state.get("draft_word2") == "Luna"

    # Select General category
    await server.admin_manager.handle_menu_selection(
        admin, "sel_cat_General", ADMIN_INFILTRADO_SELECT_CATEGORY_MENU, sel_cat_state
    )

    assert InfiltradoWordManager.count_pairs() == initial_count + 1

    # Cleanup added pair
    added = [p for p in InfiltradoWordManager.get_all_pairs() if p.word1 == "Sol" and p.word2 == "Luna"]
    assert len(added) >= 1
    assert added[-1].category == "General"
    InfiltradoWordManager.delete_pair(added[-1].id)


@pytest.mark.asyncio
async def test_admin_edit_and_delete_pair(admin_server):
    server, admin = admin_server

    # Create temporary pair
    temp_pair = InfiltradoWordManager.add_pair("EditTest1", "EditTest2")
    pair_id = temp_pair.id

    # View pair detail
    server.admin_manager._show_infiltrado_pair_detail_menu(admin, pair_id)
    detail_state = server.user_states.get(admin.username, {})
    assert detail_state.get("menu") == ADMIN_INFILTRADO_PAIR_DETAIL_MENU
    assert detail_state.get("pair_id") == pair_id

    # Select edit_word1
    await server.admin_manager.handle_menu_selection(
        admin, "edit_word1", ADMIN_INFILTRADO_PAIR_DETAIL_MENU, detail_state
    )
    edit_state1 = server.user_states.get(admin.username, {})
    assert edit_state1.get("menu") == ADMIN_INFILTRADO_EDIT_WORD1_INPUT

    # Submit updated word1
    packet_edit = {"input_id": "infiltrado_edit_word1", "text": "NuevoWord1"}
    await server.admin_manager.handle_input(admin, packet_edit, edit_state1)

    updated_pair = InfiltradoWordManager.get_pair_by_id(pair_id)
    assert updated_pair is not None
    assert updated_pair.word1 == "NuevoWord1"

    # Delete pair
    server.admin_manager._show_infiltrado_pair_detail_menu(admin, pair_id)
    detail_state = server.user_states.get(admin.username, {})
    await server.admin_manager.handle_menu_selection(
        admin, "delete_pair", ADMIN_INFILTRADO_PAIR_DETAIL_MENU, detail_state
    )
    assert InfiltradoWordManager.get_pair_by_id(pair_id) is None


@pytest.mark.asyncio
async def test_admin_categories_management(admin_server):
    server, admin = admin_server

    # Go to categories menu
    server.admin_manager._show_infiltrado_categories_menu(admin)
    cat_state = server.user_states.get(admin.username, {})
    assert cat_state.get("menu") == ADMIN_INFILTRADO_CATEGORIES_MENU

    # Click add_category
    await server.admin_manager.handle_menu_selection(
        admin, "add_category", ADMIN_INFILTRADO_CATEGORIES_MENU, cat_state
    )
    add_state = server.user_states.get(admin.username, {})
    assert add_state.get("menu") == ADMIN_INFILTRADO_ADD_CATEGORY_INPUT

    # Submit new category "CineTest"
    packet = {"input_id": "infiltrado_add_category", "text": "CineTest"}
    await server.admin_manager.handle_input(admin, packet, add_state)
    assert "CineTest" in InfiltradoWordManager.get_categories()

    # Enter CineTest category detail
    server.admin_manager._show_infiltrado_category_detail_menu(admin, "CineTest")
    detail_state = server.user_states.get(admin.username, {})
    assert detail_state.get("menu") == ADMIN_INFILTRADO_CATEGORY_DETAIL_MENU
    assert detail_state.get("category") == "CineTest"

    # Rename category to "PelisTest"
    await server.admin_manager.handle_menu_selection(
        admin, "rename_category", ADMIN_INFILTRADO_CATEGORY_DETAIL_MENU, detail_state
    )
    rename_state = server.user_states.get(admin.username, {})
    assert rename_state.get("menu") == ADMIN_INFILTRADO_RENAME_CATEGORY_INPUT
    packet_rename = {"input_id": "infiltrado_rename_category", "text": "PelisTest"}
    await server.admin_manager.handle_input(admin, packet_rename, rename_state)
    assert "PelisTest" in InfiltradoWordManager.get_categories()
    assert "CineTest" not in InfiltradoWordManager.get_categories()

    # Add a pair directly into PelisTest
    server.admin_manager._show_infiltrado_category_detail_menu(admin, "PelisTest")
    detail_state2 = server.user_states.get(admin.username, {})
    await server.admin_manager.handle_menu_selection(
        admin, "add_pair_to_category", ADMIN_INFILTRADO_CATEGORY_DETAIL_MENU, detail_state2
    )
    add_w1_state = server.user_states.get(admin.username, {})
    assert add_w1_state.get("draft_category") == "PelisTest"

    packet_w1 = {"input_id": "infiltrado_add_word1", "text": "Actor"}
    await server.admin_manager.handle_input(admin, packet_w1, add_w1_state)
    add_w2_state = server.user_states.get(admin.username, {})
    assert add_w2_state.get("draft_category") == "PelisTest"

    packet_w2 = {"input_id": "infiltrado_add_word2", "text": "Director"}
    await server.admin_manager.handle_input(admin, packet_w2, add_w2_state)

    pelis_pairs = InfiltradoWordManager.get_pairs_by_category("PelisTest")
    assert len(pelis_pairs) == 1
    pair = pelis_pairs[0]
    assert pair.word1 == "Actor"
    assert pair.category == "PelisTest"

    # Delete category PelisTest -> pair should be reassigned to General
    server.admin_manager._show_infiltrado_category_detail_menu(admin, "PelisTest")
    detail_state3 = server.user_states.get(admin.username, {})
    await server.admin_manager.handle_menu_selection(
        admin, "delete_category", ADMIN_INFILTRADO_CATEGORY_DETAIL_MENU, detail_state3
    )
    confirm_state = server.user_states.get(admin.username, {})
    assert confirm_state.get("menu") == ADMIN_INFILTRADO_DELETE_CATEGORY_CONFIRM_MENU

    # Confirm delete
    await server.admin_manager.handle_menu_selection(
        admin, "confirm", ADMIN_INFILTRADO_DELETE_CATEGORY_CONFIRM_MENU, confirm_state
    )
    assert "PelisTest" not in InfiltradoWordManager.get_categories()
    reassigned = InfiltradoWordManager.get_pair_by_id(pair.id)
    assert reassigned is not None
    assert reassigned.category == "General"

    # Cleanup
    InfiltradoWordManager.delete_pair(pair.id)


@pytest.mark.asyncio
async def test_admin_change_pair_category(admin_server):
    server, admin = admin_server

    pair = InfiltradoWordManager.add_pair("GatoTest", "PerroTest", category="General")
    assert pair.category == "General"

    # Open pair detail and select change_category
    server.admin_manager._show_infiltrado_pair_detail_menu(admin, pair.id)
    detail_state = server.user_states.get(admin.username, {})
    await server.admin_manager.handle_menu_selection(
        admin, "change_category", ADMIN_INFILTRADO_PAIR_DETAIL_MENU, detail_state
    )

    sel_cat_state = server.user_states.get(admin.username, {})
    assert sel_cat_state.get("menu") == ADMIN_INFILTRADO_SELECT_CATEGORY_MENU
    assert sel_cat_state.get("pair_id") == pair.id

    # Choose "Animales y naturaleza"
    await server.admin_manager.handle_menu_selection(
        admin, "sel_cat_Animales y naturaleza", ADMIN_INFILTRADO_SELECT_CATEGORY_MENU, sel_cat_state
    )

    updated = InfiltradoWordManager.get_pair_by_id(pair.id)
    assert updated is not None
    assert updated.category == "Animales y naturaleza"

    # Cleanup
    InfiltradoWordManager.delete_pair(pair.id)
