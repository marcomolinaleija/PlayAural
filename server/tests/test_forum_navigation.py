"""Exercise the same native forum flow over real desktop/web/mobile sockets."""

import asyncio
import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from websockets.asyncio.client import connect

from ..auth.auth import AuthManager
from ..core.server import Server, VERSION
from ..forum import navigation as nav
from ..forum.models import Draft
from ..users.network_user import NetworkUser


async def receive(ws, predicate):
    async with asyncio.timeout(15):
        while True:
            packet = json.loads(await ws.recv())
            if predicate(packet):
                return packet


async def choose(ws, menu, action, result=None):
    await ws.send(json.dumps({"type": "menu", "menu_id": menu, "selection_id": action}))
    if result:
        return await receive(ws, lambda p: p.get("menu_id") == result)


async def fill(ws, field, text):
    await choose(ws, nav.COMPOSER, "edit_title" if field == nav.TITLE_INPUT else "edit_body")
    prompt = await receive(ws, lambda p: p.get("input_id") == field and p["type"] == "request_input")
    assert prompt["multiline"] is (field == nav.BODY_INPUT)
    await ws.send(json.dumps({"type": "editbox", "input_id": field, "text": text}))
    return await receive(ws, lambda p: p.get("menu_id") == nav.COMPOSER)


@pytest.mark.parametrize("client_type", ["python", "web", "mobile"])
async def test_create_read_reply_edit_and_save_over_real_websocket(tmp_path, client_type):
    server = Server(host="127.0.0.1", port=0, db_path=str(tmp_path / "network.db"))
    await server.start()
    try:
        auth = AuthManager(server.db)
        for name in ("Alice", "Bob"):
            assert auth.register(name, "ForumPassword123", locale="es", email=f"{name}@example.com") == "ok"
            server.db.approve_user(name)
        port = server._ws_server._server.sockets[0].getsockname()[1]
        async with connect(f"ws://127.0.0.1:{port}") as alice, connect(f"ws://127.0.0.1:{port}") as bob:
            for ws, name in ((alice, "Alice"), (bob, "Bob")):
                await ws.send(json.dumps({"type": "authorize", "client": client_type, "version": VERSION,
                                          "username": name, "password": "ForumPassword123"}))
                main = await receive(ws, lambda p: p.get("menu_id") == "main_menu")
                assert "forum" in [row["id"] for row in main["items"]]
                await choose(ws, "main_menu", "forum", nav.HOME)
            await choose(alice, nav.HOME, "category:general", nav.TOPICS)
            await choose(alice, nav.TOPICS, "new_topic", nav.COMPOSER)
            await fill(alice, nav.TITLE_INPUT, "Una comunidad accesible")
            preview = await fill(alice, nav.BODY_INPUT, "Hola a todos.\nSegunda línea con <script>texto literal</script>.")
            assert any("<script>" in row["text"] and row["id"] == 'edit_body' and not row.get('read_only', False)
                       for row in preview["items"])
            assert server.db._conn.execute("SELECT COUNT(*) FROM forum_posts").fetchone()[0] == 0
            published = await choose(alice, nav.COMPOSER, "publish", nav.POST)
            assert "Hola a todos." in str(published)
            alice_uuid = server.db.get_user("Alice").uuid
            topic = server.forum_manager.service.topics(alice_uuid).items[0]
            # A queued duplicate publish cannot execute on the new surface.
            await choose(alice, nav.COMPOSER, "publish")
            unread = await choose(bob, nav.HOME, "unread", nav.TOPICS)
            assert f"topic:{topic.id}" in [row["id"] for row in unread["items"]]
            await choose(bob, nav.TOPICS, f"topic:{topic.id}", nav.THREAD)
            await choose(bob, nav.THREAD, "continue", nav.POST)
            bob_uuid = server.db.get_user("Bob").uuid
            assert server.forum_manager.service.topic(bob_uuid, topic.id).unread_count == 0
            await choose(bob, nav.POST, "reply", nav.COMPOSER)
            await fill(bob, nav.BODY_INPUT, "Gracias por abrir esta conversación.")
            await choose(bob, nav.COMPOSER, "publish", nav.POST)
            await choose(bob, nav.POST, "edit", nav.COMPOSER)
            await fill(bob, nav.BODY_INPUT, "Gracias. Esta es mi respuesta editada.")
            edited = await choose(bob, nav.COMPOSER, "publish", nav.POST)
            assert "respuesta editada" in str(edited)
            thread = await choose(bob, nav.POST, "back", nav.THREAD)
            assert thread.get("selection_id") == f"post:{server.forum_manager.service.topic(bob_uuid, topic.id).last_post_id}"
            await choose(bob, nav.THREAD, "bookmark", nav.THREAD)
            assert server.forum_manager.service.topics(bob_uuid, view="saved").total == 1
            assert server.forum_manager.service.posts(bob_uuid, topic.id).total == 2
    finally:
        await server.stop()


