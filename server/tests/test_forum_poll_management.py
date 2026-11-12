"""Poll deletion authority, confirmation identity and accessible post discovery."""

import asyncio
import json

import pytest
from websockets.asyncio.client import connect

from ..auth.auth import AuthManager
from ..core.server import Server, VERSION
from ..forum import navigation as nav
from ..forum.models import Draft, ForumError
from ..forum.polls import PollConfig
from .test_forum_thread_polls import forum, menu


def make_polls(service, users, *, closes_at=None):
    alice = users['Alice'].uuid
    topic, post = service.create_topic(alice, 'general', 'Topic', 'Original body',
                                      poll=PollConfig('Message question', ('A', 'B'), results='always', closes_at=closes_at))
    service.thread_polls.create(alice, topic, PollConfig('General question', ('Yes', 'No'), results='always', closes_at=closes_at))
    return topic, post


def target(service, topic, post, scope):
    return (service.thread_polls, topic) if scope == 'thread' else (service.polls, post)


def option_ids(polls, viewer, key):
    return tuple(option['id'] for option in polls.get(viewer, key)['options'])


@pytest.mark.parametrize('scope', ['post', 'thread'])
@pytest.mark.parametrize('state', ['open', 'voted', 'closed', 'expired', 'thread_closed'])
@pytest.mark.parametrize('actor', ['Alice', 'Staff'])
def test_author_or_moderator_can_delete_poll_without_deleting_content(forum, scope, state, actor):
    server, service, users, now = forum
    topic, post = make_polls(service, users, closes_at=now[0] + 1 if state == 'expired' else None)
    polls, key = target(service, topic, post, scope)
    alice, bob = users['Alice'].uuid, users['Bob'].uuid
    options = option_ids(polls, alice, key)
    if state != 'open':
        polls.vote(bob, key, options[:1])
    if state == 'closed':
        polls.close(alice, key)
    elif state == 'expired':
        now[0] += 2
        assert polls.get(alice, key)['closed']
    elif state == 'thread_closed':
        service.moderate(users['Staff'].uuid, topic, 'closed', True)
    assert polls.can_delete(users[actor].uuid, key)
    polls.delete(users[actor].uuid, key, expected_options=options)
    assert not polls.exists(key)
    assert not server.db._conn.execute(f'SELECT 1 FROM {polls.options_table} WHERE {polls.key} = ?', (key,)).fetchone()
    assert not server.db._conn.execute(f'SELECT 1 FROM {polls.votes_table} WHERE {polls.key} = ?', (key,)).fetchone()
    assert service.post(alice, post).body == 'Original body'
    assert service.topic(alice, topic).post_count == 1
    other, other_key = target(service, topic, post, 'post' if scope == 'thread' else 'thread')
    assert other.exists(other_key)
    assert not server.db._conn.execute('PRAGMA foreign_key_check').fetchall()


@pytest.mark.parametrize('scope', ['post', 'thread'])
def test_unrelated_member_cannot_delete_or_open_confirmation(forum, scope):
    server, service, users, _ = forum
    topic, post = make_polls(service, users)
    polls, key = target(service, topic, post, scope)
    bob = users['Bob']
    assert not polls.can_delete(bob.uuid, key)
    with pytest.raises(ForumError, match='forum-error-poll-delete-permission'):
        polls.delete(bob.uuid, key, expected_options=option_ids(polls, bob.uuid, key))
    with pytest.raises(ForumError, match='forum-error-poll-delete-permission'):
        server.forum_manager.polls.confirm_delete(bob, key, scope=scope)
    server.forum_manager.polls.ballot(bob, key, scope=scope)
    assert 'delete' not in [row['id'] for row in menu(bob, nav.POLL)['items']]
    assert polls.exists(key)


