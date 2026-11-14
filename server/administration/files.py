"""Shared accessible administration menus for upload policy and storage."""

from dataclasses import asdict
import logging
import os

from ..forum.file_settings import FilePolicy, check_storage
from ..forum.models import ForumError
from ..messages.localization import Localization
from ..ui.confirmation import show_confirmation_menu
from ..users.base import EscapeBehavior, MenuItem
from ..users.roles import DEVELOPER_TRUST_LEVEL

FILES_MENU = 'admin_files_menu'
LIMITS_MENU = 'admin_files_limits_menu'
STORAGE_MENU = 'admin_files_storage_menu'
STORAGE_CONFIRM = 'admin_files_storage_confirm'
LIMIT_INPUT = 'admin_files_limit_input'
MENU_IDS = {FILES_MENU, LIMITS_MENU, STORAGE_MENU, STORAGE_CONFIRM, LIMIT_INPUT}
logger = logging.getLogger(__name__)


class FileAdministration:
    def __init__(self, administration):
        self.administration = administration
        self.server = administration.server

    @property
    def settings(self):
        return self.server.forum_manager.service.files

    def allowed(self, user):
        try:
            if user.trust_level < DEVELOPER_TRUST_LEVEL:
                raise ForumError('dev-only-action')
            self.settings.require_developer(user.uuid)
            return True
        except ForumError as error:
            user.speak_l(error.key, buffer='system', **error.values)
            self.administration._return_to_admin_root(user)
            return False

    @staticmethod
    def text(user, key, **values):
        return Localization.get(user.locale, key, **values)

    def row(self, user, key, id, *, read_only=False, **values):
        return MenuItem(text=self.text(user, key, **values), id=id, read_only=read_only)

    def render(self, user, menu, rows, **state):
        rows.append(self.row(user, 'back', 'back'))
        user.show_menu(menu, rows, multiletter=True, escape_behavior=EscapeBehavior.SELECT_LAST)
        self.server.user_states[user.username] = {'menu': menu, **state}

    def transport_ready(self):
        media = self.server.forum_manager.media
        return media is not None and media.site is not None and not media._closing

    def show(self, user):
        if not self.allowed(user):
            return
        policy = self.settings.policy()
        status = 'listo' if self.transport_ready() else 'sin-servicio'
        rows = [self.row(user, 'admin-archivos-estado', 'status', read_only=True,
                         estado=self.text(user, 'admin-archivos-' + status)),
                self.row(user, 'admin-archivos-cargas', 'uploads_enabled',
                         estado=self.text(user, 'option-on' if policy.uploads_enabled else 'option-off')),
                self.row(user, 'admin-archivos-aprobacion', 'require_approval',
                         estado=self.text(user, 'option-on' if policy.require_approval else 'option-off')),
                self.row(user, 'admin-archivos-limites', 'limits'),
                self.row(user, 'admin-archivos-almacenamiento', 'storage')]
        if policy.backend != self.settings.active_backend:
            rows.insert(1, self.row(user, 'admin-archivos-reinicio-pendiente', 'pending', read_only=True))
        self.render(user, FILES_MENU, rows, expected_policy=asdict(policy))

    def limits(self, user):
        if not self.allowed(user):
            return
        policy = self.settings.policy()
        self.render(user, LIMITS_MENU, [
            self.row(user, 'admin-archivos-tamano', 'max_file_mib', limite=policy.max_file_mib),
            self.row(user, 'admin-archivos-cuota', 'pending_mib', limite=policy.pending_mib),
        ])

    def storage(self, user):
        if not self.allowed(user):
            return
        policy = self.settings.policy()
        rows = [self.row(user, 'admin-archivos-proveedor-activo', 'active', read_only=True,
                         proveedor=self.text(user, 'admin-archivos-' + self.settings.active_backend)),
                self.row(user, 'admin-archivos-proveedor-configurado', 'selected', read_only=True,
                         proveedor=self.text(user, 'admin-archivos-' + policy.backend)),
                self.row(user, 'admin-archivos-perfil-remoto', 'remote_status', read_only=True,
                         estado=self.text(user, 'admin-archivos-remoto-configurado' if os.environ.get('PLAYAURAL_FORUM_BUCKET')
                                          else 'admin-archivos-remoto-sin-configurar')),
                self.row(user, 'admin-archivos-local', 'local'),
                self.row(user, 'admin-archivos-s3', 's3'),
                self.row(user, 'admin-archivos-comprobar', 'probe')]
        if policy.backend != self.settings.active_backend:
            rows.insert(2, self.row(user, 'admin-archivos-reinicio-pendiente', 'pending', read_only=True))
        self.render(user, STORAGE_MENU, rows, expected_policy=asdict(policy))

    def confirm_storage(self, user, backend):
        if not self.allowed(user):
            return
        show_confirmation_menu(user, STORAGE_CONFIRM, prompt_key='admin-archivos-confirmar-proveedor', buffer='system',
                               prompt_kwargs={'proveedor': self.text(user, 'admin-archivos-' + backend)})
        self.server.user_states[user.username] = {'menu': STORAGE_CONFIRM, 'backend': backend,
                                                  'expected_policy': asdict(self.settings.policy())}

    def prompt_limit(self, user, value):
        user.show_editbox(LIMIT_INPUT, self.text(user, 'admin-archivos-introducir-limite'), value, max_length=3)

    def restore(self, user, frame):
        menu = frame['menu']
        if menu not in MENU_IDS:
            return False
        # Confirmations do not retain authority across reconnect/restoration.
        renderer = self.storage if menu in {STORAGE_MENU, STORAGE_CONFIRM} else self.limits if menu == LIMITS_MENU else self.show
        renderer(user)
        return True

    async def probe(self, user, backend):
        user.speak_l('admin-archivos-comprobando', buffer='system', history=False)
        try:
            await check_storage(self.server._forum_media_directory, backend)
        except Exception:
            logger.exception('Developer storage probe failed for backend %s', backend)
            raise ForumError('admin-archivos-comprobacion-fallida') from None
        # A demotion, ban or handover during the SDK request revokes authority.
        if self.server.users.get(user.username) is not user:
            raise ForumError('forum-error-account')
        self.settings.require_developer(user.uuid)

    async def handle(self, user, selection, menu, state):
        if not self.allowed(user):
            return
        if selection == 'back' or menu == STORAGE_CONFIRM and selection == 'no':
            self.server._nav_back(user)
            return
        maintenance = self.server.maintenance_manager
        if not maintenance.begin_tracked_work():
            user.speak_l('forum-error-media-maintenance', buffer='system')
            return
        try:
            policy = self.settings.policy()
            if (menu == FILES_MENU and selection in {'uploads_enabled', 'require_approval'}
                    or menu == STORAGE_MENU and selection in {'local', 's3', 'probe'}):
                if asdict(policy) != state.get('expected_policy'):
                    raise ForumError('admin-archivos-configuracion-cambiada')
            if menu == FILES_MENU:
                if selection == 'limits':
                    self.server._nav_push(user, self.limits)
                elif selection == 'storage':
                    self.server._nav_push(user, self.storage)
                elif selection in {'uploads_enabled', 'require_approval'}:
                    enabled = not getattr(policy, selection)
                    if selection == 'uploads_enabled' and enabled:
                        if not self.transport_ready() or policy.backend != self.settings.active_backend:
                            raise ForumError('admin-archivos-no-disponible')
                        await self.probe(user, policy.backend)
                        if self.server.user_states.get(user.username) is not state:
                            return
                    self.settings.update(user.uuid, expected=policy, **{selection: enabled})
                    user.speak_l('admin-archivos-guardado', buffer='system')
                    self.server._nav_refresh(user, self.show)
            elif menu == LIMITS_MENU and selection in {'max_file_mib', 'pending_mib'}:
                self.server.enter_input_state(user, LIMIT_INPUT, field=selection, expected_policy=asdict(policy))
                self.prompt_limit(user, str(getattr(policy, selection)))
            elif menu == STORAGE_MENU:
                if selection in {'local', 's3'}:
                    self.server._nav_push(user, self.confirm_storage, selection)
                elif selection == 'probe':
                    await self.probe(user, policy.backend)
                    if self.server.user_states.get(user.username) is not state:
                        return
                    user.speak_l('admin-archivos-comprobacion-correcta', buffer='system')
            elif menu == STORAGE_CONFIRM and selection == 'yes':
                expected = FilePolicy(**state['expected_policy']).validate()
                if policy != expected:
                    raise ForumError('admin-archivos-configuracion-cambiada')
                backend = state['backend']
                self.settings.check_backend_change(user.uuid, backend, expected=expected)
                await self.probe(user, backend)
                if self.server.user_states.get(user.username) is not state:
                    return
                self.settings.select_backend(user.uuid, backend, expected=expected)
                user.speak_l('admin-archivos-proveedor-guardado', buffer='system')
                self.server._nav_back(user)
        except ForumError as error:
            if self.server.users.get(user.username) is user:
                user.speak_l(error.key, buffer='system', **error.values)
        finally:
            maintenance.end_tracked_work()

    def input(self, user, packet, state):
        if not self.allowed(user):
            return
        if packet.get('input_id') != LIMIT_INPUT:
            return
        if not packet.get('cancelled'):
            try:
                value = packet.get('text')
                if not isinstance(value, str) or not value.isascii() or not value.isdecimal() or len(value) > 3:
                    raise ForumError('admin-archivos-limite-invalido')
                field = state.get('field')
                if field not in {'max_file_mib', 'pending_mib'}:
                    raise ForumError('admin-archivos-configuracion-invalida')
                self.settings.update(user.uuid, expected=FilePolicy(**state['expected_policy']), **{field: int(value)})
                user.speak_l('admin-archivos-guardado', buffer='system')
            except ForumError as error:
                user.speak_l(error.key, buffer='system', **error.values)
                self.prompt_limit(user, value[:3] if isinstance(value, str) else '')
                return
        user.remove_editbox(LIMIT_INPUT)
        self.server._restore_input_parent(user, state)