@pytest.fixture
def navigation_server():
    server = Server(db_path=":memory:")
    server.db.connect()
    record = server.db.create_user("Writer", "hash", locale='es')
    server.db.approve_user("Writer")
    connection = SimpleNamespace(username="Writer", retired=False)
    user = NetworkUser("Writer", "es", connection, uuid=record.uuid, approved=True)
    server._users[user.username] = user
    server._show_main_menu(user)
    yield server, user, connection
    server.db.close()


async def test_editor_cancel_discard_and_stale_input_are_safe(navigation_server):
    server, user, connection = navigation_server
    await server._handle_main_menu_selection(user, "forum")
    manager = server.forum_manager
    manager.handle_menu(user, "category:general", server._user_states[user.username])
    manager.handle_menu(user, "new_topic", server._user_states[user.username])
    manager.handle_menu(user, "edit_body", server._user_states[user.username])
    await server._handle_editbox(connection, {"type": "editbox", "input_id": "wrong", "text": "stale"})
    assert server._user_states[user.username]["menu"] == nav.BODY_INPUT
    await server._handle_editbox(connection, {"type": "editbox", "input_id": nav.BODY_INPUT, "text": "A kept draft"})
    state = server._user_states[user.username]
    manager.handle_menu(user, "back", state)
    assert server._user_states[user.username]["menu"] == nav.DISCARD
    manager.handle_menu(user, "no", server._user_states[user.username])
    assert server._user_states[user.username]["forum_draft"]["body"] == "A kept draft"
    manager.handle_menu(user, "back", server._user_states[user.username])
    manager.handle_menu(user, "yes", server._user_states[user.username])
    assert server._user_states[user.username]["menu"] == nav.TOPICS
    assert "forum_draft" not in server._user_states[user.username]
    assert server.db._conn.execute("SELECT COUNT(*) FROM forum_posts").fetchone()[0] == 0


async def test_failed_publish_keeps_draft_and_moderator_permission_is_rechecked(navigation_server):
    server, user, connection = navigation_server
    manager = server.forum_manager
    topic, post = manager.service.create_topic(user.uuid, "general", "Topic", "Original")
    server._nav_push(user, manager.views.thread, topic)
    manager.handle_menu(user, "reply", server._user_states[user.username])
    state = server._user_states[user.username]
    state["forum_draft"] = asdict(Draft("reply", topic_id=topic, body="Pending reply"))
    server.db.update_user_trust_level("Writer", 2)
    manager.service.moderate(user.uuid, topic, "closed", True)
    manager.handle_menu(user, "publish", state)
    assert server._user_states[user.username]["forum_draft"]["body"] == "Pending reply"
    assert manager.service.posts(user.uuid, topic).total == 1
    server._nav_back(user)
    manager.handle_menu(user, "toggle_closed", server._user_states[user.username])
    assert server._user_states[user.username]["menu"] == nav.MODERATE
    server.db.update_user_trust_level("Writer", 1)
    manager.handle_menu(user, "yes", server._user_states[user.username])
    assert manager.service.topic(user.uuid, topic).closed


@pytest.mark.parametrize("target", ["python", "web", "mobile"])
def test_handover_restores_draft_intent_but_never_old_confirmation(navigation_server, target):
    server, previous, connection = navigation_server
    user = NetworkUser(previous.username, previous.locale, connection, uuid=previous.uuid,
                       client_type=target, approved=True)
    server._users[user.username] = user
    draft = Draft("topic", category_id="general", title="Draft", body="Saved in session")
    composer = {"menu": nav.COMPOSER, "forum_draft": asdict(draft)}
    input_state = {"menu": nav.BODY_INPUT, "_transient": True, "_parent_frame": composer,
                   "_stack": [{"menu": nav.HOME}]}
    normalized = server._normalize_restore_state_for_client(user, input_state)
    server._restore_menu_from_state(user, normalized)
    assert server._user_states[user.username]["forum_draft"] == asdict(draft)
    confirm = {"menu": nav.DISCARD, "forum_draft": asdict(draft), "_stack": [composer]}
    normalized = server._normalize_restore_state_for_client(user, confirm)
    assert normalized["menu"] == nav.COMPOSER