@pytest.mark.parametrize('scope', ['post', 'thread'])
def test_private_membership_and_current_owner_override_global_admin_role(forum, scope):
    _, service, users, _ = forum
    alice, bob, staff = (users[name].uuid for name in ('Alice', 'Bob', 'Staff'))
    topic, _ = service.conversations.create(alice, 'Private', 'Invitation', (bob, staff))
    for member in (bob, staff):
        invitation = service.conversations.invitations(member)[0]['id']
        service.conversations.respond(member, invitation, accept=True)
    post = service.reply(bob, topic, 'Private poll body', poll=PollConfig('Private message poll', ('A', 'B')))
    service.thread_polls.create(alice, topic, PollConfig('Private general poll', ('Yes', 'No')))
    polls, key = target(service, topic, post, scope)
    assert not polls.can_delete(staff, key)
    with pytest.raises(ForumError, match='forum-error-poll-delete-permission'):
        polls.delete(staff, key, expected_options=option_ids(polls, staff, key))
    assert polls.can_delete(alice, key)
    polls.delete(alice, key, expected_options=option_ids(polls, alice, key))
    assert service.post(bob, post).body == 'Private poll body'


def test_confirmation_cannot_delete_a_replacement_poll_created_in_the_same_second(forum):
    _, service, users, _ = forum
    topic, post = make_polls(service, users)
    polls, key = target(service, topic, post, 'thread')
    alice = users['Alice'].uuid
    old = polls.get(alice, key)
    options = option_ids(polls, alice, key)
    polls.delete(alice, key, expected_options=options)
    polls.create(alice, key, PollConfig(old['question'], tuple(option['label'] for option in old['options'])))
    assert polls.get(alice, key)['created_at'] == old['created_at']
    with pytest.raises(ForumError, match='forum-error-poll-changed'):
        polls.delete(alice, key, expected_options=options)
    assert polls.exists(key)


def test_editing_a_poll_invalidates_the_old_delete_confirmation(forum):
    _, service, users, _ = forum
    topic, post = make_polls(service, users)
    polls, key = target(service, topic, post, 'thread')
    alice = users['Alice'].uuid
    options = option_ids(polls, alice, key)
    polls.edit(alice, key, PollConfig('Changed question', ('Other A', 'Other B')), revision=0)
    with pytest.raises(ForumError, match='forum-error-poll-changed'):
        polls.delete(alice, key, expected_options=options)
    assert polls.get(alice, key)['question'] == 'Changed question'


def open_ballot(server, user, topic, post, scope):
    manager = server.forum_manager
    server._nav_push(user, manager.views.thread, topic)
    if scope == 'post':
        server._nav_push(user, manager.views.post, post)
    server._nav_push(user, manager.polls.ballot, topic if scope == 'thread' else post, scope=scope)
    user.get_queued_messages()


@pytest.mark.parametrize('scope', ['post', 'thread'])
@pytest.mark.parametrize('cancel', ['no', 'back'])
def test_confirmation_cancel_keeps_votes_and_returns_to_ballot(forum, scope, cancel):
    server, service, users, _ = forum
    topic, post = make_polls(service, users)
    alice = users['Alice']
    polls, key = target(service, topic, post, scope)
    polls.vote(users['Bob'].uuid, key, option_ids(polls, alice.uuid, key)[:1])
    open_ballot(server, alice, topic, post, scope)
    manager = server.forum_manager
    manager.handle_menu(alice, 'delete', server._user_states[alice.username])
    confirmation = menu(alice, nav.POLL_DELETE)
    assert confirmation['items'][-1]['id'] == 'no'
    assert 'votos' in confirmation['items'][0]['text']
    manager.handle_menu(alice, cancel, server._user_states[alice.username])
    assert server._user_states[alice.username]['menu'] == nav.POLL
    assert polls.get(alice.uuid, key)['voters'] == 1


