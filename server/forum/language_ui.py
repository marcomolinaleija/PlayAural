"""Language selection using the shared keyboard/speech menu protocol."""

from . import navigation as nav
from .languages import FORUM_LANGUAGES
from .views import item, label


class LanguageController:
    def __init__(self, manager):
        self.manager = manager
        self.server, self.service, self.views = manager.server, manager.service, manager.views

    def show(self, user):
        current = self.service.languages.current(user.uuid)
        rows = [item(user, 'forum-language-choice', f'language:{code}',
                     language=label(user, 'forum-language-' + code),
                     selected=label(user, 'forum-language-selected') if code == current else '')
                for code in FORUM_LANGUAGES]
        title = label(user, 'forum-language-choose')
        self.views.render(user, nav.LANGUAGES, rows, title=title,
                          announcement=('forum-entry-simple', {'title': title}))

    def handle(self, user, selection, state):
        if state['menu'] == nav.HOME and selection == 'language':
            self.server._nav_push(user, self.show)
            return True
        if state['menu'] != nav.LANGUAGES:
            return False
        if selection.startswith('language:'):
            language = selection.removeprefix('language:')
            self.service.languages.select(user.uuid, language)
            if state.get('_stack') and state['_stack'][-1].get('menu') == nav.HOME:
                state['_stack'][-1]['forum_language'] = language
                state['_stack'][-1]['_restore_focus_id'] = 'language'
            self.server._nav_back(user)
        return True