async def test_forged_and_stale_menu_selections_never_route(navigation_server):
    server, user, connection = navigation_server
    await server._handle_main_menu_selection(user, "forum")
    await server._handle_menu(connection, {"type": "menu", "menu_id": nav.HOME, "selection_id": "topic:99"})
    await server._handle_menu(connection, {"type": "menu", "menu_id": nav.THREAD, "selection_id": "toggle_closed"})
    await server._handle_editbox(connection, {"type": "editbox", "input_id": nav.SEARCH_INPUT, "text": "forged search"})
    assert server._user_states[user.username]["menu"] == nav.HOME


def test_content_precedes_actions_and_entry_context_is_spoken_once(navigation_server):
    server, user, _ = navigation_server
    manager = server.forum_manager
    topic, first = manager.service.create_topic(user.uuid, "general", "Nuestra comunidad", "Primer mensaje")
    server._nav_push(user, manager.home)
    packets = user.get_queued_messages()
    home = [p for p in packets if p.get("menu_id") == nav.HOME][-1]
    assert home["items"][0]["id"] == "category:general"
    assert home["title"] == "Foro: Español"
    assert len([p for p in packets if p.get("key") == "forum-entry-home-language"]) == 1
    server._nav_push(user, manager.views.topics, "category", "general")
    packets = user.get_queued_messages()
    topics = [p for p in packets if p.get("menu_id") == nav.TOPICS][-1]
    assert [row["id"] for row in topics["items"]][:2] == [f"topic:{topic}", "new_topic"]
    assert not {"heading", "intro", "meta", "page_summary", "empty"} & {row["id"] for row in topics["items"]}
    server._nav_push(user, manager.views.thread, topic)
    packets = user.get_queued_messages()
    thread = [p for p in packets if p.get("menu_id") == nav.THREAD][-1]
    assert thread["items"][0]["id"] == f"post:{first}"
    context = [p for p in packets if p.get("key") == "forum-entry-thread-language"]
    assert len(context) == 1 and context[0]["history"] is False and context[0]["buffer"] == "misc"
    assert "Nuestra comunidad" in context[0]["text"] and "Writer" in context[0]["text"]
    assert "forum-" not in context[0]["text"]
    server._nav_refresh(user, manager.views.thread, topic)
    assert not [p for p in user.get_queued_messages() if p.get("key", "").startswith("forum-entry-")]
    server._nav_push(user, manager.views.post, first)
    packets = user.get_queued_messages()
    reader = [p for p in packets if p.get("menu_id") == nav.POST][-1]
    assert reader["items"][0]["text"] == "Primer mensaje"
    assert reader["items"][0]["read_only"]
    assert reader["items"][-1]["id"] == "back"


