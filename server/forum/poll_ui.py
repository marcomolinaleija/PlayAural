"""Optional poll setup and a previewable ballot using the shared menu protocol."""

from dataclasses import asdict, replace

from ..ui.confirmation import show_confirmation_menu
from ..users.base import MenuItem
from . import navigation as nav
from .draft_state import update_draft
from .models import Draft, ForumError
from .polls import PollConfig, validate_config
from .views import attachment_action, item, label


class PollController:
    def __init__(self, manager):
        self.manager = manager
        self.server, self.service, self.views = manager.server, manager.service, manager.views

    def extras(self, user, draft: Draft) -> None:
        rows = [item(user, 'forum-poll-change' if draft.poll else 'forum-poll-add', 'poll')]
        if self.manager.media is not None:
            attachments = [self.service.attachments._row(key) for key in draft.attachment_ids]
            rows.insert(0, attachment_action(user, 'forum-media-add', 'attachment', attachments))
        self.views.render(user, nav.EXTRAS, rows, title=label(user, 'forum-add-more'),
                          announcement=('forum-entry-simple', {'title': label(user, 'forum-add-more')}),
                          forum_draft=asdict(draft), forum_topic=draft.topic_id)

    def editor(self, user, draft: Draft) -> None:
        config = draft.poll or asdict(PollConfig('', ()))
        rows = []
        if config['question']:
            rows.append(MenuItem(text=config['question'], id='question_preview', read_only=True))
        rows.extend(MenuItem(text=option, id=f'option_preview:{index}', read_only=True)
                    for index, option in enumerate(config['options']))
        rows.extend([item(user, 'forum-poll-question', 'question'), item(user, 'forum-poll-options', 'options'),
                     item(user, 'forum-poll-multiple', 'multiple', value=label(user, 'forum-yes' if config['multiple'] else 'forum-no')),
                     item(user, 'forum-poll-change-vote', 'change_vote', value=label(user, 'forum-yes' if config['change_vote'] else 'forum-no')),
                     item(user, 'forum-poll-results', 'results', value=label(user, f"forum-poll-results-{config['results']}")),
                     item(user, 'forum-poll-deadline', 'deadline', value=label(user, f"forum-poll-days-{config.get('days', 0)}"))])
        if draft.poll:
            rows.append(item(user, 'forum-poll-remove', 'remove'))
        self.views.render(user, nav.POLL_EDITOR, rows, title=label(user, 'forum-poll-heading'),
                          announcement=('forum-entry-simple', {'title': label(user, 'forum-poll-heading')}),
                          forum_draft=asdict(draft), forum_poll_config=config, forum_topic=draft.topic_id)

    def ballot(self, user, post_id: int, choices=None) -> None:
        poll = self.service.polls.get(user.uuid, post_id)
        topic = self.service.topic(user.uuid, self.service.post(user.uuid, post_id).topic_id)
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
        post = self.service.post(user.uuid, post_id)
        if not closed and (post.author_uuid == user.uuid or self.service.can_moderate(user.uuid, post.topic_id)):
            rows.append(item(user, 'forum-poll-close', 'close'))
        rows.append(item(user, 'menu-page-refresh', 'refresh'))
        self.views.render(user, nav.POLL, rows, title=poll['question'],
                          announcement=('forum-entry-poll', {'question': poll['question'], 'mode': label(user,
                              'forum-poll-closed' if closed else 'forum-poll-many' if poll['multiple'] else 'forum-poll-one')}),
                          forum_post=post_id, forum_topic=post.topic_id, forum_choices=choices)

    def restore(self, user, state) -> bool:
        menu = state['menu']
        if menu == nav.EXTRAS:
            self.extras(user, Draft(**state['forum_draft']))
        elif menu == nav.POLL_EDITOR:
            self.editor(user, Draft(**state['forum_draft']))
        elif menu == nav.POLL:
            self.ballot(user, state['forum_post'], state.get('forum_choices'))
        else:
            return False
        return True

    def handle(self, user, selection: str, state: dict) -> bool:
        menu = state['menu']
        push, refresh = self.server._nav_push, self.server._nav_refresh
        if menu == nav.EXTRAS:
            if selection == 'poll':
                push(user, self.editor, Draft(**state['forum_draft']))
        elif menu == nav.POLL_EDITOR:
            draft = Draft(**state['forum_draft'])
            config = dict(state['forum_poll_config'])
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
            refresh(user, self.editor, draft)
        elif menu == nav.POLL:
            post_id = state['forum_post']
            poll = self.service.polls.get(user.uuid, post_id)
            if selection.startswith('choice:') and not poll['closed']:
                choice = int(selection.removeprefix('choice:'))
                choices = set(state['forum_choices']) if poll['multiple'] else set()
                if choice in choices:
                    choices.remove(choice)
                else:
                    choices.add(choice)
                refresh(user, self.ballot, post_id, sorted(choices))
            elif selection == 'submit':
                self.service.polls.vote(user.uuid, post_id, state['forum_choices'])
                user.speak_l('forum-poll-voted', buffer='system', history=False)
                refresh(user, self.ballot, post_id)
            elif selection == 'refresh':
                refresh(user, self.ballot, post_id)
            elif selection == 'close':
                push(user, self.confirm_close, post_id)
        elif menu == nav.POLL_CLOSE:
            if selection == 'yes':
                self.service.polls.close(user.uuid, state['forum_post'])
                self.server._nav_back(user)
            elif selection == 'no':
                self.server._nav_back(user)
        else:
            return False
        return True

    def confirm_close(self, user, post_id: int) -> None:
        poll = self.service.polls.get(user.uuid, post_id)
        show_confirmation_menu(user, nav.POLL_CLOSE, prompt_key='forum-poll-close-prompt',
                               prompt_kwargs={'question': poll['question']}, buffer='system')
        self.server._user_states[user.username] = {'menu': nav.POLL_CLOSE, 'forum_post': post_id}

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