@pytest.mark.parametrize('scope', ['post', 'thread'])
def test_confirmed_deletion_restores_parent_without_deleted_ballot_frames(forum, scope):
    server, service, users, _ = forum
    topic, post = make_polls(service, users)
    alice = users['Alice']
    manager = server.forum_manager
    # A pre-existing draft must survive the poll flow.
    server._nav_push(alice, manager.composer.show, Draft('topic', category_id='general', body='Keep this draft'))
    open_ballot(server, alice, topic, post, scope)
    manager.handle_menu(alice, 'delete', server._user_states[alice.username])
    manager.handle_menu(alice, 'yes', server._user_states[alice.username])
    state = server._user_states[alice.username]
    assert state['menu'] == (nav.THREAD if scope == 'thread' else nav.POST)
    assert not any(frame['menu'] in {nav.POLL, nav.POLL_DELETE} for frame in state['_stack'])
    assert any(frame.get('forum_draft', {}).get('body') == 'Keep this draft' for frame in state['_stack'])
    packet = menu(alice, state['menu'])
    assert ('thread_poll' if scope == 'thread' else 'poll') not in [row['id'] for row in packet['items']]
    if scope == 'thread':
        assert service.thread_polls.can_create(alice.uuid, topic)
    else:
        assert not service.post(alice.uuid, post).has_poll
    manager.handle_menu(alice, 'yes', state)  # queued duplicate confirmation is inert
    assert service.post(alice.uuid, post).body == 'Original body'


@pytest.mark.parametrize('revocation', ['staff', 'block', 'hidden', 'disabled', 'membership', 'approval', 'muted'])
def test_delete_rechecks_access_and_availability_when_confirmation_is_accepted(forum, revocation):
    server, service, users, _ = forum
    alice, staff = users['Alice'], users['Staff']
    topic, post = make_polls(service, users)
    actor = staff
    if revocation == 'membership':
        topic, post = service.conversations.create(alice.uuid, 'Private', 'Private body', (staff.uuid,),
                                                   poll=PollConfig('Private', ('A', 'B')))
        service.conversations.respond(staff.uuid, service.conversations.invitations(staff.uuid)[0]['id'], accept=True)
        actor = alice
    open_ballot(server, actor, topic, post, 'post')
    manager = server.forum_manager
    manager.handle_menu(actor, 'delete', server._user_states[actor.username])
    if revocation == 'staff':
        server.db.create_user('OtherDeveloper', 'hash', trust_level=3, approved=True)
        server.db.update_user_trust_level(staff.username, 1)
    elif revocation == 'block':
        server.db.block_user(staff.uuid, alice.uuid)
    elif revocation == 'hidden':
        service.moderate(staff.uuid, topic, 'hidden', True, post)
    elif revocation == 'disabled':
        server.set_forum_enabled(False)
    elif revocation == 'approval':
        server.db._conn.execute('UPDATE users SET approved = 0 WHERE uuid = ?', (staff.uuid,))
    elif revocation == 'muted':
        server.db.mute_user(staff.username, alice.username, 'Test mute', None)
    else:
        service.conversations.leave(alice.uuid, topic)
    manager.handle_menu(actor, 'yes', server._user_states[actor.username])
    assert service.polls.exists(post)


def test_message_poll_is_announced_in_row_speech_and_reader_but_never_on_hidden_posts(forum):
    server, service, users, _ = forum
    topic, post = make_polls(service, users)
    body = 'Original body\n' + 'x' * 63986
    service.edit(users['Alice'].uuid, post, body, revision=0)
    bob = users['Bob']
    manager = server.forum_manager
    assert service.post(bob.uuid, post).has_poll
    assert service.posts(bob.uuid, topic).items[0].has_poll
    manager.views.thread(bob, topic)
    row = next(row for row in menu(bob, nav.THREAD)['items'] if row['id'] == f'post:{post}')
    assert row['text'].startswith('Contiene una encuesta.')
    assert len(row['text']) < 240
    manager.reader.speak(bob, post)
    spoken = bob.get_queued_messages()[-1]
    assert spoken['text'] == 'Contiene una encuesta.\n' + body and spoken['history'] is False
    manager.reader.show(bob, post)
    packet = next(p for p in bob.get_queued_messages() if p.get('type') == 'request_input')
    assert packet['prompt'].startswith('Contiene una encuesta.') and packet['default_value'] == body
    manager.reader.close(bob, server._user_states[bob.username])
    service.moderate(users['Staff'].uuid, topic, 'hidden', True, post)
    assert not service.post(bob.uuid, post).has_poll
    manager.views.thread(bob, topic)
    row = next(row for row in menu(bob, nav.THREAD)['items'] if row['id'] == f'post:{post}')
    assert 'encuesta' not in row['text'] and 'Original body' not in row['text']


