"""Administrator menus for granting and revoking scoped translator roles."""

from ..menu_pagination import PaginatedMenuPage, clamp_page, paginate_sequence, pagination_menu_items, page_for_selection
from ..messages.localization import Localization
from ..ui.confirmation import show_confirmation_menu
from ..users.base import MenuItem
from . import navigation as nav
from .models import PAGE_SIZE, TranslationError


class TeamMenus:
    def __init__(self, controller):
        self.controller = controller
        self.service = controller.service
        self.server = controller.server

    def members(self, user, query='', page=1):
        self.service.roles.require_admin(user.uuid)
        count = self.server.db.count_users(query)
        page = clamp_page(page, count, PAGE_SIZE)
        accounts = self.server.db.search_users(query, limit=PAGE_SIZE, offset=(page - 1) * PAGE_SIZE)
        data = PaginatedMenuPage(accounts, page, count, PAGE_SIZE)
        rows = []
        for account in accounts:
            assigned = self.service.roles.assignments(user.uuid, account.uuid)
            rows.append(MenuItem(text=Localization.get(user.locale, 'translation-team-user', name=account.username,
                                                      count=sum(bool(role['enabled']) for role in assigned.values())),
                                 id='team_user:' + account.uuid))
        if not rows:
            rows.append(MenuItem(text=Localization.get(user.locale, 'translation-empty'), read_only=True))
        rows.append(MenuItem(text=Localization.get(user.locale, 'translation-team-search'), id='search'))
        rows.extend(pagination_menu_items(user.locale, data))
        self.controller.render(user, nav.TEAM, rows, 'translation-team-heading', tr_query=query, tr_page=page, tr_pages=data.total_pages)

    def member(self, user, target, page=1):
        assigned = self.service.roles.assignments(user.uuid, target)
        account = self.server.db.get_user_by_uuid(target)
        languages = list(self.service.languages(user.uuid).items())
        data = paginate_sequence(languages, page, page_size=PAGE_SIZE)
        rows = [MenuItem(text=Localization.get(user.locale, 'translation-team-language', name=language['native_name'],
                                             status=Localization.get(user.locale, 'translation-role-enabled' if assigned.get(code, {}).get('enabled') else 'translation-role-disabled')),
                         id='team_language:' + code) for code, language in data.items]
        rows.extend(pagination_menu_items(user.locale, data))
        self.controller.render(user, nav.TEAM_MEMBER, rows, 'translation-team-heading', tr_target=target,
                               tr_author_name=account.username, tr_page=data.page, tr_pages=data.total_pages)

    def confirm(self, user, target, language, enabled, revision):
        self.service.roles.require_admin(user.uuid)
        account = self.server.db.get_user_by_uuid(target)
        if account is None:
            raise TranslationError('translation-error-account')
        info = self.service.language(user.uuid, language)
        show_confirmation_menu(user, nav.TEAM_CONFIRM, buffer='system',
                               prompt_key='translation-role-confirm-grant' if enabled else 'translation-role-confirm-revoke',
                               prompt_kwargs={'author': account.username, 'language': info['native_name']})
        self.server._user_states[user.username] = {'menu': nav.TEAM_CONFIRM, 'tr_target': target, 'tr_language': language,
                                                  'tr_enabled': enabled, 'tr_role_revision': revision}

    def handle(self, user, selection, state):
        self.service.roles.require_admin(user.uuid)
        menu = state['menu']
        if menu == nav.TEAM and selection.startswith('team_user:'):
            self.server._nav_push(user, self.member, selection.removeprefix('team_user:'))
        elif menu == nav.TEAM and selection == 'search':
            self.server.enter_input_state(user, nav.SEARCH_INPUT)
            user.show_editbox(nav.SEARCH_INPUT, Localization.get(user.locale, 'translation-team-search-prompt'),
                              state.get('tr_query', ''), max_length=200)
        elif menu == nav.TEAM_MEMBER and selection.startswith('team_language:'):
            language = selection.removeprefix('team_language:')
            current = self.service.roles.assignments(user.uuid, state['tr_target']).get(language, {})
            self.server._nav_push(user, self.confirm, state['tr_target'], language, not bool(current.get('enabled')), current.get('revision', 0))
        elif menu == nav.TEAM_CONFIRM:
            if selection == 'yes':
                self.service.roles.set(user.uuid, state['tr_target'], state['tr_language'], state['tr_enabled'], state['tr_role_revision'])
                user.speak_l('translation-role-changed', buffer='system')
                account = self.server.db.get_user_by_uuid(state['tr_target'])
                online = self.server._users.get(account.username) if account else None
                if online:
                    online.speak_l('translation-role-updated', buffer='system', history=False)
            self.server._nav_back(user)
        else:
            page = page_for_selection(selection, state['tr_page'], state['tr_pages'])
            if page is not None:
                if menu == nav.TEAM:
                    self.server._nav_refresh(user, self.members, state.get('tr_query', ''), page)
                else:
                    self.server._nav_refresh(user, self.member, state['tr_target'], page)

    def restore(self, user, state):
        if state['menu'] == nav.TEAM:
            self.members(user, state.get('tr_query', ''), state.get('tr_page', 1))
        elif state['menu'] == nav.TEAM_MEMBER:
            self.member(user, state['tr_target'], state.get('tr_page', 1))
        else:
            self.confirm(user, state['tr_target'], state['tr_language'], state['tr_enabled'], state['tr_role_revision'])
