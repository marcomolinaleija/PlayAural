"""Optional poll setup and a previewable ballot using the shared menu protocol."""

from dataclasses import asdict, replace
from datetime import datetime, timezone

from ..messages.localization import Localization
from ..ui.confirmation import show_confirmation_menu
from ..users.base import MenuItem
from . import navigation as nav
from .draft_state import update_draft
from .models import Draft, ForumError
from .polls import PollConfig, validate_config
from .views import attachment_action, item, label
from .text import excerpt


class PollController:
    def __init__(self, manager):
        self.manager = manager
        self.server, self.service, self.views = manager.server, manager.service, manager.views

    def extras(self, user, draft: Draft) -> None:
        rows = [item(user, 'forum-poll-change' if draft.poll else 'forum-poll-add', 'poll')]
        policy = self.service.files.policy()
        if self.manager.media is not None and policy.uploads_enabled and policy.backend == self.service.files.active_backend:
            attachments = [self.service.attachments._row(key) for key in draft.attachment_ids]
            rows.insert(0, attachment_action(user, 'forum-media-add', 'attachment', attachments))
        self.views.render(user, nav.EXTRAS, rows, title=label(user, 'forum-add-more'),
                          announcement=('forum-entry-simple', {'title': label(user, 'forum-add-more')}),
                          forum_draft=asdict(draft), forum_topic=draft.topic_id)

    def editor(self, user, draft: Draft, *, existing=False, revision=None, original=None) -> None:
        config = draft.poll or asdict(PollConfig('', ()))
        if existing and original is None:
            original = draft.poll
        deadline = label(user, f"forum-poll-days-{config.get('days', 0)}")
        if config.get('closes_at') and not config.get('days'):
            deadline = Localization.format_utc_datetime(user.locale, datetime.fromtimestamp(config['closes_at'], timezone.utc))
        rows = [item(user, 'forum-poll-question-value', 'question', value=config['question'] or label(user, 'forum-not-written')),
                item(user, 'forum-poll-options-value', 'options',
                     value=excerpt('; '.join(config['options'])) if config['options'] else label(user, 'forum-not-written'))]
        rows.extend([
                     item(user, 'forum-poll-multiple', 'multiple', value=label(user, 'forum-yes' if config['multiple'] else 'forum-no')),
                     item(user, 'forum-poll-change-vote', 'change_vote', value=label(user, 'forum-yes' if config['change_vote'] else 'forum-no')),
                     item(user, 'forum-poll-results', 'results', value=label(user, f"forum-poll-results-{config['results']}")),
                     item(user, 'forum-poll-deadline', 'deadline', value=deadline)])
        if draft.kind == 'thread_poll':
            rows.append(item(user, 'forum-thread-poll-save' if existing else 'forum-thread-poll-create', 'save_thread_poll'))
        elif draft.poll:
            rows.append(item(user, 'forum-poll-remove', 'remove'))
        self.views.render(user, nav.POLL_EDITOR, rows, title=label(user, 'forum-poll-heading'),
                          announcement=('forum-entry-simple', {'title': label(user, 'forum-poll-heading')}),
                          forum_draft=asdict(draft), forum_poll_config=config, forum_topic=draft.topic_id,
                          forum_poll_existing=existing, forum_poll_revision=revision, forum_poll_original=original)

    def thread_editor(self, user, topic_id, *, existing=False):
        polls = self.service.thread_polls
        if existing:
            poll = polls.get(user.uuid, topic_id)
            if not polls.can_edit(user.uuid, topic_id):
                raise ForumError('forum-error-poll-started' if poll['started'] else 'forum-error-edit-permission')
            config = {key: poll[key] for key in ('question', 'multiple', 'change_vote', 'results', 'closes_at')}
            config['multiple'], config['change_vote'] = bool(config['multiple']), bool(config['change_vote'])
            config['options'] = tuple(option['label'] for option in poll['options'])
            revision = poll['revision']
        else:
            if not polls.can_create(user.uuid, topic_id):
                raise ForumError('forum-error-edit-permission')
            config, revision = None, None
        self.editor(user, Draft('thread_poll', topic_id=topic_id, poll=config), existing=existing, revision=revision)

    def ballot(self, user, post_id: int, choices=None, *, scope='post') -> None:
        polls = self.service.thread_polls if scope == 'thread' else self.service.polls
        poll = polls.get(user.uuid, post_id)
        topic = self.service.topic(user.uuid, poll['topic_id'])
        choices = tuple(poll['selected'] if choices is None else choices)
        closed = poll['closed'] or topic.closed
        rows = []
        for option in poll['options']:
            text = label(user, 'forum-poll-option', option=option['label'],
                         selected=label(user, 'forum-poll-selected') if option['id'] in choices else '')
            if poll['results_visible']:
                text = label(user, 'forum-poll-option-result', option=text, votes=option['votes'])
            rows.append(MenuItem(text=text, id=f"choice:{option['id']}", read_only=closed or bool(poll['selected'] and not poll['change_vote'])))
        if poll['results_visible']:
            rows.append(item(user, 'forum-poll-voters', 'voters', read_only=True, count=poll['voters']))
        if not closed and (not poll['selected'] or poll['change_vote']):
            rows.append(item(user, 'forum-poll-submit', 'submit'))
        if scope == 'thread' and polls.can_edit(user.uuid, post_id):
            rows.append(item(user, 'forum-thread-poll-edit', 'edit'))
        if not closed and (poll['author_uuid'] == user.uuid or self.service.can_moderate(user.uuid, topic.id)):
            rows.append(item(user, 'forum-poll-close', 'close'))
        if polls.can_delete(user.uuid, post_id):
            rows.append(item(user, 'forum-poll-delete', 'delete'))
        rows.append(item(user, 'menu-page-refresh', 'refresh'))
        self.views.render(user, nav.POLL, rows, title=poll['question'],
                          announcement=('forum-entry-poll', {'question': poll['question'], 'mode': label(user,
                              'forum-poll-closed' if closed else 'forum-poll-many' if poll['multiple'] else 'forum-poll-one')}),
                          forum_post=post_id if scope == 'post' else 0, forum_poll_id=post_id,
                          forum_poll_scope=scope, forum_topic=topic.id, forum_choices=choices)

    def restore(self, user, state) -> bool:
        menu = state['menu']
        if menu == nav.EXTRAS:
            self.extras(user, Draft(**state['forum_draft']))
        elif menu == nav.POLL_EDITOR:
            self.editor(user, Draft(**state['forum_draft']), existing=state.get('forum_poll_existing', False),
                        revision=state.get('forum_poll_revision'), original=state.get('forum_poll_original'))
        elif menu == nav.POLL:
            self.ballot(user, state['forum_poll_id'], state.get('forum_choices'), scope=state['forum_poll_scope'])
        else:
            return False
        return True

    def handle(self, user, selection: str, state: dict) -> bool:
        menu = state['menu']
        push, refresh = self.server._nav_push, self.server._nav_refresh
        if menu == nav.THREAD and selection in {'thread_poll', 'create_thread_poll'}:
            if selection == 'thread_poll':
                push(user, self.ballot, state['forum_topic'], scope='thread')
            else:
                push(user, self.thread_editor, state['forum_topic'])
        elif menu == nav.COMPOSER and selection == 'poll':
            push(user, self.editor, Draft(**state['forum_draft']))
        elif menu == nav.CONTENTS and selection == 'poll':
            push(user, self.ballot, state['forum_post'])
        elif menu == nav.EXTRAS:
            if selection == 'poll':
                push(user, self.editor, Draft(**state['forum_draft']))
        elif menu == nav.POLL_EDITOR:
            draft = Draft(**state['forum_draft'])
            config = dict(state['forum_poll_config'])
            if selection == 'save_thread_poll' and draft.kind == 'thread_poll':
                poll = draft_poll(draft)
                if state['forum_poll_existing']:
                    self.service.thread_polls.edit(user.uuid, draft.topic_id, poll, revision=state['forum_poll_revision'])
                else:
                    self.service.thread_polls.create(user.uuid, draft.topic_id, poll)
                if state.get('_stack'):
                    state['_stack'][-1]['forum_choices'] = ()
                    state['_stack'][-1]['_restore_focus_id'] = 'thread_poll'
                self.server._nav_back(user)
                user.speak_l('forum-thread-poll-saved', buffer='system')
                return True
            if selection in {'question', 'options'}:
                input_id = nav.POLL_QUESTION_INPUT if selection == 'question' else nav.POLL_OPTIONS_INPUT
                self.server.enter_input_state(user, input_id)
                self.show_input(user, input_id, config['question'] if selection == 'question' else '\n'.join(config['options']))
                return True
            if selection in {'multiple', 'change_vote'}:
                config[selection] = not config[selection]
            elif selection == 'results':
                modes = ('after_vote', 'after_close', 'always')
                config['results'] = modes[(modes.index(config['results']) + 1) % len(modes)]
            elif selection == 'deadline':
                days = (0, 1, 3, 7, 30)
                config['days'] = days[(days.index(config.get('days', 0)) + 1) % len(days)]
                config['closes_at'] = int(self.service.clock()) + config['days'] * 86400 if config['days'] else None
            elif selection == 'remove':
                draft = replace(draft, poll=None)
                update_draft(state, draft)
                self.server._nav_back(user)
                return True
            else:
                return True
            draft = replace(draft, poll=config)
            update_draft(state, draft)
            refresh(user, self.editor, draft, existing=state['forum_poll_existing'], revision=state['forum_poll_revision'],
                    original=state['forum_poll_original'])
        elif menu == nav.POLL:
            post_id, scope = state['forum_poll_id'], state['forum_poll_scope']
            polls = self.service.thread_polls if scope == 'thread' else self.service.polls
            poll = polls.get(user.uuid, post_id)
            if selection.startswith('choice:') and not poll['closed']:
                choice = int(selection.removeprefix('choice:'))
                choices = set(state['forum_choices']) if poll['multiple'] else set()
                if choice in choices:
                    choices.remove(choice)
                else:
                    choices.add(choice)
                refresh(user, self.ballot, post_id, sorted(choices), scope=scope)
            elif selection == 'submit':
                polls.vote(user.uuid, post_id, state['forum_choices'])
                user.speak_l('forum-poll-voted', buffer='system', history=False)
                refresh(user, self.ballot, post_id, scope=scope)
            elif selection == 'refresh':
                refresh(user, self.ballot, post_id, scope=scope)
            elif selection == 'edit' and scope == 'thread':
                push(user, self.thread_editor, post_id, existing=True)
            elif selection == 'close':
                push(user, self.confirm_close, post_id, scope=scope)
            elif selection == 'delete':
                push(user, self.confirm_delete, post_id, scope=scope)
        elif menu == nav.POLL_DELETE:
            if selection == 'yes':
                polls = self.service.thread_polls if state['forum_poll_scope'] == 'thread' else self.service.polls
                polls.delete(user.uuid, state['forum_poll_id'], expected_options=state['forum_poll_options'])
                # Skip the ballot that no longer exists. Restore the actual
                # thread or post actions, retaining earlier drafts/game frames.
                stack = state.get('_stack', [])
                if stack and stack[-1].get('menu') == nav.POLL:
                    stack.pop()
                self.server._nav_back(user)
                user.speak_l('forum-poll-deleted', buffer='system')
            elif selection == 'no':
                self.server._nav_back(user)
        elif menu == nav.POLL_CLOSE:
            if selection == 'yes':
                polls = self.service.thread_polls if state['forum_poll_scope'] == 'thread' else self.service.polls
                polls.close(user.uuid, state['forum_poll_id'])
                self.server._nav_back(user)
            elif selection == 'no':
                self.server._nav_back(user)
        else:
            return False
        return True

    def confirm_close(self, user, post_id: int, *, scope='post') -> None:
        polls = self.service.thread_polls if scope == 'thread' else self.service.polls
        poll = polls.get(user.uuid, post_id)
        show_confirmation_menu(user, nav.POLL_CLOSE, prompt_key='forum-poll-close-prompt',
                               prompt_kwargs={'question': poll['question']}, buffer='system')
        self.server._user_states[user.username] = {'menu': nav.POLL_CLOSE, 'forum_post': post_id if scope == 'post' else 0,
                                                  'forum_poll_id': post_id, 'forum_poll_scope': scope}

    def confirm_delete(self, user, target_id: int, *, scope='post') -> None:
        polls = self.service.thread_polls if scope == 'thread' else self.service.polls
        poll = polls.get(user.uuid, target_id)
        if not polls.can_delete(user.uuid, target_id):
            raise ForumError('forum-error-poll-delete-permission')
        show_confirmation_menu(user, nav.POLL_DELETE, prompt_key='forum-poll-delete-prompt',
                               prompt_kwargs={'question': poll['question']}, buffer='system')
        self.server._user_states[user.username] = {
            'menu': nav.POLL_DELETE, 'forum_poll_id': target_id, 'forum_poll_scope': scope,
            'forum_post': target_id if scope == 'post' else 0, 'forum_topic': poll['topic_id'],
            'forum_poll_options': tuple(option['id'] for option in poll['options']),
        }

    @staticmethod
    def show_input(user, input_id: str, value: str) -> None:
        question = input_id == nav.POLL_QUESTION_INPUT
        user.show_editbox(input_id, label(user, 'forum-poll-question-prompt' if question else 'forum-poll-options-prompt'),
                          value, multiline=not question, max_length=240 if question else 1610)

    def handle_input(self, user, packet: dict, state: dict) -> None:
        input_id = state['menu']
        if packet.get('cancelled'):
            user.remove_editbox(input_id)
            self.server._restore_input_parent(user, state)
            return
        config = dict(state['forum_poll_config'])
        text = packet.get('text')
        try:
            if not isinstance(text, str):
                raise ForumError('forum-error-poll-config')
            if input_id == nav.POLL_QUESTION_INPUT:
                config['question'] = text
            else:
                config['options'] = tuple(text.splitlines())
            # Validate this field now; the other may not be filled in yet.
            check = {key: value for key, value in config.items() if key != 'days'}
            check['question'] = check['question'] or '…'
            check['options'] = check['options'] or ('1', '2')
            validate_config(PollConfig(**check), int(self.service.clock()))
        except ForumError as error:
            user.speak_l(error.key, buffer='system', **error.values)
            self.show_input(user, input_id, text[:1610] if isinstance(text, str) else '')
            return
        draft = replace(Draft(**state['forum_draft']), poll=config)
        update_draft(state, draft)
        user.remove_editbox(input_id)
        self.server._restore_input_parent(user, state)


def draft_poll(draft: Draft):
    if draft.poll is None:
        return None
    return PollConfig(**{key: value for key, value in draft.poll.items() if key != 'days'})