async def test_attachment_actions_refresh_count_preparation_and_removal_without_duplicate_context(navigation_server, tmp_path):
    from ..forum.media_http import ForumMediaHTTP
    from ..forum.media_processing import MediaProcessor
    server, user, _ = navigation_server
    manager = server.forum_manager
    transport = ForumMediaHTTP(server, base_url='http://127.0.0.1:8001', directory=tmp_path / 'media')
    manager.media = transport
    manager.media_ui.connect(transport)
    server._nav_push(user, manager.composer.show, Draft('topic', category_id='general', title='Files', body='Body'))
    user.get_queued_messages()
    manager.handle_menu(user, 'extras', server._user_states[user.username])
    user.get_queued_messages()
    draft = Draft(**server._user_states[user.username]['forum_draft'])
    row = manager.media_ui.reserve(user, {'draft_token': draft.token, 'name': 'notes.txt', 'size': 10})
    packets = user.get_queued_messages()
    menu = next(p for p in packets if p.get('menu_id') == nav.EXTRAS)
    action = next(item for item in menu['items'] if item['id'] == 'attachment')
    assert action['text'] == 'Adjuntar archivo: 1 archivo seleccionado; 0 preparados'
    assert not any(p.get('key', '').startswith('forum-entry-') for p in packets)
    source = tmp_path / 'notes.txt'
    source.write_text('Plain text', encoding='utf-8')
    manager.service.attachments.processing(user.uuid, row['id'])
    processed = MediaProcessor().process(source, tmp_path / 'prepared')
    manager.service.attachments.complete(user.uuid, row['id'], processed)
    manager.media_ui.completed(user.uuid, row['id'], None)
    menu = next(p for p in user.get_queued_messages() if p.get('menu_id') == nav.EXTRAS)
    assert menu['items'][0]['text'] == 'Adjuntar archivo: 1 archivo seleccionado; 1 preparado'
    manager.handle_menu(user, 'back', server._user_states[user.username])
    menu = next(p for p in user.get_queued_messages() if p.get('menu_id') == nav.COMPOSER)
    assert next(item for item in menu['items'] if item['id'] == 'extras')['text'] == 'Añadir…: 1 archivo seleccionado; 1 preparado'
    manager.handle_menu(user, 'attachment:' + row['id'], server._user_states[user.username])
    user.get_queued_messages()
    manager.handle_menu(user, 'remove', server._user_states[user.username])
    menu = next(p for p in user.get_queued_messages() if p.get('menu_id') == nav.COMPOSER)
    assert next(item for item in menu['items'] if item['id'] == 'extras')['text'] == 'Añadir…'
    assert not server._user_states[user.username]['forum_draft']['attachment_ids']


async def test_composer_updates_editable_message_without_duplicate_preview_or_entry_help(navigation_server):
    server, user, connection = navigation_server
    manager = server.forum_manager
    topic, _ = manager.service.create_topic(user.uuid, "general", "Topic", "First")
    server._nav_push(user, manager.views.thread, topic)
    user.get_queued_messages()
    manager.handle_menu(user, "reply", server._user_states[user.username])
    packets = user.get_queued_messages()
    assert len([p for p in packets if p.get("key") == "forum-entry-composer"]) == 1
    menu = [p for p in packets if p.get("menu_id") == nav.COMPOSER][-1]
    assert [row["id"] for row in menu["items"]] == ["edit_body", "extras", "publish", "back"]
    manager.handle_menu(user, "edit_body", server._user_states[user.username])
    user.get_queued_messages()
    await server._handle_editbox(connection, {"type": "editbox", "input_id": nav.BODY_INPUT, "text": "Un borrador para revisar"})
    packets = user.get_queued_messages()
    assert not [p for p in packets if p.get("key", "").startswith("forum-entry-")]
    menu = [p for p in packets if p.get("menu_id") == nav.COMPOSER][-1]
    assert [row['id'] for row in menu['items']] == ['edit_body', 'extras', 'publish', 'back']
    assert menu['items'][0]['text'] == 'Mensaje: Un borrador para revisar'
    assert not menu['items'][0].get('read_only', False)
    assert menu["selection_id"] == "edit_body"
    assert menu["title"] == "Responder en «Topic»"


def test_block_during_composing_preserves_the_draft_without_allowing_a_reply(navigation_server):
    server, user, _ = navigation_server
    author = server.db.create_user("Other Author", "hash", locale='es')
    server.db.approve_user(author.username)
    manager = server.forum_manager
    topic, _ = manager.service.create_topic(author.uuid, "general", "Topic", "First message")
    server._nav_push(user, manager.views.thread, topic)
    manager.handle_menu(user, "reply", server._user_states[user.username])
    state = server._user_states[user.username]
    state["forum_draft"] = asdict(Draft("reply", topic_id=topic, body="A draft worth keeping"))
    server.db.block_user(user.uuid, author.uuid)
    manager.handle_menu(user, "publish", state)
    assert server._user_states[user.username]["menu"] == nav.COMPOSER
    assert server._user_states[user.username]["forum_draft"]["body"] == "A draft worth keeping"
    assert server.db._conn.execute("SELECT COUNT(*) FROM forum_posts").fetchone()[0] == 1


