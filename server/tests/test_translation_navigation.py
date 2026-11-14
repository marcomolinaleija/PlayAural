"""Shared translation menus preserve focus, table membership and reviewer gates."""

import asyncio
import json
from types import SimpleNamespace

import pytest
from websockets.asyncio.client import connect

from ..auth.auth import AuthManager
from ..core.server import Server, VERSION
from ..games.pig.game import PigGame
from ..translations.catalog import Catalog, default_catalog
from ..messages.localization import Localization
from ..translations import navigation as nav
from ..users.network_user import NetworkUser


def small_catalog(root):
    for language in ('es', 'en', 'fr'):
        directory = root / 'server/locales' / language
        directory.mkdir(parents=True)
        (directory / 'metadata.json').write_text(json.dumps({'code': language, 'name': language, 'native_name': language}), encoding='utf-8')
    (root / 'server/locales/es/main.ftl').write_text('hello = Hola, { $player }.\nnext = Adiós.\n', encoding='utf-8')
    return Catalog(root)


@pytest.fixture
def forum(tmp_path):
    server = Server(db_path=str(tmp_path / 'translation-nav.db'))
    server.db.connect()
    server.translations.service._catalog = small_catalog(tmp_path / 'source')
    users = {}
    for name, level in (('Author', 1), ('Staff', 2), ('Friend', 1)):
        account = server.db.create_user(name, 'hash', locale='es', approved=True, trust_level=level)
        connection = SimpleNamespace(username=name, authenticated=True, retired=False)
        users[name] = user = NetworkUser(name, 'es', connection, uuid=account.uuid, approved=True, trust_level=level)
        server._users[name] = user
        server._show_main_menu(user)
        user.get_queued_messages()
    yield server, users
    server.db.close()


async def choose(server, user, selection):
    await server._handle_menu(user._connection, {
        'type': 'menu', 'menu_id': server._user_states[user.username]['menu'], 'selection_id': selection,
    })
    return user.get_queued_messages()


async def fill(server, user, value, *, cancelled=False):
    state = server._user_states[user.username]
    await server._handle_editbox(user._connection, {'type': 'editbox', 'input_id': state['menu'], 'text': value, 'cancelled': cancelled})
    return user.get_queued_messages()


async def open_editor(server, user):
    await choose(server, user, 'personal_options')
    await choose(server, user, 'collaborate')
    await choose(server, user, 'translations')
    await choose(server, user, 'language:fr')
    await choose(server, user, 'missing')
    await choose(server, user, 'section:server:general')
    unit = next(u for u in server.translations.service.catalog.units.values() if u.key == 'hello')
    await choose(server, user, 'unit:' + unit.id)
    return server._user_states[user.username]['tr_id']


@pytest.mark.parametrize('language, mode', [
    ('id', 'all'), ('id', 'missing'), ('es', 'all'), ('en', 'all'),
    ('vi', 'all'), ('fa', 'all'), ('pt', 'all'), ('ar', 'all'),
])
async def test_real_catalog_language_sections_use_localized_game_names(forum, language, mode):
    server, users = forum
    author = users['Author']
    server.translations.service._catalog = default_catalog()
    await choose(server, author, 'personal_options')
    await choose(server, author, 'collaborate')
    await choose(server, author, 'translations')
    await choose(server, author, 'language:' + language)
    packets = await choose(server, author, mode)
    menu = next(p for p in packets if p.get('menu_id') == nav.SECTIONS)
    assert server._user_states[author.username]['menu'] == nav.SECTIONS
    if mode == 'all':
        section = next(item for item in menu['items'] if item.get('id') == 'section:server:game:ageofheroes')
        assert Localization.get(author.locale, 'game-name-ageofheroes') in section['text']
        await choose(server, author, section['id'])
        assert server._user_states[author.username]['menu'] == nav.UNITS
        await choose(server, author, 'back')
    await choose(server, author, 'back')
    assert server._user_states[author.username]['menu'] == nav.DASHBOARD


