"""One shared keyboard/speech workflow for authors and staff reviewers."""

import json
import time
from uuid import uuid4

from ..games.registry import GameRegistry
from ..menu_pagination import paginate_sequence, pagination_menu_items, page_for_selection
from ..messages.localization import Localization
from ..ui.confirmation import show_confirmation_menu
from ..users.base import EscapeBehavior, MenuItem
from . import navigation as nav
from .models import MAX_NOTE, MAX_TEXT, PAGE_SIZE, TranslationError
from .service import TranslationService
from .forms import forms, needs_forms
from .validation import clean_text
from .team import TeamMenus


def text(user, key, **values):
    return Localization.get(user.locale, key, **values)


def row(user, key, item_id, **values):
    return MenuItem(text=text(user, key, **values), id=item_id)


def excerpt(value, limit=140):
    value = ' '.join(value.split())
    return value if len(value) <= limit else value[:limit - 1] + '…'


class TranslationController:
    def __init__(self, server):
        self.server = server
        self.service = TranslationService(server.db)
        self.team = TeamMenus(self)

    def render(self, user, menu, rows, title_key, **state):
        self.service.account(user.uuid)
        previous = self.server._user_states.get(user.username, {})
        rows.append(row(user, 'back', 'back'))
        title = text(user, title_key)
        if state.get('tr_language'):
            language = self.service.language(user.uuid, state['tr_language'])
            title = text(user, 'translation-context-heading', title=title, language=language['native_name'])
        if state.get('tr_author_name'):
            title = text(user, 'translation-context-author', title=title, author=state['tr_author_name'])
        user.show_menu(menu, rows, title=title, multiletter=True, escape_behavior=EscapeBehavior.SELECT_LAST)
        self.server._user_states[user.username] = {'menu': menu, **state}
        if previous.get('menu') != menu:
            user.speak(title, buffer='misc', history=False)

    def collaborate(self, user):
        rows = [row(user, 'translation-heading', 'translations')]
        if self.service.roles.can_review(user.uuid):
            rows.append(row(user, 'translation-review-heading', 'review_translations'))
        self.render(user, nav.COLLABORATE, rows, 'translation-collaborate')

    def open_review(self, user):
        try:
            self.service.roles.require_review(user.uuid)
            self.server._nav_push(user, self.queue)
        except TranslationError as error:
            self.error(user, error)

    def open_team(self, user):
        try:
            self.service.roles.require_admin(user.uuid)
            self.server._nav_push(user, self.team.members)
        except TranslationError as error:
            self.error(user, error)

    def languages(self, user):
        rows = [MenuItem(text=language['native_name'] if language['status'] == 'installed' else
                        text(user, 'translation-language-preparing', name=language['native_name']), id='language:' + code)
                for code, language in self.service.languages(user.uuid).items()]
        rows.append(row(user, 'translation-new-language', 'new_language'))
        self.render(user, nav.LANGUAGES, rows, 'translation-choose-language')

    def dashboard(self, user, language):
        self.service.language(user.uuid, language)
        mine = self.service.proposal_page(user.uuid, language=language)
        rows = [row(user, 'translation-missing', 'missing'), row(user, 'translation-correct', 'all'),
                row(user, 'translation-mine-count', 'mine', count=mine.total),
                row(user, 'translation-credits', 'credits')]
        self.render(user, nav.DASHBOARD, rows, 'translation-heading', tr_language=language)

    def section_id(self, unit):
        stem = unit.path.rsplit('/', 1)[-1].split('.')[0]
        game = GameRegistry.get(stem)
        if game is not None:
            return unit.domain + ':game:' + stem
        return unit.domain + (':forum' if stem.startswith('forum') else ':admin' if stem.startswith('admin') else ':general')

    def section_name(self, user, section):
        parts = section.split(':')
        domain = text(user, 'translation-domain-' + parts[0])
        name = text(user, GameRegistry.get(parts[2]).get_name_key()) if parts[1] == 'game' else text(user, 'translation-section-' + parts[1])
        return domain + ': ' + name

    def matching(self, user, language, mode, section='', query=''):
        self.service.language(user.uuid, language)
        accepted = {r['unit_id']: dict(r) for r in self.service.connection.execute(
            'SELECT * FROM translation_accepted WHERE language = ?', (language,))}
        proposals = self.service.open_statuses(user.uuid, language)
        reservations = self.service.reservations.active(language)
        units = []
        query = query.casefold()
        for unit in self.service.catalog.units.values():
            if section and self.section_id(unit) != section:
                continue
            current = accepted.get(unit.id)
            outdated = bool(current and current['source_hash'] != unit.source_hash and current['value'] != self.service.catalog.current(unit, language))
            translated = current['value'] if current and current['source_hash'] == unit.source_hash else self.service.catalog.current(unit, language)
            if mode == 'missing' and translated and not outdated:
                continue
            if query and query not in unit.original.casefold() and query not in translated.casefold():
                continue
            status = proposals[unit.id] if unit.id in proposals else 'outdated' if outdated else 'translated' if translated else 'missing'
            reservation = reservations.get(unit.id)
            if reservation and reservation['owner_uuid'] != user.uuid:
                key = 'translation-reserved-review-by' if reservation['status'] == 'pending' else 'translation-reserved-by'
                status = {'key': key, 'author': reservation['username']}
            units.append((unit, status))
        return units

    def sections(self, user, language, mode):
        counts = {}
        for unit, _ in self.matching(user, language, mode):
            section = self.section_id(unit)
            counts[section] = counts.get(section, 0) + 1
        rows = [row(user, 'translation-section-row', 'section:' + section,
                    name=self.section_name(user, section), count=count) for section, count in counts.items()]
        if not rows:
            rows.append(MenuItem(text=text(user, 'translation-empty'), read_only=True))
        self.render(user, nav.SECTIONS, rows, 'translation-choose-section', tr_language=language, tr_mode=mode)

    def units(self, user, language, mode, section, query='', page=1):
        data = paginate_sequence(self.matching(user, language, mode, section, query), page, page_size=PAGE_SIZE)
        rows = [row(user, 'translation-unit-row', 'unit:' + unit.id,
                    original=excerpt(unit.original), status=self.status_text(user, status)) for unit, status in data.items]
        if not rows:
            rows.append(MenuItem(text=text(user, 'translation-empty'), read_only=True))
        rows.append(row(user, 'translation-search', 'search'))
        rows.extend(pagination_menu_items(user.locale, data))
        self.render(user, nav.UNITS, rows, 'translation-choose-text', tr_language=language, tr_mode=mode,
                    tr_section=section, tr_query=query, tr_page=data.page, tr_pages=data.total_pages)

    def mine(self, user, language, page=1):
        data = self.service.proposal_page(user.uuid, language=language, page=page)
        rows = [row(user, 'translation-unit-row', 'proposal:' + str(proposal['id']),
                    original=excerpt(proposal['source_text']), status=text(user, 'translation-status-' + proposal['status']))
                for proposal in data.items]
        if any(p['status'] in {'draft', 'changes_requested'} for p in data.items):
            rows.append(row(user, 'translation-submit-page', 'submit_page'))
        if not rows:
            rows.append(MenuItem(text=text(user, 'translation-empty'), read_only=True))
        rows.extend(pagination_menu_items(user.locale, data))
        self.render(user, nav.MINE, rows, 'translation-my-work', tr_language=language,
                    tr_page=data.page, tr_pages=data.total_pages)

    def status_text(self, user, status):
        if isinstance(status, dict):
            return text(user, status['key'], author=status['author'])
        return text(user, 'translation-status-' + status)

    def queue(self, user, language='', page=1, history=False, author=None):
        state = {'tr_language': language, 'tr_history': history, 'tr_author': author}
        count_key = 'translation-reviewed-count' if history else 'translation-pending-count'
        if not language:
            data = self.service.review_groups(user.uuid, history=history, page=page)
            languages = self.service.languages(user.uuid)
            rows = [row(user, count_key, 'review_language:' + group['language'],
                        name=languages[group['language']]['native_name'], count=group['count']) for group in data.items]
            menu = nav.REVIEW
        elif author is None:
            data = self.service.review_groups(user.uuid, language=language, history=history, page=page)
            rows = [row(user, count_key, 'review_author:' + group['author_id'],
                        name=group['author'] or text(user, 'translation-deleted-author'), count=group['count']) for group in data.items]
            menu = nav.REVIEW_AUTHORS
        else:
            data = self.service.proposal_page(user.uuid, language=language, review=True, history=history, page=page, author=author)
            account = self.server.db.get_user_by_uuid(author)
            state['tr_author_name'] = account.username if account else text(user, 'translation-deleted-author')
            rows = [row(user, 'translation-review-text-row', 'review:' + str(proposal['id']),
                        original=excerpt(proposal['source_text'], 80), value=excerpt(proposal['value'], 80),
                        status=text(user, 'translation-status-' + proposal['status'])) for proposal in data.items]
            menu = nav.REVIEW_ITEMS
        if not rows:
            rows.append(MenuItem(text=text(user, 'translation-empty-review'), read_only=True))
        if menu == nav.REVIEW:
            rows.append(row(user, 'translation-review-pending' if history else 'translation-review-history', 'toggle_history'))
        rows.extend(pagination_menu_items(user.locale, data))
        self.render(user, menu, rows, 'translation-review-history-heading' if history else 'translation-review-heading',
                    **state, tr_page=data.page, tr_pages=data.total_pages)

    def finish_review(self, user, state):
        """Return to the next pending item, or to that language's contributors."""
        stack = list(state.get('_stack', []))
        for index in range(len(stack) - 1, -1, -1):
            frame = dict(stack[index])
            if frame.get('menu') != nav.REVIEW_ITEMS:
                continue
            data = self.service.proposal_page(user.uuid, language=frame['tr_language'], review=True,
                                             history=frame.get('tr_history', False), page=frame['tr_page'], author=frame['tr_author'])
            if data.items:
                position = min(max(frame.get('_last_selection_position') or 1, 1), len(data.items))
                frame['tr_page'] = data.page
                frame['_restore_focus_id'] = 'review:' + str(data.items[position - 1]['id'])
                self.server._restore_frame(user, frame, stack[:index])
            elif index and stack[index - 1].get('menu') == nav.REVIEW_AUTHORS:
                self.server._restore_frame(user, stack[index - 1], stack[:index - 1])
            else:
                self.server._restore_frame(user, {'menu': nav.REVIEW_AUTHORS, 'tr_language': frame['tr_language'],
                                                  'tr_history': frame.get('tr_history', False)}, [])
            return
        self.server._restore_frame(user, {'menu': nav.REVIEW}, stack)

    def editor(self, user, proposal_id, review=False):
        proposal = self.service.get(user.uuid, proposal_id, review=review)
        if not review and proposal['notice_pending']:
            self.service.mark_seen(user.uuid, proposal_id)
        unit = self.service.catalog.units.get(proposal['unit_id'])
        source_name = text(user, 'translation-source-' + unit.source_locale) if unit is not None else ''
        rows = [row(user, 'translation-original-row', 'original', value=excerpt(proposal['source_text'])),
                row(user, 'translation-value-row', 'edit' if not review and proposal['status'] in {'draft', 'changes_requested'} else 'read_translation',
                    value=excerpt(proposal['value']) or text(user, 'translation-not-written'))]
        if source_name:
            rows[0].text = text(user, 'translation-original-language-row', language=source_name, value=excerpt(proposal['source_text']))
        if unit is not None and needs_forms(unit):
            values = json.loads(proposal['forms_json'])
            all_forms = forms(unit)
            rows[0].text = text(user, 'translation-original-forms-row', count=len(all_forms), language=source_name)
            rows[1].text = text(user, 'translation-value-forms-row', count=sum(bool(values.get(form.id)) for form in all_forms), total=len(all_forms))
        if unit is None:
            rows.append(MenuItem(text=text(user, 'translation-error-unit'), read_only=True))
        elif unit.source_hash != proposal['source_hash']:
            rows.append(row(user, 'translation-updated-original', 'updated_original', value=excerpt(unit.original)))
        if review and unit is not None:
            rows.append(row(user, 'translation-current-row', 'current', value=excerpt(self.service.current(proposal['language'], unit.id)) or text(user, 'translation-not-written')))
        rows.append(row(user, 'translation-preview', 'preview'))
        if proposal['note']:
            rows.append(row(user, 'translation-note-row', 'note', value=excerpt(proposal['note'])))
        if review:
            if proposal['status'] == 'pending':
                rows.extend([row(user, 'translation-approve', 'approve'),
                             row(user, 'translation-request-changes', 'request_changes'),
                             row(user, 'translation-reject', 'reject')])
            elif proposal['status'] == 'approved':
                rows.append(row(user, 'translation-revert', 'revert'))
        elif proposal['status'] in {'draft', 'changes_requested'}:
            rows.extend([row(user, 'translation-save-next', 'next'), row(user, 'translation-previous', 'previous'),
                         row(user, 'translation-submit', 'submit'), row(user, 'translation-refresh-source', 'refresh_source'),
                         row(user, 'translation-discard', 'discard')])
            reservation = self.service.reservations.active(proposal['language']).get(proposal['unit_id'])
            if reservation:
                key = 'translation-reserved-review-by' if reservation['status'] == 'pending' else 'translation-reserved-by'
                rows.append(MenuItem(text=text(user, key, author=reservation['username']), read_only=True))
                if reservation['proposal_id'] == proposal_id:
                    rows.append(row(user, 'translation-release', 'release'))
        elif proposal['status'] == 'pending':
            rows.append(row(user, 'translation-withdraw', 'withdraw'))
        else:
            rows.append(row(user, 'translation-new-proposal', 'new_proposal'))
        rows.append(row(user, 'translation-history', 'history'))
        self.render(user, nav.EDITOR, rows, 'translation-review-heading' if review else 'translation-heading',
                    tr_id=proposal_id, tr_review=review, tr_revision=proposal['revision'],
                    tr_language=proposal['language'], tr_accepted_revision=self.service.accepted_revision(proposal['language'], proposal['unit_id']))

    def form_name(self, user, form_id):
        names = []
        for part in form_id.split('/'):
            if part.startswith('case:'):
                key = part.rsplit(':', 1)[-1]
                translated = text(user, 'translation-form-' + key)
                names.append(translated if translated != 'translation-form-' + key else key)
            elif part.startswith('attribute:'):
                names.append(text(user, 'translation-form-attribute', name=part.split(':', 1)[1]))
        return ', '.join(names) or text(user, 'translation-form-text')

    def forms_menu(self, user, proposal_id, review=False):
        proposal = self.service.get(user.uuid, proposal_id, review=review)
        unit = self.service.catalog.get(proposal['unit_id'])
        values = json.loads(proposal['forms_json'])
        rows = [row(user, 'translation-form-row', 'form:' + form.id, name=self.form_name(user, form.id),
                    status=text(user, 'translation-status-draft' if values.get(form.id) else 'translation-status-missing'))
                for form in forms(unit)]
        self.render(user, nav.FORMS, rows, 'translation-forms', tr_id=proposal_id, tr_review=review,
                    tr_language=proposal['language'])

    def form_editor(self, user, proposal_id, form_id, review=False):
        proposal = self.service.get(user.uuid, proposal_id, review=review)
        form = next((form for form in forms(self.service.catalog.get(proposal['unit_id'])) if form.id == form_id), None)
        if form is None:
            raise TranslationError('translation-error-unit')
        value = json.loads(proposal['forms_json']).get(form_id, '')
        editable = not review and proposal['status'] in {'draft', 'changes_requested'}
        rows = [row(user, 'translation-original-row', 'original', value=excerpt(form.value)),
                row(user, 'translation-value-row', 'edit' if editable else 'read_translation',
                    value=excerpt(value) or text(user, 'translation-not-written')),
                row(user, 'translation-preview', 'preview')]
        self.render(user, nav.FORM_EDITOR, rows, 'translation-heading', tr_id=proposal_id,
                    tr_review=review, tr_revision=proposal['revision'], tr_form=form_id,
                    tr_language=proposal['language'])

    def reading(self, user, value, parent_state):
        self.server.enter_input_state(user, nav.READ_INPUT, tr_id=parent_state.get('tr_id'), tr_review=parent_state.get('tr_review', False))
        user.show_editbox(nav.READ_INPUT, text(user, 'translation-read-prompt'), value,
                          multiline=True, read_only=True, max_length=MAX_TEXT)

    def show_edit_input(self, user, value):
        state = self.server._user_states[user.username]
        state['tr_token'] = uuid4().hex
        state['tr_sequence'] = 0
        proposal = self.service.get(user.uuid, state['tr_id'])
        unit = self.service.catalog.get(proposal['unit_id'])
        original = next(form.value for form in forms(unit) if form.id == state['tr_form']) if state.get('tr_form') else unit.original
        user.show_editbox(nav.TEXT_INPUT, text(user, 'translation-edit-prompt'), value,
                          multiline=True, max_length=MAX_TEXT,
                          translation_draft={'token': state['tr_token'], 'original': excerpt(original, 1000)})

    def save_live_draft(self, user, packet):
        state = self.server._user_states.get(user.username, {})
        sequence = packet.get('sequence')
        if (state.get('menu') != nav.TEXT_INPUT or packet.get('input_id') != nav.TEXT_INPUT
                or not state.get('tr_token') or packet.get('token') != state['tr_token']
                or type(sequence) is not int or sequence <= state.get('tr_sequence', 0)):
            return
        # Clients debounce for 600 ms; do not turn a stream of forged edits
        # into unbounded SQLite writes or speech announcements.
        if time.monotonic() - state.get('tr_last_save', 0) < 0.2:
            return
        state['tr_sequence'] = sequence
        state['tr_last_save'] = time.monotonic()
        saved, preview, error = False, '', ''
        try:
            if state.get('tr_form'):
                proposal = self.service.save_form(user.uuid, state['tr_id'], state['tr_form'], packet.get('text'), state['tr_revision'])
            else:
                proposal = self.service.save(user.uuid, state['tr_id'], packet.get('text'), state['tr_revision'])
            state['tr_revision'] = proposal['revision']
            saved = True
            preview = self.service.preview(user.uuid, state['tr_id'], form_id=state.get('tr_form'))[:4000]
        except TranslationError as failure:
            error = text(user, failure.key, **failure.values)
        user.queue_protocol_packet({'type': 'translation_draft', 'input_id': nav.TEXT_INPUT,
                                    'token': state['tr_token'], 'sequence': sequence,
                                    'saved': saved, 'preview': preview, 'error': error})

    def preview(self, user, proposal_id, review=False, form_id=None):
        value = self.service.preview(user.uuid, proposal_id, review=review, form_id=form_id)
        self.reading(user, value, {'tr_id': proposal_id, 'tr_review': review})

    def history(self, user, proposal_id, review=False):
        events = self.service.history(user.uuid, proposal_id, review=review)
        rows = [MenuItem(text=text(user, 'translation-event-' + event['action']) +
                         (': ' + excerpt(json.loads(event['value_json']).get('note', ''))
                          if json.loads(event['value_json']).get('note') else ''), read_only=True) for event in events]
        self.render(user, nav.HISTORY, rows, 'translation-history', tr_id=proposal_id, tr_review=review)

    def credits(self, user, language):
        rows = [row(user, 'translation-credit-row', '', name=person['username'], count=person['contributions'])
                for person in self.service.credits(user.uuid, language)]
        if not rows:
            rows.append(MenuItem(text=text(user, 'translation-no-credits'), read_only=True))
        self.render(user, nav.CREDITS, rows, 'translation-credits', tr_language=language)

    def conflict(self, user, proposal_id, unsaved, form_id=None):
        proposal = self.service.get(user.uuid, proposal_id)
        rows = [row(user, 'translation-conflict-mine', 'unsaved'),
                row(user, 'translation-conflict-current', 'latest')]
        if proposal['status'] in {'draft', 'changes_requested'}:
            rows.append(row(user, 'translation-conflict-apply', 'use_mine'))
        rows.append(row(user, 'translation-conflict-keep', 'keep_current'))
        self.render(user, nav.CONFLICT, rows, 'translation-conflict-heading', tr_id=proposal_id,
                    tr_revision=proposal['revision'], tr_unsaved=unsaved, tr_form=form_id,
                    tr_language=proposal['language'])

    def recover_conflict(self, user, state, value):
        user.remove_editbox(state['menu'])
        parent = dict(state.get('_parent_frame', {}))
        parent['_stack'] = list(state.get('_stack', []))
        self.server._user_states[user.username] = parent
        self.server._nav_push(user, self.conflict, state['tr_id'], value, state.get('tr_form'))

    def new_language(self, user, draft=None):
        draft = draft or {'code': '', 'name': '', 'native_name': ''}
        rows = [row(user, 'translation-language-' + field, 'language_field:' + field,
                    value=draft[field] or text(user, 'translation-not-written')) for field in draft]
        rows.append(row(user, 'translation-language-create', 'create'))
        self.render(user, nav.NEW_LANGUAGE, rows, 'translation-new-language', tr_language_draft=dict(draft))

    def confirm(self, user, action, proposal_id, revision, review=False, accepted_revision=None, unsaved=None, form_id=None):
        self.service.get(user.uuid, proposal_id, review=review)
        show_confirmation_menu(user, nav.CONFIRM, prompt_key='translation-confirm-' + action, buffer='system')
        self.server._user_states[user.username] = {'menu': nav.CONFIRM, 'tr_action': action,
                                                  'tr_id': proposal_id, 'tr_revision': revision, 'tr_review': review}
        self.server._user_states[user.username]['tr_accepted_revision'] = accepted_revision
        if unsaved is not None:
            self.server._user_states[user.username].update(tr_unsaved=unsaved, tr_form=form_id)

    def restore(self, user, state):
        try:
            menu = state['menu']
            if menu == nav.COLLABORATE:
                self.collaborate(user)
            elif menu == nav.LANGUAGES:
                self.languages(user)
            elif menu == nav.DASHBOARD:
                self.dashboard(user, state['tr_language'])
            elif menu == nav.SECTIONS:
                self.sections(user, state['tr_language'], state['tr_mode'])
            elif menu == nav.UNITS:
                self.units(user, state['tr_language'], state['tr_mode'], state['tr_section'], state.get('tr_query', ''), state.get('tr_page', 1))
            elif menu == nav.MINE:
                self.mine(user, state['tr_language'], state.get('tr_page', 1))
            elif menu in {nav.REVIEW, nav.REVIEW_AUTHORS, nav.REVIEW_ITEMS}:
                self.queue(user, state.get('tr_language', ''), state.get('tr_page', 1), state.get('tr_history', False), state.get('tr_author'))
            elif menu in {nav.TEAM, nav.TEAM_MEMBER, nav.TEAM_CONFIRM}:
                self.team.restore(user, state)
            elif menu in {nav.EDITOR, nav.CONFIRM, *nav.INPUT_IDS}:
                if state.get('tr_id'):
                    self.editor(user, state['tr_id'], state.get('tr_review', False))
                else:
                    self.languages(user)
            elif menu == nav.HISTORY:
                self.history(user, state['tr_id'], state.get('tr_review', False))
            elif menu == nav.CREDITS:
                self.credits(user, state['tr_language'])
            elif menu == nav.NEW_LANGUAGE:
                self.new_language(user, state.get('tr_language_draft'))
            elif menu == nav.CONFLICT:
                self.conflict(user, state['tr_id'], state['tr_unsaved'], state.get('tr_form'))
            elif menu == nav.FORMS:
                self.forms_menu(user, state['tr_id'], state.get('tr_review', False))
            elif menu == nav.FORM_EDITOR:
                self.form_editor(user, state['tr_id'], state['tr_form'], state.get('tr_review', False))
            else:
                return False
        except TranslationError as error:
            self.error(user, error)
            self.server._show_personal_options_menu(user)
        return True

    def error(self, user, error):
        user.speak_l(error.key, buffer='system', **error.values)

    def notify(self, user):
        try:
            count = self.service.notice_count(user.uuid)
            if count:
                user.speak_l('translation-response-notice', count=count, buffer='system', history=False)
        except TranslationError:
            return

    def notify_author(self, proposal_id):
        proposal = self.service.connection.execute('SELECT author_uuid FROM translation_proposals WHERE id = ?', (proposal_id,)).fetchone()
        if proposal and proposal['author_uuid']:
            account = self.server.db.get_user_by_uuid(proposal['author_uuid'])
            online = self.server._users.get(account.username) if account else None
            if online:
                self.notify(online)

    def handle(self, user, selection, state):
        try:
            self._handle(user, selection, state)
        except TranslationError as error:
            self.error(user, error)

    def _handle(self, user, selection, state):
        self.service.account(user.uuid)
        if selection == 'back':
            self.server._nav_back(user)
            return
        push, refresh = self.server._nav_push, self.server._nav_refresh
        menu, language = state['menu'], state.get('tr_language', '')
        if menu in {nav.TEAM, nav.TEAM_MEMBER, nav.TEAM_CONFIRM}:
            self.team.handle(user, selection, state)
            return
        if menu == nav.COLLABORATE and selection == 'translations':
            push(user, self.languages)
        elif menu == nav.COLLABORATE and selection == 'review_translations':
            self.service.roles.require_review(user.uuid)
            push(user, self.queue)
        elif menu == nav.LANGUAGES:
            if selection.startswith('language:'):
                language = selection.removeprefix('language:')
                self.service.language(user.uuid, language)
                push(user, self.dashboard, language)
            elif selection == 'new_language':
                push(user, self.new_language)
        elif menu == nav.DASHBOARD:
            if selection in {'missing', 'all'}:
                push(user, self.sections, language, selection)
            elif selection == 'mine':
                push(user, self.mine, language)
            elif selection == 'credits':
                push(user, self.credits, language)
        elif menu == nav.SECTIONS and selection.startswith('section:'):
            push(user, self.units, language, state['tr_mode'], selection.removeprefix('section:'))
        elif menu in {nav.UNITS, nav.MINE, nav.REVIEW, nav.REVIEW_AUTHORS, nav.REVIEW_ITEMS}:
            if menu == nav.REVIEW and selection.startswith('review_language:'):
                push(user, self.queue, selection.removeprefix('review_language:'), 1, state.get('tr_history', False))
            elif menu == nav.REVIEW_AUTHORS and selection.startswith('review_author:'):
                push(user, self.queue, language, 1, state.get('tr_history', False), selection.removeprefix('review_author:'))
            elif selection.startswith('unit:'):
                proposal = self.service.draft(user.uuid, language, selection.removeprefix('unit:'))
                push(user, self.editor, proposal['id'])
            elif selection.startswith(('proposal:', 'review:')):
                push(user, self.editor, int(selection.split(':')[1]), menu == nav.REVIEW_ITEMS)
            elif selection == 'search':
                self.server.enter_input_state(user, nav.SEARCH_INPUT, **{k: v for k, v in state.items() if k.startswith('tr_')})
                user.show_editbox(nav.SEARCH_INPUT, text(user, 'translation-search-prompt'), max_length=200)
            elif selection == 'submit_page':
                proposals = self.service.proposal_page(user.uuid, language=language, page=state['tr_page'])
                batch = [(p['id'], p['revision']) for p in proposals.items if p['status'] in {'draft', 'changes_requested'}]
                count = self.service.submit(user.uuid, batch)
                user.speak_l('translation-submitted', count=count, buffer='system')
                refresh(user, self.mine, language, state['tr_page'])
            elif menu == nav.REVIEW and selection == 'toggle_history':
                refresh(user, self.queue, language, 1, not state.get('tr_history', False))
            else:
                page = page_for_selection(selection, state['tr_page'], state['tr_pages'])
                if page is not None:
                    if menu == nav.UNITS:
                        refresh(user, self.units, language, state['tr_mode'], state['tr_section'], state.get('tr_query', ''), page)
                    else:
                        if menu == nav.MINE:
                            refresh(user, self.mine, language, page)
                        else:
                            refresh(user, self.queue, language, page, state.get('tr_history', False), state.get('tr_author'))
        elif menu == nav.FORMS and selection.startswith('form:'):
            push(user, self.form_editor, state['tr_id'], selection.removeprefix('form:'), state['tr_review'])
        elif menu in {nav.EDITOR, nav.FORM_EDITOR}:
            proposal = self.service.get(user.uuid, state['tr_id'], review=state['tr_review'])
            if selection in {'original', 'updated_original', 'read_translation', 'current', 'note'}:
                unit = self.service.catalog.units.get(proposal['unit_id'])
                if menu == nav.EDITOR and selection in {'original', 'read_translation'} and unit is not None and needs_forms(unit):
                    push(user, self.forms_menu, proposal['id'], state['tr_review'])
                    return
                value = proposal['source_text'] if selection == 'original' else proposal['note'] if selection == 'note' else self.service.current(language, proposal['unit_id']) if selection == 'current' else proposal['value']
                if selection == 'updated_original':
                    value = self.service.catalog.get(proposal['unit_id']).original
                if menu == nav.FORM_EDITOR:
                    form = next(form for form in forms(self.service.catalog.get(proposal['unit_id'])) if form.id == state['tr_form'])
                    value = form.value if selection == 'original' else json.loads(proposal['forms_json']).get(form.id, '')
                self.reading(user, value, state)
            elif selection == 'edit':
                self.service.reservations.reserve(user.uuid, proposal['id'], state['tr_revision'])
                if menu == nav.EDITOR and needs_forms(self.service.catalog.get(proposal['unit_id'])):
                    push(user, self.forms_menu, proposal['id'])
                else:
                    self.server.enter_input_state(user, nav.TEXT_INPUT, tr_id=proposal['id'], tr_revision=state['tr_revision'],
                                                  tr_review=False, tr_form=state.get('tr_form'))
                    value = json.loads(proposal['forms_json']).get(state['tr_form'], '') if state.get('tr_form') else proposal['value']
                    self.show_edit_input(user, value)
            elif selection == 'preview':
                self.preview(user, proposal['id'], state['tr_review'], state.get('tr_form'))
            elif selection == 'history':
                push(user, self.history, proposal['id'], state['tr_review'])
            elif selection in {'submit', 'approve', 'revert', 'discard', 'withdraw', 'release'}:
                push(user, self.confirm, selection, proposal['id'], state['tr_revision'], state['tr_review'], state.get('tr_accepted_revision'))
            elif selection in {'request_changes', 'reject'}:
                self.service.account(user.uuid, reviewer=True)
                self.server.enter_input_state(user, nav.NOTE_INPUT, tr_id=proposal['id'], tr_revision=state['tr_revision'],
                                              tr_review=True, tr_action=selection)
                user.show_editbox(nav.NOTE_INPUT, text(user, 'translation-review-note-prompt'), multiline=True, max_length=MAX_NOTE)
            elif selection == 'refresh_source':
                self.service.refresh_source(user.uuid, proposal['id'], state['tr_revision'])
                refresh(user, self.editor, proposal['id'])
            elif selection in {'next', 'previous'}:
                self.next(user, state, 1 if selection == 'next' else -1)
            elif selection == 'new_proposal':
                draft = self.service.draft(user.uuid, language, proposal['unit_id'], copy_from=proposal['id'])
                refresh(user, self.editor, draft['id'])
        elif menu == nav.NEW_LANGUAGE:
            if selection.startswith('language_field:'):
                field = selection.removeprefix('language_field:')
                if field not in state['tr_language_draft']:
                    return
                self.server.enter_input_state(user, nav.LANGUAGE_INPUT, tr_language_draft=state['tr_language_draft'], tr_field=field)
                user.show_editbox(nav.LANGUAGE_INPUT, text(user, 'translation-language-' + field + '-prompt'), state['tr_language_draft'][field], max_length=80)
            elif selection == 'create':
                draft = state['tr_language_draft']
                code = self.service.create_language(user.uuid, draft['code'], draft['name'], draft['native_name'])
                refresh(user, self.dashboard, code)
        elif menu == nav.CONFLICT:
            if selection in {'unsaved', 'latest'}:
                proposal = self.service.get(user.uuid, state['tr_id'])
                value = state['tr_unsaved'] if selection == 'unsaved' else json.loads(proposal['forms_json']).get(state['tr_form'], '') if state.get('tr_form') else proposal['value']
                self.reading(user, value, state)
            elif selection == 'use_mine':
                push(user, self.confirm, 'overwrite', state['tr_id'], state['tr_revision'],
                     False, None, state['tr_unsaved'], state.get('tr_form'))
            elif selection == 'keep_current':
                self.server._nav_back(user)
        elif menu == nav.CONFIRM and selection == 'yes':
            action, proposal_id, revision = state['tr_action'], state['tr_id'], state['tr_revision']
            if action == 'submit':
                self.service.submit(user.uuid, [(proposal_id, revision)])
            elif action == 'approve':
                self.service.review(user.uuid, proposal_id, revision, 'approved')
            elif action == 'revert':
                self.service.revert(user.uuid, proposal_id, revision, accepted_revision=state.get('tr_accepted_revision'))
            elif action == 'withdraw':
                self.service.withdraw(user.uuid, proposal_id, revision)
            elif action == 'discard':
                self.service.discard(user.uuid, proposal_id, revision)
            elif action == 'release':
                self.service.reservations.release(user.uuid, proposal_id, revision)
            elif action == 'overwrite':
                if state.get('tr_form'):
                    self.service.save_form(user.uuid, proposal_id, state['tr_form'], state['tr_unsaved'], revision)
                else:
                    self.service.save(user.uuid, proposal_id, state['tr_unsaved'], revision)
                self.server._nav_back(user)
            if action in {'approve', 'revert'}:
                self.finish_review(user, state)
            else:
                self.server._nav_back(user)
            if action in {'approve', 'revert'}:
                self.notify_author(proposal_id)
            user.speak_l('translation-action-' + action, buffer='system')
        elif menu == nav.CONFIRM and selection == 'no':
            self.server._nav_back(user)

    def next(self, user, state, direction):
        frames = [f for f in state.get('_stack', []) if f.get('menu') == nav.UNITS]
        if not frames:
            self.server._nav_back(user)
            return
        frame = frames[-1]
        units = self.matching(user, frame['tr_language'], frame['tr_mode'], frame['tr_section'], frame.get('tr_query', ''))
        proposal = self.service.get(user.uuid, state['tr_id'])
        ids = [unit.id for unit, _ in units]
        if proposal['unit_id'] not in ids or not 0 <= ids.index(proposal['unit_id']) + direction < len(ids):
            user.speak_l('translation-no-more', buffer='system')
            return
        next_index = ids.index(proposal['unit_id']) + direction
        draft = self.service.draft(user.uuid, frame['tr_language'], ids[next_index])
        frame['tr_page'] = next_index // PAGE_SIZE + 1
        frame['_restore_focus_id'] = 'unit:' + ids[next_index]
        self.server._nav_refresh(user, self.editor, draft['id'])

    def handle_input(self, user, packet, state):
        input_id = state['menu']
        if packet.get('input_id') != input_id:
            return
        try:
            self.service.account(user.uuid)
            if packet.get('cancelled') or input_id == nav.READ_INPUT:
                if input_id == nav.TEXT_INPUT and isinstance(packet.get('text'), str):
                    try:
                        if state.get('tr_form'):
                            self.service.save_form(user.uuid, state['tr_id'], state['tr_form'], packet['text'], state['tr_revision'])
                        else:
                            self.service.save(user.uuid, state['tr_id'], packet['text'], state['tr_revision'])
                    except TranslationError as error:
                        self.error(user, error)
                        if error.key in {'translation-error-changed', 'translation-error-reserved', 'translation-error-reserved-review'}:
                            self.recover_conflict(user, state, packet['text'])
                            return
                user.remove_editbox(input_id)
                self.server._restore_input_parent(user, state)
                return
            value = packet.get('text')
            if input_id == nav.TEXT_INPUT:
                if state.get('tr_form'):
                    self.service.save_form(user.uuid, state['tr_id'], state['tr_form'], value, state['tr_revision'])
                else:
                    self.service.save(user.uuid, state['tr_id'], value, state['tr_revision'])
            elif input_id == nav.NOTE_INPUT:
                self.service.review(user.uuid, state['tr_id'], state['tr_revision'],
                                    'changes_requested' if state['tr_action'] == 'request_changes' else 'rejected', value)
                user.remove_editbox(input_id)
                self.finish_review(user, state)
                self.notify_author(state['tr_id'])
                user.speak_l('translation-action-' + state['tr_action'], buffer='system')
                return
            elif input_id == nav.SEARCH_INPUT:
                query = clean_text(value, limit=200, empty=True).strip()
                state['_parent_frame']['tr_query'] = query
                state['_parent_frame']['tr_page'] = 1
            elif input_id == nav.LANGUAGE_INPUT:
                value = clean_text(value, limit=80).strip()
                state['_parent_frame']['tr_language_draft'][state['tr_field']] = value
            user.remove_editbox(input_id)
            self.server._restore_input_parent(user, state)
        except TranslationError as error:
            self.error(user, error)
            value = packet.get('text', '')
            value = value if isinstance(value, str) else ''
            if input_id == nav.TEXT_INPUT and error.key in {'translation-error-changed', 'translation-error-reserved', 'translation-error-reserved-review'}:
                self.recover_conflict(user, state, value)
                return
            if error.key in {'translation-error-account', 'translation-error-reviewer', 'translation-error-muted', 'translation-error-readonly', 'translation-error-unit'}:
                user.remove_editbox(input_id)
                self.server._restore_input_parent(user, state)
                return
            limit = MAX_NOTE if input_id == nav.NOTE_INPUT else 200 if input_id == nav.SEARCH_INPUT else 80 if input_id == nav.LANGUAGE_INPUT else MAX_TEXT
            key = 'translation-review-note-prompt' if input_id == nav.NOTE_INPUT else 'translation-search-prompt' if input_id == nav.SEARCH_INPUT else 'translation-language-' + state.get('tr_field', 'name') + '-prompt' if input_id == nav.LANGUAGE_INPUT else 'translation-edit-prompt'
            if input_id == nav.TEXT_INPUT:
                self.show_edit_input(user, value[:limit])
            else:
                user.show_editbox(input_id, text(user, key), value[:limit], multiline=input_id == nav.NOTE_INPUT, max_length=limit)
