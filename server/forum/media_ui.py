"""Explicit file picking, bounded draft ownership and shared media presentation."""

from dataclasses import asdict, replace

from . import navigation as nav
from .attachments import MAX_ATTACHMENTS
from .draft_state import update_draft
from .models import Draft, ForumError
from .media_processing import PICKER_EXTENSIONS
from .views import item, label


class MediaController:
    def __init__(self, manager):
        self.manager, self.server, self.service = manager, manager.server, manager.service

    @property
    def transport(self):
        return self.manager.media

    def connect(self, transport) -> None:
        transport.on_reserve = self.reserve
        transport.worker.on_complete = self.completed

    @staticmethod
    def find_draft(state: dict, *, token=None, attachment_id=None):
        for frame in [state, state.get('_parent_frame', {}), *reversed(state.get('_stack', []))]:
            draft = frame.get('forum_draft')
            if draft and (token is None or draft.get('token') == token) and (
                attachment_id is None or attachment_id in draft.get('attachment_ids', ())
            ):
                return Draft(**draft)
        raise ForumError('forum-error-media-draft')

    def choose(self, user, draft: Draft) -> None:
        self.service.account(user.uuid, writing=True)
        if self.transport is None:
            raise ForumError('forum-error-media-unavailable')
        if len(draft.attachment_ids) >= MAX_ATTACHMENTS:
            raise ForumError('forum-error-media-quota', limit=MAX_ATTACHMENTS)
        user.queue_protocol_packet({'type': 'forum_file_picker', 'draft_token': draft.token,
                                   'accepted_extensions': list(PICKER_EXTENSIONS),
                                   **self.transport.credentials(user), 'labels': self.labels(user)})

    def reserve(self, user, payload: dict) -> dict:
        token = payload.get('draft_token')
        if not isinstance(token, str):
            raise ForumError('forum-error-media-draft')
        state = self.server._user_states.get(user.username, {})
        draft = self.find_draft(state, token=token)
        if draft.kind == 'edit' or len(draft.attachment_ids) >= MAX_ATTACHMENTS:
            raise ForumError('forum-error-media-quota', limit=MAX_ATTACHMENTS)
        row = self.service.attachments.reserve(user.uuid, payload.get('name'), payload.get('size'), payload.get('description', ''),
                                               topic_id=draft.topic_id, private=draft.kind == 'private')
        draft = replace(draft, attachment_ids=(*draft.attachment_ids, row['id']))
        update_draft(state, draft)
        self.refresh_draft(user, draft, state)
        return row

    def refresh_draft(self, user, draft: Draft, state: dict) -> None:
        if state['menu'] == nav.COMPOSER:
            self.server._nav_refresh(user, self.manager.composer.show, draft)
        elif state['menu'] == nav.EXTRAS:
            self.server._nav_refresh(user, self.manager.polls.extras, draft)

    def completed(self, viewer: str, attachment_id: str, error_key: str | None) -> None:
        # The worker callback itself runs on the server loop, never in FFmpeg's
        # thread. A replacement session may retain the draft's confirmed intent.
        if not self.server.forum_enabled:
            return
        with self.transport.worker.database_work():
            account = self.service.repository.database.get_user_by_uuid(viewer)
            user = self.server._users.get(account.username) if account else None
            if user is None:
                return
            state = self.server._user_states.get(user.username, {})
            try:
                draft = self.find_draft(state, attachment_id=attachment_id)
            except ForumError:
                try:
                    self.service.attachments.discard(viewer, attachment_id)
                except ForumError:
                    pass
                return
            self.refresh_draft(user, draft, state)
            if state['menu'] == nav.ATTACHMENT and state.get('forum_attachment') == attachment_id:
                self.server._nav_refresh(user, self.attachment, draft, attachment_id)
            row = self.service.attachments._row(attachment_id)
            if error_key:
                user.speak_l('forum-media-prepared-error', name=row['name'], reason=label(user, error_key), buffer='system', history=False)
            else:
                user.speak_l('forum-media-prepared', name=row['name'], status=label(user, 'forum-media-approval-' + row['approval']),
                             buffer='system', history=False)

    def attachment(self, user, draft: Draft, attachment_id: str) -> None:
        if attachment_id not in draft.attachment_ids:
            raise ForumError('forum-error-missing')
        row = self.service.attachments._row(attachment_id)
        if row['owner_uuid'] != user.uuid or row['published']:
            raise ForumError('forum-error-missing')
        rows = []
        if row['description']:
            rows.append(item(user, 'forum-media-description-text', 'description_text', read_only=True, text=row['description']))
        if row['state'] == 'ready':
            rows.append(item(user, 'forum-media-open', 'open'))
        rows.extend([item(user, 'forum-media-describe', 'description'), item(user, 'forum-media-remove', 'remove')])
        self.manager.views.render(user, nav.ATTACHMENT, rows, title=row['name'],
                                  announcement=('forum-entry-attachment', {'name': row['name'], 'status': label(user, 'forum-media-' + row['state'])}),
                                  forum_draft=asdict(draft), forum_attachment=attachment_id, forum_topic=draft.topic_id)

    @staticmethod
    def labels(user) -> dict:
        return {key: label(user, 'forum-media-control-' + key) for key in (
            'play', 'pause', 'position', 'volume', 'speed', 'close', 'download', 'zoom_in', 'zoom_out',
            'fullscreen', 'uploading', 'processing', 'error', 'choose', 'description', 'saved', 'size_error',
            'captions', 'captions_on', 'captions_off', 'captions_error',
            'selected', 'file_filter', 'all_files',
        )}

    def open(self, user, attachment_id: str) -> None:
        if self.transport is None:
            raise ForumError('forum-error-media-unavailable')
        row = self.service.attachments.get(user.uuid, attachment_id)
        user.queue_protocol_packet({'type': 'forum_open_media', **self.transport.credentials(user),
                                   'attachment': {key: row[key] for key in (
                                       'id', 'name', 'description', 'kind', 'mime', 'size', 'duration', 'width', 'height')},
                                   'url': f"{self.transport.base_url}/files/{attachment_id}",
                                   'captions_url': f"{self.transport.base_url}/files/{attachment_id}/captions" if row['captions_key'] else '',
                                   'labels': self.labels(user)})

    def handle(self, user, selection: str, state: dict) -> bool:
        if state['menu'] == nav.ATTACHMENT:
            draft, attachment_id = Draft(**state['forum_draft']), state['forum_attachment']
            if selection == 'open':
                self.open(user, attachment_id)
            elif selection == 'description':
                row = self.service.attachments._row(attachment_id)
                self.server.enter_input_state(user, nav.MEDIA_DESCRIPTION_INPUT)
                self.show_input(user, row['description'])
            elif selection == 'remove':
                self.service.attachments.discard(user.uuid, attachment_id)
                update_draft(state, replace(draft, attachment_ids=tuple(key for key in draft.attachment_ids if key != attachment_id)))
                self.server._nav_back(user)
            return True
        if state['menu'] in {nav.COMPOSER, nav.POST, nav.CONTENTS} and selection.startswith('attachment:'):
            attachment_id = selection.removeprefix('attachment:')
            if state['menu'] == nav.COMPOSER:
                self.server._nav_push(user, self.attachment, Draft(**state['forum_draft']), attachment_id)
            else:
                post = self.service.post(user.uuid, state['forum_post'])
                if self.service.attachments.get(user.uuid, attachment_id)['post_id'] != post.id:
                    raise ForumError('forum-error-missing')
                self.open(user, attachment_id)
            return True
        if state['menu'] == nav.EXTRAS and selection == 'attachment':
            self.choose(user, Draft(**state['forum_draft']))
            return True
        return False

    @staticmethod
    def show_input(user, value: str) -> None:
        user.show_editbox(nav.MEDIA_DESCRIPTION_INPUT, label(user, 'forum-media-description-prompt'),
                          value, multiline=True, max_length=1000)

    def handle_input(self, user, packet: dict, state: dict) -> None:
        if not packet.get('cancelled'):
            try:
                text = packet.get('text')
                if not isinstance(text, str):
                    raise ForumError('forum-error-media-description')
                self.service.attachments.describe(user.uuid, state['forum_attachment'], text)
            except ForumError as error:
                user.speak_l(error.key, buffer='system', **error.values)
                self.show_input(user, text[:1000] if isinstance(text, str) else '')
                return
        user.remove_editbox(nav.MEDIA_DESCRIPTION_INPUT)
        self.server._restore_input_parent(user, state)