async def test_complete_author_staff_review_and_credit_with_readonly_source(forum):
    server, users = forum
    author, staff = users['Author'], users['Staff']
    proposal_id = await open_editor(server, author)
    await choose(server, author, 'original')
    assert server._user_states[author.username]['menu'] == nav.READ_INPUT
    await fill(server, author, 'Forged original')
    assert server.translations.service.get(author.uuid, proposal_id)['source_text'] == 'Hola, { $player }.'
    await choose(server, author, 'edit')
    packets = await fill(server, author, 'Bonjour, { $player }.')
    editor = next(p for p in packets if p.get('menu_id') == nav.EDITOR)
    assert editor['selection_id'] == 'edit'
    assert 'Bonjour' in editor['items'][1]['text']
    await choose(server, author, 'preview')
    await fill(server, author, '', cancelled=True)
    await choose(server, author, 'submit')
    await choose(server, author, 'yes')
    assert server.translations.service.get(author.uuid, proposal_id)['status'] == 'pending'
    await choose(server, staff, 'administration')
    await choose(server, staff, 'review_translations')
    assert server._user_states[staff.username]['menu'] == nav.REVIEW
    await choose(server, staff, 'review_language:fr')
    await choose(server, staff, 'review_author:' + author.uuid)
    await choose(server, staff, 'review:' + str(proposal_id))
    await choose(server, staff, 'approve')
    await choose(server, staff, 'yes')
    assert server.translations.service.get(author.uuid, proposal_id)['status'] == 'approved'
    assert server.translations.service.credits(author.uuid, 'fr')[0]['username'] == 'Author'


async def test_admin_grants_translator_role_and_member_reviews_without_admin_access(forum):
    server, users = forum
    author, staff, translator = users['Author'], users['Staff'], users['Friend']
    proposal_id = await open_editor(server, author)
    await choose(server, author, 'edit')
    await fill(server, author, 'Bonjour, { $player }.')
    await choose(server, author, 'submit')
    await choose(server, author, 'yes')
    await choose(server, staff, 'administration')
    await choose(server, staff, 'translation_team')
    await choose(server, staff, 'search')
    packets = await fill(server, staff, 'Friend')
    menu = next(p for p in packets if p.get('menu_id') == nav.TEAM)
    assert [item['id'] for item in menu['items'] if item.get('id', '').startswith('team_user:')] == ['team_user:' + translator.uuid]
    await choose(server, staff, 'team_user:' + translator.uuid)
    await choose(server, staff, 'team_language:fr')
    await choose(server, staff, 'yes')
    assert server.db.get_user('Friend').trust_level == 1
    assert server._get_user_role_and_client_text('es', translator)[0] == 'Traductor'
    await choose(server, translator, 'personal_options')
    await choose(server, translator, 'collaborate')
    await choose(server, translator, 'review_translations')
    await choose(server, translator, 'review_language:fr')
    await choose(server, translator, 'review_author:' + author.uuid)
    await choose(server, translator, 'review:' + str(proposal_id))
    await choose(server, translator, 'approve')
    await choose(server, translator, 'yes')
    assert server.translations.service.get(author.uuid, proposal_id)['status'] == 'approved'
    await choose(server, staff, 'team_language:fr')
    await choose(server, staff, 'yes')
    assert not server.translations.service.roles.can_review(translator.uuid)
    # A stale open reviewer screen cannot retain its old privileges.
    server.translations.open_review(translator)
    assert server._user_states[translator.username]['menu'] == nav.REVIEW_AUTHORS