async def test_optional_poll_editor_returns_to_preview_and_preserves_focus_and_draft(navigation_server):
    server, user, connection = navigation_server
    manager = server.forum_manager
    await server._handle_main_menu_selection(user, 'forum')
    for selection in ('category:ideas', 'new_topic', 'extras', 'poll', 'question'):
        manager.handle_menu(user, selection, server._user_states[user.username])
    await server._handle_editbox(connection, {'type': 'editbox', 'input_id': nav.POLL_QUESTION_INPUT, 'text': '¿Qué jugamos?'})
    manager.handle_menu(user, 'options', server._user_states[user.username])
    await server._handle_editbox(connection, {'type': 'editbox', 'input_id': nav.POLL_OPTIONS_INPUT, 'text': 'Ajedrez\nPig\nUno'})
    manager.handle_menu(user, 'multiple', server._user_states[user.username])
    manager.handle_menu(user, 'back', server._user_states[user.username])
    assert server._user_states[user.username]['menu'] == nav.EXTRAS
    manager.handle_menu(user, 'back', server._user_states[user.username])
    state = server._user_states[user.username]
    assert state['menu'] == nav.COMPOSER
    assert state['forum_draft']['poll']['question'] == '¿Qué jugamos?'
    assert state['forum_draft']['poll']['multiple']
    manager.handle_menu(user, 'edit_body', state)
    await server._handle_editbox(connection, {'type': 'editbox', 'input_id': nav.BODY_INPUT, 'text': 'Elijamos juntos.'})
    menu = [packet for packet in user.get_queued_messages() if packet.get('menu_id') == nav.COMPOSER and 'items' in packet][-1]
    assert [row['id'] for row in menu['items']][:2] == ['edit_title', 'edit_body']
    assert menu['selection_id'] == 'edit_body'
    assert '¿Qué jugamos?' in str(menu)
    assert not server.db._conn.execute('SELECT 1 FROM forum_polls').fetchone()


@pytest.mark.parametrize('kind', ['topic', 'reply', 'edit', 'private'])
async def test_compact_fields_keep_full_multiline_text_and_draft_when_cancelled(navigation_server, kind):
    server, user, connection = navigation_server
    manager = server.forum_manager
    topic, post = manager.service.create_topic(user.uuid, 'general', 'Existing topic', 'Existing message')
    body = 'Primera línea\n' + 'x' * (8000 - len('Primera línea\n'))
    draft = Draft(kind, category_id='general', topic_id=topic, post_id=post, title='A title', body=body)
    server._nav_push(user, manager.composer.show, draft)
    packets = user.get_queued_messages()
    menu = next(packet for packet in packets if packet.get('menu_id') == nav.COMPOSER)
    ids = [row['id'] for row in menu['items']]
    assert not any(item_id.startswith('preview:') for item_id in ids)
    assert ids.count('edit_body') == 1
    assert ('edit_title' in ids) is (kind in {'topic', 'private'})
    message = next(row for row in menu['items'] if row['id'] == 'edit_body')
    assert message['text'].startswith('Mensaje: Primera línea ')
    assert message['text'].endswith('…') and len(message['text']) <= 169
    assert not message.get('read_only', False)
    assert ids[-1] == 'back' and ids[-2] == 'publish'
    manager.handle_menu(user, 'edit_body', server._user_states[user.username])
    prompt = next(packet for packet in user.get_queued_messages() if packet['type'] == 'request_input')
    assert prompt['default_value'] == body and prompt['multiline'] and prompt['max_length'] == 8000
    await server._handle_editbox(connection, {'type': 'editbox', 'input_id': nav.BODY_INPUT, 'cancelled': True})
    assert server._user_states[user.username]['forum_draft']['body'] == body
    assert manager.service.post(user.uuid, post).body == 'Existing message'


