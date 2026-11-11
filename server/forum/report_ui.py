"""Compact, explicitly confirmed reports of public threads and messages."""

import logging

from ..moderation.reports import MAX_REPORT_DETAILS_LENGTH, REPORT_REASON_CODES, report_reason_localization_key
from ..ui.confirmation import show_confirmation_menu
from . import navigation as nav
from .models import ForumError
from .reporting import ReportTarget, capture_public_report
from .text import excerpt, validate_text
from .views import item, label

logger = logging.getLogger(__name__)


class ReportController:
    def __init__(self, manager):
        self.manager = manager
        self.server, self.service, self.views = manager.server, manager.service, manager.views

    def capture(self, user, draft):
        evidence = capture_public_report(self.service, user.uuid, draft['kind'], draft['id'])
        if evidence.revision != draft['revision']:
            raise ForumError('forum-report-changed')
        return evidence

    def editor(self, user, draft):
        evidence = self.capture(user, draft)
        reason = label(user, report_reason_localization_key(draft['reason'])) if draft['reason'] else label(user, 'forum-report-choose-reason')
        rows = [item(user, 'forum-report-content', 'report_content', read_only=True,
                     title=evidence.title, body=excerpt(evidence.body)),
                item(user, 'forum-report-reason', 'reason', reason=reason),
                item(user, 'forum-report-details', 'details', details=excerpt(draft['details']) or label(user, 'forum-report-no-details')),
                item(user, 'report-submit', 'submit')]
        self.views.render(user, nav.REPORT, rows, title=label(user, 'forum-report-' + draft['kind']),
                          announcement=('forum-entry-simple', {'title': label(user, 'forum-report-' + draft['kind'])}),
                          forum_report=dict(draft))

    def reasons(self, user, draft):
        self.capture(user, draft)
        rows = [item(user, report_reason_localization_key(code), 'reason:' + code) for code in REPORT_REASON_CODES]
        self.views.render(user, nav.REPORT_REASON, rows, title=label(user, 'forum-report-choose-reason'),
                          announcement=('forum-entry-simple', {'title': label(user, 'forum-report-choose-reason')}),
                          forum_report=dict(draft))

    def confirm(self, user, draft):
        evidence = self.capture(user, draft)
        if draft['reason'] not in REPORT_REASON_CODES:
            raise ForumError('forum-report-choose-reason')
        show_confirmation_menu(user, nav.REPORT_CONFIRM, prompt_key='forum-report-confirm', buffer='system',
                               prompt_kwargs={'title': evidence.title,
                                              'reason': label(user, report_reason_localization_key(draft['reason']))})
        self.server._user_states[user.username] = {'menu': nav.REPORT_CONFIRM, 'forum_report': dict(draft)}

    def restore(self, user, state):
        if state['menu'] == nav.REPORT:
            self.editor(user, state['forum_report'])
        elif state['menu'] == nav.REPORT_REASON:
            self.reasons(user, state['forum_report'])
        else:
            return False
        return True

    def handle(self, user, selection, state):
        menu = state['menu']
        if (menu == nav.THREAD and selection == 'report_thread') or (menu == nav.POST and selection == 'report_post'):
            kind = 'thread' if menu == nav.THREAD else 'post'
            evidence = capture_public_report(self.service, user.uuid, kind, state['forum_topic' if kind == 'thread' else 'forum_post'])
            target = evidence.target
            self.server._nav_push(user, self.editor, {'kind': kind, 'id': target.id,
                                   'revision': target.revision, 'reason': '', 'details': ''})
            return True
        if menu not in {nav.REPORT, nav.REPORT_REASON, nav.REPORT_CONFIRM}:
            return False
        draft = state['forum_report']
        if menu == nav.REPORT:
            if selection == 'reason':
                self.server._nav_push(user, self.reasons, draft)
            elif selection == 'details':
                self.server.enter_input_state(user, nav.REPORT_DETAILS_INPUT, forum_report=dict(draft))
                self.show_input(user, draft['details'])
            elif selection == 'submit':
                self.server._nav_push(user, self.confirm, draft)
        elif menu == nav.REPORT_REASON and selection.startswith('reason:'):
            code = selection.removeprefix('reason:')
            if code in REPORT_REASON_CODES:
                state['_stack'][-1]['forum_report'] = {**draft, 'reason': code}
                self.server._nav_back(user)
        elif menu == nav.REPORT_CONFIRM:
            if selection == 'no':
                self.server._nav_back(user)
            elif selection == 'yes':
                try:
                    outcome = self.server.db.submit_moderation_report(
                        reporter_uuid=user.uuid, reporter_username=user.username,
                        forum_target=ReportTarget(draft['kind'], draft['id'], draft['revision']),
                        reason_code=draft['reason'], details=draft['details'])
                except ForumError:
                    raise
                except Exception:
                    logger.exception('Unable to persist public forum report')
                    user.speak_l('report-failed', buffer='system')
                    return True
                if outcome.outcome in {'created', 'duplicate'}:
                    # Remove confirmation and form together; refreshing the form
                    # could otherwise fail after a successful commit.
                    state['_stack'] = state.get('_stack', [])[:-1]
                    self.server._nav_back(user)
                    user.speak_l('forum-report-submitted' if outcome.outcome == 'created' else 'forum-report-duplicate', buffer='system')
                    if outcome.outcome == 'created':
                        report = self.server.db.get_moderation_report(outcome.report_id)
                        self.server._notify_new_moderation_report(report.id,
                            report.reported_username or label(user, 'forum-deleted-account'), reporter_username=user.username)
                else:
                    user.speak_l('forum-report-limit', buffer='system', minutes=max(1, (outcome.retry_after_seconds + 59) // 60))
        return True

    @staticmethod
    def show_input(user, value):
        user.show_editbox(nav.REPORT_DETAILS_INPUT, label(user, 'forum-report-details-prompt'), value,
                          multiline=True, max_length=MAX_REPORT_DETAILS_LENGTH)

    def handle_input(self, user, packet, state):
        if not packet.get('cancelled'):
            value = packet.get('text')
            try:
                self.service.account(user.uuid)
                if not isinstance(value, str) or len(value) > MAX_REPORT_DETAILS_LENGTH:
                    raise ForumError('forum-report-details-length', limit=MAX_REPORT_DETAILS_LENGTH)
                value = validate_text(value) if value.strip() else ''
            except ForumError as error:
                user.speak_l(error.key, buffer='system', **error.values)
                self.show_input(user, value[:MAX_REPORT_DETAILS_LENGTH] if isinstance(value, str) else '')
                return
            state['_parent_frame']['forum_report'] = {**state['forum_report'], 'details': value}
        user.remove_editbox(nav.REPORT_DETAILS_INPUT)
        self.server._restore_input_parent(user, state)