async def test_review_returns_to_next_proposal_then_contributor_list(forum):
    server, users = forum
    author, staff, friend = users['Author'], users['Staff'], users['Friend']
    service = server.translations.service
    first_id = await open_editor(server, author)
    first = service.get(author.uuid, first_id)
    first = service.save(author.uuid, first_id, 'Bonjour, { $player }.', first['revision'])
    service.submit(author.uuid, [(first_id, first['revision'])])
    next_unit = next(u for u in service.catalog.units.values() if u.key == 'next')
    second = service.draft(author.uuid, 'fr', next_unit.id)
    second = service.save(author.uuid, second['id'], 'Au revoir.', second['revision'])
    service.submit(author.uuid, [(second['id'], second['revision'])])
    await choose(server, staff, 'administration')
    await choose(server, staff, 'review_translations')
    await choose(server, staff, 'review_language:fr')
    await choose(server, staff, 'review_author:' + author.uuid)
    await choose(server, staff, 'review:' + str(second['id']))
    await choose(server, staff, 'approve')
    packets = await choose(server, staff, 'yes')
    menu = next(p for p in reversed(packets) if p.get('menu_id') == nav.REVIEW_ITEMS)
    assert menu['selection_id'] == 'review:' + str(first_id)
    other = service.draft(friend.uuid, 'fr', next_unit.id)
    other = service.save(friend.uuid, other['id'], 'À bientôt.', other['revision'])
    service.submit(friend.uuid, [(other['id'], other['revision'])])
    await choose(server, staff, 'review:' + str(first_id))
    await choose(server, staff, 'request_changes')
    packets = await fill(server, staff, 'Usa un saludo informal.')
    menu = next(p for p in packets if p.get('menu_id') == nav.REVIEW_AUTHORS)
    assert [item['id'] for item in menu['items'] if item.get('id', '').startswith('review_author:')] == ['review_author:' + friend.uuid]
    assert service.get(author.uuid, first_id)['status'] == 'changes_requested'


async def test_reserved_text_remains_readable_but_editing_waits_for_release(forum):
    server, users = forum
    author, other = users['Author'], users['Friend']
    first_id = await open_editor(server, author)
    await choose(server, author, 'edit')
    second_id = await open_editor(server, other)
    await choose(server, other, 'original')
    await fill(server, other, '', cancelled=True)
    packets = await choose(server, other, 'edit')
    assert server._user_states[other.username]['menu'] == nav.EDITOR
    assert any(packet.get('key') == 'translation-error-reserved' for packet in packets)
    await fill(server, author, 'Bonjour, { $player }.')
    await choose(server, author, 'release')
    await choose(server, author, 'yes')
    assert server.translations.service.get(author.uuid, first_id)['value'] == 'Bonjour, { $player }.'
    await choose(server, other, 'edit')
    assert server._user_states[other.username]['menu'] == nav.TEXT_INPUT
    await fill(server, other, 'Salut, { $player }.')
    assert server.translations.service.get(other.uuid, second_id)['value'] == 'Salut, { $player }.'


async def test_guided_variants_are_ordinary_editors_and_keep_original_readonly(forum):
    server, users = forum
    author = users['Author']
    service = server.translations.service
    root = service.catalog.root
    (root / 'server/locales/es/main.ftl').write_text(
        'variants = { $count ->\n    [one] Un punto.\n   *[other] { $count } puntos.\n}\n', encoding='utf-8')
    service._catalog = Catalog(root)
    unit = next(iter(service.catalog.units.values()))
    proposal = service.draft(author.uuid, 'fr', unit.id)
    server._nav_push(author, server.translations.editor, proposal['id'])
    await choose(server, author, 'edit')
    assert server._user_states[author.username]['menu'] == nav.FORMS
    await choose(server, author, 'form:text/case:0:one')
    await choose(server, author, 'original')
    await fill(server, author, 'Forged')
    await choose(server, author, 'edit')
    await fill(server, author, 'Un point.')
    await choose(server, author, 'back')
    await choose(server, author, 'form:text/case:0:other')
    await choose(server, author, 'edit')
    await fill(server, author, '{ $count } points.')
    await choose(server, author, 'back')
    await choose(server, author, 'back')
    await choose(server, author, 'submit')
    await choose(server, author, 'yes')
    assert service.get(author.uuid, proposal['id'])['status'] == 'pending'