@pytest.mark.parametrize('scope', ['post', 'thread'])
@pytest.mark.parametrize('client_type', ['python', 'web'])
async def test_delete_closed_poll_and_explicit_thread_reply_over_real_websocket(tmp_path, scope, client_type):
    server = Server(host='127.0.0.1', port=0, db_path=str(tmp_path / 'poll-management.db'))
    await server.start()
    try:
        auth = AuthManager(server.db)
        assert auth.register('Alice', 'ForumPassword123', locale='es', email='alice@example.test') == 'ok'
        server.db.approve_user('Alice')
        service = server.forum_manager.service
        alice = server.db.get_user('Alice').uuid
        topic, post = service.create_topic(alice, 'general', 'Thread', 'Body', poll=PollConfig('Message', ('A', 'B')))
        service.thread_polls.create(alice, topic, PollConfig('General', ('Yes', 'No')))
        polls, key = target(service, topic, post, scope)
        polls.close(alice, key)
        port = server._ws_server._server.sockets[0].getsockname()[1]
        async def receive(ws, predicate):
            async with asyncio.timeout(15):
                while True:
                    packet = json.loads(await ws.recv())
                    if predicate(packet):
                        return packet
        async def choose(ws, surface, action, destination):
            await ws.send(json.dumps({'type':'menu', 'menu_id':surface, 'selection_id':action}))
            return await receive(ws, lambda p:p.get('menu_id') == destination)
        async with connect(f'ws://127.0.0.1:{port}') as ws:
            await ws.send(json.dumps({'type':'authorize', 'client':client_type, 'version':VERSION,
                                      'username':'Alice', 'password':'ForumPassword123'}))
            await receive(ws, lambda p:p.get('menu_id') == 'main_menu')
            await choose(ws, 'main_menu', 'forum', nav.HOME)
            await choose(ws, nav.HOME, 'category:general', nav.TOPICS)
            thread = await choose(ws, nav.TOPICS, f'topic:{topic}', nav.THREAD)
            assert next(row for row in thread['items'] if row['id'] == f'post:{post}')['text'].startswith('Contiene una encuesta.')
            if scope == 'post':
                await ws.send(json.dumps({'type':'keybind', 'menu_id':nav.THREAD,
                                          'menu_item_id':f'post:{post}', 'key':'applications'}))
                context = await receive(ws, lambda p:p.get('menu_id') == nav.POST)
                assert next(row for row in context['items'] if row['id'] == 'reply')['text'] == 'Responder al hilo'
            ballot = await choose(ws, nav.THREAD if scope == 'thread' else nav.POST,
                                  'thread_poll' if scope == 'thread' else 'poll', nav.POLL)
            assert 'delete' in [row['id'] for row in ballot['items']] and 'close' not in [row['id'] for row in ballot['items']]
            await choose(ws, nav.POLL, 'delete', nav.POLL_DELETE)
            parent = await choose(ws, nav.POLL_DELETE, 'yes', nav.THREAD if scope == 'thread' else nav.POST)
            assert not polls.exists(key)
            assert ('thread_poll' if scope == 'thread' else 'poll') not in [row['id'] for row in parent['items']]
    finally:
        await server.stop()