@pytest.mark.parametrize('client_type', ['python', 'web', 'mobile'])
async def test_private_invitation_and_poll_over_real_clients(tmp_path, client_type):
    server = Server(host='127.0.0.1', port=0, db_path=str(tmp_path / 'private-network.db'))
    await server.start()
    try:
        auth = AuthManager(server.db)
        for name in ('Alice', 'Bob'):
            assert auth.register(name, 'ForumPassword123', locale='es', email=f'{name}@example.com') == 'ok'
            server.db.approve_user(name)
        port = server._ws_server._server.sockets[0].getsockname()[1]
        async with connect(f'ws://127.0.0.1:{port}') as alice, connect(f'ws://127.0.0.1:{port}') as bob:
            for ws, name in ((alice, 'Alice'), (bob, 'Bob')):
                await ws.send(json.dumps({'type': 'authorize', 'client': client_type, 'version': VERSION,
                                          'username': name, 'password': 'ForumPassword123'}))
                await receive(ws, lambda packet: packet.get('menu_id') == 'main_menu')
                await choose(ws, 'main_menu', 'forum', nav.HOME)
            await choose(alice, nav.HOME, 'private', nav.TOPICS)
            await choose(alice, nav.TOPICS, 'new_private', nav.COMPOSER)
            await choose(alice, nav.COMPOSER, 'recipients')
            await receive(alice, lambda packet: packet.get('input_id') == nav.RECIPIENTS_INPUT)
            await alice.send(json.dumps({'type': 'editbox', 'input_id': nav.RECIPIENTS_INPUT, 'text': 'Bob'}))
            await receive(alice, lambda packet: packet.get('menu_id') == nav.COMPOSER)
            await fill(alice, nav.TITLE_INPUT, 'Nuestra partida')
            await fill(alice, nav.BODY_INPUT, 'Elijamos un juego en privado.')
            await choose(alice, nav.COMPOSER, 'extras', nav.EXTRAS)
            await choose(alice, nav.EXTRAS, 'poll', nav.POLL_EDITOR)
            for selection, input_id, text in (('question', nav.POLL_QUESTION_INPUT, '¿Qué juego?'),
                                               ('options', nav.POLL_OPTIONS_INPUT, 'Ajedrez\nPig')):
                await choose(alice, nav.POLL_EDITOR, selection)
                await receive(alice, lambda packet: packet.get('input_id') == input_id)
                await alice.send(json.dumps({'type': 'editbox', 'input_id': input_id, 'text': text}))
                await receive(alice, lambda packet: packet.get('menu_id') == nav.POLL_EDITOR)
            await choose(alice, nav.POLL_EDITOR, 'back', nav.EXTRAS)
            await choose(alice, nav.EXTRAS, 'back', nav.COMPOSER)
            assert not server.db._conn.execute('SELECT 1 FROM forum_private_invites').fetchone()
            published = await choose(alice, nav.COMPOSER, 'publish', nav.POST)
            assert published['items'][0]['text'] == 'Elijamos un juego en privado.'
            await choose(bob, nav.HOME, 'recent', nav.TOPICS)
            assert server.forum_manager.service.topics(server.db.get_user('Bob').uuid).total == 0
            await choose(bob, nav.TOPICS, 'back', nav.HOME)
            await choose(bob, nav.HOME, 'private', nav.TOPICS)
            invitations = await choose(bob, nav.TOPICS, 'invitations', nav.INVITATIONS)
            invitation = invitations['items'][0]['id']
            assert invitation.startswith('invitation:')
            await choose(bob, nav.INVITATIONS, invitation, nav.INVITATION)
            thread = await choose(bob, nav.INVITATION, 'accept', nav.THREAD)
            assert thread['items'][0]['id'].startswith('post:')
            post_id = thread['items'][0]['id']
            await choose(bob, nav.THREAD, 'bookmark', nav.THREAD)
            await choose(bob, nav.THREAD, 'back', nav.INVITATIONS)
            await choose(bob, nav.INVITATIONS, 'back', nav.TOPICS)
            await choose(bob, nav.TOPICS, 'back', nav.HOME)
            saved = await choose(bob, nav.HOME, 'saved', nav.TOPICS)
            assert 'Nuestra partida' in saved['items'][0]['text']
            assert 'Conversaciones privadas' in saved['items'][0]['text']
            thread = await choose(bob, nav.TOPICS, saved['items'][0]['id'], nav.THREAD)
            await choose(bob, nav.THREAD, post_id, nav.POST)
            poll = await choose(bob, nav.POST, 'poll', nav.POLL)
            choice = poll['items'][0]['id']
            selected = await choose(bob, nav.POLL, choice, nav.POLL)
            assert 'seleccionada' in selected['items'][0]['text']
            bob_uuid = server.db.get_user('Bob').uuid
            post_number = int(post_id.removeprefix('post:'))
            assert not server.forum_manager.service.polls.get(bob_uuid, post_number)['selected']
            await choose(bob, nav.POLL, 'submit', nav.POLL)
            assert server.forum_manager.service.polls.get(bob_uuid, post_number)['voters'] == 1
            assert not any('forum-' in str(row.get('text', '')) for row in poll['items'])
    finally:
        await server.stop()