async def test_new_language_and_reviewed_history_can_revert_an_approval(forum):
    server, users = forum
    author, staff = users['Author'], users['Staff']
    await choose(server, author, 'personal_options')
    await choose(server, author, 'collaborate')
    await choose(server, author, 'translations')
    await choose(server, author, 'new_language')
    for field, value in (('code', 'de'), ('name', 'German'), ('native_name', 'Deutsch')):
        await choose(server, author, 'language_field:' + field)
        await fill(server, author, value)
    await choose(server, author, 'create')
    assert server._user_states[author.username]['tr_language'] == 'de'
    await choose(server, author, 'missing')
    await choose(server, author, 'section:server:general')
    unit = next(u for u in server.translations.service.catalog.units.values() if u.key == 'next')
    await choose(server, author, 'unit:' + unit.id)
    proposal_id = server._user_states[author.username]['tr_id']
    await choose(server, author, 'edit')
    await fill(server, author, 'Auf Wiedersehen.')
    await choose(server, author, 'submit')
    await choose(server, author, 'yes')
    await choose(server, staff, 'administration')
    await choose(server, staff, 'review_translations')
    await choose(server, staff, 'review_language:de')
    await choose(server, staff, 'review_author:' + author.uuid)
    await choose(server, staff, 'review:' + str(proposal_id))
    await choose(server, staff, 'approve')
    await choose(server, staff, 'yes')
    await choose(server, staff, 'back')
    await choose(server, staff, 'toggle_history')
    await choose(server, staff, 'review_language:de')
    await choose(server, staff, 'review_author:' + author.uuid)
    await choose(server, staff, 'review:' + str(proposal_id))
    await choose(server, staff, 'revert')
    await choose(server, staff, 'yes')
    assert server.translations.service.get(author.uuid, proposal_id)['status'] == 'reverted'


async def test_next_restores_the_new_unit_and_page_on_back(forum):
    server, users = forum
    author = users['Author']
    service = server.translations.service
    root = service.catalog.root
    (root / 'server/locales/es/main.ftl').write_text(
        ''.join(f'entry-{number:02} = Texto {number}.\n' for number in range(32)), encoding='utf-8')
    service._catalog = Catalog(root)
    units = list(service.catalog.units.values())
    server._nav_push(author, server.translations.units, 'fr', 'missing', 'server:general')
    await choose(server, author, 'unit:' + units[29].id)
    await choose(server, author, 'next')
    packets = await choose(server, author, 'back')
    menu = next(p for p in packets if p.get('menu_id') == nav.UNITS)
    assert server._user_states[author.username]['tr_page'] == 2
    assert menu['selection_id'] == 'unit:' + units[30].id


async def test_translation_overlay_returns_to_game_without_pausing_or_leaving(forum):
    server, users = forum
    author, friend = users['Author'], users['Friend']
    table = server._tables.create_table('pig', author.username, author)
    table.game = game = PigGame()
    game._table = table
    game.initialize_lobby(author.username, author)
    table.add_member(friend.username, friend, as_spectator=False)
    game.add_player(friend.username, friend)
    game.on_start()
    server._user_states[author.username] = {'menu': 'in_game', 'table_id': table.table_id}
    server._nav_push(author, server._show_personal_options_menu)
    await choose(server, author, 'collaborate')
    await choose(server, author, 'translations')
    await choose(server, author, 'language:fr')
    assert server._tables.find_user_table(author.username) is table
    before = game.turn_index
    game.on_tick()
    assert game.game_active and server._tables.find_user_table(author.username) is table
    for _ in range(4):
        await choose(server, author, 'back')
    assert server._user_states[author.username]['menu'] == 'in_game'
    assert game.turn_index == before


