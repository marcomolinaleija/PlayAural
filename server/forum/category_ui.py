"""Subforum configuration through the shared menu, input and focus protocol."""

from ..ui.confirmation import show_confirmation_menu
from . import navigation as nav
from .categories import validate_category_text
from .models import ForumError, MAX_CATEGORY_NAME_LENGTH, MAX_CATEGORY_DESCRIPTION_LENGTH
from .views import category_name, item, label


class CategoryController:
    def __init__(self, manager):
        self.manager = manager
        self.server, self.service, self.views = manager.server, manager.service, manager.views
        self.admin = self.service.category_admin

    def index(self, user, language: str | None = None) -> None:
        self.admin.authorize(user.uuid)
        language = language or self.service.languages.current(user.uuid)
        rows = [item(user, 'forum-category-row', f'edit_category:{category.id}',
                     name=category_name(user, category), count=category.topic_count)
                for category in self.service.categories(user.uuid, language=language)]
        rows.append(item(user, 'forum-category-create', 'create_category'))
        self.views.render(user, nav.CATEGORIES, rows, title=label(user, 'forum-categories-manage'),
                          announcement=('forum-entry-simple', {'title': label(user, 'forum-categories-manage')}), forum_language=language)

    def editor(self, user, draft: dict) -> None:
        self.admin.authorize(user.uuid)
        draft = dict(draft)
        draft.setdefault('language', self.service.languages.current(user.uuid))
        category_id = draft.get('id', '')
        if category_id:
            draft['language'] = self.admin.get(user.uuid, category_id).language
        title = label(user, 'forum-category-edit' if category_id else 'forum-category-create')
        rows = [item(user, 'forum-category-name', 'edit_category_name', name=draft['name'] or label(user, 'forum-not-written')),
                item(user, 'forum-category-description', 'edit_category_description',
                     description=draft['description'] or label(user, 'forum-category-no-description')),
                item(user, 'forum-category-save', 'save_category')]
        if category_id:
            rows.append(item(user, 'forum-category-delete', 'delete_category'))
        self.views.render(user, nav.CATEGORY_EDITOR, rows, title=title,
                          announcement=('forum-entry-simple', {'title': title}),
                          forum_category=category_id, forum_category_draft=dict(draft))

    def destinations(self, user, category_id: str, revision: int) -> None:
        source = self.admin.get(user.uuid, category_id)
        self.admin._revision(source, revision)
        rows = [item(user, 'forum-category-move-target', f'move_category:{category.id}', name=category_name(user, category))
                for category in self.service.categories(user.uuid, language=source.language) if category.id != category_id]
        if not rows:
            raise ForumError('forum-error-category-destination')
        title = label(user, 'forum-category-destination-heading')
        self.views.render(user, nav.CATEGORY_DESTINATION, rows, title=title,
                          announcement=('forum-entry-simple', {'title': title}),
                          forum_category=category_id, forum_category_revision=revision)

    def confirm(self, user, category_id: str, revision: int, destination: str | None = None) -> None:
        category = self.admin.get(user.uuid, category_id)
        self.admin._revision(category, revision)
        target = self.admin.get(user.uuid, destination) if destination else None
        show_confirmation_menu(
            user, nav.CATEGORY_DELETE, buffer='system',
            prompt_key='forum-category-delete-move-prompt' if target else 'forum-category-delete-empty-prompt',
            prompt_kwargs={'name': category_name(user, category),
                           **({'destination': category_name(user, target)} if target else {})},
        )
        self.server._user_states[user.username] = {
            'menu': nav.CATEGORY_DELETE, 'forum_category': category_id,
            'forum_category_revision': revision, 'forum_category_destination': destination,
        }

    def restore(self, user, state: dict) -> bool:
        if state['menu'] == nav.CATEGORIES:
            self.index(user, state.get('forum_language'))
        elif state['menu'] == nav.CATEGORY_EDITOR:
            self.editor(user, state['forum_category_draft'])
        elif state['menu'] == nav.CATEGORY_DESTINATION:
            self.destinations(user, state['forum_category'], state['forum_category_revision'])
        else:
            return False
        return True

    def handle(self, user, selection: str, state: dict) -> bool:
        menu = state['menu']
        if menu == nav.HOME and selection == 'manage_categories':
            self.admin.authorize(user.uuid)
            self.server._nav_push(user, self.index, state.get('forum_language'))
            return True
        if menu not in nav.CATEGORY_MENU_IDS:
            return False
        self.admin.authorize(user.uuid)
        push = self.server._nav_push
        if menu == nav.CATEGORIES:
            if selection == 'create_category':
                push(user, self.editor, {'id': '', 'name': '', 'description': '', 'revision': 0, 'language': state.get('forum_language') or self.service.languages.current(user.uuid)})
            elif selection.startswith('edit_category:'):
                category = self.admin.get(user.uuid, selection.removeprefix('edit_category:'))
                push(user, self.editor, {'id': category.id, 'name': category_name(user, category),
                                         'description': category.description, 'revision': category.revision})
        elif menu == nav.CATEGORY_EDITOR:
            draft = state['forum_category_draft']
            if selection in {'edit_category_name', 'edit_category_description'}:
                field = 'name' if selection == 'edit_category_name' else 'description'
                input_id = nav.CATEGORY_NAME_INPUT if field == 'name' else nav.CATEGORY_DESCRIPTION_INPUT
                self.server.enter_input_state(user, input_id, forum_category_draft=dict(draft))
                self.show_input(user, input_id, draft[field])
            elif selection == 'save_category':
                if draft['id']:
                    self.admin.edit(user.uuid, draft['id'], draft['name'], draft['description'], draft['revision'])
                    category_id = draft['id']
                else:
                    category_id = self.admin.create(user.uuid, draft['name'], draft['description'], language=draft['language'])
                stack = state.get('_stack', [])
                if stack and stack[-1].get('menu') == nav.CATEGORIES:
                    stack[-1]['_restore_focus_id'] = f'edit_category:{category_id}'
                self.server._nav_back(user)
                user.speak_l('forum-category-saved', buffer='system')
                self.refresh_readers(user)
            elif selection == 'delete_category' and draft['id']:
                category = self.admin.get(user.uuid, draft['id'])
                if category.topic_count:
                    push(user, self.destinations, category.id, draft['revision'])
                else:
                    push(user, self.confirm, category.id, draft['revision'])
        elif menu == nav.CATEGORY_DESTINATION and selection.startswith('move_category:'):
            push(user, self.confirm, state['forum_category'], state['forum_category_revision'],
                 selection.removeprefix('move_category:'))
        elif menu == nav.CATEGORY_DELETE:
            if selection == 'yes':
                category_id = state['forum_category']
                self.admin.delete(user.uuid, category_id, state['forum_category_revision'],
                                  destination=state['forum_category_destination'])
                state['_stack'] = [frame for frame in state.get('_stack', [])
                                   if not (frame.get('forum_category') == category_id
                                           and frame.get('menu') in nav.CATEGORY_MENU_IDS)]
                self.server._nav_back(user)
                user.speak_l('forum-category-deleted', buffer='system')
                self.refresh_readers(user)
            elif selection == 'no':
                self.server._nav_back(user)
        return True

    @staticmethod
    def show_input(user, input_id: str, value: str) -> None:
        description = input_id == nav.CATEGORY_DESCRIPTION_INPUT
        user.show_editbox(input_id, label(user, 'forum-category-description-prompt' if description else 'forum-category-name-prompt'),
                          value, multiline=description,
                          max_length=MAX_CATEGORY_DESCRIPTION_LENGTH if description else MAX_CATEGORY_NAME_LENGTH)

    def handle_input(self, user, packet: dict, state: dict) -> None:
        input_id = state['menu']
        if packet.get('cancelled'):
            user.remove_editbox(input_id)
            self.server._restore_input_parent(user, state)
            return
        description = input_id == nav.CATEGORY_DESCRIPTION_INPUT
        value = packet.get('text')
        try:
            self.admin.authorize(user.uuid, writing=True)
            value = validate_category_text(value, description=description)
        except ForumError as error:
            user.speak_l(error.key, buffer='system', **error.values)
            limit = MAX_CATEGORY_DESCRIPTION_LENGTH if description else MAX_CATEGORY_NAME_LENGTH
            self.show_input(user, input_id, value[:limit] if isinstance(value, str) else '')
            return
        draft = dict(state['forum_category_draft'])
        draft['description' if description else 'name'] = value
        state['_parent_frame']['forum_category_draft'] = draft
        user.remove_editbox(input_id)
        self.server._restore_input_parent(user, state)

    def refresh_readers(self, actor) -> None:
        for user in list(self.server._users.values()):
            if user is actor:
                continue
            state = self.server._user_states.get(user.username, {})
            menu = state.get('menu')
            try:
                if menu == nav.HOME:
                    self.server._nav_refresh(user, self.views.home, state.get('forum_language'))
                elif menu == nav.CATEGORIES:
                    self.server._nav_refresh(user, self.index, state.get('forum_language'))
                elif menu == nav.TOPICS and state.get('forum_view') == 'category':
                    category_id = state['forum_category']
                    if self.service.repository.has_category(category_id):
                        self.server._nav_refresh(user, self.views.topics, 'category', category_id, '', state['forum_page'])
                    else:
                        self.server._nav_back(user)
            except ForumError:
                # An account may have lost approval or staff rights meanwhile.
                continue
