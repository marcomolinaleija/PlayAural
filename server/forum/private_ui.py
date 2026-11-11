"""Private conversations reuse the existing reader and composer on every client."""

from dataclasses import asdict, replace

from ..ui.confirmation import show_confirmation_menu
from ..users.base import MenuItem
from . import navigation as nav
from .conversations import MAX_MEMBERS
from .draft_state import update_draft
from .models import Draft, ForumError
from .views import item, label


class PrivateController:
    def __init__(self, manager):
        self.server, self.service, self.views = manager.server, manager.service, manager.views
        self.conversations = self.service.conversations

    def invitations(self, user) -> None:
        invitations = self.conversations.invitations(user.uuid)
        rows = [item(user, 'forum-private-invitation-row', f"invitation:{invitation['id']}",
                     title=invitation['title'], name=invitation['inviter_name']) for invitation in invitations]
        rows.append(item(user, 'menu-page-refresh', 'refresh'))
        self.views.render(user, nav.INVITATIONS, rows, title=label(user, 'forum-private-invitations'),
                          announcement=('forum-entry-invitations', {'count': len(invitations)}))

    def invitation(self, user, invite_id: str) -> None:
        invitation = next((entry for entry in self.conversations.invitations(user.uuid) if entry['id'] == invite_id), None)
        if invitation is None:
            raise ForumError('forum-error-missing')
        rows = [item(user, 'forum-private-accept', 'accept'), item(user, 'forum-private-decline', 'decline')]
        self.views.render(user, nav.INVITATION, rows, title=invitation['title'],
                          announcement=('forum-entry-invitation', {'title': invitation['title'], 'name': invitation['inviter_name']}),
                          forum_invitation=invite_id)

    def members(self, user, topic_id: int) -> None:
        members = self.conversations.members(user.uuid, topic_id)
        owner = self.conversations.owner(user.uuid, topic_id)
        rows = [MenuItem(text=label(user, 'forum-private-owner-row', name=member['username']) if member['is_owner']
                         else label(user, 'forum-private-remove-member', name=member['username']) if owner else member['username'],
                         id=f"member:{member['user_uuid']}", read_only=not owner or member['user_uuid'] == user.uuid) for member in members]
        if owner:
            rows.append(item(user, 'forum-private-invite', 'invite'))
        rows.append(item(user, 'forum-private-leave', 'leave'))
        self.views.render(user, nav.MEMBERS, rows, title=label(user, 'forum-private-members'),
                          announcement=('forum-entry-members', {'count': len(members)}), forum_topic=topic_id)

    def confirm_leave(self, user, topic_id: int) -> None:
        topic = self.service.topic(user.uuid, topic_id)
        self.conversations.members(user.uuid, topic_id)
        show_confirmation_menu(user, nav.LEAVE, prompt_key='forum-private-leave-prompt',
                               prompt_kwargs={'title': topic.title}, buffer='system')
        self.server._user_states[user.username] = {'menu': nav.LEAVE, 'forum_topic': topic_id}

    def confirm_remove(self, user, topic_id: int, participant: str) -> None:
        if not self.conversations.owner(user.uuid, topic_id):
            raise ForumError('forum-error-private-owner')
        member = next((member for member in self.conversations.members(user.uuid, topic_id)
                       if member['user_uuid'] == participant and participant != user.uuid), None)
        if member is None:
            raise ForumError('forum-error-missing')
        show_confirmation_menu(user, nav.REMOVE_MEMBER, prompt_key='forum-private-remove-prompt',
                               prompt_kwargs={'name': member['username']}, buffer='system')
        self.server._user_states[user.username] = {'menu': nav.REMOVE_MEMBER, 'forum_topic': topic_id, 'forum_participant': participant}

    def restore(self, user, state: dict) -> bool:
        if state['menu'] == nav.INVITATIONS:
            self.invitations(user)
        elif state['menu'] == nav.INVITATION:
            self.invitation(user, state['forum_invitation'])
        elif state['menu'] == nav.MEMBERS:
            self.members(user, state['forum_topic'])
        else:
            return False
        return True

    def handle(self, user, selection: str, state: dict) -> bool:
        menu = state['menu']
        push, refresh = self.server._nav_push, self.server._nav_refresh
        if menu == nav.INVITATIONS:
            if selection.startswith('invitation:'):
                push(user, self.invitation, selection.removeprefix('invitation:'))
            elif selection == 'refresh':
                refresh(user, self.invitations)
        elif menu == nav.INVITATION:
            if selection in {'accept', 'decline'}:
                topic_id = self.conversations.respond(user.uuid, state['forum_invitation'], accept=selection == 'accept')
                self.server._nav_back(user)
                if selection == 'accept':
                    push(user, self.views.thread, topic_id)
        elif menu == nav.MEMBERS:
            if selection == 'invite':
                self.server.enter_input_state(user, nav.INVITE_INPUT)
                self.show_input(user, nav.INVITE_INPUT, '')
            elif selection == 'leave':
                push(user, self.confirm_leave, state['forum_topic'])
            elif selection.startswith('member:'):
                push(user, self.confirm_remove, state['forum_topic'], selection.removeprefix('member:'))
        elif menu == nav.REMOVE_MEMBER:
            if selection == 'yes':
                self.conversations.remove(user.uuid, state['forum_topic'], state['forum_participant'])
                self.server._nav_back(user)
                user.speak_l('forum-private-member-removed', buffer='system')
            elif selection == 'no':
                self.server._nav_back(user)
        elif menu == nav.LEAVE:
            if selection == 'yes':
                self.conversations.leave(user.uuid, state['forum_topic'])
                # Remove all frames pointing at the conversation whose access
                # was revoked, preserving the route to the rest of the app.
                state['_stack'] = [frame for frame in state.get('_stack', [])
                                   if frame.get('forum_topic') != state['forum_topic']]
                refresh(user, self.views.topics, 'private')
                user.speak_l('forum-private-left', buffer='system')
            elif selection == 'no':
                self.server._nav_back(user)
        else:
            return False
        return True

    def edit_recipients(self, user, draft: Draft) -> None:
        names = []
        for user_uuid in draft.recipients:
            account = self.service.repository.database.get_user_by_uuid(user_uuid)
            if account:
                names.append(account.username)
        self.server.enter_input_state(user, nav.RECIPIENTS_INPUT)
        self.show_input(user, nav.RECIPIENTS_INPUT, '\n'.join(names))

    @staticmethod
    def show_input(user, input_id: str, value: str) -> None:
        many = input_id == nav.RECIPIENTS_INPUT
        user.show_editbox(input_id, label(user, 'forum-private-recipients-prompt' if many else 'forum-private-invite-prompt'),
                          value, multiline=many, max_length=1000 if many else 100)

    def handle_input(self, user, packet: dict, state: dict) -> None:
        input_id = state['menu']
        if packet.get('cancelled'):
            user.remove_editbox(input_id)
            self.server._restore_input_parent(user, state)
            return
        text = packet.get('text')
        try:
            many = input_id == nav.RECIPIENTS_INPUT
            if not isinstance(text, str) or len(text) > (1000 if many else 100):
                raise ForumError('forum-error-private-recipients', limit=MAX_MEMBERS - 1)
            names = [name.strip() for name in text.splitlines() if name.strip()]
            if not 1 <= len(names) <= (MAX_MEMBERS - 1 if many else 1):
                raise ForumError('forum-error-private-recipients', limit=MAX_MEMBERS - 1)
            recipients = []
            for name in names:
                account = self.service.repository.database.get_user(name)
                if not account:
                    raise ForumError('forum-error-private-user', name=name)
                self.service.account(account.uuid)
                recipients.append(account.uuid)
            if user.uuid in recipients or len(set(recipients)) != len(recipients):
                raise ForumError('forum-error-private-recipients', limit=MAX_MEMBERS - 1)
            if many:
                for recipient in recipients:
                    self.conversations._admit(recipient, [user.uuid, *recipients])
                draft = replace(Draft(**state['forum_draft']), recipients=tuple(recipients))
                update_draft(state, draft)
            else:
                self.conversations.invite(user.uuid, state['forum_topic'], recipients[0])
        except ForumError as error:
            user.speak_l(error.key, buffer='system', **error.values)
            self.show_input(user, input_id, text[:1000] if isinstance(text, str) else '')
            return
        user.remove_editbox(input_id)
        self.server._restore_input_parent(user, state)
        if not many:
            user.speak_l('forum-private-invited', buffer='system')
