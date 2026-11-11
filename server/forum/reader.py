"""Full-message read-only text with compact actions and stable return focus."""

from . import navigation as nav
from .models import MAX_BODY_LENGTH
from .views import author, label


class MessageReader:
    def __init__(self, manager):
        self.manager = manager
        self.server, self.service, self.views = manager.server, manager.service, manager.views

    def open(self, user, post_id: int) -> None:
        self.views.post(user, post_id)
        self.show(user, post_id)

    def show(self, user, post_id: int) -> None:
        # Recheck visibility, bilateral blocks, membership and current hidden
        # state every time. Navigation stores ids, never a cached message body.
        post = self.service.post(user.uuid, post_id, mark_read=True)
        if post.hidden:
            self.server._nav_refresh(user, self.views.post, post_id)
            return
        state = self.server._user_states[user.username]
        state['_restore_focus_id'] = 'read_body'
        self.server.enter_input_state(user, nav.BODY_READER, forum_post=post.id)
        user.show_editbox(nav.BODY_READER, label(user, 'forum-body-reader', author=author(user, post)),
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