async def test_return_for_changes_and_retry_invalid_input_preserves_editor(forum):
    server, users = forum
    author, staff = users['Author'], users['Staff']
    proposal_id = await open_editor(server, author)
    await choose(server, author, 'edit')
    await fill(server, author, 'Bonjour, { $player }.')
    await choose(server, author, 'submit')
    await choose(server, author, 'yes')
    server._nav_push(staff, server.translations.editor, proposal_id, True)
    await choose(server, staff, 'request_changes')
    await fill(server, staff, 'Usa un saludo informal.')
    proposal = server.translations.service.get(author.uuid, proposal_id)
    assert proposal['status'] == 'changes_requested' and proposal['note'] == 'Usa un saludo informal.'
    server._nav_refresh(author, server.translations.editor, proposal_id)
    await choose(server, author, 'edit')
    await fill(server, author, 'Salut, { $player }.')
    await choose(server, author, 'submit')
    await choose(server, author, 'yes')
    assert server.translations.service.get(author.uuid, proposal_id)['status'] == 'pending'


async def test_live_drafts_are_input_bound_preserve_partial_text_and_close_without_losing_last_edit(forum):
    server, users = forum
    author = users['Author']
    proposal_id = await open_editor(server, author)
    packets = await choose(server, author, 'edit')
    prompt = next(p for p in packets if p.get('input_id') == nav.TEXT_INPUT)
    token = prompt['translation_draft']['token']
    server.translations.save_live_draft(author, {'input_id': nav.TEXT_INPUT, 'token': token, 'sequence': 1, 'text': 'Bonjour {'})
    assert server.translations.service.get(author.uuid, proposal_id)['value'] == 'Bonjour {'
    response = next(p for p in author.get_queued_messages() if p.get('type') == 'translation_draft')
    assert response['saved'] and response['error']
    server.translations.save_live_draft(author, {'input_id': nav.TEXT_INPUT, 'token': 'retired', 'sequence': 2, 'text': 'Forged'})
    server.translations.save_live_draft(users['Friend'], {'input_id': nav.TEXT_INPUT, 'token': token, 'sequence': 2, 'text': 'Forged'})
    assert server.translations.service.get(author.uuid, proposal_id)['value'] == 'Bonjour {'
    await fill(server, author, 'Bonjour, { $player }.', cancelled=True)
    assert server.translations.service.get(author.uuid, proposal_id)['value'] == 'Bonjour, { $player }.'
    server.translations.save_live_draft(author, {'input_id': nav.TEXT_INPUT, 'token': token, 'sequence': 3, 'text': 'Late'})
    assert server.translations.service.get(author.uuid, proposal_id)['value'] == 'Bonjour, { $player }.'


async def test_concurrent_edit_requires_explicit_choice_and_does_not_drop_user_text(forum):
    server, users = forum
    author = users['Author']
    proposal_id = await open_editor(server, author)
    await choose(server, author, 'edit')
    current = server.translations.service.get(author.uuid, proposal_id)
    server.translations.service.save(author.uuid, proposal_id, 'Another device.', current['revision'])
    await fill(server, author, 'Mon brouillon, { $player }.')
    assert server._user_states[author.username]['menu'] == nav.CONFLICT
    assert server.translations.service.get(author.uuid, proposal_id)['value'] == 'Another device.'
    await choose(server, author, 'use_mine')
    await choose(server, author, 'yes')
    assert server._user_states[author.username]['menu'] == nav.EDITOR
    assert server.translations.service.get(author.uuid, proposal_id)['value'] == 'Mon brouillon, { $player }.'


