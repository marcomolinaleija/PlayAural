"""In-place speech, optional read-only text and contextual post actions."""

from . import navigation as nav
from .models import MAX_BODY_LENGTH
from .views import author, label, post_notice


class MessageReader:
    def __init__(self, manager):
        self.manager = manager
        self.server, self.service, self.views = manager.server, manager.service, manager.views

    def open(self, user, post_id: int) -> None:
        """Locate a notification/continuation target in its real message list."""
        self.locate(user, post_id)
        self.speak(user, post_id)

    def locate(self, user, post_id: int) -> None:
        post = self.service.post(user.uuid, post_id)
        page = self.service.repository.post_page(user.uuid, post.topic_id, post.id)
        self.views.thread(user, post.topic_id, page)
        state = self.server._user_states[user.username]
        state['_restore_focus_id'] = f'post:{post.id}'
        self.server._restore_menu_focus(user, state)

    def speak(self, user, post_id: int) -> None:
        post = self.service.post(user.uuid, post_id)
        if post.hidden:
            user.speak_l('forum-hidden-post', buffer='misc', history=False)
        else:
            self.service.post(user.uuid, post_id, mark_read=True)
            # Keep the complete body, including line breaks and all 64,000
            # characters. Speech does not replace the visible list or focus.
            # Fluent bounds individual interpolated values. Localize only the
            # notice, keeping the full 64,000-character body outside formatting.
            notice = post_notice(user, post)
            text = notice + '\n' + post.body if notice else post.body
            user.speak(text, buffer='misc', history=False, interrupt=True)

    def activate(self, user, post_id: int) -> None:
        """Enter opens the only resource, or a compact chooser for several."""
        post = self.service.post(user.uuid, post_id)
        if post.hidden:
            self.speak(user, post_id)
            return
        attachments = self.service.attachments.for_post(user.uuid, post_id) if post.attachment_count else []
        count = len(attachments) + int(post.has_poll)
        if count > 1:
            self.server._nav_push(user, self.views.contents, post_id)
        elif post.has_poll:
            self.server._nav_push(user, self.manager.polls.ballot, post_id)
        elif attachments:
            self.manager.media_ui.open(user, attachments[0]['id'])
        else:
            self.speak(user, post_id)

    def handle_keybind(self, user, packet, state):
        if state.get('menu') != nav.THREAD or packet.get('control') or packet.get('alt') or packet.get('meta'):
            return
        key, shift = packet.get('key'), bool(packet.get('shift'))
        if not isinstance(key, str):
            return
        command = ('context' if key == 'applications' and not shift or key == 'f10' and shift
                   else 'text' if key == 'enter' and shift
                   else 'activate' if key == 'enter' and not shift
                   else 'speak' if key == 'right' and not shift else None)
        if command is None:
            return
        if packet.get('menu_id') != nav.THREAD or user._last_menu_packet_id != nav.THREAD:
            return
        item_id = packet.get('menu_item_id')
        if not isinstance(item_id, str) or not item_id.startswith('post:'):
            return
        position = self.server._menu_item_position(user, nav.THREAD, item_id)
        if position is None or (packet.get('menu_index') is not None
                                and (type(packet['menu_index']) is not int or packet['menu_index'] != position)):
            return
        post_id = int(item_id.removeprefix('post:'))
        post = self.service.post(user.uuid, post_id)
        if post.topic_id != state['forum_topic']:
            return
        self.server._remember_current_menu_focus(user, nav.THREAD,
                                                 {'selection_id': item_id, 'selection': position})
        if command == 'context':
            self.server._nav_push(user, self.views.post, post_id)
        elif command == 'text':
            self.show(user, post_id)
        elif command == 'activate':
            self.activate(user, post_id)
        else:
            self.speak(user, post_id)

    def show(self, user, post_id: int) -> None:
        # Recheck visibility, bilateral blocks, membership and current hidden
        # state every time. Navigation stores ids, never a cached message body.
        post = self.service.post(user.uuid, post_id)
        if post.hidden:
            user.speak_l('forum-hidden-post', buffer='misc', history=False)
            return
        self.service.post(user.uuid, post_id, mark_read=True)
        state = self.server._user_states[user.username]
        if state.get('menu') == nav.POST:
            self.server._nav_back(user)
            state = self.server._user_states[user.username]
        if state.get('menu') != nav.THREAD or state.get('forum_topic') != post.topic_id:
            self.server._nav_refresh(user, self.locate, post_id)
            state = self.server._user_states[user.username]
        state['_restore_focus_id'] = f'post:{post.id}'
        self.server.enter_input_state(user, nav.BODY_READER, forum_post=post.id)
        prompt = label(user, 'forum-body-reader', author=author(user, post))
        notice = post_notice(user, post)
        if notice:
            prompt = notice + ' ' + prompt
        user.show_editbox(nav.BODY_READER, prompt,
                          post.body, multiline=True, read_only=True, max_length=MAX_BODY_LENGTH)

    def close(self, user, state: dict) -> None:
        # Enter and Escape both close; even a forged edited payload is inert.
        user.remove_editbox(nav.BODY_READER)
        if not self.server.forum_enabled:
            # Leave unavailable reading surfaces, retaining any local composer
            # and non-forum return context already present in navigation.
            state['_stack'] = [frame for frame in state.get('_stack', [])
                               if frame.get('menu') not in nav.MENU_IDS or frame.get('menu') == nav.COMPOSER]
            self.server._nav_back(user)
            user.speak_l('forum-unavailable', buffer='system')
            return
        self.server._restore_input_parent(user, state)