@pytest.mark.parametrize('client_type', ['python', 'web', 'mobile'])
async def test_translator_flow_over_real_websocket(tmp_path, client_type):
    server = Server(host='127.0.0.1', port=0, db_path=str(tmp_path / 'translation-socket.db'))
    server.translations.service._catalog = small_catalog(tmp_path / 'source')
    await server.start()
    try:
        auth = AuthManager(server.db)
        assert auth.register('Staff', 'StaffTranslatePassword123', locale='es', email='staff@example.test') == 'ok'
        server.db.approve_user('Staff')
        assert auth.register('Author', 'TranslatePassword123', locale='es', email='author@example.test') == 'ok'
        server.db.approve_user('Author')
        port = server._ws_server._server.sockets[0].getsockname()[1]
        async def receive(ws, predicate):
            async with asyncio.timeout(15):
                while True:
                    packet = json.loads(await ws.recv())
                    if predicate(packet):
                        return packet
        async def select(ws, menu, selection, target):
            await ws.send(json.dumps({'type': 'menu', 'menu_id': menu, 'selection_id': selection}))
            return await receive(ws, lambda p: p.get('menu_id') == target)
        async with connect(f'ws://127.0.0.1:{port}') as ws:
            await ws.send(json.dumps({'type': 'authorize', 'client': client_type, 'version': VERSION,
                                     'username': 'Author', 'password': 'TranslatePassword123'}))
            await receive(ws, lambda p: p.get('menu_id') == 'main_menu')
            for menu, action, target in (
                ('main_menu', 'personal_options', 'personal_options_menu'),
                ('personal_options_menu', 'collaborate', nav.COLLABORATE),
                (nav.COLLABORATE, 'translations', nav.LANGUAGES),
                (nav.LANGUAGES, 'language:fr', nav.DASHBOARD),
                (nav.DASHBOARD, 'missing', nav.SECTIONS),
                (nav.SECTIONS, 'section:server:general', nav.UNITS),
            ):
                await select(ws, menu, action, target)
            unit = next(u for u in server.translations.service.catalog.units.values() if u.key == 'hello')
            await select(ws, nav.UNITS, 'unit:' + unit.id, nav.EDITOR)
            await ws.send(json.dumps({'type': 'menu', 'menu_id': nav.EDITOR, 'selection_id': 'edit'}))
            prompt = await receive(ws, lambda p: p.get('input_id') == nav.TEXT_INPUT)
            assert prompt['multiline'] and not prompt['read_only']
            await ws.send(json.dumps({'type': 'translation_draft', 'input_id': nav.TEXT_INPUT,
                                     'token': prompt['translation_draft']['token'], 'sequence': 1,
                                     'text': 'Bonjour, { $player }.'}))
            draft_ack = await receive(ws, lambda p: p.get('type') == 'translation_draft')
            assert draft_ack['saved'] and not draft_ack['error'] and 'Bonjour' in draft_ack['preview']
            await ws.send(json.dumps({'type': 'editbox', 'input_id': nav.TEXT_INPUT, 'text': 'Bonjour, { $player }.'}))
            await receive(ws, lambda p: p.get('menu_id') == nav.EDITOR)
            await select(ws, nav.EDITOR, 'submit', nav.CONFIRM)
            await select(ws, nav.CONFIRM, 'yes', nav.EDITOR)
            author = server.db.get_user('Author')
            proposal = server.translations.service.proposals(author.uuid)[0]
            assert proposal['status'] == 'pending'
            async with connect(f'ws://127.0.0.1:{port}') as staff:
                await staff.send(json.dumps({'type': 'authorize', 'client': client_type, 'version': VERSION,
                                            'username': 'Staff', 'password': 'StaffTranslatePassword123'}))
                await receive(staff, lambda p: p.get('menu_id') == 'main_menu')
                await select(staff, 'main_menu', 'administration', 'admin_menu')
                await select(staff, 'admin_menu', 'review_translations', nav.REVIEW)
                await select(staff, nav.REVIEW, 'review_language:fr', nav.REVIEW_AUTHORS)
                await select(staff, nav.REVIEW_AUTHORS, 'review_author:' + author.uuid, nav.REVIEW_ITEMS)
                await select(staff, nav.REVIEW_ITEMS, 'review:' + str(proposal['id']), nav.EDITOR)
                await select(staff, nav.EDITOR, 'approve', nav.CONFIRM)
                await select(staff, nav.CONFIRM, 'yes', nav.REVIEW_AUTHORS)
                assert server.translations.service.get(author.uuid, proposal['id'])['status'] == 'approved'
                notice = await receive(ws, lambda p: p.get('key') == 'translation-response-notice')
                assert notice['history'] is False
    finally:
        await server.stop()
