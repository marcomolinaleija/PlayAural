"""Administration functionality for the PlayAural server."""

import functools
import logging
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from ..copy_protocol import CopyDirective, UNSAFE_BIDI_CONTROLS
from ..users.network_user import NetworkUser
from ..users.base import EscapeBehavior, MenuItem
from ..ui.confirmation import ConfirmationChoice, show_confirmation_menu
from ..users.identity import username_key
from ..users.roles import (
    ADMIN_TRUST_LEVEL,
    DEVELOPER_TRUST_LEVEL,
    USER_TRUST_LEVEL,
)
from ..messages.localization import DEFAULT_LOCALE, Localization
from ..messages.localized_content import (
    encode_localized_custom_text,
    localized_penalty_reason_for_locale,
    localized_text_for_locale,
    normalize_localized_text,
    normalize_localized_value,
)
from ..persistence.database import (
    BanRecord,
    DatabaseStorageAnalysis,
    GlobalChatMessageRecord,
    ModerationReportRecord,
    MuteRecord,
)
from ..chat_channels import GLOBAL_CHAT_CHANNELS
from ..moderation.chat_history import (
    GLOBAL_CHAT_HISTORY_PERIODS,
    GlobalChatHistoryFilter,
)
from ..moderation.reports import (
    CLOSED_REPORT_STATUSES,
    MODERATION_CONTEXT_PAGE_SIZE,
    MODERATION_REVIEW_PAGE_SIZE,
    REPORT_CONTEXT_CODES,
    REPORT_CONTEXT_GLOBAL,
    REPORT_CONTEXT_MESSAGES_AFTER,
    REPORT_CONTEXT_MESSAGES_BEFORE,
    REPORT_ORIGIN_AUTOMATED_SPAM,
    REPORT_ORIGIN_MANUAL,
    REPORT_STATUS_SET,
    AutomatedSpamEvidence,
    report_reason_localization_key,
)
from ..core.power import (
    POWER_MAX_CUSTOM_DELAY_MINUTES,
    PowerAction,
    ServerPowerManager,
)
from ..core.maintenance import (
    DatabaseMaintenanceBusyError,
    DatabaseMaintenanceUnavailableError,
)
from ..core.sound_events import AVAILABLE_SOUND_ASSETS, SOUND_EVENTS
from ..menu_pagination import (
    DEFAULT_MENU_PAGE_SIZE,
    MENU_PAGE_IDS,
    PaginatedMenuPage,
    announce_page_refresh,
    clamp_page,
    is_page_navigation,
    is_page_refresh,
    page_for_selection,
    pagination_menu_items,
    paginate_sequence,
)
from ..games.infiltrado.words import InfiltradoWordManager

if TYPE_CHECKING:
    from ..core.server import Server

ADMIN_TARGET_PAGE_SIZE = DEFAULT_MENU_PAGE_SIZE
ADMIN_TARGET_SEARCH_INPUT = "admin_target_search_input"
ADMIN_LOCALIZED_TEXT_MENU = "admin_localized_text_menu"
ADMIN_LOCALIZED_TEXT_INPUT = "admin_localized_text_input"
ADMIN_SOUND_EVENTS_MENU = "admin_sound_events_menu"
ADMIN_SOUND_PICKER_MENU = "admin_sound_picker_menu"
ADMIN_INFILTRADO_WORDS_MENU = "admin_infiltrado_words_menu"
ADMIN_INFILTRADO_PAIRS_LIST_MENU = "admin_infiltrado_pairs_list_menu"
ADMIN_INFILTRADO_PAIR_DETAIL_MENU = "admin_infiltrado_pair_detail_menu"
ADMIN_INFILTRADO_CATEGORIES_MENU = "admin_infiltrado_categories_menu"
ADMIN_INFILTRADO_CATEGORY_DETAIL_MENU = "admin_infiltrado_category_detail_menu"
ADMIN_INFILTRADO_SELECT_CATEGORY_MENU = "admin_infiltrado_select_category_menu"
ADMIN_INFILTRADO_DELETE_CATEGORY_CONFIRM_MENU = "admin_infiltrado_delete_category_confirm_menu"
ADMIN_INFILTRADO_ADD_WORD1_INPUT = "admin_infiltrado_add_word1_input"
ADMIN_INFILTRADO_ADD_WORD2_INPUT = "admin_infiltrado_add_word2_input"
ADMIN_INFILTRADO_EDIT_WORD1_INPUT = "admin_infiltrado_edit_word1_input"
ADMIN_INFILTRADO_EDIT_WORD2_INPUT = "admin_infiltrado_edit_word2_input"
ADMIN_INFILTRADO_ADD_CATEGORY_INPUT = "admin_infiltrado_add_category_input"
ADMIN_INFILTRADO_RENAME_CATEGORY_INPUT = "admin_infiltrado_rename_category_input"
ADMIN_USERS_MENU = "admin_users_menu"
ADMIN_SANCTIONS_MENU = "admin_sanctions_menu"
ADMIN_SERVER_CONTENT_MENU = "admin_server_content_menu"
ADMIN_SYSTEM_MENU = "admin_system_menu"

ADMIN_SUBMENU_ROOT_ITEM_MAP = {
    "account_approval": "admin_users",
    "toggle_account_approval": "admin_users",
    "pending_nick_changes": "admin_users",
    "promote_admin": "admin_users",
    "demote_admin": "admin_users",
    "grant_coins": "admin_users",
    "moderation": "admin_moderation",
    "kick_user": "admin_moderation",
    "mute_user": "admin_moderation",
    "unmute_user": "admin_moderation",
    "ban_user": "admin_moderation",
    "unban_user": "admin_moderation",
    "broadcast_announcement": "admin_server_content",
    "manage_motd": "admin_server_content",
    "sound_settings": "admin_server_content",
    "manage_infiltrado_words": "admin_server_content",
    "server_power": "admin_system",
    "database_management": "admin_system",
    "smtp_settings": "admin_system",
}
ADMIN_NICK_CHANGES_MENU = "admin_nick_changes_menu"
ADMIN_NICK_CHANGE_ACTIONS_MENU = "admin_nick_change_actions_menu"
ADMIN_NICK_REJECT_REASON_INPUT = "admin_nick_reject_reason_input"
ADMIN_NICK_REJECT_REFUND_MENU = "admin_nick_reject_refund_menu"
ADMIN_MODERATION_MENU = "admin_moderation_menu"
ADMIN_MODERATION_REPORTS_MENU = "admin_moderation_reports_menu"
ADMIN_MODERATION_REPORT_DETAIL_MENU = "admin_moderation_report_detail_menu"
ADMIN_MODERATION_CONTEXT_MENU = "admin_moderation_context_menu"
ADMIN_MODERATION_SENDER_RESULTS_MENU = "admin_moderation_sender_results_menu"
ADMIN_MODERATION_HISTORY_MENU = "admin_moderation_history_menu"
ADMIN_MODERATION_MESSAGES_MENU = "admin_moderation_messages_menu"
ADMIN_MODERATION_MESSAGE_LANGUAGE_MENU = "admin_moderation_message_language_menu"
ADMIN_MODERATION_MESSAGE_PERIOD_MENU = "admin_moderation_message_period_menu"
ADMIN_MODERATION_CLEAR_CONFIRM_MENU = "admin_moderation_clear_confirm_menu"
ADMIN_MODERATION_HISTORY_INPUT = "admin_moderation_history_input"
ADMIN_DATABASE_MENU = "admin_database_menu"
ADMIN_DATABASE_BACKUP_CONFIRM_MENU = "admin_database_backup_confirm_menu"
ADMIN_DATABASE_STORAGE_ANALYSIS_MENU = "admin_database_storage_analysis_menu"
ADMIN_DATABASE_STORAGE_CLEANUP_CONFIRM_MENU = (
    "admin_database_storage_cleanup_confirm_menu"
)
ADMIN_DATABASE_COMPACT_CONFIRM_MENU = "admin_database_compact_confirm_menu"
DATABASE_STORAGE_SIZE_UNITS = (
    ("gib", 1024**3),
    ("mib", 1024**2),
    ("kib", 1024),
)
GRANT_COINS_MENU = "grant_coins_menu"
GRANT_COINS_AMOUNT_MENU = "grant_coins_amount_menu"
GRANT_COINS_INPUT = "grant_coins_input"
GRANT_COINS_PRESET_AMOUNTS = (100, 500, 1000, 5000, 10000, 50000)



def _localized_database_size(locale: str, size_bytes: int) -> str:
    """Render a non-negative byte count in a compact locale-aware unit."""
    safe_size = max(0, int(size_bytes))
    for unit, divisor in DATABASE_STORAGE_SIZE_UNITS:
        if safe_size >= divisor:
            return Localization.get(
                locale,
                f"admin-database-size-{unit}",
                value=safe_size / divisor,
            )
    return Localization.get(
        locale,
        "admin-database-size-bytes",
        value=safe_size,
    )


@dataclass(frozen=True)
class AdminLocalizedTextSpec:
    """Presentation and validation rules for one localized admin workflow."""

    subject_key: str
    submit_key: str
    multiline: bool
    max_length: int
    required_trust_level: int = ADMIN_TRUST_LEVEL


ADMIN_LOCALIZED_TEXT_SPECS = {
    "motd": AdminLocalizedTextSpec(
        subject_key="admin-localized-text-subject-motd",
        submit_key="admin-localized-text-publish-motd",
        multiline=True,
        max_length=4000,
    ),
    "power": AdminLocalizedTextSpec(
        subject_key="admin-localized-text-subject-power",
        submit_key="admin-localized-text-continue",
        multiline=False,
        max_length=500,
        required_trust_level=DEVELOPER_TRUST_LEVEL,
    ),
    "ban": AdminLocalizedTextSpec(
        subject_key="admin-localized-text-subject-ban",
        submit_key="admin-localized-text-apply-ban",
        multiline=False,
        max_length=200,
    ),
    "mute": AdminLocalizedTextSpec(
        subject_key="admin-localized-text-subject-mute",
        submit_key="admin-localized-text-apply-mute",
        multiline=False,
        max_length=200,
    ),
}

ADMIN_MENU_IDS = {
    "admin_menu",
    ADMIN_USERS_MENU,
    ADMIN_SANCTIONS_MENU,
    ADMIN_SERVER_CONTENT_MENU,
    ADMIN_SYSTEM_MENU,
    ADMIN_MODERATION_MENU,
    ADMIN_MODERATION_REPORTS_MENU,
    ADMIN_MODERATION_REPORT_DETAIL_MENU,
    ADMIN_MODERATION_CONTEXT_MENU,
    ADMIN_MODERATION_SENDER_RESULTS_MENU,
    ADMIN_MODERATION_HISTORY_MENU,
    ADMIN_MODERATION_MESSAGES_MENU,
    ADMIN_MODERATION_MESSAGE_LANGUAGE_MENU,
    ADMIN_MODERATION_MESSAGE_PERIOD_MENU,
    ADMIN_MODERATION_CLEAR_CONFIRM_MENU,
    ADMIN_DATABASE_MENU,
    ADMIN_DATABASE_BACKUP_CONFIRM_MENU,
    ADMIN_DATABASE_STORAGE_ANALYSIS_MENU,
    ADMIN_DATABASE_STORAGE_CLEANUP_CONFIRM_MENU,
    ADMIN_DATABASE_COMPACT_CONFIRM_MENU,
    "account_approval_menu",
    "pending_user_actions_menu",
    "promote_admin_menu",
    "demote_admin_menu",
    "promote_confirm_menu",
    "demote_confirm_menu",
    "kick_menu",
    "kick_confirm_menu",
    "broadcast_choice_menu",
    "ban_menu",
    "ban_duration_menu",
    "ban_reason_menu",
    "unban_menu",
    "mute_menu",
    "mute_duration_menu",
    "mute_reason_menu",
    "unmute_menu",
    "manage_motd_menu",
    "view_motd_menu",
    "server_power_menu",
    "server_power_delay_menu",
    "server_power_reason_menu",
    "server_power_confirm_menu",
    ADMIN_LOCALIZED_TEXT_MENU,
    ADMIN_SOUND_EVENTS_MENU,
    ADMIN_SOUND_PICKER_MENU,
    "smtp_settings_menu",
    "smtp_encryption_menu",
    "smtp_setting_input",
    "admin_broadcast_input",
    ADMIN_LOCALIZED_TEXT_INPUT,
    "server_power_custom_delay_input",
    ADMIN_TARGET_SEARCH_INPUT,
    ADMIN_MODERATION_HISTORY_INPUT,
    ADMIN_INFILTRADO_WORDS_MENU,
    ADMIN_INFILTRADO_PAIRS_LIST_MENU,
    ADMIN_INFILTRADO_PAIR_DETAIL_MENU,
    ADMIN_INFILTRADO_CATEGORIES_MENU,
    ADMIN_INFILTRADO_CATEGORY_DETAIL_MENU,
    ADMIN_INFILTRADO_SELECT_CATEGORY_MENU,
    ADMIN_INFILTRADO_DELETE_CATEGORY_CONFIRM_MENU,
    ADMIN_INFILTRADO_ADD_WORD1_INPUT,
    ADMIN_INFILTRADO_ADD_WORD2_INPUT,
    ADMIN_INFILTRADO_EDIT_WORD1_INPUT,
    ADMIN_INFILTRADO_EDIT_WORD2_INPUT,
    ADMIN_INFILTRADO_ADD_CATEGORY_INPUT,
    ADMIN_INFILTRADO_RENAME_CATEGORY_INPUT,
    GRANT_COINS_MENU,
    GRANT_COINS_AMOUNT_MENU,
    GRANT_COINS_INPUT,
    ADMIN_NICK_CHANGES_MENU,
    ADMIN_NICK_CHANGE_ACTIONS_MENU,
    ADMIN_NICK_REJECT_REASON_INPUT,
    ADMIN_NICK_REJECT_REFUND_MENU,
}


@dataclass(frozen=True)
class AdminTargetRow:
    """Display text plus stable username action target for admin lists."""

    username: str
    label: str


def require_admin(func):
    """Decorator that checks if the user is still an admin before executing an admin action."""
    @functools.wraps(func)
    async def wrapper(self, admin, *args, **kwargs):
        if admin.trust_level < ADMIN_TRUST_LEVEL:
            admin.speak_l("not-admin-anymore", buffer="system")
            self.server._show_main_menu(admin)
            return
        return await func(self, admin, *args, **kwargs)
    return wrapper


class AdministrationManager:
    """
    Manager class providing administration functionality.
    """

    def __init__(self, server: "Server"):
        self.server = server

    def _localized_text_locale_groups(
        self, display_locale: str
    ) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
        """Return metadata-driven required and optional editor locales."""
        languages = Localization.get_available_languages(display_locale)
        official_codes = set(Localization.official_locale_codes())
        official = [
            (code, name) for code, name in languages.items() if code in official_codes
        ]
        community = [
            (code, name) for code, name in languages.items() if code not in official_codes
        ]
        return official, community

    def _require_localized_text_access(
        self, user: NetworkUser, spec: AdminLocalizedTextSpec
    ) -> bool:
        """Revalidate access whenever a reusable admin editor is used."""
        if user.trust_level >= spec.required_trust_level:
            return True
        if user.trust_level < ADMIN_TRUST_LEVEL:
            user.speak_l("not-admin-anymore", buffer="system")
            self.server._show_main_menu(user)
        else:
            user.speak_l("dev-only-action", buffer="system")
            self._return_to_admin_root(user)
        return False

    def _show_admin_localized_text_menu(
        self,
        user: NetworkUser,
        purpose: str,
        translations: dict[str, str] | None = None,
        context: dict[str, Any] | None = None,
        *,
        focus_id: str | None = None,
    ) -> None:
        """Show the reusable form-like editor for administrator-authored text."""
        spec = ADMIN_LOCALIZED_TEXT_SPECS.get(purpose)
        if spec is None:
            self._return_to_admin_root(user)
            return
        if not self._require_localized_text_access(user, spec):
            return
        official, community = self._localized_text_locale_groups(user.locale)
        if not official:
            user.speak_l("error-no-languages", buffer="system")
            self.server._nav_back(user)
            return

        values = normalize_localized_text(
            translations,
            max_length=spec.max_length,
            multiline=spec.multiline,
        )
        editor_context = dict(context or {})
        subject = Localization.get(user.locale, spec.subject_key)
        fallback_name = official[0][1] if official else DEFAULT_LOCALE
        items = [
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-localized-text-instructions",
                    subject=subject,
                    fallback=fallback_name,
                ),
                id="",
            )
        ]
        if purpose == "motd":
            try:
                version = int(editor_context.get("version", 0) or 0)
            except (TypeError, ValueError):
                version = 0
                editor_context["version"] = version
            items.append(
                MenuItem(
                    text=Localization.get(
                        user.locale,
                        "admin-localized-text-motd-version",
                        version=version,
                    ),
                    id="localized_text_version",
                )
            )

        items.append(
            MenuItem(
                text=Localization.get(
                    user.locale, "admin-localized-text-official-heading"
                ),
                id="",
            )
        )
        for code, name in official:
            status_key = (
                "admin-localized-text-required-set"
                if values.get(code)
                else "admin-localized-text-required-missing"
            )
            items.append(
                MenuItem(
                    text=Localization.get(
                        user.locale,
                        "admin-localized-text-field",
                        language=name,
                        status=Localization.get(user.locale, status_key),
                    ),
                    id=f"localized_text_locale_{code}",
                )
            )

        if community:
            items.append(
                MenuItem(
                    text=Localization.get(
                        user.locale, "admin-localized-text-community-heading"
                    ),
                    id="",
                )
            )
            for code, name in community:
                status_key = (
                    "admin-localized-text-optional-set"
                    if values.get(code)
                    else "admin-localized-text-optional-fallback"
                )
                items.append(
                    MenuItem(
                        text=Localization.get(
                            user.locale,
                            "admin-localized-text-field",
                            language=name,
                            status=Localization.get(user.locale, status_key),
                        ),
                        id=f"localized_text_locale_{code}",
                    )
                )

        items.extend(
            [
                MenuItem(
                    text=Localization.get(user.locale, spec.submit_key),
                    id="localized_text_submit",
                ),
                MenuItem(text=Localization.get(user.locale, "back"), id="back"),
            ]
        )
        user.show_menu(
            ADMIN_LOCALIZED_TEXT_MENU,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
            selection_id=focus_id,
        )
        self.server.user_states[user.username] = {
            "menu": ADMIN_LOCALIZED_TEXT_MENU,
            "localized_text_purpose": purpose,
            "localized_text_translations": values,
            "localized_text_context": editor_context,
        }

    def _refresh_admin_localized_text_with_focus(
        self,
        user: NetworkUser,
        purpose: str,
        translations: dict[str, str],
        context: dict[str, Any],
        focus_id: str,
    ) -> None:
        """Refresh the editor and persist its deliberate validation focus."""
        current = self.server.user_states.get(user.username, {})
        current["_last_selection_id"] = focus_id
        current.pop("_last_selection_position", None)
        self.server._nav_refresh(
            user,
            self._show_admin_localized_text_menu,
            purpose,
            translations,
            context,
            focus_id=focus_id,
        )

    async def _handle_admin_localized_text_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        """Edit or complete one reusable localized-text form."""
        if selection_id == "back":
            self.server._nav_back(user)
            return
        purpose = str(state.get("localized_text_purpose") or "")
        spec = ADMIN_LOCALIZED_TEXT_SPECS.get(purpose)
        if spec is None:
            self._return_to_admin_root(user)
            return
        if not self._require_localized_text_access(user, spec):
            return
        translations = dict(state.get("localized_text_translations") or {})
        context = dict(state.get("localized_text_context") or {})

        if selection_id == "localized_text_version" and purpose == "motd":
            try:
                current_version = int(context.get("version", 0) or 0)
            except (TypeError, ValueError):
                current_version = 0
            user.show_editbox(
                ADMIN_LOCALIZED_TEXT_INPUT,
                Localization.get(user.locale, "motd-version-prompt"),
                default_value=str(current_version),
                multiline=False,
            )
            self.server.enter_input_state(
                user,
                ADMIN_LOCALIZED_TEXT_INPUT,
                localized_text_field="version",
                localized_text_purpose=purpose,
            )
            return

        if selection_id.startswith("localized_text_locale_"):
            language = selection_id.removeprefix("localized_text_locale_")
            languages = Localization.get_available_languages(user.locale)
            if language not in languages:
                return
            subject = Localization.get(user.locale, spec.subject_key)
            user.show_editbox(
                ADMIN_LOCALIZED_TEXT_INPUT,
                Localization.get(
                    user.locale,
                    "admin-localized-text-prompt",
                    subject=subject,
                    language=languages[language],
                    max=spec.max_length,
                ),
                default_value=translations.get(language, ""),
                multiline=spec.multiline,
                max_length=spec.max_length,
            )
            self.server.enter_input_state(
                user,
                ADMIN_LOCALIZED_TEXT_INPUT,
                localized_text_field="locale",
                localized_text_language=language,
                localized_text_purpose=purpose,
            )
            return

        if selection_id == "localized_text_submit":
            await self._complete_admin_localized_text(
                user, purpose, translations, context
            )

    async def _complete_admin_localized_text(
        self,
        user: NetworkUser,
        purpose: str,
        translations: dict[str, str],
        context: dict[str, Any],
    ) -> None:
        """Validate and dispatch one localized administrator action."""
        spec = ADMIN_LOCALIZED_TEXT_SPECS[purpose]
        values = normalize_localized_text(
            translations,
            max_length=spec.max_length,
            multiline=spec.multiline,
        )
        official, _community = self._localized_text_locale_groups(user.locale)
        missing = [(code, name) for code, name in official if not values.get(code)]
        if missing:
            user.speak_l(
                "admin-localized-text-missing-required",
                buffer="system",
                languages=Localization.format_list_and(
                    user.locale, [name for _code, name in missing]
                ),
            )
            self._refresh_admin_localized_text_with_focus(
                user,
                purpose,
                values,
                context,
                f"localized_text_locale_{missing[0][0]}",
            )
            return

        if purpose == "motd":
            try:
                version = int(context.get("version", 0) or 0)
            except (TypeError, ValueError):
                version = 0
            if version <= 0:
                user.speak_l("invalid-motd-version", buffer="system")
                self._refresh_admin_localized_text_with_focus(
                    user,
                    purpose,
                    values,
                    context,
                    "localized_text_version",
                )
                return
            self.server.db.create_motd(version, values)
            user.speak_l("motd-created", buffer="system", version=version)
            for recipient in self.server.users.values():
                if not recipient.approved:
                    continue
                motd_text = localized_text_for_locale(recipient.locale, values)
                recipient.play_sound_family("notify")
                recipient.speak_l(
                    "motd-broadcast", buffer="system", message=motd_text
                )
            self.server._nav_back(user)
            return

        if purpose == "power":
            action = str(context.get("power_action") or "")
            try:
                delay_seconds = int(context.get("power_delay_seconds") or 0)
            except (TypeError, ValueError):
                delay_seconds = 0
            if (
                action not in {PowerAction.REBOOT.value, PowerAction.SHUTDOWN.value}
                or delay_seconds <= 0
            ):
                self._return_to_admin_root(user, "server_power")
                return
            self.server._nav_push(
                user,
                self._show_server_power_confirm_menu,
                action,
                delay_seconds,
                "custom",
                values,
            )
            return

        target_username = str(context.get("target_username") or "")
        duration = str(context.get("duration") or "")
        if not target_username or not duration:
            self._return_to_admin_root(user, f"{purpose}_user")
            return
        reason = encode_localized_custom_text(values)
        if purpose == "ban":
            await self._perform_ban(user, target_username, duration, reason)
        elif purpose == "mute":
            await self._perform_mute(user, target_username, duration, reason)

    def _return_to_admin_root(
        self, user: NetworkUser, focus_id: str | None = None
    ) -> None:
        """Return to the top-level Admin menu without discarding outer navigation."""
        username = user.username
        current = self.server.user_states.get(username, {})
        stack = list(current.get("_stack", []))
        parent_stack: list[dict[str, Any]] = []
        admin_frame: dict[str, Any] | None = None

        for frame in stack:
            if frame.get("menu") == "admin_menu":
                admin_frame = frame
                break
            parent_stack.append(frame)

        restore_frame = dict(admin_frame or {"menu": "admin_menu"})
        if focus_id:
            mapped_focus = ADMIN_SUBMENU_ROOT_ITEM_MAP.get(focus_id, focus_id)
            restore_frame["_restore_focus_id"] = mapped_focus
            restore_frame["_last_selection_id"] = mapped_focus
            restore_frame.pop("_restore_focus_position", None)
            restore_frame.pop("_last_selection_position", None)

        self._show_admin_menu(user)
        state = self.server.user_states.get(username)
        if state is not None:
            state["_stack"] = parent_stack
            self.server._restore_menu_focus(user, restore_frame)

    def _admin_target_search_text(self, user: NetworkUser, query: str) -> str:
        query = query.strip()
        if query:
            return Localization.get(
                user.locale,
                "admin-search-users-current",
                query=query,
            )
        return Localization.get(user.locale, "admin-search-users")

    def _show_admin_target_menu(
        self,
        user: NetworkUser,
        *,
        menu_id: str,
        mode: str,
        action_prefix: str,
        targets: PaginatedMenuPage[str | AdminTargetRow],
        empty_key: str,
        query: str = "",
        focus_page_start: bool = False,
    ) -> None:
        query = query.strip()
        items = [
            MenuItem(text=self._admin_target_search_text(user, query), id="search")
        ]
        focus_position: int | None = None

        if targets.total:
            if targets.total_pages > 1:
                summary_key = (
                    "menu-page-summary-query" if query else "menu-page-summary"
                )
                items.append(
                    MenuItem(
                        text=Localization.get(
                            user.locale,
                            summary_key,
                            query=query,
                            start=targets.start_index,
                            end=targets.end_index,
                            total=targets.total,
                            page=targets.page,
                            pages=targets.total_pages,
                        ),
                        id="page_summary",
                        read_only=True,
                    )
                )

            if focus_page_start:
                focus_position = len(items) + 1
            for target in targets.items:
                if isinstance(target, AdminTargetRow):
                    label = target.label
                    target_username = target.username
                else:
                    label = target
                    target_username = target
                items.append(
                    MenuItem(text=label, id=f"{action_prefix}_{target_username}")
                )
            items.extend(
                pagination_menu_items(user.locale, targets, include_refresh=True)
            )
        elif query:
            items.append(
                MenuItem(
                    text=Localization.get(user.locale, "admin-search-no-results"),
                    id="",
                )
            )
            items.extend(
                pagination_menu_items(user.locale, targets, include_refresh=True)
            )
        else:
            items.append(MenuItem(text=Localization.get(user.locale, empty_key), id=""))
            items.extend(
                pagination_menu_items(user.locale, targets, include_refresh=True)
            )

        items.append(MenuItem(text=Localization.get(user.locale, "back"), id="back"))
        user.show_menu(
            menu_id,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
            position=focus_position,
        )
        self.server.user_states[user.username] = {
            "menu": menu_id,
            "target_mode": mode,
            "search_query": query,
            "target_page": targets.page,
            "target_page_count": targets.total_pages,
        }

    def _show_admin_target_search_input(
        self, user: NetworkUser, mode: str, query: str = ""
    ) -> None:
        user.show_editbox(
            ADMIN_TARGET_SEARCH_INPUT,
            Localization.get(
                user.locale,
                "admin-search-prompt",
            ),
            default_value=query.strip(),
            multiline=False,
        )
        self.server.enter_input_state(
            user,
            ADMIN_TARGET_SEARCH_INPUT,
            target_mode=mode,
        )

    def _refresh_admin_target_menu(
        self,
        user: NetworkUser,
        mode: str,
        query: str = "",
        page: int = 1,
        *,
        focus_page_start: bool = False,
    ) -> None:
        show_fn = {
            "promote": self._show_promote_admin_menu,
            "demote": self._show_demote_admin_menu,
            "kick": self._show_kick_menu,
            "ban": self._show_ban_menu,
            "unban": self._show_unban_menu,
            "mute": self._show_mute_menu,
            "unmute": self._show_unmute_menu,
            "grant_coins": self._show_grant_coins_menu,
        }.get(mode)
        if show_fn is None:
            self._return_to_admin_root(user)
            return
        self.server._nav_refresh(
            user,
            show_fn,
            query.strip(),
            page,
            focus_page_start=focus_page_start,
        )

    def _handle_target_search_selection(
        self, user: NetworkUser, state: dict[str, Any]
    ) -> None:
        mode = state.get("target_mode")
        if not mode:
            self._return_to_admin_root(user)
            return
        self._show_admin_target_search_input(
            user,
            str(mode),
            str(state.get("search_query", "")),
        )

    def _handle_target_page_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> bool:
        if selection_id not in MENU_PAGE_IDS:
            return False
        mode = state.get("target_mode")
        if not mode:
            self._return_to_admin_root(user)
            return True
        query = str(state.get("search_query", ""))
        next_page = page_for_selection(
            selection_id,
            state.get("target_page", 1),
            state.get("target_page_count", 1),
        )
        if next_page is None:
            return False
        if is_page_refresh(selection_id):
            announce_page_refresh(user)
        self._refresh_admin_target_menu(
            user,
            str(mode),
            query,
            next_page,
            focus_page_start=is_page_navigation(selection_id),
        )
        return True

    def _search_user_targets_page(
        self,
        query: str,
        page: int,
        **filters: Any,
    ) -> PaginatedMenuPage[str]:
        total = self.server.db.count_users(query, **filters)
        safe_page = clamp_page(page, total, ADMIN_TARGET_PAGE_SIZE)
        offset = (safe_page - 1) * ADMIN_TARGET_PAGE_SIZE
        usernames = [
            record.username
            for record in self.server.db.search_users(
                query,
                limit=ADMIN_TARGET_PAGE_SIZE,
                offset=offset,
                **filters,
            )
        ]
        return PaginatedMenuPage(
            items=usernames,
            total=total,
            page=safe_page,
            page_size=ADMIN_TARGET_PAGE_SIZE,
        )

    def _search_promote_targets(
        self, query: str, page: int
    ) -> PaginatedMenuPage[str]:
        return self._search_user_targets_page(
            query,
            page,
            approved=True,
            max_trust_level=USER_TRUST_LEVEL,
        )

    def _search_demote_targets(
        self, user: NetworkUser, query: str, page: int
    ) -> PaginatedMenuPage[str]:
        return self._search_user_targets_page(
            query,
            page,
            min_trust_level=ADMIN_TRUST_LEVEL,
            max_trust_level=ADMIN_TRUST_LEVEL,
            exclude_username=user.username,
        )

    def _search_ban_targets(
        self, user: NetworkUser, query: str, page: int
    ) -> PaginatedMenuPage[str]:
        max_trust = (
            ADMIN_TRUST_LEVEL
            if user.trust_level >= DEVELOPER_TRUST_LEVEL
            else USER_TRUST_LEVEL
        )
        return self._search_user_targets_page(
            query,
            page,
            approved=True,
            max_trust_level=max_trust,
            exclude_username=user.username,
            exclude_active_bans=True,
        )

    def _search_mute_targets(
        self, user: NetworkUser, query: str, page: int
    ) -> PaginatedMenuPage[str]:
        max_trust = (
            ADMIN_TRUST_LEVEL
            if user.trust_level >= DEVELOPER_TRUST_LEVEL
            else USER_TRUST_LEVEL
        )
        return self._search_user_targets_page(
            query,
            page,
            approved=True,
            max_trust_level=max_trust,
            exclude_username=user.username,
            exclude_active_mutes=True,
        )

    def _search_kick_targets(
        self, user: NetworkUser, query: str, page: int
    ) -> PaginatedMenuPage[str]:
        term = username_key(query)
        targets = []
        for target in self.server.users.values():
            if target.username == user.username:
                continue
            if target.trust_level >= DEVELOPER_TRUST_LEVEL:
                continue
            if (
                user.trust_level < DEVELOPER_TRUST_LEVEL
                and target.trust_level >= ADMIN_TRUST_LEVEL
            ):
                continue
            if term and term not in username_key(target.username):
                continue
            targets.append(target.username)
        targets.sort(key=lambda username: (username_key(username), username))
        return paginate_sequence(
            targets,
            page,
            page_size=ADMIN_TARGET_PAGE_SIZE,
        )

    def _penalty_admin_text(self, locale: str, admin_username: str | None) -> str:
        admin_name = str(admin_username or "").strip()
        if admin_name:
            return admin_name
        return Localization.get(locale, "admin-penalty-admin-unknown")

    def _format_remaining_duration(self, locale: str, expires_at: datetime) -> str:
        now = datetime.now(expires_at.tzinfo) if expires_at.tzinfo else datetime.now()
        total_seconds = int((expires_at - now).total_seconds())
        if total_seconds < 60:
            return Localization.get(locale, "admin-penalty-remaining-less-minute")

        total_minutes = (total_seconds + 59) // 60
        days, remainder = divmod(total_minutes, 24 * 60)
        hours, minutes = divmod(remainder, 60)
        parts: list[str] = []
        if days:
            parts.append(
                Localization.get(locale, "admin-penalty-remaining-days", count=days)
            )
        if hours:
            parts.append(
                Localization.get(locale, "admin-penalty-remaining-hours", count=hours)
            )
        if minutes:
            parts.append(
                Localization.get(
                    locale,
                    "admin-penalty-remaining-minutes",
                    count=minutes,
                )
            )
        return Localization.format_list_and(locale, parts)

    def _penalty_expiry_text(self, locale: str, expires_at: str | None) -> str:
        raw_expiry = str(expires_at or "").strip()
        if not raw_expiry:
            return Localization.get(locale, "admin-penalty-expiry-permanent")

        try:
            expiry = datetime.fromisoformat(raw_expiry)
        except ValueError:
            return Localization.get(locale, "admin-penalty-expiry-unknown")

        now = datetime.now(expiry.tzinfo) if expiry.tzinfo else datetime.now()
        if expiry <= now:
            return Localization.get(locale, "admin-penalty-expiry-expired")

        return Localization.get(
            locale,
            "admin-penalty-expiry-timed",
            date=expiry.strftime("%Y-%m-%d %H:%M"),
            remaining=self._format_remaining_duration(locale, expiry),
        )

    def _ban_record_row(self, locale: str, record: BanRecord) -> AdminTargetRow:
        return AdminTargetRow(
            username=record.username,
            label=Localization.get(
                locale,
                "admin-active-ban-entry",
                username=record.username,
                expires=self._penalty_expiry_text(locale, record.expires_at),
                reason=localized_penalty_reason_for_locale(locale, record.reason_key),
                admin=self._penalty_admin_text(locale, record.admin_username),
            ),
        )

    def _mute_record_row(self, locale: str, record: MuteRecord) -> AdminTargetRow:
        return AdminTargetRow(
            username=record.username,
            label=Localization.get(
                locale,
                "admin-active-mute-entry",
                username=record.username,
                expires=self._penalty_expiry_text(locale, record.expires_at),
                reason=localized_penalty_reason_for_locale(locale, record.reason),
                admin=self._penalty_admin_text(locale, record.admin_username),
            ),
        )

    def _search_active_bans_page(
        self, query: str, page: int, locale: str
    ) -> PaginatedMenuPage[AdminTargetRow]:
        total = self.server.db.count_active_banned_users(query)
        safe_page = clamp_page(page, total, ADMIN_TARGET_PAGE_SIZE)
        offset = (safe_page - 1) * ADMIN_TARGET_PAGE_SIZE
        return PaginatedMenuPage(
            items=[
                self._ban_record_row(locale, record)
                for record in self.server.db.search_active_ban_records(
                    query,
                    limit=ADMIN_TARGET_PAGE_SIZE,
                    offset=offset,
                )
            ],
            total=total,
            page=safe_page,
            page_size=ADMIN_TARGET_PAGE_SIZE,
        )

    def _search_active_mutes_page(
        self, query: str, page: int, locale: str
    ) -> PaginatedMenuPage[AdminTargetRow]:
        total = self.server.db.count_active_muted_users(query)
        safe_page = clamp_page(page, total, ADMIN_TARGET_PAGE_SIZE)
        offset = (safe_page - 1) * ADMIN_TARGET_PAGE_SIZE
        return PaginatedMenuPage(
            items=[
                self._mute_record_row(locale, record)
                for record in self.server.db.search_active_mute_records(
                    query,
                    limit=ADMIN_TARGET_PAGE_SIZE,
                    offset=offset,
                )
            ],
            total=total,
            page=safe_page,
            page_size=ADMIN_TARGET_PAGE_SIZE,
        )

    # ==================== Manual Moderation Review ====================

    @staticmethod
    def _format_moderation_timestamp(locale: str, value: str) -> str:
        """Format a stored instant as a human-readable localized UTC value."""
        try:
            parsed = datetime.fromisoformat(str(value))
            if parsed.tzinfo is None:
                raise ValueError
            return Localization.format_utc_datetime(locale, parsed)
        except (TypeError, ValueError):
            return Localization.get(locale, "admin-moderation-value-unknown")

    def _moderation_reason_name(self, locale: str, reason_code: str) -> str:
        try:
            key = report_reason_localization_key(reason_code)
        except ValueError:
            return Localization.get(locale, "admin-moderation-value-unknown")
        return Localization.get(locale, key)

    @staticmethod
    def _moderation_status_name(locale: str, status: str) -> str:
        if status not in REPORT_STATUS_SET:
            status = "unknown"
        return Localization.get(locale, f"admin-moderation-status-{status}")

    def _moderation_channel_name(
        self, locale: str, channel_code: str | None
    ) -> str:
        if channel_code is None:
            return Localization.get(locale, "report-channel-unspecified")
        return self.server._get_global_chat_channel_name(locale, channel_code)

    @staticmethod
    def _moderation_reporter_name(
        locale: str, report: ModerationReportRecord
    ) -> str:
        if report.origin_code == REPORT_ORIGIN_AUTOMATED_SPAM:
            return Localization.get(locale, "system-name")
        return report.reporter_username

    @staticmethod
    def _moderation_origin_name(locale: str, origin_code: str) -> str:
        if origin_code == REPORT_ORIGIN_AUTOMATED_SPAM:
            key = "admin-moderation-origin-automatic"
        elif origin_code == REPORT_ORIGIN_MANUAL:
            key = "admin-moderation-origin-manual"
        else:
            return Localization.get(locale, "admin-moderation-value-unknown")
        return Localization.get(locale, key)

    @staticmethod
    def _moderation_scope_name(locale: str, scope: str) -> str:
        if scope not in REPORT_CONTEXT_CODES:
            return Localization.get(locale, "admin-moderation-value-unknown")
        return Localization.get(locale, f"admin-moderation-scope-{scope}")

    def _automated_report_evidence_items(
        self, user: NetworkUser, report: ModerationReportRecord
    ) -> list[MenuItem]:
        """Render structured System evidence without exposing storage JSON."""
        if report.origin_code != REPORT_ORIGIN_AUTOMATED_SPAM:
            return []
        evidence = (
            AutomatedSpamEvidence.from_json(report.evidence_json)
            if report.evidence_json is not None
            else None
        )
        if evidence is not None and evidence.scope != report.context_code:
            evidence = None
        if evidence is None:
            text = Localization.get(
                user.locale,
                "admin-moderation-automatic-evidence-unavailable",
            )
        else:
            text = Localization.get(
                user.locale,
                "admin-moderation-automatic-evidence",
                scope=self._moderation_scope_name(user.locale, evidence.scope),
                detection=Localization.get(
                    user.locale,
                    f"admin-moderation-detection-{evidence.detection_kind.replace('_', '-')}",
                ),
                incidents=evidence.incident_count,
                rejected=evidence.rejected_attempt_count,
                accepted=evidence.accepted_message_count,
                window=ServerPowerManager.format_duration(
                    user.locale,
                    evidence.observation_window_seconds,
                ),
                sample=evidence.sample_message,
            )
        return [MenuItem(text=text, id="automatic_evidence", read_only=True)]

    def _require_developer_moderation_access(self, user: NetworkUser) -> bool:
        """Protect irreversible evidence cleanup at display and action time."""
        if user.trust_level >= DEVELOPER_TRUST_LEVEL:
            return True
        user.speak_l("dev-only-action", buffer="system")
        self._return_to_admin_root(user, "moderation")
        return False

    def _show_moderation_menu(self, user: NetworkUser) -> None:
        """Show report review, history lookup, and explicit retention controls."""
        open_reports = self.server.db.count_moderation_reports(status="open")
        all_reports = self.server.db.count_moderation_reports()
        message_count = self.server.db.count_global_chat_messages()
        closed_reports = self.server.db.count_moderation_reports(
            statuses=CLOSED_REPORT_STATUSES
        )
        global_chat_enabled = self.server.global_chat_sending_enabled
        global_voice_chat_enabled = self.server.global_voice_chat_enabled
        items = [
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-moderation-global-chat-toggle",
                    status=Localization.get(
                        user.locale,
                        "option-on" if global_chat_enabled else "option-off",
                    ),
                ),
                id="toggle_global_chat",
                description_key=(
                    "admin-moderation-global-chat-toggle-description"
                    if user.trust_level >= DEVELOPER_TRUST_LEVEL
                    else "admin-moderation-global-chat-status-description"
                ),
                read_only=user.trust_level < DEVELOPER_TRUST_LEVEL,
            ),
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-moderation-global-voice-chat-toggle",
                    status=Localization.get(
                        user.locale,
                        "option-on" if global_voice_chat_enabled else "option-off",
                    ),
                ),
                id="toggle_global_voice_chat",
                description_key=(
                    "admin-moderation-global-voice-chat-toggle-description"
                    if user.trust_level >= DEVELOPER_TRUST_LEVEL
                    else "admin-moderation-global-voice-chat-status-description"
                ),
                read_only=user.trust_level < DEVELOPER_TRUST_LEVEL,
            ),
            MenuItem(
                text=Localization.get(user.locale, 'forum-availability-toggle',
                                     status=Localization.get(user.locale, 'option-on' if self.server.forum_enabled else 'option-off')),
                id='toggle_forum',
                description_key='forum-availability-description',
                read_only=user.trust_level < ADMIN_TRUST_LEVEL,
            ),
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-moderation-section-reports",
                ),
                id="reports_heading",
                read_only=True,
            ),
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-moderation-open-reports",
                    count=open_reports,
                ),
                id="reports_open",
            ),
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-moderation-closed-reports",
                    count=closed_reports,
                ),
                id="reports_closed",
            ),
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-moderation-all-reports",
                    count=all_reports,
                ),
                id="reports_all",
            ),
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-moderation-section-messages",
                ),
                id="messages_heading",
                read_only=True,
            ),
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-moderation-browse-messages",
                ),
                id="browse_messages",
            ),
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-moderation-find-history",
                ),
                id="find_history",
            ),
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-moderation-retained-summary",
                    messages=message_count,
                    closed=closed_reports,
                ),
                id="retained_summary",
                read_only=True,
            ),
        ]
        if user.trust_level >= DEVELOPER_TRUST_LEVEL:
            items.extend(
                [
                    MenuItem(
                        text=Localization.get(
                            user.locale,
                            "admin-moderation-section-retention",
                        ),
                        id="retention_heading",
                        read_only=True,
                    ),
                    MenuItem(
                        text=Localization.get(
                            user.locale,
                            "admin-moderation-clear-history",
                            count=message_count,
                        ),
                        id="clear_history",
                    ),
                    MenuItem(
                        text=Localization.get(
                            user.locale,
                            "admin-moderation-clear-closed-reports",
                            count=closed_reports,
                        ),
                        id="clear_closed_reports",
                    ),
                ]
            )
        items.append(MenuItem(text=Localization.get(user.locale, "back"), id="back"))
        user.show_menu(
            ADMIN_MODERATION_MENU,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {"menu": ADMIN_MODERATION_MENU}

    def _moderation_reports_page(
        self, report_filter: str, page: int
    ) -> PaginatedMenuPage[ModerationReportRecord]:
        status = "open" if report_filter == "open" else None
        statuses = (
            CLOSED_REPORT_STATUSES
            if report_filter == "closed"
            else None
        )
        total = self.server.db.count_moderation_reports(
            status=status,
            statuses=statuses,
        )
        safe_page = clamp_page(page, total, MODERATION_REVIEW_PAGE_SIZE)
        offset = (safe_page - 1) * MODERATION_REVIEW_PAGE_SIZE
        return PaginatedMenuPage(
            items=self.server.db.list_moderation_reports(
                status=status,
                statuses=statuses,
                limit=MODERATION_REVIEW_PAGE_SIZE,
                offset=offset,
            ),
            total=total,
            page=safe_page,
            page_size=MODERATION_REVIEW_PAGE_SIZE,
        )

    def _report_list_row(
        self, user: NetworkUser, report: ModerationReportRecord
    ) -> str:
        return Localization.get(
            user.locale,
            "admin-moderation-report-row",
            id=report.id,
            time=self._format_moderation_timestamp(
                user.locale,
                report.reported_at_utc,
            ),
            target=report.reported_username,
            target_id=report.reported_uuid,
            reason=self._moderation_reason_name(user.locale, report.reason_code),
            reporter=self._moderation_reporter_name(user.locale, report),
            status=self._moderation_status_name(user.locale, report.status),
        )

    def _show_moderation_reports_menu(
        self,
        user: NetworkUser,
        report_filter: str = "open",
        page: int = 1,
        *,
        focus_page_start: bool = False,
    ) -> None:
        """Show a paginated report queue using stable report IDs."""
        if report_filter not in {"open", "closed", "all"}:
            report_filter = "open"
        reports = self._moderation_reports_page(report_filter, page)
        items: list[MenuItem] = [
            MenuItem(
                text=Localization.get(
                    user.locale,
                    {
                        "open": "admin-moderation-open-report-list",
                        "closed": "admin-moderation-closed-report-list",
                        "all": "admin-moderation-all-report-list",
                    }[report_filter],
                ),
                id="report_list_heading",
                read_only=True,
            )
        ]
        focus_position: int | None = None
        if reports.items:
            if reports.total_pages > 1:
                items.append(
                    MenuItem(
                        text=Localization.get(
                            user.locale,
                            "menu-page-summary",
                            start=reports.start_index,
                            end=reports.end_index,
                            total=reports.total,
                            page=reports.page,
                            pages=reports.total_pages,
                        ),
                        id="page_summary",
                        read_only=True,
                    )
                )
            if focus_page_start:
                focus_position = len(items) + 1
            items.extend(
                MenuItem(
                    text=self._report_list_row(user, report),
                    id=f"moderation_report_{report.id}",
                )
                for report in reports.items
            )
            items.extend(
                pagination_menu_items(user.locale, reports, include_refresh=True)
            )
        else:
            items.append(
                MenuItem(
                    text=Localization.get(
                        user.locale, "admin-moderation-no-reports"
                    ),
                    id="no_reports",
                    read_only=True,
                )
            )
        items.append(MenuItem(text=Localization.get(user.locale, "back"), id="back"))
        user.show_menu(
            ADMIN_MODERATION_REPORTS_MENU,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
            position=focus_position,
        )
        self.server.user_states[user.username] = {
            "menu": ADMIN_MODERATION_REPORTS_MENU,
            "report_filter": report_filter,
            "moderation_page": reports.page,
            "moderation_page_count": reports.total_pages,
        }

    def _show_moderation_report_detail_menu(
        self, user: NetworkUser, report_id: int
    ) -> None:
        """Show every immutable identity and review field for one report."""
        report = self.server.db.get_moderation_report(report_id)
        if report is None:
            items = [
                MenuItem(
                    text=Localization.get(
                        user.locale, "admin-moderation-report-unavailable"
                    ),
                    id="report_unavailable",
                    read_only=True,
                ),
                MenuItem(text=Localization.get(user.locale, "back"), id="back"),
            ]
        else:
            has_global_history = report.context_code == REPORT_CONTEXT_GLOBAL
            items = [
                MenuItem(
                    text=Localization.get(
                        user.locale, "admin-moderation-report-id", id=report.id
                    ),
                    id="report_id",
                    read_only=True,
                ),
                MenuItem(
                    text=Localization.get(
                        user.locale,
                        "admin-moderation-report-time",
                        time=self._format_moderation_timestamp(
                            user.locale,
                            report.reported_at_utc
                        ),
                    ),
                    id="report_time",
                    read_only=True,
                ),
                MenuItem(
                    text=Localization.get(
                        user.locale,
                        "admin-moderation-report-status",
                        status=self._moderation_status_name(
                            user.locale, report.status
                        ),
                    ),
                    id="report_status",
                    read_only=True,
                ),
                MenuItem(
                    text=Localization.get(
                        user.locale,
                        "admin-moderation-report-origin",
                        origin=self._moderation_origin_name(
                            user.locale, report.origin_code
                        ),
                    ),
                    id="report_origin",
                    read_only=True,
                ),
                MenuItem(
                    text=Localization.get(
                        user.locale,
                        "admin-moderation-report-reporter",
                        username=self._moderation_reporter_name(
                            user.locale, report
                        ),
                        uuid=report.reporter_uuid,
                    ),
                    id="reporter_identity",
                    read_only=True,
                ),
                MenuItem(
                    text=Localization.get(
                        user.locale,
                        "admin-moderation-report-target",
                        username=report.reported_username,
                        uuid=report.reported_uuid,
                    ),
                    id="target_identity",
                    read_only=True,
                ),
                MenuItem(
                    text=Localization.get(
                        user.locale,
                        "admin-moderation-report-reason",
                        reason=self._moderation_reason_name(
                            user.locale, report.reason_code
                        ),
                    ),
                    id="report_reason",
                    read_only=True,
                ),
                MenuItem(
                    text=Localization.get(
                        user.locale,
                        (
                            "admin-moderation-report-scope"
                            if report.origin_code
                            == REPORT_ORIGIN_AUTOMATED_SPAM
                            else "admin-moderation-report-channel"
                        ),
                        **(
                            {
                                "scope": self._moderation_scope_name(
                                    user.locale,
                                    report.context_code,
                                )
                            }
                            if report.origin_code
                            == REPORT_ORIGIN_AUTOMATED_SPAM
                            else {
                                "channel": self._moderation_channel_name(
                                    user.locale, report.channel_code
                                )
                            }
                        ),
                    ),
                    id="report_channel",
                    read_only=True,
                ),
            ]
            if has_global_history:
                items.append(
                    MenuItem(
                        text=Localization.get(
                            user.locale,
                            (
                                "admin-moderation-report-anchor"
                                if report.context_anchor_message_id is not None
                                else "admin-moderation-report-anchor-unavailable"
                            ),
                            id=report.context_anchor_message_id,
                        ),
                        id="report_anchor",
                        read_only=True,
                    )
                )
            items.extend(self._automated_report_evidence_items(user, report))
            if report.details:
                items.append(
                    MenuItem(
                        text=Localization.get(
                            user.locale,
                            "admin-moderation-report-details",
                            details=report.details,
                        ),
                        id="report_details",
                        read_only=True,
                    )
                )
            if report.reviewed_at_utc:
                items.append(
                    MenuItem(
                        text=Localization.get(
                            user.locale,
                            "admin-moderation-report-review",
                            reviewer=(
                                report.reviewed_by_username
                                or Localization.get(
                                    user.locale,
                                    "admin-moderation-value-unknown",
                                )
                            ),
                            reviewer_id=(
                                report.reviewed_by_uuid
                                or Localization.get(
                                    user.locale,
                                    "admin-moderation-value-unknown",
                                )
                            ),
                            time=self._format_moderation_timestamp(
                                user.locale,
                                report.reviewed_at_utc
                            ),
                        ),
                        id="report_review",
                        read_only=True,
                    )
                )
            if has_global_history:
                items.append(
                    MenuItem(
                        text=Localization.get(
                            user.locale, "admin-moderation-view-context"
                        ),
                        id="view_context",
                    )
                )
                items.append(
                    MenuItem(
                        text=Localization.get(
                            user.locale, "admin-moderation-view-target-history"
                        ),
                        id="view_target_history",
                    )
                )
            if report.status == "open":
                items.extend(
                    [
                        MenuItem(
                            text=Localization.get(
                                user.locale, "admin-moderation-mark-reviewed"
                            ),
                            id="set_status_reviewed",
                        ),
                        MenuItem(
                            text=Localization.get(
                                user.locale, "admin-moderation-dismiss-report"
                            ),
                            id="set_status_dismissed",
                        ),
                        MenuItem(
                            text=Localization.get(
                                user.locale, "admin-moderation-mark-actioned"
                            ),
                            id="set_status_actioned",
                        ),
                    ]
                )
            items.append(MenuItem(text=Localization.get(user.locale, "back"), id="back"))
        user.show_menu(
            ADMIN_MODERATION_REPORT_DETAIL_MENU,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {
            "menu": ADMIN_MODERATION_REPORT_DETAIL_MENU,
            "report_id": int(report_id),
        }

    def _context_message_row(
        self,
        user: NetworkUser,
        message: GlobalChatMessageRecord,
        target_uuid: str,
        anchor_message_id: int | None,
    ) -> str:
        if message.id == anchor_message_id:
            key = "admin-moderation-context-anchor-message"
        elif message.sender_uuid == target_uuid:
            key = "admin-moderation-context-target-message"
        else:
            key = "admin-moderation-context-message"
        return Localization.get(
            user.locale,
            key,
            id=message.id,
            time=self._format_moderation_timestamp(
                user.locale,
                message.sent_at_utc,
            ),
            username=message.sender_username,
            uuid=message.sender_uuid,
            channel=self._moderation_channel_name(
                user.locale, message.channel_code
            ),
            message=self._single_line_moderation_message(message.message),
        )

    @staticmethod
    def _single_line_moderation_message(message: str) -> str:
        """Keep untrusted audit text on one line without bidi spoofing."""
        safe_characters: list[str] = []
        for character in str(message):
            category = unicodedata.category(character)
            if category in {"Cc", "Zl", "Zp"}:
                safe_characters.append(" ")
            elif character not in UNSAFE_BIDI_CONTROLS:
                safe_characters.append(character)
        return "".join(safe_characters)

    def _moderation_copy_page_item(
        self,
        user: NetworkUser,
        rows: list[str],
    ) -> MenuItem:
        """Build one consistent local copy action for rendered audit rows."""
        count = len(rows)
        return MenuItem(
            text=Localization.get(
                user.locale,
                "admin-moderation-copy-page",
                count=count,
            ),
            id="copy_page",
            copy_directive=CopyDirective(
                text="\n".join(rows),
                success_text=Localization.get(
                    user.locale,
                    "admin-moderation-copy-page-success",
                    count=count,
                ),
                failure_text=Localization.get(
                    user.locale,
                    "admin-moderation-copy-page-failed",
                ),
            ),
        )

    def _show_moderation_context_menu(
        self,
        user: NetworkUser,
        report_id: int,
        page: int = 1,
        *,
        focus_page_start: bool = False,
    ) -> None:
        """Show bounded chronological chat context around a report instant."""
        report = self.server.db.get_moderation_report(report_id)
        items: list[MenuItem] = []
        safe_page = 1
        page_count = 1
        focus_position: int | None = None
        if report is None:
            items.append(
                MenuItem(
                    text=Localization.get(
                        user.locale, "admin-moderation-report-unavailable"
                    ),
                    id="report_unavailable",
                    read_only=True,
                )
            )
        else:
            items.append(
                MenuItem(
                    text=Localization.get(
                        user.locale,
                        "admin-moderation-context-heading",
                        id=report.id,
                        time=self._format_moderation_timestamp(
                            user.locale,
                            report.reported_at_utc
                        ),
                        channel=self._moderation_channel_name(
                            user.locale, report.channel_code
                        ),
                    ),
                    id="context_heading",
                    read_only=True,
                )
            )
            all_messages = self.server.db.get_global_chat_context(
                report.reported_at_utc,
                anchor_message_id=report.context_anchor_message_id,
                channel_code=report.channel_code,
                before_count=REPORT_CONTEXT_MESSAGES_BEFORE,
                after_count=REPORT_CONTEXT_MESSAGES_AFTER,
            )
            messages = paginate_sequence(
                all_messages,
                page,
                page_size=MODERATION_CONTEXT_PAGE_SIZE,
            )
            safe_page = messages.page
            page_count = messages.total_pages
            if messages.items:
                if messages.total_pages > 1:
                    items.append(
                        MenuItem(
                            text=Localization.get(
                                user.locale,
                                "menu-page-summary",
                                start=messages.start_index,
                                end=messages.end_index,
                                total=messages.total,
                                page=messages.page,
                                pages=messages.total_pages,
                            ),
                            id="page_summary",
                            read_only=True,
                        )
                    )
                rows = [
                    self._context_message_row(
                        user,
                        message,
                        report.reported_uuid,
                        report.context_anchor_message_id,
                    )
                    for message in messages.items
                ]
                items.append(self._moderation_copy_page_item(user, rows))
                if focus_page_start:
                    focus_position = len(items) + 1
                items.extend(
                    MenuItem(
                        text=row,
                        id=f"context_message_{message.id}",
                        read_only=True,
                    )
                    for message, row in zip(messages.items, rows, strict=True)
                )
                items.extend(
                    pagination_menu_items(
                        user.locale,
                        messages,
                        include_refresh=True,
                    )
                )
            else:
                items.append(
                    MenuItem(
                        text=Localization.get(
                            user.locale, "admin-moderation-context-empty"
                        ),
                        id="context_empty",
                        read_only=True,
                    )
                )
        items.append(MenuItem(text=Localization.get(user.locale, "back"), id="back"))
        user.show_menu(
            ADMIN_MODERATION_CONTEXT_MENU,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
            position=focus_position,
        )
        self.server.user_states[user.username] = {
            "menu": ADMIN_MODERATION_CONTEXT_MENU,
            "report_id": int(report_id),
            "moderation_page": safe_page,
            "moderation_page_count": page_count,
        }

    def _show_moderation_history_input(self, user: NetworkUser) -> None:
        user.show_editbox(
            ADMIN_MODERATION_HISTORY_INPUT,
            Localization.get(user.locale, "admin-moderation-history-prompt"),
            multiline=False,
        )
        self.server.enter_input_state(user, ADMIN_MODERATION_HISTORY_INPUT)

    def _moderation_sender_results_page(
        self, username: str, page: int
    ) -> PaginatedMenuPage[Any]:
        total = self.server.db.count_global_chat_sender_identities(username)
        safe_page = clamp_page(page, total, MODERATION_REVIEW_PAGE_SIZE)
        offset = (safe_page - 1) * MODERATION_REVIEW_PAGE_SIZE
        return PaginatedMenuPage(
            items=self.server.db.find_global_chat_sender_summaries(
                username,
                limit=MODERATION_REVIEW_PAGE_SIZE,
                offset=offset,
            ),
            total=total,
            page=safe_page,
            page_size=MODERATION_REVIEW_PAGE_SIZE,
        )

    def _show_moderation_sender_results_menu(
        self,
        user: NetworkUser,
        username: str,
        page: int = 1,
        *,
        focus_page_start: bool = False,
    ) -> None:
        """Disambiguate historical identities before showing their messages."""
        sender_results = self._moderation_sender_results_page(username, page)
        items = [
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-moderation-sender-results-heading",
                    username=username,
                ),
                id="sender_results_heading",
                read_only=True,
            )
        ]
        focus_position: int | None = None
        if sender_results.items:
            if sender_results.total_pages > 1:
                items.append(
                    MenuItem(
                        text=Localization.get(
                            user.locale,
                            "menu-page-summary",
                            start=sender_results.start_index,
                            end=sender_results.end_index,
                            total=sender_results.total,
                            page=sender_results.page,
                            pages=sender_results.total_pages,
                        ),
                        id="page_summary",
                        read_only=True,
                    )
                )
            if focus_page_start:
                focus_position = len(items) + 1
            items.extend(
                MenuItem(
                    text=Localization.get(
                        user.locale,
                        "admin-moderation-sender-result",
                        username=summary.sender_username,
                        uuid=summary.sender_uuid,
                        count=summary.message_count,
                        first=self._format_moderation_timestamp(
                            user.locale,
                            summary.first_sent_at_utc
                        ),
                        last=self._format_moderation_timestamp(
                            user.locale,
                            summary.last_sent_at_utc
                        ),
                    ),
                    id=f"history_sender_{summary.sender_uuid}",
                )
                for summary in sender_results.items
            )
            items.extend(
                pagination_menu_items(
                    user.locale, sender_results, include_refresh=True
                )
            )
        else:
            items.append(
                MenuItem(
                    text=Localization.get(
                        user.locale,
                        "admin-moderation-no-sender-history",
                        username=username,
                    ),
                    id="no_sender_history",
                    read_only=True,
                )
            )
        items.append(MenuItem(text=Localization.get(user.locale, "back"), id="back"))
        user.show_menu(
            ADMIN_MODERATION_SENDER_RESULTS_MENU,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
            position=focus_position,
        )
        self.server.user_states[user.username] = {
            "menu": ADMIN_MODERATION_SENDER_RESULTS_MENU,
            "history_username": username,
            "moderation_page": sender_results.page,
            "moderation_page_count": sender_results.total_pages,
        }

    def _moderation_history_page(
        self, sender_uuid: str, page: int
    ) -> PaginatedMenuPage[GlobalChatMessageRecord]:
        total = self.server.db.count_global_chat_messages(sender_uuid=sender_uuid)
        safe_page = clamp_page(page, total, MODERATION_REVIEW_PAGE_SIZE)
        offset = (safe_page - 1) * MODERATION_REVIEW_PAGE_SIZE
        return PaginatedMenuPage(
            items=self.server.db.list_global_chat_messages(
                sender_uuid=sender_uuid,
                limit=MODERATION_REVIEW_PAGE_SIZE,
                offset=offset,
            ),
            total=total,
            page=safe_page,
            page_size=MODERATION_REVIEW_PAGE_SIZE,
        )

    def _show_moderation_history_menu(
        self,
        user: NetworkUser,
        sender_uuid: str,
        page: int = 1,
        *,
        focus_page_start: bool = False,
    ) -> None:
        """Show one immutable sender identity's retained global messages."""
        history = self._moderation_history_page(sender_uuid, page)
        sender_name = (
            history.items[0].sender_username
            if history.items
            else Localization.get(
                user.locale, "admin-moderation-value-unknown"
            )
        )
        items = [
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-moderation-history-heading",
                    username=sender_name,
                    uuid=sender_uuid,
                    count=history.total,
                ),
                id="history_heading",
                read_only=True,
            )
        ]
        focus_position: int | None = None
        if history.items:
            if history.total_pages > 1:
                items.append(
                    MenuItem(
                        text=Localization.get(
                            user.locale,
                            "menu-page-summary",
                            start=history.start_index,
                            end=history.end_index,
                            total=history.total,
                            page=history.page,
                            pages=history.total_pages,
                        ),
                        id="page_summary",
                        read_only=True,
                    )
                )
            rows = [
                Localization.get(
                    user.locale,
                    "admin-moderation-history-message",
                    id=message.id,
                    time=self._format_moderation_timestamp(
                        user.locale,
                        message.sent_at_utc,
                    ),
                    username=message.sender_username,
                    channel=self._moderation_channel_name(
                        user.locale, message.channel_code
                    ),
                    message=self._single_line_moderation_message(
                        message.message
                    ),
                )
                for message in history.items
            ]
            items.append(self._moderation_copy_page_item(user, rows))
            if focus_page_start:
                focus_position = len(items) + 1
            items.extend(
                MenuItem(
                    text=row,
                    id=f"history_message_{message.id}",
                    read_only=True,
                )
                for message, row in zip(history.items, rows, strict=True)
            )
            items.extend(
                pagination_menu_items(user.locale, history, include_refresh=True)
            )
        else:
            items.append(
                MenuItem(
                    text=Localization.get(
                        user.locale, "admin-moderation-history-empty"
                    ),
                    id="history_empty",
                    read_only=True,
                )
            )
        items.append(MenuItem(text=Localization.get(user.locale, "back"), id="back"))
        user.show_menu(
            ADMIN_MODERATION_HISTORY_MENU,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
            position=focus_position,
        )
        self.server.user_states[user.username] = {
            "menu": ADMIN_MODERATION_HISTORY_MENU,
            "history_sender_uuid": sender_uuid,
            "moderation_page": history.page,
            "moderation_page_count": history.total_pages,
        }

    def _moderation_message_sort_name(
        self,
        locale: str,
        sort_order: str,
    ) -> str:
        return Localization.get(
            locale,
            f"admin-moderation-message-sort-{sort_order}",
        )

    def _moderation_message_period_name(
        self,
        locale: str,
        period: str,
    ) -> str:
        return Localization.get(
            locale,
            f"admin-moderation-message-period-{period.replace('_', '-')}",
        )

    def _moderation_message_channel_name(
        self,
        locale: str,
        channel_code: str | None,
    ) -> str:
        if channel_code is None:
            return Localization.get(
                locale,
                "admin-moderation-message-language-all",
            )
        return self._moderation_channel_name(locale, channel_code)

    @staticmethod
    def _moderation_message_filter_from_state(
        state: dict[str, Any],
    ) -> GlobalChatHistoryFilter:
        return GlobalChatHistoryFilter.from_values(
            channel_code=state.get("message_channel"),
            period=state.get("message_period"),
            sort_order=state.get("message_sort"),
        )

    def _moderation_messages_page(
        self,
        history_filter: GlobalChatHistoryFilter,
        page: int,
    ) -> PaginatedMenuPage[GlobalChatMessageRecord]:
        started_at, ended_before = history_filter.utc_bounds()
        started_text = (
            started_at.isoformat(timespec="microseconds")
            if started_at is not None
            else None
        )
        ended_text = (
            ended_before.isoformat(timespec="microseconds")
            if ended_before is not None
            else None
        )
        total = self.server.db.count_global_chat_messages(
            channel_code=history_filter.channel_code,
            started_at_utc=started_text,
            ended_before_utc=ended_text,
        )
        safe_page = clamp_page(page, total, MODERATION_REVIEW_PAGE_SIZE)
        offset = (safe_page - 1) * MODERATION_REVIEW_PAGE_SIZE
        return PaginatedMenuPage(
            items=self.server.db.list_global_chat_messages(
                channel_code=history_filter.channel_code,
                started_at_utc=started_text,
                ended_before_utc=ended_text,
                sort_order=history_filter.sort_order,
                limit=MODERATION_REVIEW_PAGE_SIZE,
                offset=offset,
            ),
            total=total,
            page=safe_page,
            page_size=MODERATION_REVIEW_PAGE_SIZE,
        )

    def _show_moderation_messages_menu(
        self,
        user: NetworkUser,
        channel_code: str | None = None,
        period: str = "all",
        sort_order: str = "newest",
        page: int = 1,
        *,
        focus_page_start: bool = False,
    ) -> None:
        """Show all retained global messages with exposed, composable filters."""
        history_filter = GlobalChatHistoryFilter.from_values(
            channel_code=channel_code,
            period=period,
            sort_order=sort_order,
        )
        messages = self._moderation_messages_page(history_filter, page)
        channel_name = self._moderation_message_channel_name(
            user.locale,
            history_filter.channel_code,
        )
        period_name = self._moderation_message_period_name(
            user.locale,
            history_filter.period,
        )
        sort_name = self._moderation_message_sort_name(
            user.locale,
            history_filter.sort_order,
        )
        items: list[MenuItem] = [
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-moderation-message-list-heading",
                    count=messages.total,
                    sort=sort_name,
                    channel=channel_name,
                    period=period_name,
                ),
                id="message_list_heading",
                read_only=True,
            ),
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-moderation-message-filter-sort",
                    sort=sort_name,
                ),
                id="message_filter_sort",
            ),
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-moderation-message-filter-language",
                    channel=channel_name,
                ),
                id="message_filter_language",
            ),
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-moderation-message-filter-period",
                    period=period_name,
                ),
                id="message_filter_period",
            ),
        ]
        if not history_filter.is_default:
            items.append(
                MenuItem(
                    text=Localization.get(
                        user.locale,
                        "admin-moderation-message-filter-reset",
                    ),
                    id="message_filter_reset",
                )
            )

        focus_position: int | None = None
        if messages.items:
            if messages.total_pages > 1:
                items.append(
                    MenuItem(
                        text=Localization.get(
                            user.locale,
                            "menu-page-summary",
                            start=messages.start_index,
                            end=messages.end_index,
                            total=messages.total,
                            page=messages.page,
                            pages=messages.total_pages,
                        ),
                        id="page_summary",
                        read_only=True,
                    )
                )
            rows = [
                Localization.get(
                    user.locale,
                    "admin-moderation-message-row",
                    id=message.id,
                    time=self._format_moderation_timestamp(
                        user.locale,
                        message.sent_at_utc,
                    ),
                    username=message.sender_username,
                    uuid=message.sender_uuid,
                    channel=self._moderation_channel_name(
                        user.locale,
                        message.channel_code,
                    ),
                    message=self._single_line_moderation_message(
                        message.message
                    ),
                )
                for message in messages.items
            ]
            items.append(self._moderation_copy_page_item(user, rows))
            if focus_page_start:
                focus_position = len(items) + 1
            items.extend(
                MenuItem(
                    text=row,
                    id=f"moderation_message_{message.id}",
                    read_only=True,
                )
                for message, row in zip(messages.items, rows, strict=True)
            )
            items.extend(
                pagination_menu_items(
                    user.locale,
                    messages,
                    include_refresh=True,
                )
            )
        else:
            items.append(
                MenuItem(
                    text=Localization.get(
                        user.locale,
                        "admin-moderation-message-list-empty",
                    ),
                    id="message_list_empty",
                    read_only=True,
                )
            )
        items.append(MenuItem(text=Localization.get(user.locale, "back"), id="back"))
        user.show_menu(
            ADMIN_MODERATION_MESSAGES_MENU,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
            position=focus_position,
        )
        self.server.user_states[user.username] = {
            "menu": ADMIN_MODERATION_MESSAGES_MENU,
            "message_channel": history_filter.channel_code,
            "message_period": history_filter.period,
            "message_sort": history_filter.sort_order,
            "moderation_page": messages.page,
            "moderation_page_count": messages.total_pages,
        }

    def _show_moderation_message_language_menu(
        self,
        user: NetworkUser,
        channel_code: str | None = None,
        period: str = "all",
        sort_order: str = "newest",
    ) -> None:
        """Show the language facet for the global message browser."""
        history_filter = GlobalChatHistoryFilter.from_values(
            channel_code=channel_code,
            period=period,
            sort_order=sort_order,
        )
        current_name = self._moderation_message_channel_name(
            user.locale,
            history_filter.channel_code,
        )
        items = [
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-moderation-message-language-menu",
                    channel=current_name,
                ),
                id="message_language_heading",
                read_only=True,
            )
        ]
        all_languages = Localization.get(
            user.locale,
            "admin-moderation-message-language-all",
        )
        items.append(
            MenuItem(
                text=(
                    Localization.get(
                        user.locale,
                        "admin-moderation-message-filter-current",
                        value=all_languages,
                    )
                    if history_filter.channel_code is None
                    else all_languages
                ),
                id="message_language_all",
            )
        )
        for channel in GLOBAL_CHAT_CHANNELS:
            channel_name = self._moderation_channel_name(
                user.locale,
                channel.code,
            )
            items.append(
                MenuItem(
                    text=(
                        Localization.get(
                            user.locale,
                            "admin-moderation-message-filter-current",
                            value=channel_name,
                        )
                        if history_filter.channel_code == channel.code
                        else channel_name
                    ),
                    id=f"message_language_{channel.code}",
                )
            )
        items.append(MenuItem(text=Localization.get(user.locale, "back"), id="back"))
        user.show_menu(
            ADMIN_MODERATION_MESSAGE_LANGUAGE_MENU,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {
            "menu": ADMIN_MODERATION_MESSAGE_LANGUAGE_MENU,
            "message_channel": history_filter.channel_code,
            "message_period": history_filter.period,
            "message_sort": history_filter.sort_order,
        }

    def _show_moderation_message_period_menu(
        self,
        user: NetworkUser,
        channel_code: str | None = None,
        period: str = "all",
        sort_order: str = "newest",
    ) -> None:
        """Show the UTC time facet for the global message browser."""
        history_filter = GlobalChatHistoryFilter.from_values(
            channel_code=channel_code,
            period=period,
            sort_order=sort_order,
        )
        current_name = self._moderation_message_period_name(
            user.locale,
            history_filter.period,
        )
        items = [
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-moderation-message-period-menu",
                    period=current_name,
                ),
                id="message_period_heading",
                read_only=True,
            )
        ]
        for period_code in GLOBAL_CHAT_HISTORY_PERIODS:
            period_name = self._moderation_message_period_name(
                user.locale,
                period_code,
            )
            items.append(
                MenuItem(
                    text=(
                        Localization.get(
                            user.locale,
                            "admin-moderation-message-filter-current",
                            value=period_name,
                        )
                        if history_filter.period == period_code
                        else period_name
                    ),
                    id=f"message_period_{period_code}",
                )
            )
        items.append(MenuItem(text=Localization.get(user.locale, "back"), id="back"))
        user.show_menu(
            ADMIN_MODERATION_MESSAGE_PERIOD_MENU,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {
            "menu": ADMIN_MODERATION_MESSAGE_PERIOD_MENU,
            "message_channel": history_filter.channel_code,
            "message_period": history_filter.period,
            "message_sort": history_filter.sort_order,
        }

    def _apply_moderation_message_filter(
        self,
        user: NetworkUser,
        history_filter: GlobalChatHistoryFilter,
    ) -> None:
        """Apply a child selector value and restore its message-list parent."""
        state = self.server.user_states.get(user.username, {})
        stack = list(state.get("_stack", []))
        if not stack or stack[-1].get("menu") != ADMIN_MODERATION_MESSAGES_MENU:
            self._return_to_admin_root(user, "moderation")
            return
        parent = dict(stack[-1])
        parent.update(
            {
                "message_channel": history_filter.channel_code,
                "message_period": history_filter.period,
                "message_sort": history_filter.sort_order,
                "moderation_page": 1,
            }
        )
        stack[-1] = parent
        state["_stack"] = stack
        self.server._nav_back(user)

    def _show_moderation_clear_confirm_menu(
        self, user: NetworkUser, clear_kind: str
    ) -> None:
        """Require a developer-only confirmation before deleting evidence."""
        if not self._require_developer_moderation_access(user):
            return
        if clear_kind == "history":
            count = self.server.db.count_global_chat_messages()
            open_reports = self.server.db.count_moderation_reports(status="open")
            prompt_key = "admin-moderation-clear-history-confirm"
            prompt_kwargs = {"count": count, "open": open_reports}
        elif clear_kind == "closed_reports":
            count = self.server.db.count_moderation_reports(
                statuses=CLOSED_REPORT_STATUSES
            )
            prompt_key = "admin-moderation-clear-closed-confirm"
            prompt_kwargs = {"count": count}
        else:
            self._return_to_admin_root(user, "moderation")
            return
        show_confirmation_menu(
            user,
            ADMIN_MODERATION_CLEAR_CONFIRM_MENU,
            prompt_key=prompt_key,
            prompt_kwargs=prompt_kwargs,
            confirm_choice=ConfirmationChoice("confirm", "confirm-yes"),
            cancel_choice=ConfirmationChoice("back", "confirm-no"),
            buffer="system",
        )
        self.server.user_states[user.username] = {
            "menu": ADMIN_MODERATION_CLEAR_CONFIRM_MENU,
            "moderation_clear_kind": clear_kind,
        }

    # ==================== Menu Display Functions ====================

    def _show_admin_menu(self, user: NetworkUser) -> None:
        """Show administration menu compacted into logical submenus."""
        items = [
            MenuItem(
                text=Localization.get(user.locale, "admin-section-users"),
                id="admin_users",
                description_key="admin-desc-section-users",
            ),
            MenuItem(
                text=Localization.get(user.locale, "admin-section-moderation"),
                id="admin_moderation",
                description_key="admin-desc-section-moderation",
            ),
            MenuItem(
                text=Localization.get(user.locale, "admin-section-server-content"),
                id="admin_server_content",
                description_key="admin-desc-section-server-content",
            ),
        ]
        if user.trust_level >= DEVELOPER_TRUST_LEVEL:
            items.append(
                MenuItem(
                    text=Localization.get(user.locale, "admin-section-system"),
                    id="admin_system",
                    description_key="admin-desc-section-system",
                )
            )
        items.append(
            MenuItem(
                text=Localization.get(user.locale, "admin-switch-server"),
                id="switch_server",
                description_key="admin-desc-switch-server",
            )
        )
        items.append(MenuItem(text=Localization.get(user.locale, "back"), id="back"))
        user.show_menu(
            "admin_menu",
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {"menu": "admin_menu"}

    def _show_admin_users_menu(self, user: NetworkUser) -> None:
        """Show user and account administration submenu."""
        items = [
            MenuItem(
                text=Localization.get(user.locale, "account-approval"),
                id="account_approval",
            ),
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-account-approval-toggle",
                    status=Localization.get(
                        user.locale,
                        "option-on"
                        if self.server.account_approval_required
                        else "option-off",
                    ),
                ),
                id="toggle_account_approval",
                description_key="admin-desc-account-approval-toggle",
            ),
            MenuItem(
                text=Localization.get(user.locale, "admin-pending-nick-changes"),
                id="pending_nick_changes",
                description_key="admin-desc-pending-nick-changes",
            ),
            MenuItem(
                text=Localization.get(user.locale, "promote-admin"),
                id="promote_admin",
            ),
            MenuItem(
                text=Localization.get(user.locale, "demote-admin"),
                id="demote_admin",
            ),
            MenuItem(
                text=Localization.get(user.locale, "admin-grant-coins"),
                id="grant_coins",
                description_key="admin-desc-grant-coins",
            ),
            MenuItem(text=Localization.get(user.locale, "back"), id="back"),
        ]
        user.show_menu(
            ADMIN_USERS_MENU,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {"menu": ADMIN_USERS_MENU}

    def _show_admin_sanctions_menu(self, user: NetworkUser) -> None:
        """Show moderation and sanctions administration submenu."""
        items = [
            MenuItem(
                text=Localization.get(user.locale, "admin-moderation"),
                id="moderation",
            ),
            MenuItem(
                text=Localization.get(user.locale, "kick-user"),
                id="kick_user",
            ),
            MenuItem(
                text=Localization.get(user.locale, "mute-user"),
                id="mute_user",
            ),
            MenuItem(
                text=Localization.get(user.locale, "unmute-user"),
                id="unmute_user",
            ),
            MenuItem(
                text=Localization.get(user.locale, "ban-user"),
                id="ban_user",
            ),
            MenuItem(
                text=Localization.get(user.locale, "unban-user"),
                id="unban_user",
            ),
            MenuItem(text=Localization.get(user.locale, "back"), id="back"),
        ]
        user.show_menu(
            ADMIN_SANCTIONS_MENU,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {"menu": ADMIN_SANCTIONS_MENU}

    def _show_admin_server_content_menu(self, user: NetworkUser) -> None:
        """Show server and content administration submenu."""
        items = [
            MenuItem(
                text=Localization.get(user.locale, "broadcast-announcement"),
                id="broadcast_announcement",
            ),
            MenuItem(
                text=Localization.get(user.locale, "manage-motd"),
                id="manage_motd",
            ),
            MenuItem(
                text=Localization.get(user.locale, "admin-sound-settings"),
                id="sound_settings",
                description_key="admin-desc-sound-settings",
            ),
            MenuItem(
                text=Localization.get(user.locale, "admin-infiltrado-words"),
                id="manage_infiltrado_words",
                description_key="admin-desc-infiltrado-words",
            ),
            MenuItem(text=Localization.get(user.locale, "back"), id="back"),
        ]
        user.show_menu(
            ADMIN_SERVER_CONTENT_MENU,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {"menu": ADMIN_SERVER_CONTENT_MENU}

    def _show_admin_system_menu(self, user: NetworkUser) -> None:
        """Show developer-only system maintenance submenu."""
        if user.trust_level < DEVELOPER_TRUST_LEVEL:
            user.speak_l("dev-only-action", buffer="system")
            self.server._nav_back(user)
            return
        items = [
            MenuItem(
                text=Localization.get(user.locale, "server-power-management"),
                id="server_power",
            ),
            MenuItem(
                text=Localization.get(user.locale, "admin-database-management"),
                id="database_management",
            ),
            MenuItem(
                text=Localization.get(user.locale, "admin-smtp-settings"),
                id="smtp_settings",
            ),
            MenuItem(text=Localization.get(user.locale, "back"), id="back"),
        ]
        user.show_menu(
            ADMIN_SYSTEM_MENU,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {"menu": ADMIN_SYSTEM_MENU}

    def _pending_users_page(self, page: int) -> PaginatedMenuPage[Any]:
        total = self.server.db.count_pending_users()
        safe_page = clamp_page(page, total, ADMIN_TARGET_PAGE_SIZE)
        offset = (safe_page - 1) * ADMIN_TARGET_PAGE_SIZE
        return PaginatedMenuPage(
            items=self.server.db.get_pending_users(
                limit=ADMIN_TARGET_PAGE_SIZE,
                offset=offset,
            ),
            total=total,
            page=safe_page,
            page_size=ADMIN_TARGET_PAGE_SIZE,
        )

    def refresh_account_approval_menus(self, *, exclude_username: str = "") -> None:
        """Refresh open account-approval lists after the pending queue changes."""
        for username, user in self.server.users.items():
            if username == exclude_username:
                continue
            state = self.server.user_states.get(username, {})
            if state.get("menu") != "account_approval_menu":
                continue
            self.server._nav_refresh(
                user,
                self._show_account_approval_menu,
                state.get("account_approval_page", 1),
            )

    def _show_account_approval_menu(
        self, user: NetworkUser, page: int = 1, *, focus_page_start: bool = False
    ) -> None:
        """Show account approval menu with pending users."""
        pending = self._pending_users_page(page)

        items = []
        focus_position: int | None = None
        if not pending.items:
            items.append(MenuItem(text=Localization.get(user.locale, "no-pending-accounts"), id=""))
            items.extend(
                pagination_menu_items(user.locale, pending, include_refresh=True)
            )
        else:
            if focus_page_start:
                focus_position = len(items) + 1
            for pending_user in pending.items:
                items.append(MenuItem(text=pending_user.username, id=f"pending_{pending_user.username}"))
            if pending.total_pages > 1:
                items.append(
                    MenuItem(
                        text=Localization.get(
                            user.locale,
                            "menu-page-summary",
                            start=pending.start_index,
                            end=pending.end_index,
                            total=pending.total,
                            page=pending.page,
                            pages=pending.total_pages,
                        ),
                        id="page_summary",
                        read_only=True,
                    )
                )
            items.extend(
                pagination_menu_items(user.locale, pending, include_refresh=True)
            )
        items.append(MenuItem(text=Localization.get(user.locale, "back"), id="back"))

        user.show_menu(
            "account_approval_menu",
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
            position=focus_position,
        )
        self.server.user_states[user.username] = {
            "menu": "account_approval_menu",
            "account_approval_page": pending.page,
            "account_approval_page_count": pending.total_pages,
        }

    def _show_pending_user_actions_menu(self, user: NetworkUser, pending_username: str) -> None:
        """Show actions for a pending user (approve, decline)."""
        items = [
            MenuItem(text=Localization.get(user.locale, "approve-account"), id="approve"),
            MenuItem(text=Localization.get(user.locale, "decline-account"), id="decline"),
            MenuItem(text=Localization.get(user.locale, "back"), id="back"),
        ]
        user.show_menu(
            "pending_user_actions_menu",
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {
            "menu": "pending_user_actions_menu",
            "pending_username": pending_username,
        }

    def _pending_nick_requests_page(self, page: int) -> PaginatedMenuPage[Any]:
        total = self.server.db.count_pending_nick_requests()
        safe_page = clamp_page(page, total, ADMIN_TARGET_PAGE_SIZE)
        offset = (safe_page - 1) * ADMIN_TARGET_PAGE_SIZE
        return PaginatedMenuPage(
            items=self.server.db.list_pending_nick_requests(
                limit=ADMIN_TARGET_PAGE_SIZE,
                offset=offset,
            ),
            total=total,
            page=safe_page,
            page_size=ADMIN_TARGET_PAGE_SIZE,
        )

    def refresh_pending_nick_changes_menus(self, *, exclude_username: str = "") -> None:
        """Refresh open pending nick-change menus after the queue changes."""
        for username, user in self.server.users.items():
            if username == exclude_username:
                continue
            state = self.server.user_states.get(username, {})
            if state.get("menu") != ADMIN_NICK_CHANGES_MENU:
                continue
            self.server._nav_refresh(
                user,
                self._show_pending_nick_changes_menu,
                state.get("nick_changes_page", 1),
            )

    def _show_pending_nick_changes_menu(
        self, user: NetworkUser, page: int = 1, *, focus_page_start: bool = False
    ) -> None:
        """Show paginated menu of pending user nick-change requests."""
        pending = self._pending_nick_requests_page(page)
        items: list[MenuItem] = []
        focus_position: int | None = None
        if not pending.items:
            items.append(
                MenuItem(
                    text=Localization.get(user.locale, "admin-no-pending-nick-changes"),
                    id="",
                    read_only=True,
                )
            )
            items.extend(
                pagination_menu_items(user.locale, pending, include_refresh=True)
            )
        else:
            if focus_page_start:
                focus_position = len(items) + 1
            for req in pending.items:
                collisions = self.server.db.find_nick_collision_usernames(
                    req.requested_username,
                    exclude_uuid=req.user_uuid,
                )
                if req.coins_paid > 0 and collisions:
                    row_text = Localization.get(
                        user.locale,
                        "admin-nick-change-row-paid-collision",
                        old_nick=req.old_username,
                        new_nick=req.requested_username,
                        coins=req.coins_paid,
                        collision=", ".join(collisions),
                    )
                elif req.coins_paid > 0:
                    row_text = Localization.get(
                        user.locale,
                        "admin-nick-change-row-paid",
                        old_nick=req.old_username,
                        new_nick=req.requested_username,
                        coins=req.coins_paid,
                    )
                elif collisions:
                    row_text = Localization.get(
                        user.locale,
                        "admin-nick-change-row-collision",
                        old_nick=req.old_username,
                        new_nick=req.requested_username,
                        collision=", ".join(collisions),
                    )
                else:
                    row_text = Localization.get(
                        user.locale,
                        "admin-nick-change-row",
                        old_nick=req.old_username,
                        new_nick=req.requested_username,
                    )
                items.append(
                    MenuItem(
                        text=row_text,
                        id=f"nick_req_{req.id}",
                    )
                )
            if pending.total_pages > 1:
                items.append(
                    MenuItem(
                        text=Localization.get(
                            user.locale,
                            "menu-page-summary",
                            start=pending.start_index,
                            end=pending.end_index,
                            total=pending.total,
                            page=pending.page,
                            pages=pending.total_pages,
                        ),
                        id="page_summary",
                        read_only=True,
                    )
                )
            items.extend(
                pagination_menu_items(user.locale, pending, include_refresh=True)
            )
        items.append(MenuItem(text=Localization.get(user.locale, "back"), id="back"))
        user.show_menu(
            ADMIN_NICK_CHANGES_MENU,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
            position=focus_position,
        )
        self.server.user_states[user.username] = {
            "menu": ADMIN_NICK_CHANGES_MENU,
            "nick_changes_page": pending.page,
            "nick_changes_page_count": pending.total_pages,
        }

    def _show_pending_nick_change_actions_menu(
        self, user: NetworkUser, request_id: int
    ) -> None:
        """Show details and actions (validate, reject) for one pending nick change request."""
        req = self.server.db.get_nick_change_request(request_id)
        if req is None or req.status != "pending":
            user.speak_l("admin-nick-error-not-pending", buffer="system")
            self.server._nav_back(user)
            return

        collisions = self.server.db.find_nick_collision_usernames(
            req.requested_username,
            exclude_uuid=req.user_uuid,
        )
        items: list[MenuItem] = [
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-nick-detail-summary",
                    old_nick=req.old_username,
                    new_nick=req.requested_username,
                ),
                id="nick_detail_summary",
                read_only=True,
            ),
            MenuItem(
                text=(
                    Localization.get(
                        user.locale,
                        "admin-nick-detail-paid",
                        coins=req.coins_paid,
                    )
                    if req.coins_paid > 0
                    else Localization.get(user.locale, "admin-nick-detail-free")
                ),
                id="nick_detail_paid",
                read_only=True,
            ),
        ]
        if collisions:
            collision_str = ", ".join(collisions)
            items.append(
                MenuItem(
                    text=Localization.get(
                        user.locale,
                        "admin-nick-detail-collision-warning",
                        collision=collision_str,
                    ),
                    id="nick_detail_collision",
                    read_only=True,
                )
            )
            user.speak_l(
                "admin-nick-detail-collision-warning",
                buffer="system",
                collision=collision_str,
            )

        items.extend(
            [
                MenuItem(
                    text=Localization.get(user.locale, "admin-nick-approve"),
                    id="approve",
                ),
                MenuItem(
                    text=Localization.get(user.locale, "admin-nick-reject"),
                    id="reject",
                ),
                MenuItem(text=Localization.get(user.locale, "back"), id="back"),
            ]
        )
        user.show_menu(
            ADMIN_NICK_CHANGE_ACTIONS_MENU,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {
            "menu": ADMIN_NICK_CHANGE_ACTIONS_MENU,
            "nick_request_id": int(request_id),
        }

    def _show_pending_nick_reject_refund_menu(
        self, user: NetworkUser, request_id: int, reason: str
    ) -> None:
        """Ask the admin whether to refund the 30,000 coins when rejecting a paid nick change."""
        req = self.server.db.get_nick_change_request(request_id)
        if req is None or req.status != "pending":
            user.speak_l("admin-nick-error-not-pending", buffer="system")
            self.server._nav_back(user)
            return

        items = [
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-nick-reject-refund-prompt",
                    player=req.old_username,
                    coins=req.coins_paid,
                ),
                id="nick_reject_refund_prompt",
                read_only=True,
            ),
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-nick-reject-with-refund",
                    coins=req.coins_paid,
                ),
                id="reject_refund",
            ),
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-nick-reject-without-refund",
                ),
                id="reject_no_refund",
            ),
            MenuItem(text=Localization.get(user.locale, "back"), id="back"),
        ]
        user.show_menu(
            ADMIN_NICK_REJECT_REFUND_MENU,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {
            "menu": ADMIN_NICK_REJECT_REFUND_MENU,
            "nick_request_id": int(request_id),
            "reject_reason": reason,
        }

    def _show_promote_admin_menu(
        self,
        user: NetworkUser,
        query: str = "",
        page: int = 1,
        *,
        focus_page_start: bool = False,
    ) -> None:
        """Show searchable promote-admin targets."""
        self._show_admin_target_menu(
            user,
            menu_id="promote_admin_menu",
            mode="promote",
            action_prefix="promote",
            targets=self._search_promote_targets(query, page),
            empty_key="no-users-to-promote",
            query=query,
            focus_page_start=focus_page_start,
        )

    def _show_demote_admin_menu(
        self,
        user: NetworkUser,
        query: str = "",
        page: int = 1,
        *,
        focus_page_start: bool = False,
    ) -> None:
        """Show searchable demote-admin targets."""
        self._show_admin_target_menu(
            user,
            menu_id="demote_admin_menu",
            mode="demote",
            action_prefix="demote",
            targets=self._search_demote_targets(user, query, page),
            empty_key="no-admins-to-demote",
            query=query,
            focus_page_start=focus_page_start,
        )

    def _show_promote_confirm_menu(self, user: NetworkUser, target_username: str) -> None:
        """Show confirmation menu for promoting a user to admin."""
        show_confirmation_menu(
            user,
            "promote_confirm_menu",
            prompt_key="confirm-promote",
            prompt_kwargs={"player": target_username},
            buffer="system",
        )
        self.server.user_states[user.username] = {
            "menu": "promote_confirm_menu",
            "target_username": target_username,
        }

    def _show_demote_confirm_menu(self, user: NetworkUser, target_username: str) -> None:
        """Show confirmation menu for demoting an admin."""
        show_confirmation_menu(
            user,
            "demote_confirm_menu",
            prompt_key="confirm-demote",
            prompt_kwargs={"player": target_username},
            buffer="system",
        )
        self.server.user_states[user.username] = {
            "menu": "demote_confirm_menu",
            "target_username": target_username,
        }

    def _show_broadcast_choice_menu(self, user: NetworkUser, action: str, target_username: str) -> None:
        """Show menu to choose broadcast audience (all users, admins only, or nobody/silent)."""
        items = [
            MenuItem(text=Localization.get(user.locale, "broadcast-to-all"), id="all"),
            MenuItem(text=Localization.get(user.locale, "broadcast-to-admins"), id="admins"),
            MenuItem(text=Localization.get(user.locale, "broadcast-to-nobody"), id="nobody"),
            MenuItem(text=Localization.get(user.locale, "back"), id="back"),
        ]
        user.show_menu(
            "broadcast_choice_menu",
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {
            "menu": "broadcast_choice_menu",
            "action": action,  # "promote" or "demote"
            "target_username": target_username,
        }

    # ==================== Menu Selection Handlers ====================

    async def handle_menu_selection(
        self, user: NetworkUser, selection_id: str, current_menu: str, state: dict[str, Any]
    ) -> None:
        """Main entry point for handling admin-related menu selections."""
        if current_menu == "admin_menu":
            await self._handle_admin_menu_selection(user, selection_id)
        elif current_menu in (
            ADMIN_USERS_MENU,
            ADMIN_SANCTIONS_MENU,
            ADMIN_SERVER_CONTENT_MENU,
            ADMIN_SYSTEM_MENU,
        ):
            await self._handle_admin_submenu_selection(user, selection_id, current_menu)
        elif current_menu == ADMIN_MODERATION_MENU:
            await self._handle_moderation_selection(user, selection_id)
        elif current_menu == ADMIN_MODERATION_REPORTS_MENU:
            await self._handle_moderation_reports_selection(
                user, selection_id, state
            )
        elif current_menu == ADMIN_MODERATION_REPORT_DETAIL_MENU:
            await self._handle_moderation_report_detail_selection(
                user, selection_id, state
            )
        elif current_menu == ADMIN_MODERATION_CONTEXT_MENU:
            await self._handle_moderation_context_selection(
                user, selection_id, state
            )
        elif current_menu == ADMIN_MODERATION_SENDER_RESULTS_MENU:
            await self._handle_moderation_sender_results_selection(
                user, selection_id, state
            )
        elif current_menu == ADMIN_MODERATION_HISTORY_MENU:
            await self._handle_moderation_history_selection(
                user, selection_id, state
            )
        elif current_menu == ADMIN_MODERATION_MESSAGES_MENU:
            await self._handle_moderation_messages_selection(
                user, selection_id, state
            )
        elif current_menu == ADMIN_MODERATION_MESSAGE_LANGUAGE_MENU:
            await self._handle_moderation_message_language_selection(
                user, selection_id, state
            )
        elif current_menu == ADMIN_MODERATION_MESSAGE_PERIOD_MENU:
            await self._handle_moderation_message_period_selection(
                user, selection_id, state
            )
        elif current_menu == ADMIN_MODERATION_CLEAR_CONFIRM_MENU:
            await self._handle_moderation_clear_confirm_selection(
                user, selection_id, state
            )
        elif current_menu == ADMIN_DATABASE_MENU:
            await self._handle_database_management_selection(
                user, selection_id
            )
        elif current_menu == ADMIN_DATABASE_BACKUP_CONFIRM_MENU:
            await self._handle_database_backup_confirm_selection(
                user, selection_id
            )
        elif current_menu == ADMIN_DATABASE_STORAGE_ANALYSIS_MENU:
            await self._handle_database_storage_analysis_selection(
                user, selection_id
            )
        elif current_menu == ADMIN_DATABASE_STORAGE_CLEANUP_CONFIRM_MENU:
            await self._handle_database_storage_cleanup_confirm_selection(
                user, selection_id
            )
        elif current_menu == ADMIN_DATABASE_COMPACT_CONFIRM_MENU:
            await self._handle_database_compact_confirm_selection(
                user, selection_id
            )
        elif current_menu == ADMIN_SOUND_EVENTS_MENU:
            await self._handle_sound_events_menu_selection(user, selection_id)
        elif current_menu == ADMIN_SOUND_PICKER_MENU:
            await self._handle_sound_picker_menu_selection(user, selection_id)
        elif current_menu == "account_approval_menu":
            await self._handle_account_approval_selection(user, selection_id, state)
        elif current_menu == "pending_user_actions_menu":
            await self._handle_pending_user_actions_selection(user, selection_id, state)
        elif current_menu == ADMIN_NICK_CHANGES_MENU:
            await self._handle_pending_nick_changes_selection(user, selection_id, state)
        elif current_menu == ADMIN_NICK_CHANGE_ACTIONS_MENU:
            await self._handle_pending_nick_change_actions_selection(
                user, selection_id, state
            )
        elif current_menu == ADMIN_NICK_REJECT_REFUND_MENU:
            await self._handle_pending_nick_reject_refund_selection(
                user, selection_id, state
            )
        elif current_menu == "promote_admin_menu":
            await self._handle_promote_admin_selection(user, selection_id, state)
        elif current_menu == "demote_admin_menu":
            await self._handle_demote_admin_selection(user, selection_id, state)
        elif current_menu == "promote_confirm_menu":
            await self._handle_promote_confirm_selection(user, selection_id, state)
        elif current_menu == "demote_confirm_menu":
            await self._handle_demote_confirm_selection(user, selection_id, state)
        elif current_menu == "kick_menu":
             await self._handle_kick_selection(user, selection_id, state)
        elif current_menu == "kick_confirm_menu":
             await self._handle_kick_confirm_selection(user, selection_id, state)
        elif current_menu == "broadcast_choice_menu":
            await self._handle_broadcast_choice_selection(user, selection_id, state)
        elif current_menu == "ban_menu":
             await self._handle_ban_selection(user, selection_id, state)
        elif current_menu == "ban_duration_menu":
             await self._handle_ban_duration_selection(user, selection_id, state)
        elif current_menu == "ban_reason_menu":
             await self._handle_ban_reason_selection(user, selection_id, state)
        elif current_menu == "unban_menu":
             await self._handle_unban_selection(user, selection_id, state)
        elif current_menu == "mute_menu":
             await self._handle_mute_selection(user, selection_id, state)
        elif current_menu == "mute_duration_menu":
             await self._handle_mute_duration_selection(user, selection_id, state)
        elif current_menu == "mute_reason_menu":
             await self._handle_mute_reason_selection(user, selection_id, state)
        elif current_menu == "unmute_menu":
             await self._handle_unmute_selection(user, selection_id, state)
        elif current_menu == GRANT_COINS_MENU:
             await self._handle_grant_coins_selection(user, selection_id, state)
        elif current_menu == GRANT_COINS_AMOUNT_MENU:
             await self._handle_grant_coins_amount_selection(user, selection_id, state)
        elif current_menu == "manage_motd_menu":
             await self._handle_manage_motd_selection(user, selection_id, state)
        elif current_menu == "view_motd_menu":
             if selection_id == "back":
                 self.server._nav_back(user)
        elif current_menu == "server_power_menu":
             await self._handle_server_power_selection(user, selection_id, state)
        elif current_menu == "server_power_delay_menu":
             await self._handle_server_power_delay_selection(user, selection_id, state)
        elif current_menu == "server_power_reason_menu":
             await self._handle_server_power_reason_selection(user, selection_id, state)
        elif current_menu == "server_power_confirm_menu":
             await self._handle_server_power_confirm_selection(user, selection_id, state)
        elif current_menu == ADMIN_LOCALIZED_TEXT_MENU:
             await self._handle_admin_localized_text_selection(user, selection_id, state)
        elif current_menu == "smtp_settings_menu":
             await self._handle_smtp_settings_selection(user, selection_id)
        elif current_menu == "smtp_encryption_menu":
             await self._handle_smtp_encryption_selection(user, selection_id)
        elif current_menu == ADMIN_INFILTRADO_WORDS_MENU:
             await self._handle_infiltrado_words_selection(user, selection_id, state)
        elif current_menu == ADMIN_INFILTRADO_PAIRS_LIST_MENU:
             await self._handle_infiltrado_pairs_list_selection(user, selection_id, state)
        elif current_menu == ADMIN_INFILTRADO_PAIR_DETAIL_MENU:
             await self._handle_infiltrado_pair_detail_selection(user, selection_id, state)
        elif current_menu == ADMIN_INFILTRADO_CATEGORIES_MENU:
             await self._handle_infiltrado_categories_selection(user, selection_id, state)
        elif current_menu == ADMIN_INFILTRADO_CATEGORY_DETAIL_MENU:
             await self._handle_infiltrado_category_detail_selection(user, selection_id, state)
        elif current_menu == ADMIN_INFILTRADO_SELECT_CATEGORY_MENU:
             await self._handle_infiltrado_select_category_selection(user, selection_id, state)
        elif current_menu == ADMIN_INFILTRADO_DELETE_CATEGORY_CONFIRM_MENU:
             await self._handle_infiltrado_delete_category_confirm_selection(user, selection_id, state)

    async def _handle_admin_submenu_selection(
        self, user: NetworkUser, selection_id: str, current_menu: str
    ) -> None:
        """Handle selection in an admin submenu."""
        if selection_id == "back":
            self.server._nav_back(user)
            return
        if selection_id == "toggle_account_approval":
            new_value = not self.server.account_approval_required
            self.server.set_account_approval_required(new_value)
            status_text = Localization.get(
                user.locale,
                "option-on" if new_value else "option-off",
            )
            user.speak_l(
                "admin-account-approval-toggle-feedback",
                buffer="system",
                status=status_text,
            )
            user.play_sound("menuenter.ogg")
            self._show_admin_users_menu(user)
            return
        await self._handle_admin_menu_selection(user, selection_id)

    async def _handle_admin_menu_selection(
        self, user: NetworkUser, selection_id: str
    ) -> None:
        """Handle admin menu selection."""
        if selection_id == "admin_users":
            self.server._nav_push(user, self._show_admin_users_menu)
        elif selection_id in ("admin_moderation", "admin_sanctions"):
            self.server._nav_push(user, self._show_admin_sanctions_menu)
        elif selection_id == "admin_server_content":
            self.server._nav_push(user, self._show_admin_server_content_menu)
        elif selection_id == "admin_system":
            if user.trust_level >= DEVELOPER_TRUST_LEVEL:
                self.server._nav_push(user, self._show_admin_system_menu)
            else:
                user.speak_l("dev-only-action", buffer="system")
                self.server._nav_refresh(user, self._show_admin_menu)
        elif selection_id == "account_approval":
            if self.server.db.count_pending_users() == 0:
                user.speak_l("no-pending-accounts", buffer="system")
                return
            self.server._nav_push(user, self._show_account_approval_menu)
        elif selection_id == "pending_nick_changes":
            if self.server.db.count_pending_nick_requests() == 0:
                user.speak_l("admin-no-pending-nick-changes", buffer="system")
                return
            self.server._nav_push(user, self._show_pending_nick_changes_menu)
        elif selection_id == "toggle_account_approval":
            new_value = not self.server.account_approval_required
            self.server.set_account_approval_required(new_value)
            status_text = Localization.get(
                user.locale,
                "option-on" if new_value else "option-off",
            )
            user.speak_l(
                "admin-account-approval-toggle-feedback",
                buffer="system",
                status=status_text,
            )
            user.play_sound("menuenter.ogg")
            self._show_admin_menu(user)
        elif selection_id == "moderation":
            self.server._nav_push(user, self._show_moderation_menu)
        elif selection_id == "promote_admin":
            if self._search_promote_targets("", 1).total == 0:
                user.speak_l("no-users-to-promote", buffer="system")
                return
            self.server._nav_push(user, self._show_promote_admin_menu)
        elif selection_id == "demote_admin":
            if self._search_demote_targets(user, "", 1).total == 0:
                user.speak_l("no-admins-to-demote", buffer="system")
                return
            self.server._nav_push(user, self._show_demote_admin_menu)
        elif selection_id == "ban_user":
            if self._search_ban_targets(user, "", 1).total == 0:
                user.speak_l("no-users-to-ban", buffer="system")
                return
            self.server._nav_push(user, self._show_ban_menu)
        elif selection_id == "unban_user":
            if self.server.db.count_active_banned_users("") == 0:
                user.speak_l("no-banned-users", buffer="system")
                return
            self.server._nav_push(user, self._show_unban_menu)
        elif selection_id == "mute_user":
            if self._search_mute_targets(user, "", 1).total == 0:
                user.speak_l("no-users-to-mute", buffer="system")
                return
            self.server._nav_push(user, self._show_mute_menu)
        elif selection_id == "unmute_user":
            if self.server.db.count_active_muted_users("") == 0:
                user.speak_l("no-muted-users", buffer="system")
                return
            self.server._nav_push(user, self._show_unmute_menu)
        elif selection_id == "kick_user":
            if self._search_kick_targets(user, "", 1).total == 0:
                user.speak_l("no-users-to-kick", buffer="system")
                return
            self.server._nav_push(user, self._show_kick_menu)
        elif selection_id == "grant_coins":
            if self._search_grant_coins_targets(user, "", 1).total == 0:
                user.speak_l("admin-grant-coins-no-users", buffer="system")
                return
            self.server._nav_push(user, self._show_grant_coins_menu)
        elif selection_id == "broadcast_announcement":
            self._show_broadcast_input_menu(user)
        elif selection_id == "manage_motd":
            self.server._nav_push(user, self._show_manage_motd_menu)
        elif selection_id == "server_power":
            if user.trust_level >= DEVELOPER_TRUST_LEVEL:
                self.server._nav_push(user, self._show_server_power_menu)
            else:
                user.speak_l("dev-only-action", buffer="system")
                self.server._nav_refresh(user, self._show_admin_menu)
        elif selection_id == "database_management":
            if user.trust_level >= DEVELOPER_TRUST_LEVEL:
                self.server._nav_push(
                    user,
                    self._show_database_management_menu,
                )
            else:
                user.speak_l("dev-only-action", buffer="system")
                self.server._nav_refresh(user, self._show_admin_menu)
        elif selection_id == "smtp_settings":
            if user.trust_level >= DEVELOPER_TRUST_LEVEL:
                self.server._nav_push(user, self._show_smtp_settings_menu)
            else:
                user.speak_l("dev-only-action", buffer="system")
                self.server._nav_refresh(user, self._show_admin_menu)
        elif selection_id == "sound_settings":
            if user.trust_level < ADMIN_TRUST_LEVEL:
                user.speak_l("admin-only-action", buffer="system")
                return
            self.server._nav_push(user, self._show_sound_events_menu)
        elif selection_id == "manage_infiltrado_words":
            if user.trust_level < ADMIN_TRUST_LEVEL:
                user.speak_l("admin-only-action", buffer="system")
                return
            self.server._nav_push(user, self._show_infiltrado_words_menu)
        elif selection_id == "switch_server":
            await self.server._complete_switch_server(user)
        elif selection_id == "back":
            self.server._nav_back(user)

    def _show_sound_events_menu(self, user: NetworkUser) -> None:
        """Show menu of configurable sound events."""
        if user.trust_level < ADMIN_TRUST_LEVEL:
            user.speak_l("admin-only-action", buffer="system")
            self.server._nav_back(user)
            return
        items = []
        for event_id, event_def in SOUND_EVENTS.items():
            current_sound = self.server.get_sound_for_event(event_id)
            event_name = Localization.get(user.locale, event_def.label_key)
            text = f"{event_name}: {current_sound}"
            desc_key = event_def.description_key
            items.append(
                MenuItem(
                    text=text,
                    id=event_id,
                    description_key=desc_key,
                )
            )
        items.append(MenuItem(text=Localization.get(user.locale, "back"), id="back"))
        user.show_menu(
            ADMIN_SOUND_EVENTS_MENU,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {
            "menu": ADMIN_SOUND_EVENTS_MENU,
        }

    async def _handle_sound_events_menu_selection(
        self, user: NetworkUser, selection_id: str
    ) -> None:
        """Handle selection in sound events menu."""
        if selection_id == "back":
            self.server._nav_back(user)
            return
        if selection_id in SOUND_EVENTS:
            self.server._nav_push(
                user, self._show_sound_picker_menu, selection_id
            )

    def _show_sound_picker_menu(
        self, user: NetworkUser, event_id: str
    ) -> None:
        """Show menu to pick a sound for the given event."""
        if user.trust_level < ADMIN_TRUST_LEVEL:
            user.speak_l("admin-only-action", buffer="system")
            self.server._nav_back(user)
            return
        event_def = SOUND_EVENTS.get(event_id)
        if not event_def:
            self.server._nav_back(user)
            return
        current_sound = self.server.get_sound_for_event(event_id)
        items = []
        current_tag = Localization.get(user.locale, "current-selection")
        default_tag = Localization.get(user.locale, "default-selection")
        for sound_name in AVAILABLE_SOUND_ASSETS:
            tags = []
            if sound_name == current_sound:
                tags.append(current_tag)
            if sound_name == event_def.default_sound:
                tags.append(default_tag)
            tag_str = f" ({', '.join(tags)})" if tags else ""
            items.append(
                MenuItem(
                    text=f"{sound_name}{tag_str}",
                    id=sound_name,
                    sound=sound_name,
                )
            )
        items.append(
            MenuItem(
                text=Localization.get(user.locale, "cancel"),
                id="back",
            )
        )
        user.show_menu(
            ADMIN_SOUND_PICKER_MENU,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
            selection_id=current_sound,
        )
        self.server.user_states[user.username] = {
            "menu": ADMIN_SOUND_PICKER_MENU,
            "sound_event_id": event_id,
        }

    async def _handle_sound_picker_menu_selection(
        self, user: NetworkUser, selection_id: str
    ) -> None:
        """Handle sound picker selection."""
        state = self.server.user_states.get(user.username, {})
        event_id = state.get("sound_event_id")
        if not event_id or event_id not in SOUND_EVENTS:
            self.server._nav_back(user)
            return
        if selection_id == "back":
            self.server._nav_back(user)
            return
        if selection_id in AVAILABLE_SOUND_ASSETS:
            event_def = SOUND_EVENTS[event_id]
            self.server.set_sound_for_event(event_id, selection_id)
            event_label = Localization.get(user.locale, event_def.label_key)
            user.speak_l(
                "sound-event-updated",
                buffer="system",
                event=event_label,
                sound=selection_id,
            )
            user.play_sound(selection_id, buffer="system")
            self.server._nav_back(user)

    def _require_developer_database_access(self, user: NetworkUser) -> bool:
        """Protect database maintenance at display and action time."""
        if user.trust_level >= DEVELOPER_TRUST_LEVEL:
            return True
        user.speak_l("dev-only-action", buffer="system")
        self._return_to_admin_root(user, "database_management")
        return False

    def _show_database_management_menu(self, user: NetworkUser) -> None:
        """Show the extensible developer-only database maintenance section."""
        if not self._require_developer_database_access(user):
            return
        items = [
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-database-management-summary",
                ),
                id="database_management_summary",
                read_only=True,
            ),
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-database-backup",
                ),
                id="backup_database",
            ),
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-database-storage-analyze",
                ),
                id="analyze_storage",
            ),
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-database-storage-cleanup",
                ),
                id="cleanup_storage",
            ),
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-database-compact",
                ),
                id="compact_database",
            ),
            MenuItem(text=Localization.get(user.locale, "back"), id="back"),
        ]
        user.show_menu(
            ADMIN_DATABASE_MENU,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {"menu": ADMIN_DATABASE_MENU}

    def _show_database_backup_confirm_menu(self, user: NetworkUser) -> None:
        """Confirm an exclusive, validated SQLite backup operation."""
        if not self._require_developer_database_access(user):
            return
        show_confirmation_menu(
            user,
            ADMIN_DATABASE_BACKUP_CONFIRM_MENU,
            prompt_key="admin-database-backup-confirm",
            confirm_choice=ConfirmationChoice("confirm", "confirm-yes"),
            cancel_choice=ConfirmationChoice("back", "confirm-no"),
            buffer="system",
        )
        self.server.user_states[user.username] = {
            "menu": ADMIN_DATABASE_BACKUP_CONFIRM_MENU
        }

    def _database_storage_analysis_rows(
        self,
        user: NetworkUser,
        analysis: DatabaseStorageAnalysis,
        *,
        include_all_categories: bool,
    ) -> list[MenuItem]:
        """Build stable read-only rows from one structured cleanup preview."""
        rows = [
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-database-storage-analysis-summary",
                    size=_localized_database_size(
                        user.locale,
                        analysis.database_size_bytes,
                    ),
                    reusable=_localized_database_size(
                        user.locale,
                        analysis.reusable_database_bytes,
                    ),
                    records=analysis.total_candidate_records,
                ),
                id="storage_analysis_summary",
                read_only=True,
            )
        ]
        visible_categories = (
            analysis.categories
            if include_all_categories
            else tuple(
                category for category in analysis.categories if category.count
            )
        )
        for category in visible_categories:
            label = Localization.get(
                user.locale,
                "admin-database-storage-category-"
                + category.code.replace("_", "-"),
                days=category.retention_days or 0,
            )
            rows.append(
                MenuItem(
                    text=Localization.get(
                        user.locale,
                        "admin-database-storage-category-row",
                        category=label,
                        count=category.count,
                    ),
                    id=f"storage_category_{category.code}",
                    read_only=True,
                )
            )
        if not visible_categories:
            rows.append(
                MenuItem(
                    text=Localization.get(
                        user.locale,
                        "admin-database-storage-no-record-candidates",
                    ),
                    id="storage_no_record_candidates",
                    read_only=True,
                )
            )
        rows.append(
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-database-storage-temporary-files",
                    count=analysis.incomplete_backup_file_count,
                    size=_localized_database_size(
                        user.locale,
                        analysis.incomplete_backup_file_bytes,
                    ),
                ),
                id="storage_temporary_files",
                read_only=True,
            )
        )
        if analysis.invalid_timestamp_values:
            rows.append(
                MenuItem(
                    text=Localization.get(
                        user.locale,
                        "admin-database-storage-invalid-timestamps",
                        count=analysis.invalid_timestamp_values,
                    ),
                    id="storage_invalid_timestamps",
                    read_only=True,
                )
            )
        rows.append(
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-database-storage-exclusions",
                ),
                id="storage_exclusions",
                read_only=True,
            )
        )
        return rows

    def _show_database_storage_analysis_menu(
        self,
        user: NetworkUser,
        analysis: DatabaseStorageAnalysis,
    ) -> None:
        """Show a non-mutating, refreshable storage-cleanup preview."""
        if not self._require_developer_database_access(user):
            return
        items = self._database_storage_analysis_rows(
            user,
            analysis,
            include_all_categories=True,
        )
        items.extend(
            (
                MenuItem(
                    text=Localization.get(
                        user.locale,
                        "admin-database-storage-refresh-analysis",
                    ),
                    id="refresh",
                ),
                MenuItem(text=Localization.get(user.locale, "back"), id="back"),
            )
        )
        user.show_menu(
            ADMIN_DATABASE_STORAGE_ANALYSIS_MENU,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {
            "menu": ADMIN_DATABASE_STORAGE_ANALYSIS_MENU,
            "storage_analysis": analysis,
        }

    def _show_database_storage_cleanup_confirm_menu(
        self,
        user: NetworkUser,
        analysis: DatabaseStorageAnalysis,
    ) -> None:
        """Confirm the exclusive cleanup using a recent eligibility preview."""
        if not self._require_developer_database_access(user):
            return
        show_confirmation_menu(
            user,
            ADMIN_DATABASE_STORAGE_CLEANUP_CONFIRM_MENU,
            prompt_key="admin-database-storage-cleanup-confirm",
            context_items=self._database_storage_analysis_rows(
                user,
                analysis,
                include_all_categories=False,
            ),
            confirm_choice=ConfirmationChoice("confirm", "confirm-yes"),
            cancel_choice=ConfirmationChoice("back", "confirm-no"),
            buffer="system",
        )
        self.server.user_states[user.username] = {
            "menu": ADMIN_DATABASE_STORAGE_CLEANUP_CONFIRM_MENU,
            "storage_analysis": analysis,
        }

    def _show_database_compact_confirm_menu(self, user: NetworkUser) -> None:
        """Confirm an exclusive SQLite compaction operation."""
        if not self._require_developer_database_access(user):
            return
        show_confirmation_menu(
            user,
            ADMIN_DATABASE_COMPACT_CONFIRM_MENU,
            prompt_key="admin-database-compact-confirm",
            confirm_choice=ConfirmationChoice("confirm", "confirm-yes"),
            cancel_choice=ConfirmationChoice("back", "confirm-no"),
            buffer="system",
        )
        self.server.user_states[user.username] = {
            "menu": ADMIN_DATABASE_COMPACT_CONFIRM_MENU
        }

    async def _handle_database_management_selection(
        self,
        user: NetworkUser,
        selection_id: str,
    ) -> None:
        if not self._require_developer_database_access(user):
            return
        if selection_id == "backup_database":
            self.server._nav_push(
                user,
                self._show_database_backup_confirm_menu,
            )
        elif selection_id in {"analyze_storage", "cleanup_storage"}:
            analysis = await self._analyze_database_storage(user)
            if analysis is None:
                return
            show_fn = (
                self._show_database_storage_analysis_menu
                if selection_id == "analyze_storage"
                else self._show_database_storage_cleanup_confirm_menu
            )
            self.server._nav_push(user, show_fn, analysis)
        elif selection_id == "compact_database":
            self.server._nav_push(
                user,
                self._show_database_compact_confirm_menu,
            )
        elif selection_id == "back":
            self.server._nav_back(user)

    async def _analyze_database_storage(
        self,
        user: NetworkUser,
    ) -> DatabaseStorageAnalysis | None:
        try:
            return await self.server.maintenance_manager.analyze_storage()
        except DatabaseMaintenanceBusyError:
            user.speak_l(
                "admin-database-maintenance-busy",
                buffer="system",
            )
        except Exception:
            logging.getLogger("playaural").exception(
                "Developer-requested storage analysis failed"
            )
            user.speak_l(
                "admin-database-storage-analysis-failed",
                buffer="system",
            )
        return None

    async def _handle_database_storage_analysis_selection(
        self,
        user: NetworkUser,
        selection_id: str,
    ) -> None:
        if not self._require_developer_database_access(user):
            return
        if selection_id == "back":
            self.server._nav_back(user)
            return
        if selection_id != "refresh":
            return
        analysis = await self._analyze_database_storage(user)
        if analysis is not None:
            self.server._nav_refresh(
                user,
                self._show_database_storage_analysis_menu,
                analysis,
            )

    async def _handle_database_storage_cleanup_confirm_selection(
        self,
        user: NetworkUser,
        selection_id: str,
    ) -> None:
        if not self._require_developer_database_access(user):
            return
        if selection_id == "back":
            self.server._nav_back(user)
            return
        if selection_id != "confirm":
            return

        current_analysis = await self._analyze_database_storage(user)
        if current_analysis is None:
            return
        if not current_analysis.has_candidates:
            user.speak_l(
                "admin-database-storage-cleanup-not-needed",
                buffer="system",
            )
            self.server._nav_back(user)
            return

        try:
            operation_result = await self.server.maintenance_manager.clean_storage(
                requested_by=user.username,
            )
        except DatabaseMaintenanceBusyError:
            user.speak_l(
                "admin-database-maintenance-busy",
                buffer="system",
            )
        except DatabaseMaintenanceUnavailableError:
            # The manager delivered the critical notice and deliberately keeps
            # the server frozen for operator recovery.
            pass
        except Exception:
            logging.getLogger("playaural").exception(
                "Developer-requested storage cleanup failed"
            )
            user.speak_l(
                "admin-database-storage-cleanup-failed",
                buffer="system",
            )
        else:
            result = operation_result.cleanup
            backup = operation_result.safety_backup
            user.speak_l(
                "admin-database-storage-cleanup-success",
                buffer="system",
                records=result.total_deleted_records,
                files=backup.incomplete_files_removed,
                file_size=_localized_database_size(
                    user.locale,
                    backup.incomplete_file_bytes_removed,
                ),
                reusable=_localized_database_size(
                    user.locale,
                    result.reusable_database_bytes,
                ),
                filename=(backup.archive_path or backup.path).name,
            )
        if not self.server.maintenance_manager.is_active:
            self.server._nav_back(user)

    async def _handle_database_backup_confirm_selection(
        self,
        user: NetworkUser,
        selection_id: str,
    ) -> None:
        if not self._require_developer_database_access(user):
            return
        if selection_id == "back":
            self.server._nav_back(user)
            return
        if selection_id != "confirm":
            return

        try:
            result = await self.server.maintenance_manager.back_up_database(
                requested_by=user.username,
            )
        except DatabaseMaintenanceBusyError:
            user.speak_l(
                "admin-database-maintenance-busy",
                buffer="system",
            )
        except DatabaseMaintenanceUnavailableError:
            # The manager already delivered an immediate critical notice and
            # intentionally keeps all queued output frozen.
            pass
        except Exception:
            logging.getLogger("playaural").exception(
                "Developer-requested database backup failed"
            )
            user.speak_l(
                "admin-database-backup-failed",
                buffer="system",
            )
        else:
            user.speak_l(
                "admin-database-backup-success",
                buffer="system",
                filename=(result.archive_path or result.path).name,
                size=_localized_database_size(user.locale, result.archive_size_bytes or result.size_bytes),
            )
        if not self.server.maintenance_manager.is_active:
            self.server._nav_back(user)

    async def _handle_database_compact_confirm_selection(
        self,
        user: NetworkUser,
        selection_id: str,
    ) -> None:
        if not self._require_developer_database_access(user):
            return
        if selection_id == "back":
            self.server._nav_back(user)
            return
        if selection_id != "confirm":
            return

        try:
            operation_result = await self.server.maintenance_manager.compact_database(
                requested_by=user.username,
            )
        except DatabaseMaintenanceBusyError:
            user.speak_l(
                "admin-database-maintenance-busy",
                buffer="system",
            )
        except DatabaseMaintenanceUnavailableError:
            # The manager already delivered an immediate critical notice and
            # intentionally keeps all queued output frozen.
            pass
        except Exception:
            logging.getLogger("playaural").exception(
                "Developer-requested database compaction failed"
            )
            user.speak_l(
                "admin-database-compact-failed",
                buffer="system",
            )
        else:
            result = operation_result.compaction
            user.speak_l(
                "admin-database-compact-success",
                buffer="system",
                before=_localized_database_size(user.locale, result.before_bytes),
                after=_localized_database_size(user.locale, result.after_bytes),
                reclaimed=_localized_database_size(
                    user.locale,
                    result.reclaimed_bytes,
                ),
                filename=(operation_result.safety_backup.archive_path or operation_result.safety_backup.path).name,
            )
        if not self.server.maintenance_manager.is_active:
            self.server._nav_back(user)

    async def _handle_moderation_selection(
        self, user: NetworkUser, selection_id: str
    ) -> None:
        if selection_id == 'toggle_forum':
            account = self.server.db.get_user_by_uuid(user.uuid)
            if (user.trust_level < ADMIN_TRUST_LEVEL or not account or not account.approved
                    or account.trust_level < ADMIN_TRUST_LEVEL or self.server.db.get_active_ban(account.username)):
                user.speak_l('not-admin-anymore', buffer='system')
                return
            enabled = not self.server.forum_enabled
            try:
                self.server.set_forum_enabled(enabled)
            except Exception:
                logging.getLogger('playaural').exception('Failed to persist forum availability')
                user.speak_l('forum-availability-update-failed', buffer='system')
                return
            for recipient in tuple(self.server.users.values()):
                recipient.play_sound_family('notify', buffer='system')
                recipient.speak_l('forum-availability-enabled' if enabled else 'forum-unavailable', buffer='system')
                if self.server.user_states.get(recipient.username, {}).get('menu') == ADMIN_MODERATION_MENU:
                    self.server._nav_refresh(recipient, self._show_moderation_menu)
        elif selection_id == "toggle_global_chat":
            if user.trust_level < DEVELOPER_TRUST_LEVEL:
                user.speak_l("dev-only-action", buffer="system")
                self.server._nav_refresh(user, self._show_moderation_menu)
                return
            enabled = not self.server.global_chat_sending_enabled
            try:
                self.server.set_global_chat_sending_enabled(enabled)
            except Exception:
                logging.getLogger("playaural").exception(
                    "Failed to persist the global-chat availability setting"
                )
                user.speak_l(
                    "admin-moderation-global-chat-update-failed",
                    buffer="system",
                )
                return
            announcement_key = (
                "global-chat-availability-enabled"
                if enabled
                else "global-chat-availability-disabled"
            )
            for recipient in tuple(self.server.users.values()):
                recipient.play_sound_family("notify", buffer="system")
                recipient.speak_l(announcement_key, buffer="system")
                recipient_state = self.server.user_states.get(
                    recipient.username,
                    {},
                )
                if recipient_state.get("menu") == ADMIN_MODERATION_MENU:
                    self.server._nav_refresh(
                        recipient,
                        self._show_moderation_menu,
                    )
        elif selection_id == "toggle_global_voice_chat":
            if user.trust_level < DEVELOPER_TRUST_LEVEL:
                user.speak_l("dev-only-action", buffer="system")
                self.server._nav_refresh(user, self._show_moderation_menu)
                return
            enabled = not self.server.global_voice_chat_enabled
            try:
                self.server.set_global_voice_chat_enabled(enabled)
            except Exception:
                logging.getLogger("playaural").exception(
                    "Failed to persist the global-voice-chat availability setting"
                )
                user.speak_l(
                    "admin-moderation-global-voice-chat-update-failed",
                    buffer="system",
                )
                return
            announcement_key = (
                "global-voice-chat-availability-enabled"
                if enabled
                else "global-voice-chat-availability-disabled"
            )
            for recipient in tuple(self.server.users.values()):
                recipient.play_sound_family("notify", buffer="system")
                recipient.speak_l(announcement_key, buffer="system")
                recipient_state = self.server.user_states.get(
                    recipient.username,
                    {},
                )
                if recipient_state.get("menu") == ADMIN_MODERATION_MENU:
                    self.server._nav_refresh(
                        recipient,
                        self._show_moderation_menu,
                    )
        elif selection_id == "reports_open":
            if self.server.db.count_moderation_reports(status="open") == 0:
                user.speak_l("admin-moderation-no-reports", buffer="system")
                return
            self.server._nav_push(
                user, self._show_moderation_reports_menu, "open"
            )
        elif selection_id == "reports_closed":
            if self.server.db.count_moderation_reports(statuses=CLOSED_REPORT_STATUSES) == 0:
                user.speak_l("admin-moderation-no-reports", buffer="system")
                return
            self.server._nav_push(
                user, self._show_moderation_reports_menu, "closed"
            )
        elif selection_id == "reports_all":
            if self.server.db.count_moderation_reports() == 0:
                user.speak_l("admin-moderation-no-reports", buffer="system")
                return
            self.server._nav_push(
                user, self._show_moderation_reports_menu, "all"
            )
        elif selection_id == "browse_messages":
            if self.server.db.count_global_chat_messages() == 0:
                user.speak_l("admin-moderation-message-list-empty", buffer="system")
                return
            self.server._nav_push(user, self._show_moderation_messages_menu)
        elif selection_id == "find_history":
            self._show_moderation_history_input(user)
        elif selection_id == "clear_history":
            if user.trust_level >= DEVELOPER_TRUST_LEVEL:
                self.server._nav_push(
                    user,
                    self._show_moderation_clear_confirm_menu,
                    "history",
                )
            else:
                user.speak_l("dev-only-action", buffer="system")
                self.server._nav_refresh(user, self._show_moderation_menu)
        elif selection_id == "clear_closed_reports":
            if user.trust_level >= DEVELOPER_TRUST_LEVEL:
                self.server._nav_push(
                    user,
                    self._show_moderation_clear_confirm_menu,
                    "closed_reports",
                )
            else:
                user.speak_l("dev-only-action", buffer="system")
                self.server._nav_refresh(user, self._show_moderation_menu)
        elif selection_id == "back":
            self.server._nav_back(user)

    async def _handle_moderation_reports_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        if selection_id == "back":
            self.server._nav_back(user)
            return
        report_filter = str(state.get("report_filter", "open"))
        if report_filter not in {"open", "closed", "all"}:
            report_filter = "open"
        if selection_id in MENU_PAGE_IDS:
            next_page = page_for_selection(
                selection_id,
                state.get("moderation_page", 1),
                state.get("moderation_page_count", 1),
            )
            if next_page is None:
                return
            if is_page_refresh(selection_id):
                announce_page_refresh(user)
            self.server._nav_refresh(
                user,
                self._show_moderation_reports_menu,
                report_filter,
                next_page,
                focus_page_start=is_page_navigation(selection_id),
            )
            return
        prefix = "moderation_report_"
        if not selection_id.startswith(prefix):
            return
        try:
            report_id = int(selection_id[len(prefix):])
        except ValueError:
            return
        if self.server.db.get_moderation_report(report_id) is None:
            user.speak_l(
                "admin-moderation-report-unavailable", buffer="system"
            )
            self.server._nav_refresh(
                user,
                self._show_moderation_reports_menu,
                report_filter,
                int(state.get("moderation_page", 1) or 1),
            )
            return
        self.server._nav_push(
            user, self._show_moderation_report_detail_menu, report_id
        )

    async def _handle_moderation_report_detail_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        if selection_id == "back":
            self.server._nav_back(user)
            return
        try:
            report_id = int(state.get("report_id", 0) or 0)
        except (TypeError, ValueError):
            report_id = 0
        report = self.server.db.get_moderation_report(report_id)
        if report is None:
            user.speak_l(
                "admin-moderation-report-unavailable", buffer="system"
            )
            self.server._nav_back(user)
            return
        if selection_id == "view_context":
            self.server._nav_push(
                user, self._show_moderation_context_menu, report.id
            )
            return
        if selection_id == "view_target_history":
            self.server._nav_push(
                user,
                self._show_moderation_history_menu,
                report.reported_uuid,
            )
            return
        prefix = "set_status_"
        if not selection_id.startswith(prefix):
            return
        status = selection_id[len(prefix):]
        if status not in CLOSED_REPORT_STATUSES:
            return
        if report.status != "open":
            user.speak_l(
                "admin-moderation-report-already-closed", buffer="system"
            )
            self.server._nav_refresh(
                user, self._show_moderation_report_detail_menu, report.id
            )
            return
        updated = self.server.db.set_moderation_report_status(
            report.id,
            status,
            reviewer_uuid=user.uuid,
            reviewer_username=user.username,
        )
        if updated:
            user.speak_l(
                "admin-moderation-report-status-updated",
                buffer="system",
                id=report.id,
                status=self._moderation_status_name(user.locale, status),
            )
        else:
            user.speak_l(
                "admin-moderation-report-already-closed", buffer="system"
            )
        self.server._nav_refresh(
            user, self._show_moderation_report_detail_menu, report.id
        )

    async def _handle_moderation_sender_results_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        if selection_id == "back":
            self.server._nav_back(user)
            return
        username = str(state.get("history_username", ""))
        if selection_id in MENU_PAGE_IDS:
            next_page = page_for_selection(
                selection_id,
                state.get("moderation_page", 1),
                state.get("moderation_page_count", 1),
            )
            if next_page is None:
                return
            if is_page_refresh(selection_id):
                announce_page_refresh(user)
            self.server._nav_refresh(
                user,
                self._show_moderation_sender_results_menu,
                username,
                next_page,
                focus_page_start=is_page_navigation(selection_id),
            )
            return
        prefix = "history_sender_"
        if selection_id.startswith(prefix):
            sender_uuid = selection_id[len(prefix):]
            if not sender_uuid:
                return
            self.server._nav_push(
                user, self._show_moderation_history_menu, sender_uuid
            )

    async def _handle_moderation_context_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        """Navigate one bounded page of retained report context."""
        if selection_id == "back":
            self.server._nav_back(user)
            return
        if selection_id not in MENU_PAGE_IDS:
            return
        try:
            report_id = int(state.get("report_id", 0) or 0)
        except (TypeError, ValueError):
            report_id = 0
        if report_id <= 0:
            self.server._nav_back(user)
            return
        next_page = page_for_selection(
            selection_id,
            state.get("moderation_page", 1),
            state.get("moderation_page_count", 1),
        )
        if next_page is None:
            return
        if is_page_refresh(selection_id):
            announce_page_refresh(user)
        self.server._nav_refresh(
            user,
            self._show_moderation_context_menu,
            report_id,
            next_page,
            focus_page_start=is_page_navigation(selection_id),
        )

    async def _handle_moderation_history_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        if selection_id == "back":
            self.server._nav_back(user)
            return
        if selection_id not in MENU_PAGE_IDS:
            return
        sender_uuid = str(state.get("history_sender_uuid", ""))
        if not sender_uuid:
            self.server._nav_back(user)
            return
        next_page = page_for_selection(
            selection_id,
            state.get("moderation_page", 1),
            state.get("moderation_page_count", 1),
        )
        if next_page is None:
            return
        if is_page_refresh(selection_id):
            announce_page_refresh(user)
        self.server._nav_refresh(
            user,
            self._show_moderation_history_menu,
            sender_uuid,
            next_page,
            focus_page_start=is_page_navigation(selection_id),
        )

    async def _handle_moderation_messages_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        """Handle the paginated message browser and its exposed filters."""
        if selection_id == "back":
            self.server._nav_back(user)
            return
        history_filter = self._moderation_message_filter_from_state(state)
        if selection_id == "message_filter_sort":
            next_sort = (
                "oldest"
                if history_filter.sort_order == "newest"
                else "newest"
            )
            self.server._nav_refresh(
                user,
                self._show_moderation_messages_menu,
                history_filter.channel_code,
                history_filter.period,
                next_sort,
                1,
            )
            return
        if selection_id == "message_filter_language":
            self.server._nav_push(
                user,
                self._show_moderation_message_language_menu,
                history_filter.channel_code,
                history_filter.period,
                history_filter.sort_order,
            )
            return
        if selection_id == "message_filter_period":
            self.server._nav_push(
                user,
                self._show_moderation_message_period_menu,
                history_filter.channel_code,
                history_filter.period,
                history_filter.sort_order,
            )
            return
        if selection_id == "message_filter_reset":
            self.server._nav_refresh(
                user,
                self._show_moderation_messages_menu,
            )
            return
        if selection_id not in MENU_PAGE_IDS:
            return
        next_page = page_for_selection(
            selection_id,
            state.get("moderation_page", 1),
            state.get("moderation_page_count", 1),
        )
        if next_page is None:
            return
        if is_page_refresh(selection_id):
            announce_page_refresh(user)
        self.server._nav_refresh(
            user,
            self._show_moderation_messages_menu,
            history_filter.channel_code,
            history_filter.period,
            history_filter.sort_order,
            next_page,
            focus_page_start=is_page_navigation(selection_id),
        )

    async def _handle_moderation_message_language_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        """Apply one language facet without adding redundant stack frames."""
        if selection_id == "back":
            self.server._nav_back(user)
            return
        prefix = "message_language_"
        if not selection_id.startswith(prefix):
            return
        selected = selection_id[len(prefix):]
        channel_code = None if selected == "all" else selected
        history_filter = GlobalChatHistoryFilter.from_values(
            channel_code=channel_code,
            period=state.get("message_period"),
            sort_order=state.get("message_sort"),
        )
        if selected != "all" and history_filter.channel_code != selected:
            return
        self._apply_moderation_message_filter(user, history_filter)

    async def _handle_moderation_message_period_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        """Apply one UTC date facet without adding redundant stack frames."""
        if selection_id == "back":
            self.server._nav_back(user)
            return
        prefix = "message_period_"
        if not selection_id.startswith(prefix):
            return
        period = selection_id[len(prefix):]
        if period not in GLOBAL_CHAT_HISTORY_PERIODS:
            return
        history_filter = GlobalChatHistoryFilter.from_values(
            channel_code=state.get("message_channel"),
            period=period,
            sort_order=state.get("message_sort"),
        )
        self._apply_moderation_message_filter(user, history_filter)

    async def _handle_moderation_clear_confirm_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        if selection_id == "back":
            self.server._nav_back(user)
            return
        if selection_id != "confirm":
            return
        if not self._require_developer_moderation_access(user):
            return
        clear_kind = str(state.get("moderation_clear_kind", ""))
        if clear_kind == "history":
            count = self.server.db.clear_global_chat_messages()
            user.speak_l(
                "admin-moderation-history-cleared",
                buffer="system",
                count=count,
            )
        elif clear_kind == "closed_reports":
            count = self.server.db.clear_closed_moderation_reports()
            user.speak_l(
                "admin-moderation-closed-reports-cleared",
                buffer="system",
                count=count,
            )
        else:
            self._return_to_admin_root(user, "moderation")
            return
        self.server._nav_back(user)

    async def _handle_account_approval_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        """Handle account approval menu selection."""
        if selection_id == "back":
            self.server._nav_back(user)
        elif selection_id in MENU_PAGE_IDS:
            next_page = page_for_selection(
                selection_id,
                state.get("account_approval_page", 1),
                state.get("account_approval_page_count", 1),
            )
            if next_page is None:
                return
            if is_page_refresh(selection_id):
                announce_page_refresh(user)
            self.server._nav_refresh(
                user,
                self._show_account_approval_menu,
                next_page,
                focus_page_start=is_page_navigation(selection_id),
            )
        elif selection_id.startswith("pending_"):
            pending_username = selection_id[8:]  # Remove "pending_" prefix
            self.server._nav_push(
                user, self._show_pending_user_actions_menu, pending_username
            )

    async def _handle_pending_user_actions_selection(
        self, user: NetworkUser, selection_id: str, state: dict
    ) -> None:
        """Handle pending user actions menu selection."""
        pending_username = state.get("pending_username")
        if not pending_username:
            self.server._nav_back(user)
            return

        if selection_id == "approve":
            await self._approve_user(user, pending_username)
        elif selection_id == "decline":
            await self._decline_user(user, pending_username)
        elif selection_id == "back":
            self.server._nav_back(user)

    async def _handle_pending_nick_changes_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        """Handle selection in the pending nick-changes queue menu."""
        if selection_id == "back":
            self.server._nav_back(user)
        elif selection_id in MENU_PAGE_IDS:
            next_page = page_for_selection(
                selection_id,
                state.get("nick_changes_page", 1),
                state.get("nick_changes_page_count", 1),
            )
            if next_page is None:
                return
            if is_page_refresh(selection_id):
                announce_page_refresh(user)
            self.server._nav_refresh(
                user,
                self._show_pending_nick_changes_menu,
                next_page,
                focus_page_start=is_page_navigation(selection_id),
            )
        elif selection_id.startswith("nick_req_"):
            try:
                req_id = int(selection_id[len("nick_req_") :])
            except ValueError:
                return
            self.server._nav_push(
                user, self._show_pending_nick_change_actions_menu, req_id
            )

    async def _handle_pending_nick_change_actions_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        """Handle validate/reject actions for one pending nick change request."""
        try:
            request_id = int(state.get("nick_request_id", 0) or 0)
        except (TypeError, ValueError):
            request_id = 0
        if request_id <= 0:
            self.server._nav_back(user)
            return

        if selection_id == "approve":
            await self._approve_nick_change_request(user, request_id)
        elif selection_id == "reject":
            req = self.server.db.get_nick_change_request(request_id)
            if req is None or req.status != "pending":
                user.speak_l("admin-nick-error-not-pending", buffer="system")
                self.server._nav_back(user)
                return
            user.show_editbox(
                ADMIN_NICK_REJECT_REASON_INPUT,
                Localization.get(
                    user.locale,
                    "admin-nick-reject-reason-prompt",
                    player=req.old_username,
                    new_nick=req.requested_username,
                ),
                multiline=False,
                max_length=200,
            )
            self.server.enter_input_state(
                user,
                ADMIN_NICK_REJECT_REASON_INPUT,
                nick_request_id=request_id,
            )
        elif selection_id == "back":
            self.server._nav_back(user)

    async def _handle_pending_nick_reject_refund_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        """Handle refund choice when rejecting a paid nick change request."""
        try:
            request_id = int(state.get("nick_request_id", 0) or 0)
        except (TypeError, ValueError):
            request_id = 0
        reason = str(state.get("reject_reason") or "").strip()
        if selection_id == "back":
            self.server._nav_back(user)
            return
        if request_id <= 0 or not reason:
            self.server._nav_back(user)
            return
        if selection_id == "reject_refund":
            await self._complete_reject_nick_change_request(
                user, request_id, reason, refund_coins=True
            )
        elif selection_id == "reject_no_refund":
            await self._complete_reject_nick_change_request(
                user, request_id, reason, refund_coins=False
            )

    @require_admin
    async def _approve_nick_change_request(
        self, admin: NetworkUser, request_id: int
    ) -> None:
        """Approve a pending nick change request and propagate the new username."""
        req = self.server.db.get_nick_change_request(request_id)
        if req is None or req.status != "pending":
            admin.speak_l("admin-nick-error-not-pending", buffer="system")
            self.server._nav_back(admin)
            return

        target_online = any(
            u.uuid == req.user_uuid for u in self.server.users.values()
        )
        outcome = self.server.db.approve_nick_change_request(
            request_id,
            reviewer_uuid=admin.uuid,
            reviewer_username=admin.username,
            mark_notified=target_online,
        )
        if outcome.code == "username_taken":
            admin.speak_l(
                "admin-nick-error-already-taken",
                buffer="system",
                new_nick=outcome.new_username or req.requested_username,
            )
            return
        if not outcome.ok or outcome.request is None:
            admin.speak_l("admin-nick-error-not-pending", buffer="system")
            self.server._nav_back(admin)
            return

        target_user = self.server.apply_runtime_username_change(
            outcome.request.user_uuid,
            outcome.old_username,
            outcome.new_username,
        )
        if target_user is not admin:
            admin.play_sound("accountapprove.ogg")
            admin.speak_l(
                "admin-nick-approved-feedback",
                buffer="system",
                old_nick=outcome.old_username,
                new_nick=outcome.new_username,
            )
        self.server._notify_admins(
            "account-action",
            "accountactionnotify.ogg",
            exclude_username=admin.username,
        )

        if target_user is not None:
            target_user.play_sound("accountapprove.ogg")
            target_user.speak_l(
                "nick-change-approved-reconnect-user",
                buffer="system",
                new_nick=outcome.new_username,
                seconds=5,
            )
            self.server.schedule_nick_change_reconnect(
                target_user,
                outcome.new_username,
                delay_seconds=5.0,
            )

        self.refresh_pending_nick_changes_menus(exclude_username=admin.username)
        if self.server.db.count_pending_nick_requests() > 0:
            self.server._nav_back(admin)
        else:
            self._return_to_admin_root(admin, "pending_nick_changes")

    @require_admin
    async def _complete_reject_nick_change_request(
        self,
        admin: NetworkUser,
        request_id: int,
        reason: str,
        *,
        refund_coins: bool,
    ) -> None:
        """Reject a pending nick change request with a reason and optional coin refund."""
        req = self.server.db.get_nick_change_request(request_id)
        if req is None or req.status != "pending":
            admin.speak_l("admin-nick-error-not-pending", buffer="system")
            self.server._nav_back(admin)
            return

        target_user = next(
            (u for u in self.server.users.values() if u.uuid == req.user_uuid),
            None,
        )
        outcome = self.server.db.reject_nick_change_request(
            request_id,
            reviewer_uuid=admin.uuid,
            reviewer_username=admin.username,
            reason=reason,
            refund_coins=refund_coins,
            mark_notified=target_user is not None,
        )
        if not outcome.ok or outcome.request is None:
            admin.speak_l("admin-nick-error-not-pending", buffer="system")
            self.server._nav_back(admin)
            return

        if target_user is not admin:
            admin.play_sound("accountdeni.ogg")
            if outcome.refunded_coins > 0:
                admin.speak_l(
                    "admin-nick-rejected-refunded-feedback",
                    buffer="system",
                    player=outcome.old_username,
                    new_nick=outcome.new_username,
                    coins=outcome.refunded_coins,
                )
            else:
                admin.speak_l(
                    "admin-nick-rejected-feedback",
                    buffer="system",
                    player=outcome.old_username,
                    new_nick=outcome.new_username,
                )

        self.server._notify_admins(
            "account-action",
            "accountactionnotify.ogg",
            exclude_username=admin.username,
        )

        if target_user is not None:
            target_user.play_sound("accountdeni.ogg")
            if outcome.refunded_coins > 0:
                target_user.play_sound("game_citadels/coins_small.ogg")
                target_user.speak_l(
                    "nick-change-rejected-refunded-user",
                    buffer="system",
                    new_nick=outcome.new_username,
                    reason=outcome.request.reject_reason,
                    coins=outcome.refunded_coins,
                    balance=outcome.balance,
                )
            else:
                target_user.speak_l(
                    "nick-change-rejected-user",
                    buffer="system",
                    new_nick=outcome.new_username,
                    reason=outcome.request.reject_reason,
                )
            self.server.refresh_user_nick_menu_if_open(target_user)

        self.refresh_pending_nick_changes_menus(exclude_username=admin.username)
        if self.server.db.count_pending_nick_requests() > 0:
            # Pop back to the pending list
            while (
                self.server.user_states.get(admin.username, {}).get("menu")
                in (ADMIN_NICK_REJECT_REFUND_MENU, ADMIN_NICK_CHANGE_ACTIONS_MENU)
            ):
                self.server._nav_back(admin)
        else:
            self._return_to_admin_root(admin, "pending_nick_changes")

    async def _handle_promote_admin_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        """Handle promote admin menu selection."""
        if selection_id == "back":
            self.server._nav_back(user)
        elif selection_id == "search":
            self._handle_target_search_selection(user, state)
        elif self._handle_target_page_selection(user, selection_id, state):
            return
        elif selection_id.startswith("promote_"):
            target_username = selection_id[8:]  # Remove "promote_" prefix
            self.server._nav_push(user, self._show_promote_confirm_menu, target_username)

    async def _handle_demote_admin_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        """Handle demote admin menu selection."""
        if selection_id == "back":
            self.server._nav_back(user)
        elif selection_id == "search":
            self._handle_target_search_selection(user, state)
        elif self._handle_target_page_selection(user, selection_id, state):
            return
        elif selection_id.startswith("demote_"):
            target_username = selection_id[7:]  # Remove "demote_" prefix
            self.server._nav_push(user, self._show_demote_confirm_menu, target_username)

    async def _handle_promote_confirm_selection(
        self, user: NetworkUser, selection_id: str, state: dict
    ) -> None:
        """Handle promote confirmation menu selection."""
        target_username = state.get("target_username")
        if not target_username:
            self.server._nav_back(user)
            return

        if selection_id == "yes":
            # Show broadcast choice menu
            self.server._nav_push(
                user, self._show_broadcast_choice_menu, "promote", target_username
            )
        else:
            # No or back - return to promote admin menu
            self.server._nav_back(user)

    async def _handle_demote_confirm_selection(
        self, user: NetworkUser, selection_id: str, state: dict
    ) -> None:
        """Handle demote confirmation menu selection."""
        target_username = state.get("target_username")
        if not target_username:
            self.server._nav_back(user)
            return

        if selection_id == "yes":
            # Show broadcast choice menu
            self.server._nav_push(
                user, self._show_broadcast_choice_menu, "demote", target_username
            )
        else:
            # No or back - return to demote admin menu
            self.server._nav_back(user)

    async def _handle_kick_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        """Handle kick user menu selection."""
        if selection_id == "back":
            self.server._nav_back(user)
        elif selection_id == "search":
            self._handle_target_search_selection(user, state)
        elif self._handle_target_page_selection(user, selection_id, state):
            return
        elif selection_id.startswith("kick_"):
            target_username = selection_id[5:]  # Remove "kick_" prefix
            self.server._nav_push(user, self._show_kick_confirm_menu, target_username)

    async def _handle_kick_confirm_selection(
        self, user: NetworkUser, selection_id: str, state: dict
    ) -> None:
        """Handle kick confirmation menu selection."""
        target_username = state.get("target_username")
        if not target_username:
            self.server._nav_back(user)
            return

        if selection_id == "yes":
            await self.kick_user(user, target_username)
        else:
            # No or back - return to kick menu
            # Or return to admin menu directly? Usually back to list is better to verify safety.
            # But here "No" usually means "Cancel action".
            self.server._nav_back(user)

    async def _handle_broadcast_choice_selection(
        self, user: NetworkUser, selection_id: str, state: dict
    ) -> None:
        """Handle broadcast choice menu selection."""
        action = state.get("action")
        target_username = state.get("target_username")

        if selection_id == "back":
            self.server._nav_back(user)
            return

        if not action or not target_username:
            self._return_to_admin_root(user)
            return

        # Determine broadcast scope: "all", "admins", or "nobody"
        broadcast_scope = selection_id  # "all", "admins", or "nobody"

        if action == "promote":
            await self._promote_to_admin(user, target_username, broadcast_scope)
        elif action == "demote":
            await self._demote_from_admin(user, target_username, broadcast_scope)

    # ==================== Admin Actions ====================

    @require_admin
    async def _approve_user(self, admin: NetworkUser, username: str) -> None:
        """Approve a pending user account."""
        if self.server.db.approve_user(username):
            admin.speak_l("account-approved", buffer="system", player=username)

            # Notify other admins of the account action
            self.server._notify_admins(
                "account-action",
                "accountactionnotify.ogg",
                exclude_username=admin.username,
            )

            # Check if the user is online and waiting for approval
            waiting_user = self.server.users.get(username)
            if waiting_user:
                # Update the user's approved status so they can now interact
                waiting_user.set_approved(True)

                waiting_state = self.server.user_states.get(username, {})
                if waiting_state.get("menu") == "waiting_for_approval":
                    # User is online and waiting - welcome them and show main menu
                    waiting_user.speak_l("account-approved-welcome", buffer="system")
                    waiting_user.play_sound("accountapprove.ogg")
                    waiting_user.complete_session_handover()
                    self.server._show_main_menu(waiting_user)

        self.refresh_account_approval_menus(exclude_username=admin.username)
        self.server._nav_back(admin)

    @require_admin
    async def _decline_user(self, admin: NetworkUser, username: str) -> None:
        """Decline and delete a pending user account."""
        target_record = self.server.db.get_user(username)
        target_locale = target_record.locale if target_record else "en"
        deleted = await self.server._delete_account_and_evict(
            username,
            {
                "type": "disconnect",
                "reason": Localization.get(
                    target_locale,
                    "account-declined-goodbye",
                ),
                "reconnect": False,
            },
        )
        if deleted:
            admin.speak_l("account-declined", buffer="system", player=username)

            # Notify other admins of the account action
            self.server._notify_admins(
                "account-action",
                "accountactionnotify.ogg",
                exclude_username=admin.username,
            )

        self.refresh_account_approval_menus(exclude_username=admin.username)
        self.server._nav_back(admin)

    def _reject_stale_role_target(
        self,
        admin: NetworkUser,
        username: str,
        focus_id: str,
    ) -> None:
        """Explain and safely exit an outdated role-confirmation workflow."""
        admin.speak_l(
            "admin-role-target-changed",
            buffer="system",
            player=username,
        )
        self._return_to_admin_root(admin, focus_id)

    @require_admin
    async def _promote_to_admin(
        self, admin: NetworkUser, username: str, broadcast_scope: str
    ) -> None:
        """Promote a user to admin."""
        try:
            change = self.server.db.update_user_trust_level(
                username,
                ADMIN_TRUST_LEVEL,
                expected_trust_level=USER_TRUST_LEVEL,
            )
        except ValueError:
            self._reject_stale_role_target(admin, username, "promote_admin")
            return
        if change is None:
            self._reject_stale_role_target(admin, username, "promote_admin")
            return
        username = change.username

        # Update the user's trust level if they are online
        target_user = self.server.users.get(username)
        if target_user:
            target_user.set_trust_level(ADMIN_TRUST_LEVEL)
            self.server.on_user_presence_changed()

        # Always notify the target user with personalized message
        if target_user:
            target_user.speak_l("promote-announcement-you", buffer="system")
            target_user.play_sound("accountpromoteadmin.ogg")

        # Broadcast the announcement to others based on scope
        if broadcast_scope == "nobody":
            # Silent mode - only notify the admin who performed the action
            admin.speak_l("promote-announcement", buffer="system", player=username)
            admin.play_sound("accountpromoteadmin.ogg")
        else:
            # Broadcast to all or admins (excluding the target user who already got personalized message)
            self._broadcast_admin_change(
                "promote-announcement",
                "accountpromoteadmin.ogg",
                username,
                broadcast_scope,
                exclude_username=username,
            )

        self._return_to_admin_root(admin, "promote_admin")

    @require_admin
    async def _demote_from_admin(
        self, admin: NetworkUser, username: str, broadcast_scope: str
    ) -> None:
        """Demote an admin to regular user."""
        try:
            change = self.server.db.update_user_trust_level(
                username,
                USER_TRUST_LEVEL,
                expected_trust_level=ADMIN_TRUST_LEVEL,
            )
        except ValueError:
            self._reject_stale_role_target(admin, username, "demote_admin")
            return
        if change is None:
            self._reject_stale_role_target(admin, username, "demote_admin")
            return
        username = change.username

        # Update the user's trust level if they are online
        target_user = self.server.users.get(username)
        if target_user:
            target_user.set_trust_level(USER_TRUST_LEVEL)
            self.server.on_user_presence_changed()

        # Always notify the target user with personalized message
        if target_user:
            target_user.speak_l("demote-announcement-you", buffer="system")
            target_user.play_sound("accountdemoteadmin.ogg")

        # Broadcast the announcement to others based on scope
        if broadcast_scope == "nobody":
            # Silent mode - only notify the admin who performed the action
            admin.speak_l("demote-announcement", buffer="system", player=username)
            admin.play_sound("accountdemoteadmin.ogg")
        else:
            # Broadcast to all or admins (excluding the target user who already got personalized message)
            self._broadcast_admin_change(
                "demote-announcement",
                "accountdemoteadmin.ogg",
                username,
                broadcast_scope,
                exclude_username=username,
            )

        self._return_to_admin_root(admin, "demote_admin")

    def _broadcast_admin_change(
        self,
        message_id: str,
        sound: str,
        player_name: str,
        broadcast_scope: str,
        exclude_username: str | None = None,
    ) -> None:
        """Broadcast an admin promotion/demotion announcement."""
        for username, user in self.server.users.items():
            if not user.approved:
                continue  # Don't send broadcasts to unapproved users
            if exclude_username and username == exclude_username:
                continue  # Skip the excluded user
            if (
                broadcast_scope == "admins"
                and user.trust_level < ADMIN_TRUST_LEVEL
            ):
                continue  # Only admins if broadcasting to admins only
            user.speak_l(message_id, buffer="system", player=player_name)
            user.play_sound(sound)

    def _show_broadcast_input_menu(self, user: NetworkUser) -> None:
        """Show input box for broadcast message."""
        user.show_editbox(
            "broadcast_message",
            Localization.get(user.locale, "admin-broadcast-prompt"),
            multiline=True,
        )
        self.server.enter_input_state(user, "admin_broadcast_input")

    async def handle_input(
        self, user: NetworkUser, packet: dict, state: dict
    ) -> bool:
        """
        Handle input from an admin menu editbox.
        Returns True if handled, False otherwise.
        """
        menu_id = state.get("menu")
        input_id = packet.get("input_id")
        value = packet.get("text", packet.get("value")) # Support both just in case

        if menu_id in ADMIN_MENU_IDS and user.trust_level < ADMIN_TRUST_LEVEL:
            user.speak_l("not-admin-anymore", buffer="system")
            self.server._show_main_menu(user)
            return True

        if menu_id == "smtp_setting_input":
            if user.trust_level < DEVELOPER_TRUST_LEVEL:
                user.speak_l("dev-only-action", buffer="system")
                self.server._nav_back(user)
                return True
            if value is not None:
                field = state.get("field")
                config = self.server.db.get_smtp_config()
                if not config:
                    from ..persistence.database import SmtpConfig
                    config = SmtpConfig("", 587, "", "", "", "", "tls")

                host = config.host
                port = config.port
                username = config.username
                password = config.password
                from_email = config.from_email
                from_name = config.from_name
                encryption_type = config.encryption_type

                if field == "host":
                    host = value.strip()
                elif field == "port":
                    try:
                        port = int(value.strip())
                    except ValueError:
                        user.speak_l("invalid-volume", buffer="system")  # Generic invalid number sound
                        self.server._restore_input_parent(user, state)
                        return True
                elif field == "username":
                    username = value.strip()
                elif field == "password":
                    password = value
                elif field == "from_email":
                    from_email = value.strip()
                elif field == "from_name":
                    from_name = value.strip()
                elif field == "test_email":
                    if value.strip():
                        await self._run_smtp_test(user, config, value.strip())
                    self.server._restore_input_parent(user, state)
                    return True

                self.server.db.update_smtp_config(host, port, username, password, from_email, from_name, encryption_type)
                user.speak_l("admin-smtp-updated-success", buffer="system")
            self.server._restore_input_parent(user, state)
            return True
        elif menu_id == ADMIN_MODERATION_HISTORY_INPUT:
            if input_id != ADMIN_MODERATION_HISTORY_INPUT:
                self.server._restore_input_parent(user, state)
                return True
            username = str(value or "").strip()
            if not username:
                self.server._restore_input_parent(user, state)
                return True
            if self.server.db.count_global_chat_sender_identities(username) == 0:
                self.server._restore_input_parent(user, state)
                user.speak_l(
                    "admin-moderation-no-sender-history",
                    buffer="system",
                    username=username,
                )
                return True
            self.server._nav_push_from_input(
                user,
                self._show_moderation_sender_results_menu,
                username,
                fallback_parent={
                    "menu": ADMIN_MODERATION_MENU,
                    "_last_selection_id": "find_history",
                },
            )
            return True
        elif menu_id == ADMIN_TARGET_SEARCH_INPUT and input_id == ADMIN_TARGET_SEARCH_INPUT:
            mode = state.get("target_mode")
            if not mode:
                self._return_to_admin_root(user)
                return True
            self.server._restore_input_parent(user, state)
            self._refresh_admin_target_menu(user, str(mode), value or "", 1)
            return True
        elif menu_id == "admin_broadcast_input" and input_id == "broadcast_message":
            if value:
                await self.perform_broadcast(user, value, show_menu=False)
                self.server._restore_input_parent(user, state)
            else:
                # Cancelled or empty
                self.server._restore_input_parent(user, state)
            return True
        elif menu_id == GRANT_COINS_INPUT and input_id == "grant_coins_custom_amount":
            target_username = state.get("target_username")
            if not target_username:
                self.server._restore_input_parent(user, state)
                return True
            if not value or not value.strip():
                self.server._restore_input_parent(user, state)
                return True
            try:
                amount = int(value.strip())
                if amount <= 0:
                    user.speak_l("admin-grant-coins-error-positive", buffer="system")
                    self.server._restore_input_parent(user, state)
                    return True
            except ValueError:
                user.speak_l("admin-grant-coins-error-invalid", buffer="system")
                self.server._restore_input_parent(user, state)
                return True

            await self._grant_coins_to_user(user, target_username, amount)
            return True
        elif (
            menu_id == "server_power_custom_delay_input"
            and input_id == "server_power_custom_delay_input"
        ):
            if not self._require_dev_power(user):
                return True
            action = str(state.get("power_action") or "")
            if not value:
                self.server._restore_input_parent(user, state)
                return True
            delay_seconds = ServerPowerManager.seconds_from_custom_minutes(value)
            if delay_seconds is None:
                user.speak_l(
                    "server-power-invalid-custom-delay",
                    buffer="system",
                    max=POWER_MAX_CUSTOM_DELAY_MINUTES,
                )
                self.server._restore_input_parent(user, state)
                return True
            self.server._restore_input_parent(user, state)
            self.server._nav_push(
                user,
                self._show_server_power_reason_menu,
                action,
                delay_seconds,
            )
            return True
        elif menu_id == ADMIN_LOCALIZED_TEXT_INPUT:
            parent = dict(state.get("_parent_frame") or {})
            if parent.get("menu") != ADMIN_LOCALIZED_TEXT_MENU:
                self._return_to_admin_root(user)
                return True
            purpose = str(parent.get("localized_text_purpose") or "")
            spec = ADMIN_LOCALIZED_TEXT_SPECS.get(purpose)
            if spec is None or purpose != state.get("localized_text_purpose"):
                self._return_to_admin_root(user)
                return True
            if not self._require_localized_text_access(user, spec):
                return True
            if input_id != ADMIN_LOCALIZED_TEXT_INPUT:
                self.server._restore_input_parent(user, state)
                return True
            field = str(state.get("localized_text_field") or "")
            context = dict(parent.get("localized_text_context") or {})
            translations = dict(parent.get("localized_text_translations") or {})
            raw_value = str(value or "")

            if field == "version" and purpose == "motd":
                try:
                    version = int(raw_value.strip())
                    if version <= 0:
                        raise ValueError
                except ValueError:
                    user.speak_l("invalid-motd-version", buffer="system")
                    self.server._restore_input_parent(user, state)
                    return True
                context["version"] = version
                parent["localized_text_context"] = context
            elif field == "locale":
                language = str(state.get("localized_text_language") or "")
                if language not in Localization.available_locale_codes():
                    self.server._restore_input_parent(user, state)
                    return True
                text = normalize_localized_value(
                    raw_value,
                    multiline=spec.multiline,
                )
                if len(text) > spec.max_length:
                    user.speak_l(
                        "admin-localized-text-too-long",
                        buffer="system",
                        max=spec.max_length,
                    )
                    self.server._restore_input_parent(user, state)
                    return True
                if text:
                    translations[language] = text
                else:
                    translations.pop(language, None)
                parent["localized_text_translations"] = translations
            else:
                self.server._restore_input_parent(user, state)
                return True

            state["_parent_frame"] = parent
            self.server._restore_input_parent(user, state)
            return True

        elif menu_id == ADMIN_INFILTRADO_ADD_WORD1_INPUT:
            if value:
                clean_w1 = str(value).strip()
                parent = dict(state.get("_parent_frame") or {})
                target_cat = state.get("draft_category")
                self.server.enter_input_state(
                    user,
                    ADMIN_INFILTRADO_ADD_WORD2_INPUT,
                    draft_word1=clean_w1,
                    draft_category=target_cat,
                    _parent_frame=parent,
                )
                user.show_editbox(
                    "infiltrado_add_word2",
                    Localization.get(user.locale, "admin-infiltrado-prompt-word2"),
                )
            else:
                self.server._restore_input_parent(user, state)
            return True

        elif menu_id == ADMIN_INFILTRADO_ADD_WORD2_INPUT:
            word1 = state.get("draft_word1")
            clean_w2 = str(value or "").strip()
            target_cat = state.get("draft_category")
            parent = dict(state.get("_parent_frame") or {})
            if word1 and clean_w2:
                if target_cat:
                    pair = InfiltradoWordManager.add_pair(word1, clean_w2, category=target_cat)
                    user.speak_l(
                        "admin-infiltrado-pair-added",
                        buffer="system",
                        word1=pair.word1,
                        word2=pair.word2,
                        category=pair.category,
                    )
                    user.play_sound("menuenter.ogg")
                    self.server._restore_input_parent(user, state)
                else:
                    self._show_infiltrado_select_category_menu(
                        user, draft_word1=word1, draft_word2=clean_w2, parent_frame=parent
                    )
            else:
                self.server._restore_input_parent(user, state)
            return True

        elif menu_id == ADMIN_INFILTRADO_ADD_CATEGORY_INPUT:
            cat_name = str(value or "").strip()
            parent = dict(state.get("_parent_frame") or {})
            draft_w1 = state.get("draft_word1")
            draft_w2 = state.get("draft_word2")
            if cat_name:
                added = InfiltradoWordManager.add_category(cat_name)
                if not added:
                    user.speak_l("admin-infiltrado-category-already-exists", buffer="system")
                else:
                    user.speak_l(
                        "admin-infiltrado-category-added", buffer="system", category=cat_name
                    )
                    user.play_sound("menuenter.ogg")
                    if draft_w1 and draft_w2:
                        pair = InfiltradoWordManager.add_pair(
                            draft_w1, draft_w2, category=cat_name
                        )
                        user.speak_l(
                            "admin-infiltrado-pair-added",
                            buffer="system",
                            word1=pair.word1,
                            word2=pair.word2,
                            category=pair.category,
                        )
            self.server._restore_input_parent(user, state)
            return True

        elif menu_id == ADMIN_INFILTRADO_RENAME_CATEGORY_INPUT:
            old_cat = state.get("category")
            new_name = str(value or "").strip()
            if old_cat and new_name:
                renamed = InfiltradoWordManager.rename_category(old_cat, new_name)
                if renamed:
                    user.speak_l(
                        "admin-infiltrado-category-renamed",
                        buffer="system",
                        old_category=old_cat,
                        new_category=new_name,
                    )
                    user.play_sound("menuenter.ogg")
                else:
                    user.speak_l("admin-infiltrado-category-already-exists", buffer="system")
            self.server._restore_input_parent(user, state)
            return True

        elif menu_id == ADMIN_INFILTRADO_EDIT_WORD1_INPUT:
            pair_id = state.get("pair_id")
            clean_w1 = str(value or "").strip()
            if pair_id and clean_w1:
                pair = InfiltradoWordManager.update_pair(int(pair_id), word1=clean_w1)
                if pair:
                    user.speak_l(
                        "admin-infiltrado-pair-updated",
                        buffer="system",
                        word1=pair.word1,
                        word2=pair.word2,
                    )
                    user.play_sound("menuenter.ogg")
            self.server._restore_input_parent(user, state)
            return True

        elif menu_id == ADMIN_INFILTRADO_EDIT_WORD2_INPUT:
            pair_id = state.get("pair_id")
            clean_w2 = str(value or "").strip()
            if pair_id and clean_w2:
                pair = InfiltradoWordManager.update_pair(int(pair_id), word2=clean_w2)
                if pair:
                    user.speak_l(
                        "admin-infiltrado-pair-updated",
                        buffer="system",
                        word1=pair.word1,
                        word2=pair.word2,
                    )
                    user.play_sound("menuenter.ogg")
            self.server._restore_input_parent(user, state)
            return True

        elif menu_id == ADMIN_NICK_REJECT_REASON_INPUT:
            try:
                request_id = int(state.get("nick_request_id", 0) or 0)
            except (TypeError, ValueError):
                request_id = 0
            clean_reason = " ".join(str(value or "").split()).strip()
            if not clean_reason:
                user.speak_l("admin-nick-reject-reason-empty", buffer="system")
                self.server._restore_input_parent(user, state)
                return True
            req = self.server.db.get_nick_change_request(request_id)
            if req is None or req.status != "pending":
                user.speak_l("admin-nick-error-not-pending", buffer="system")
                self.server._restore_input_parent(user, state)
                return True
            if req.coins_paid > 0:
                self.server._nav_push_from_input(
                    user,
                    self._show_pending_nick_reject_refund_menu,
                    request_id,
                    clean_reason,
                )
            else:
                self.server._restore_input_parent(user, state)
                await self._complete_reject_nick_change_request(
                    user, request_id, clean_reason, refund_coins=False
                )
            return True

        return False

    def _show_smtp_settings_menu(self, user: NetworkUser) -> None:
        """Show SMTP configuration menu. Dev-only."""
        if user.trust_level < DEVELOPER_TRUST_LEVEL:
            user.speak_l("dev-only-action", buffer="system")
            self.server._nav_back(user)
            return
        config = self.server.db.get_smtp_config()
        if not config:
            from ..persistence.database import SmtpConfig
            config = SmtpConfig("", 587, "", "", "", "", "tls")

        not_set = Localization.get(user.locale, "smtp-not-set")
        host_str = config.host if config.host else not_set
        username_str = config.username if config.username else not_set
        password_str = "********" if config.password else not_set
        from_email_str = config.from_email if config.from_email else not_set
        from_name_str = config.from_name if config.from_name else not_set

        enc_key = f"smtp-enc-{config.encryption_type.lower()}"
        encryption_str = Localization.get(user.locale, enc_key)

        items = [
            MenuItem(text=Localization.get(user.locale, "smtp-host", value=host_str), id="set_host"),
            MenuItem(text=Localization.get(user.locale, "smtp-port", value=config.port), id="set_port"),
            MenuItem(text=Localization.get(user.locale, "smtp-username", value=username_str), id="set_username"),
            MenuItem(text=Localization.get(user.locale, "smtp-password", value=password_str), id="set_password"),
            MenuItem(text=Localization.get(user.locale, "smtp-from-email", value=from_email_str), id="set_from_email"),
            MenuItem(text=Localization.get(user.locale, "smtp-from-name", value=from_name_str), id="set_from_name"),
            MenuItem(text=Localization.get(user.locale, "smtp-encryption", value=encryption_str), id="set_encryption"),
            MenuItem(text=Localization.get(user.locale, "smtp-test-connection"), id="test_connection"),
            MenuItem(text=Localization.get(user.locale, "back"), id="back"),
        ]

        user.show_menu(
            "smtp_settings_menu",
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {"menu": "smtp_settings_menu"}

    async def _handle_smtp_settings_selection(self, user: NetworkUser, selection_id: str) -> None:
        """Handle selection in the SMTP settings menu. Dev-only."""
        if user.trust_level < DEVELOPER_TRUST_LEVEL:
            user.speak_l("dev-only-action", buffer="system")
            self.server._nav_back(user)
            return
        if selection_id == "back":
            self.server._nav_back(user)
            return

        if selection_id == "set_encryption":
            self.server._nav_push(user, self._show_smtp_encryption_menu)
            return

        if selection_id == "test_connection":
            user.show_editbox(
                "smtp_test_email",
                Localization.get(user.locale, "smtp-prompt-test-email"),
                multiline=False,
            )
            self.server.enter_input_state(user, "smtp_setting_input", field="test_email")
            return

        # Handle text inputs
        field_map = {
            "set_host": ("host", "smtp-prompt-host", False),
            "set_port": ("port", "smtp-prompt-port", False),
            "set_username": ("username", "smtp-prompt-username", False),
            "set_password": ("password", "smtp-prompt-password", True),
            "set_from_email": ("from_email", "smtp-prompt-from-email", False),
            "set_from_name": ("from_name", "smtp-prompt-from-name", False),
        }

        if selection_id in field_map:
            field, prompt_key, is_password = field_map[selection_id]
            # Get current value for default
            config = self.server.db.get_smtp_config()
            default_val = ""
            if config and not is_password:
                default_val = str(getattr(config, field))

            user.show_editbox(
                f"smtp_{field}",
                Localization.get(user.locale, prompt_key),
                default_value=default_val,
                multiline=False,
            )
            self.server.enter_input_state(user, "smtp_setting_input", field=field)

    def _show_smtp_encryption_menu(self, user: NetworkUser) -> None:
        """Show encryption type selection."""
        config = self.server.db.get_smtp_config()
        current = config.encryption_type if config else "tls"

        def format_enc(key):
            text = Localization.get(user.locale, key)
            return Localization.get(user.locale, "smtp-current-enc", value=text) if current == key.replace("smtp-enc-", "") else text

        items = [
            MenuItem(text=format_enc("smtp-enc-none"), id="enc_none"),
            MenuItem(text=format_enc("smtp-enc-ssl"), id="enc_ssl"),
            MenuItem(text=format_enc("smtp-enc-tls"), id="enc_tls"),
            MenuItem(text=Localization.get(user.locale, "back"), id="back"),
        ]

        user.show_menu(
            "smtp_encryption_menu",
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {"menu": "smtp_encryption_menu"}

    async def _handle_smtp_encryption_selection(self, user: NetworkUser, selection_id: str) -> None:
        """Handle selection in the SMTP encryption menu. Dev-only."""
        if user.trust_level < DEVELOPER_TRUST_LEVEL:
            user.speak_l("dev-only-action", buffer="system")
            self.server._nav_back(user)
            return
        if selection_id == "back":
            self.server._nav_back(user)
            return

        if selection_id.startswith("enc_"):
            enc_type = selection_id[4:]
            config = self.server.db.get_smtp_config()
            if config:
                self.server.db.update_smtp_config(
                    config.host, config.port, config.username, config.password,
                    config.from_email, config.from_name, enc_type
                )
                user.speak_l("admin-smtp-updated-success", buffer="system")
        self.server._nav_back(user)

    async def _run_smtp_test(self, user: NetworkUser, config, target_email: str) -> None:
        """Run the actual SMTP test."""
        from ..core.smtp_mailer import SmtpMailer

        user.speak_l("smtp-test-sending", buffer="system")

        subject = Localization.get(user.locale, "email-test-subject")
        body = Localization.get(user.locale, "email-test-body")
        body_html = Localization.get(user.locale, "email-test-body-html")

        success, error = await SmtpMailer.send_email(config, target_email, subject, body, html_body=body_html)

        if success:
            user.speak_l("smtp-test-success", buffer="system", email=target_email)
        else:
            user.speak_l("smtp-test-failed", buffer="system", error=error)


    def _require_dev_power(self, user: NetworkUser) -> bool:
        if user.trust_level >= DEVELOPER_TRUST_LEVEL:
            return True
        user.speak_l("dev-only-action", buffer="system")
        self._return_to_admin_root(user)
        return False

    def _show_server_power_menu(self, user: NetworkUser) -> None:
        """Show developer-only server power controls."""
        if not self._require_dev_power(user):
            return

        items: list[MenuItem] = []
        operation = self.server.power_manager.active_operation
        if operation:
            items.append(
                MenuItem(
                    text=Localization.get(
                        user.locale,
                        "server-power-active-status",
                        action=self.server.power_manager.format_action(
                            user.locale, operation.action
                        ),
                        reason=self.server.power_manager.format_reason(
                            user.locale, operation
                        ),
                    ),
                    id="",
                )
            )
            items.append(
                MenuItem(
                    text=Localization.get(user.locale, "server-power-cancel"),
                    id="cancel",
                )
            )
        else:
            items.append(
                MenuItem(
                    text=Localization.get(user.locale, "server-power-reboot"),
                    id="reboot",
                )
            )
            items.append(
                MenuItem(
                    text=Localization.get(user.locale, "server-power-shutdown"),
                    id="shutdown",
                )
            )
        items.append(MenuItem(text=Localization.get(user.locale, "back"), id="back"))
        user.show_menu(
            "server_power_menu",
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {"menu": "server_power_menu"}

    async def _handle_server_power_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        if not self._require_dev_power(user):
            return
        if selection_id == "back":
            self.server._nav_back(user)
            return
        if selection_id == "cancel":
            operation = self.server.power_manager.active_operation
            if not operation or not self.server.power_manager.cancel():
                user.speak_l("server-power-cancel-none", buffer="system")
                self.server._nav_refresh(user, self._show_server_power_menu)
                return
            user.speak_l("server-power-cancelled", buffer="system")
            await self.server.power_manager.broadcast_cancelled(user, operation)
            self.server._nav_refresh(user, self._show_server_power_menu)
            return
        if selection_id in {PowerAction.REBOOT.value, PowerAction.SHUTDOWN.value}:
            if self.server.power_manager.is_scheduled:
                user.speak_l("server-power-already-scheduled", buffer="system")
                self.server._nav_refresh(user, self._show_server_power_menu)
                return
            self.server._nav_push(
                user,
                self._show_server_power_delay_menu,
                selection_id,
            )

    def _show_server_power_delay_menu(
        self, user: NetworkUser, action: str
    ) -> None:
        if not self._require_dev_power(user):
            return
        items = [
            MenuItem(
                text=Localization.get(user.locale, "server-power-delay-30s"),
                id="delay_30",
            ),
            MenuItem(
                text=Localization.get(user.locale, "server-power-delay-1m"),
                id="delay_60",
            ),
            MenuItem(
                text=Localization.get(user.locale, "server-power-delay-5m"),
                id="delay_300",
            ),
            MenuItem(
                text=Localization.get(user.locale, "server-power-delay-10m"),
                id="delay_600",
            ),
            MenuItem(
                text=Localization.get(user.locale, "server-power-delay-30m"),
                id="delay_1800",
            ),
            MenuItem(
                text=Localization.get(user.locale, "server-power-delay-1h"),
                id="delay_3600",
            ),
            MenuItem(
                text=Localization.get(user.locale, "server-power-delay-2h"),
                id="delay_7200",
            ),
            MenuItem(
                text=Localization.get(user.locale, "server-power-delay-custom"),
                id="delay_custom",
            ),
            MenuItem(text=Localization.get(user.locale, "back"), id="back"),
        ]
        user.show_menu(
            "server_power_delay_menu",
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {
            "menu": "server_power_delay_menu",
            "power_action": action,
        }

    async def _handle_server_power_delay_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        if not self._require_dev_power(user):
            return
        if selection_id == "back":
            self.server._nav_back(user)
            return
        action = str(state.get("power_action") or "")
        if action not in {PowerAction.REBOOT.value, PowerAction.SHUTDOWN.value}:
            self._return_to_admin_root(user, "server_power")
            return
        if selection_id == "delay_custom":
            user.show_editbox(
                "server_power_custom_delay_input",
                Localization.get(
                    user.locale,
                    "server-power-custom-delay-prompt",
                    max=POWER_MAX_CUSTOM_DELAY_MINUTES,
                ),
                multiline=False,
            )
            self.server.enter_input_state(
                user,
                "server_power_custom_delay_input",
                power_action=action,
            )
            return
        if selection_id.startswith("delay_"):
            try:
                delay_seconds = int(selection_id[6:])
            except ValueError:
                return
            self.server._nav_push(
                user,
                self._show_server_power_reason_menu,
                action,
                delay_seconds,
            )

    def _show_server_power_reason_menu(
        self, user: NetworkUser, action: str, delay_seconds: int
    ) -> None:
        if not self._require_dev_power(user):
            return
        items = [
            MenuItem(
                text=Localization.get(user.locale, "server-power-reason-update"),
                id="reason_update",
            ),
            MenuItem(
                text=Localization.get(user.locale, "server-power-reason-maintenance"),
                id="reason_maintenance",
            ),
            MenuItem(
                text=Localization.get(user.locale, "server-power-reason-security"),
                id="reason_security",
            ),
            MenuItem(
                text=Localization.get(user.locale, "server-power-reason-technical"),
                id="reason_technical",
            ),
            MenuItem(
                text=Localization.get(user.locale, "server-power-reason-custom"),
                id="reason_custom",
            ),
            MenuItem(text=Localization.get(user.locale, "back"), id="back"),
        ]
        user.show_menu(
            "server_power_reason_menu",
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {
            "menu": "server_power_reason_menu",
            "power_action": action,
            "power_delay_seconds": delay_seconds,
        }

    async def _handle_server_power_reason_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        if not self._require_dev_power(user):
            return
        if selection_id == "back":
            self.server._nav_back(user)
            return
        action = str(state.get("power_action") or "")
        delay_seconds = int(state.get("power_delay_seconds") or 0)
        if action not in {PowerAction.REBOOT.value, PowerAction.SHUTDOWN.value}:
            self._return_to_admin_root(user, "server_power")
            return
        if selection_id == "reason_custom":
            self.server._nav_push(
                user,
                self._show_admin_localized_text_menu,
                "power",
                {},
                {
                    "power_action": action,
                    "power_delay_seconds": delay_seconds,
                },
            )
            return
        if selection_id.startswith("reason_"):
            reason_id = selection_id[7:]
            self.server._nav_push(
                user,
                self._show_server_power_confirm_menu,
                action,
                delay_seconds,
                reason_id,
                {},
            )

    def _show_server_power_confirm_menu(
        self,
        user: NetworkUser,
        action: str,
        delay_seconds: int,
        reason_id: str,
        custom_reasons: dict[str, str],
    ) -> None:
        if not self._require_dev_power(user):
            return
        action_enum = PowerAction(action)
        reason_text = (
            ServerPowerManager._custom_reason_for_locale(user.locale, custom_reasons)
            if reason_id == "custom"
            else Localization.get(user.locale, f"server-power-reason-{reason_id}")
        )
        show_confirmation_menu(
            user,
            "server_power_confirm_menu",
            prompt_key="server-power-confirm-summary",
            prompt_kwargs={
                "action": self.server.power_manager.format_action(
                    user.locale, action_enum
                ),
                "duration": ServerPowerManager.format_duration(
                    user.locale, delay_seconds
                ),
                "reason": reason_text,
            },
            confirm_choice=ConfirmationChoice("confirm", "confirm-yes"),
            cancel_choice=ConfirmationChoice("back", "confirm-no"),
            buffer="system",
        )
        self.server.user_states[user.username] = {
            "menu": "server_power_confirm_menu",
            "power_action": action,
            "power_delay_seconds": delay_seconds,
            "power_reason_id": reason_id,
            "power_custom_reasons": dict(custom_reasons),
        }

    async def _handle_server_power_confirm_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        if not self._require_dev_power(user):
            return
        if selection_id == "back":
            self.server._nav_back(user)
            return
        if selection_id != "confirm":
            return
        if self.server.power_manager.is_scheduled:
            user.speak_l("server-power-already-scheduled", buffer="system")
            self._return_to_admin_root(user, "server_power")
            return
        if self.server.maintenance_manager.is_active:
            user.speak_l("server-power-maintenance-active", buffer="system")
            self._return_to_admin_root(user, "server_power")
            return
        try:
            action = PowerAction(str(state.get("power_action") or ""))
        except ValueError:
            self._return_to_admin_root(user, "server_power")
            return
        delay_seconds = int(state.get("power_delay_seconds") or 0)
        reason_id = str(state.get("power_reason_id") or "unspecified")
        custom_reasons = dict(state.get("power_custom_reasons") or {})
        try:
            operation = self.server.power_manager.schedule(
                action=action,
                delay_seconds=delay_seconds,
                requested_by=user.username,
                reason_id=reason_id,
                custom_reasons=custom_reasons,
            )
        except RuntimeError:
            user.speak_l("server-power-maintenance-active", buffer="system")
            self._return_to_admin_root(user, "server_power")
            return
        user.speak_l(
            "server-power-scheduled",
            buffer="system",
            action=self.server.power_manager.format_action(user.locale, action),
            duration=ServerPowerManager.format_duration(
                user.locale, operation.delay_seconds
            ),
        )
        self._return_to_admin_root(user, "server_power")

    def _show_manage_motd_menu(self, user: NetworkUser) -> None:
        """Show the manage MOTD menu."""
        items = [
            MenuItem(text=Localization.get(user.locale, "create-update-motd"), id="create_update"),
            MenuItem(text=Localization.get(user.locale, "view-motd"), id="view"),
            MenuItem(text=Localization.get(user.locale, "delete-motd"), id="delete"),
            MenuItem(text=Localization.get(user.locale, "back"), id="back"),
        ]
        user.show_menu(
            "manage_motd_menu",
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {"menu": "manage_motd_menu"}

    def _show_view_motd_menu(self, user: NetworkUser) -> None:
        """Show the active MOTD text as a read-only menu."""
        active_version = self.server.db.get_highest_motd_version()
        motd_text = (
            self.server.db.get_motd(active_version, user.locale)
            if active_version
            else ""
        )
        if not motd_text:
            motd_text = Localization.get(user.locale, "motd-not-exists")

        items = [
            MenuItem(text=line, id="")
            for line in motd_text.split("\n")
        ]
        items.append(MenuItem(text=Localization.get(user.locale, "back"), id="back"))

        user.show_menu(
            "view_motd_menu",
            items,
            multiletter=False,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {"menu": "view_motd_menu"}

    async def _handle_manage_motd_selection(
        self, user: NetworkUser, selection_id: str, state: dict
    ) -> None:
        """Handle MOTD management selection."""
        if selection_id == "create_update":
            self.server._nav_push(
                user,
                self._show_admin_localized_text_menu,
                "motd",
                {},
                {"version": self.server.db.get_highest_motd_version() + 1},
            )

        elif selection_id == "view":
            active_version = self.server.db.get_highest_motd_version()
            if active_version == 0:
                user.speak_l("motd-not-exists", buffer="system")
                self.server._nav_refresh(user, self._show_manage_motd_menu)
            else:
                self.server._nav_push(user, self._show_view_motd_menu)

        elif selection_id == "delete":
            if self.server.db.get_highest_motd_version() == 0:
                user.speak_l("motd-delete-empty", buffer="system")
            else:
                self.server.db.delete_motd()
                user.speak_l("motd-deleted", buffer="system")
            self.server._nav_refresh(user, self._show_manage_motd_menu)

        elif selection_id == "back":
            self.server._nav_back(user)

    @require_admin
    async def perform_broadcast(self, admin: NetworkUser, message: str, show_menu: bool = True) -> None:
        """Perform the broadcast action."""
        # Clean up message
        message = message.strip()
        if not message:
            if show_menu:
                self._return_to_admin_root(admin, "broadcast_announcement")
            return

        # Prepare packets
        chat_packet = {
            "type": "chat",
            "convo": "announcement",
            "sender": admin.username, # Sender is still useful for logging/auditing but ignored by client display
            "message": message, # Raw message, client adds prefix
        }
        
        # Current clients own the single announcement cue; the server sends no
        # duplicate sound packet.

        count = 0
        total_online = len(self.server.users)
        
        # We iterate a copy of values to be safe against dictionary changes during async await
        users_list = list(self.server.users.values())
        
        for user in users_list:
            if user.approved:
                try:
                    # Send Chat
                    await user.connection.send(chat_packet)
                    count += 1
                except Exception as e:
                    print(f"Failed to broadcast to {user.username}: {e}")

        # Send confirmation to admin using speak_l (this uses queue, which is fine for local feedback)
        admin.speak_l("admin-broadcast-sent", buffer="system", count=count)
        
        # Also play a confirmation sound for admin locally via queue
        
        if show_menu:
            self._return_to_admin_root(admin, "broadcast_announcement")

    # ==================== Kick System ====================

    def _show_kick_menu(
        self,
        user: NetworkUser,
        query: str = "",
        page: int = 1,
        *,
        focus_page_start: bool = False,
    ) -> None:
        """Show searchable online kick targets."""
        self._show_admin_target_menu(
            user,
            menu_id="kick_menu",
            mode="kick",
            action_prefix="kick",
            targets=self._search_kick_targets(user, query, page),
            empty_key="no-users-to-kick",
            query=query,
            focus_page_start=focus_page_start,
        )

    def _show_kick_confirm_menu(self, user: NetworkUser, target_username: str) -> None:
        """Show confirmation menu for kicking a user."""
        show_confirmation_menu(
            user,
            "kick_confirm_menu",
            prompt_key="kick-confirm",
            prompt_kwargs={"player": target_username},
            buffer="system",
        )
        self.server.user_states[user.username] = {
            "menu": "kick_confirm_menu",
            "target_username": target_username,
        }

    @require_admin
    async def kick_user(self, admin: NetworkUser, target_username: str, show_menu: bool = True) -> None:
        """Kick a user from the server."""
        resolution = self.server.db.resolve_user(target_username)
        if resolution.ambiguous:
            admin.speak_l(
                "username-ambiguous",
                buffer="system",
                username=target_username,
            )
            if show_menu:
                self.server._nav_back(admin)
            return
        target_record = resolution.user
        if target_record:
            target_username = target_record.username

        # Check if user is online
        target_user = self.server.users.get(target_username)
        if not target_user:
            admin.speak_l("user-not-online", buffer="system", target=target_username)
            if show_menu:
                self.server._nav_back(admin)
            return

        # Check immunity
        if target_user.trust_level >= DEVELOPER_TRUST_LEVEL:
            admin.speak_l("permission-denied", buffer="system")
            if show_menu:
                self.server._nav_back(admin)
            return
        
        if (
            admin.trust_level < DEVELOPER_TRUST_LEVEL
            and target_user.trust_level >= ADMIN_TRUST_LEVEL
        ):
            admin.speak_l("permission-denied", buffer="system")
            if show_menu:
                self.server._nav_back(admin)
            return

        # Broadcast the moderation event in each listener's locale.
        for u in self.server.users.values():
            if u.approved:
                u.speak_l("kick-broadcast", buffer="system", target=target_username, actor=admin.username)
                u.play_sound("kick.ogg")

        # 2. Atomically evict the exact current account owner. This serializes
        # moderation against a simultaneous device handover and makes the old
        # socket incapable of mutating game/session state before it closes.
        await self.server._evict_account_session(
            target_username,
            {"type": "force_exit", "reason": "kicked"},
        )

        # 3. Return Admin to Menu
        if show_menu:
            self._return_to_admin_root(admin, "kick_user")

    # ==================== Ban System ====================

    def _show_ban_menu(
        self,
        user: NetworkUser,
        query: str = "",
        page: int = 1,
        *,
        focus_page_start: bool = False,
    ) -> None:
        """Show searchable ban targets."""
        self._show_admin_target_menu(
            user,
            menu_id="ban_menu",
            mode="ban",
            action_prefix="ban",
            targets=self._search_ban_targets(user, query, page),
            empty_key="no-users-to-ban",
            query=query,
            focus_page_start=focus_page_start,
        )

    async def _handle_ban_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        if selection_id == "back":
            self.server._nav_back(user)
        elif selection_id == "search":
            self._handle_target_search_selection(user, state)
        elif self._handle_target_page_selection(user, selection_id, state):
            return
        elif selection_id.startswith("ban_"):
            target_username = selection_id[4:]
            self.server._nav_push(user, self._show_ban_duration_menu, target_username)

    def _show_ban_duration_menu(self, user: NetworkUser, target_username: str) -> None:
        """Show duration options for banning."""
        items = [
            MenuItem(text=Localization.get(user.locale, "ban-duration-1h"), id="duration_1h"),
            MenuItem(text=Localization.get(user.locale, "ban-duration-6h"), id="duration_6h"),
            MenuItem(text=Localization.get(user.locale, "ban-duration-12h"), id="duration_12h"),
            MenuItem(text=Localization.get(user.locale, "ban-duration-1d"), id="duration_1d"),
            MenuItem(text=Localization.get(user.locale, "ban-duration-3d"), id="duration_3d"),
            MenuItem(text=Localization.get(user.locale, "ban-duration-1w"), id="duration_1w"),
            MenuItem(text=Localization.get(user.locale, "ban-duration-1m"), id="duration_1m"),
            MenuItem(text=Localization.get(user.locale, "ban-duration-permanent"), id="duration_perm"),
            MenuItem(text=Localization.get(user.locale, "back"), id="back"),
        ]

        user.show_menu(
            "ban_duration_menu",
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {
            "menu": "ban_duration_menu",
            "target_username": target_username,
        }

    async def _handle_ban_duration_selection(self, user: NetworkUser, selection_id: str, state: dict) -> None:
        if selection_id == "back":
            self.server._nav_back(user)
            return

        target_username = state.get("target_username")
        if not target_username:
            self.server._nav_back(user)
            return

        if selection_id.startswith("duration_"):
            duration = selection_id[9:]
            self.server._nav_push(
                user, self._show_ban_reason_menu, target_username, duration
            )

    def _show_ban_reason_menu(self, user: NetworkUser, target_username: str, duration: str) -> None:
        """Show reason options for banning."""
        items = [
            MenuItem(text=Localization.get(user.locale, "reason-spam"), id="reason_spam"),
            MenuItem(text=Localization.get(user.locale, "reason-harassment"), id="reason_harassment"),
            MenuItem(text=Localization.get(user.locale, "reason-cheating"), id="reason_cheating"),
            MenuItem(text=Localization.get(user.locale, "reason-inappropriate"), id="reason_inappropriate"),
            MenuItem(text=Localization.get(user.locale, "reason-custom"), id="reason_custom"),
            MenuItem(text=Localization.get(user.locale, "back"), id="back"),
        ]

        user.show_menu(
            "ban_reason_menu",
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {
            "menu": "ban_reason_menu",
            "target_username": target_username,
            "duration": duration,
        }

    async def _handle_ban_reason_selection(self, user: NetworkUser, selection_id: str, state: dict) -> None:
        if selection_id == "back":
            target_username = state.get("target_username")
            if target_username:
                self.server._nav_back(user)
            else:
                self._return_to_admin_root(user, "ban_user")
            return

        target_username = state.get("target_username")
        duration = state.get("duration")

        if not target_username or not duration:
            self._return_to_admin_root(user, "ban_user")
            return

        if selection_id == "reason_custom":
            self.server._nav_push(
                user,
                self._show_admin_localized_text_menu,
                "ban",
                {},
                {"target_username": target_username, "duration": duration},
            )
        elif selection_id.startswith("reason_"):
            # Internal reason keys are formatted like "reason-spam"
            reason_key = selection_id.replace("_", "-")
            await self._perform_ban(user, target_username, duration, reason_key)

    @require_admin
    async def _perform_ban(self, admin: NetworkUser, target_username: str, duration_id: str, reason_key: str) -> None:
        # Calculate expires_at
        now = datetime.now()
        expires_at = None
        duration_locale_key = f"ban-duration-{duration_id}"

        if duration_id == "1h":
            expires_at = (now + timedelta(hours=1)).isoformat()
        elif duration_id == "6h":
            expires_at = (now + timedelta(hours=6)).isoformat()
        elif duration_id == "12h":
            expires_at = (now + timedelta(hours=12)).isoformat()
        elif duration_id == "1d":
            expires_at = (now + timedelta(days=1)).isoformat()
        elif duration_id == "3d":
            expires_at = (now + timedelta(days=3)).isoformat()
        elif duration_id == "1w":
            expires_at = (now + timedelta(weeks=1)).isoformat()
        elif duration_id == "1m":
            expires_at = (now + timedelta(days=30)).isoformat()
        elif duration_id == "perm":
            expires_at = None
            duration_locale_key = "ban-duration-permanent"

        # Check target user hierarchy again for safety
        target_record = self.server.db.get_user(target_username)
        if not target_record:
            admin.speak_l("user-not-online", buffer="system", target=target_username)
            self._return_to_admin_root(admin, "ban_user")
            return
        target_username = target_record.username

        if target_record.trust_level >= DEVELOPER_TRUST_LEVEL or (
            admin.trust_level < DEVELOPER_TRUST_LEVEL
            and target_record.trust_level >= ADMIN_TRUST_LEVEL
        ):
            admin.speak_l("permission-denied", buffer="system")
            self._return_to_admin_root(admin, "ban_user")
            return

        # Write to database
        self.server.db.ban_user(target_username, admin.username, reason_key, expires_at)

        # Broadcast
        for u in self.server.users.values():
            if u.approved:
                loc_reason = localized_penalty_reason_for_locale(
                    u.locale, reason_key
                )

                loc_duration = Localization.get(u.locale, duration_locale_key)
                u.speak_l("ban-broadcast", buffer="system", target=target_username, actor=admin.username, reason=loc_reason, duration=loc_duration)
                u.play_sound("accountban.ogg")

        # Centralized eviction serializes this moderation action against device
        # handover and prevents stale close callbacks from touching a successor.
        await self.server._evict_account_session(
            target_username,
            {"type": "force_exit", "reason": "banned"},
        )

        self._return_to_admin_root(admin, "ban_user")

    def _show_unban_menu(
        self,
        user: NetworkUser,
        query: str = "",
        page: int = 1,
        *,
        focus_page_start: bool = False,
    ) -> None:
        """Show searchable active bans."""
        self._show_admin_target_menu(
            user,
            menu_id="unban_menu",
            mode="unban",
            action_prefix="unban",
            targets=self._search_active_bans_page(query, page, user.locale),
            empty_key="no-banned-users",
            query=query,
            focus_page_start=focus_page_start,
        )

    async def _handle_unban_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        if selection_id == "back":
            self.server._nav_back(user)
        elif selection_id == "search":
            self._handle_target_search_selection(user, state)
        elif self._handle_target_page_selection(user, selection_id, state):
            return
        elif selection_id.startswith("unban_"):
            target_username = selection_id[6:]
            await self._perform_unban(user, target_username)

    @require_admin
    async def _perform_unban(self, admin: NetworkUser, target_username: str) -> None:
        if self.server.db.unban_user(target_username):
            # Broadcast
            for u in self.server.users.values():
                if u.approved:
                    u.speak_l("unban-broadcast", buffer="system", target=target_username, actor=admin.username)
                    u.play_sound("accountban.ogg") # Requested to use same sound

        state = self.server.user_states.get(admin.username, {})
        self._refresh_admin_target_menu(
            admin,
            "unban",
            str(state.get("search_query", "")),
            int(state.get("target_page", 1) or 1),
        )

    # ==================== Mute / Unmute ====================

    def _show_mute_menu(
        self,
        user: NetworkUser,
        query: str = "",
        page: int = 1,
        *,
        focus_page_start: bool = False,
    ) -> None:
        """Show searchable mute targets."""
        self._show_admin_target_menu(
            user,
            menu_id="mute_menu",
            mode="mute",
            action_prefix="mute",
            targets=self._search_mute_targets(user, query, page),
            empty_key="no-users-to-mute",
            query=query,
            focus_page_start=focus_page_start,
        )

    async def _handle_mute_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        if selection_id == "back":
            self.server._nav_back(user)
        elif selection_id == "search":
            self._handle_target_search_selection(user, state)
        elif self._handle_target_page_selection(user, selection_id, state):
            return
        elif selection_id.startswith("mute_"):
            target_username = selection_id[5:]
            self.server._nav_push(user, self._show_mute_duration_menu, target_username)

    def _show_mute_duration_menu(self, user: NetworkUser, target_username: str) -> None:
        """Show duration options for muting."""
        items = [
            MenuItem(text=Localization.get(user.locale, "mute-duration-5m"), id="duration_5m"),
            MenuItem(text=Localization.get(user.locale, "mute-duration-15m"), id="duration_15m"),
            MenuItem(text=Localization.get(user.locale, "mute-duration-30m"), id="duration_30m"),
            MenuItem(text=Localization.get(user.locale, "mute-duration-1h"), id="duration_1h"),
            MenuItem(text=Localization.get(user.locale, "mute-duration-6h"), id="duration_6h"),
            MenuItem(text=Localization.get(user.locale, "mute-duration-1d"), id="duration_1d"),
            MenuItem(text=Localization.get(user.locale, "mute-duration-permanent"), id="duration_perm"),
            MenuItem(text=Localization.get(user.locale, "back"), id="back"),
        ]

        user.show_menu(
            "mute_duration_menu",
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {
            "menu": "mute_duration_menu",
            "target_username": target_username,
        }

    async def _handle_mute_duration_selection(self, user: NetworkUser, selection_id: str, state: dict) -> None:
        if selection_id == "back":
            self.server._nav_back(user)
            return

        target_username = state.get("target_username")
        if not target_username:
            self.server._nav_back(user)
            return

        if selection_id.startswith("duration_"):
            duration = selection_id[9:]
            self.server._nav_push(
                user, self._show_mute_reason_menu, target_username, duration
            )

    def _show_mute_reason_menu(self, user: NetworkUser, target_username: str, duration: str) -> None:
        """Show reason options for muting."""
        items = [
            MenuItem(text=Localization.get(user.locale, "reason-spam"), id="reason_spam"),
            MenuItem(text=Localization.get(user.locale, "reason-harassment"), id="reason_harassment"),
            MenuItem(text=Localization.get(user.locale, "reason-inappropriate"), id="reason_inappropriate"),
            MenuItem(text=Localization.get(user.locale, "reason-custom"), id="reason_custom"),
            MenuItem(text=Localization.get(user.locale, "back"), id="back"),
        ]

        user.show_menu(
            "mute_reason_menu",
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {
            "menu": "mute_reason_menu",
            "target_username": target_username,
            "duration": duration,
        }

    async def _handle_mute_reason_selection(self, user: NetworkUser, selection_id: str, state: dict) -> None:
        if selection_id == "back":
            target_username = state.get("target_username")
            if target_username:
                self.server._nav_back(user)
            else:
                self._return_to_admin_root(user, "mute_user")
            return

        target_username = state.get("target_username")
        duration = state.get("duration")

        if not target_username or not duration:
            self._return_to_admin_root(user, "mute_user")
            return

        if selection_id == "reason_custom":
            self.server._nav_push(
                user,
                self._show_admin_localized_text_menu,
                "mute",
                {},
                {"target_username": target_username, "duration": duration},
            )
        elif selection_id.startswith("reason_"):
            reason_key = selection_id.replace("_", "-")
            await self._perform_mute(user, target_username, duration, reason_key)

    @require_admin
    async def _perform_mute(self, admin: NetworkUser, target_username: str, duration_id: str, reason_key: str) -> None:
        now = datetime.now()
        expires_at = None
        duration_locale_key = f"mute-duration-{duration_id}"

        if duration_id == "5m":
            expires_at = (now + timedelta(minutes=5)).isoformat()
        elif duration_id == "15m":
            expires_at = (now + timedelta(minutes=15)).isoformat()
        elif duration_id == "30m":
            expires_at = (now + timedelta(minutes=30)).isoformat()
        elif duration_id == "1h":
            expires_at = (now + timedelta(hours=1)).isoformat()
        elif duration_id == "6h":
            expires_at = (now + timedelta(hours=6)).isoformat()
        elif duration_id == "1d":
            expires_at = (now + timedelta(days=1)).isoformat()
        elif duration_id == "perm":
            expires_at = None
            duration_locale_key = "mute-duration-permanent"

        # Hierarchy check
        target_record = self.server.db.get_user(target_username)
        if not target_record:
            admin.speak_l("user-not-found", buffer="system")
            self._return_to_admin_root(admin, "mute_user")
            return
        target_username = target_record.username

        if target_record.trust_level >= DEVELOPER_TRUST_LEVEL or (
            admin.trust_level < DEVELOPER_TRUST_LEVEL
            and target_record.trust_level >= ADMIN_TRUST_LEVEL
        ):
            admin.speak_l("permission-denied", buffer="system")
            self._return_to_admin_root(admin, "mute_user")
            return

        # Write to database
        self.server.db.mute_user(target_username, admin.username, reason_key, expires_at)

        # Broadcast to admins
        for u in self.server.users.values():
            if u.trust_level >= ADMIN_TRUST_LEVEL:
                loc_reason = localized_penalty_reason_for_locale(
                    u.locale, reason_key
                )
                loc_duration = Localization.get(u.locale, duration_locale_key)
                u.speak_l("mute-broadcast", buffer="system", target=target_username, actor=admin.username, reason=loc_reason, duration=loc_duration)

        # Notify the muted user if they are online
        target_user = self.server.users.get(target_username)
        if target_user:
            loc_reason = localized_penalty_reason_for_locale(
                target_user.locale, reason_key
            )
            loc_duration = Localization.get(target_user.locale, duration_locale_key)
            target_user.speak_l("you-have-been-muted", buffer="system", reason=loc_reason, duration=loc_duration)
            target_user.play_sound("accountban.ogg")
            await self.server.force_voice_context_leave(
                target_username,
                message_key="voice-status-disconnected",
            )

        self._return_to_admin_root(admin, "mute_user")

    def _show_unmute_menu(
        self,
        user: NetworkUser,
        query: str = "",
        page: int = 1,
        *,
        focus_page_start: bool = False,
    ) -> None:
        """Show searchable active mutes."""
        self._show_admin_target_menu(
            user,
            menu_id="unmute_menu",
            mode="unmute",
            action_prefix="unmute",
            targets=self._search_active_mutes_page(query, page, user.locale),
            empty_key="no-muted-users",
            query=query,
            focus_page_start=focus_page_start,
        )

    async def _handle_unmute_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        if selection_id == "back":
            self.server._nav_back(user)
        elif selection_id == "search":
            self._handle_target_search_selection(user, state)
        elif self._handle_target_page_selection(user, selection_id, state):
            return
        elif selection_id.startswith("unmute_"):
            target_username = selection_id[7:]
            await self._perform_unmute(user, target_username)

    @require_admin
    async def _perform_unmute(self, admin: NetworkUser, target_username: str) -> None:
        if self.server.db.unmute_user(target_username):
            # Broadcast to admins
            for u in self.server.users.values():
                if u.trust_level >= ADMIN_TRUST_LEVEL:
                    u.speak_l("unmute-broadcast", buffer="system", target=target_username, actor=admin.username)

            # Notify the unmuted user if they are online
            target_user = self.server.users.get(target_username)
            if target_user:
                target_user.speak_l("you-have-been-unmuted", buffer="system")

        state = self.server.user_states.get(admin.username, {})
        self._refresh_admin_target_menu(
            admin,
            "unmute",
            str(state.get("search_query", "")),
            int(state.get("target_page", 1) or 1),
        )

    # ------------------------------------------------------------------ #
    # Grant Coins to Players                                             #
    # ------------------------------------------------------------------ #

    def _search_grant_coins_targets(
        self, user: NetworkUser, query: str, page: int
    ) -> PaginatedMenuPage[str]:
        return self._search_user_targets_page(
            query,
            page,
            approved=True,
        )

    def _show_grant_coins_menu(
        self,
        user: NetworkUser,
        query: str = "",
        page: int = 1,
        *,
        focus_page_start: bool = False,
    ) -> None:
        """Show searchable list of users to grant coins."""
        self._show_admin_target_menu(
            user,
            menu_id=GRANT_COINS_MENU,
            mode="grant_coins",
            action_prefix="grant_coins",
            targets=self._search_grant_coins_targets(user, query, page),
            empty_key="admin-grant-coins-no-users",
            query=query,
            focus_page_start=focus_page_start,
        )

    async def _handle_grant_coins_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        if selection_id == "back":
            self.server._nav_back(user)
        elif selection_id == "search":
            self._handle_target_search_selection(user, state)
        elif self._handle_target_page_selection(user, selection_id, state):
            return
        elif selection_id.startswith("grant_coins_"):
            target_username = selection_id[len("grant_coins_"):]
            self.server._nav_push(user, self._show_grant_coins_amount_menu, target_username)

    def _show_grant_coins_amount_menu(
        self, user: NetworkUser, target_username: str
    ) -> None:
        """Show amount options to grant coins to the selected user."""
        resolution = self.server.db.resolve_user(target_username)
        target_record = resolution.user
        current_balance = 0
        if target_record:
            wallet = self.server.db.get_wallet(target_record.uuid)
            current_balance = wallet.balance
            display_name = target_record.username
        else:
            display_name = target_username

        items = [
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-grant-coins-target-balance",
                    player=display_name,
                    coins=current_balance,
                ),
                id="target_balance",
                read_only=True,
            )
        ]

        for amount in GRANT_COINS_PRESET_AMOUNTS:
            items.append(
                MenuItem(
                    text=Localization.get(
                        user.locale,
                        "coins-amount-option",
                        coins=amount,
                    ),
                    id=f"amount_{amount}",
                )
            )

        items.append(
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-grant-coins-custom-amount",
                ),
                id="amount_custom",
            )
        )
        items.append(MenuItem(text=Localization.get(user.locale, "back"), id="back"))

        user.show_menu(
            GRANT_COINS_AMOUNT_MENU,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {
            "menu": GRANT_COINS_AMOUNT_MENU,
            "target_username": target_username,
        }

    async def _handle_grant_coins_amount_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        target_username = state.get("target_username")
        if not target_username:
            self.server._nav_back(user)
            return

        if selection_id == "back":
            self.server._nav_back(user)
        elif selection_id == "amount_custom":
            user.show_editbox(
                "grant_coins_custom_amount",
                Localization.get(user.locale, "admin-grant-coins-prompt-amount"),
            )
            self.server.enter_input_state(
                user,
                GRANT_COINS_INPUT,
                target_username=target_username,
            )
        elif selection_id.startswith("amount_"):
            try:
                amount = int(selection_id[len("amount_"):])
                if amount > 0:
                    await self._grant_coins_to_user(user, target_username, amount)
            except ValueError:
                self.server._nav_back(user)

    @require_admin
    async def _grant_coins_to_user(
        self, admin: NetworkUser, target_username: str, amount: int
    ) -> None:
        """Grant virtual coins to a player and broadcast audio and speech notifications."""
        if amount <= 0:
            admin.speak_l("admin-grant-coins-error-positive", buffer="system")
            return

        resolution = self.server.db.resolve_user(target_username)
        if resolution.ambiguous:
            admin.speak_l(
                "username-ambiguous",
                buffer="system",
                username=target_username,
            )
            self._return_to_admin_root(admin, "grant_coins")
            return

        target_record = resolution.user
        if not target_record:
            admin.speak_l("auth-error-user-not-found", buffer="system")
            self._return_to_admin_root(admin, "grant_coins")
            return

        success, new_balance = self.server.db.adjust_wallet_balance(
            target_record.uuid,
            amount,
        )
        if not success:
            admin.speak_l("auth-registration-error", buffer="system")
            self._return_to_admin_root(admin, "grant_coins")
            return

        admin.play_sound("coins_grant.ogg")
        admin.speak_l(
            "admin-grant-coins-success",
            buffer="system",
            player=target_record.username,
            amount=amount,
            balance=new_balance,
        )

        target_user = self.server.users.get(target_record.username)
        if target_user and target_user.username != admin.username:
            target_user.play_sound("coins_grant.ogg")
            target_user.speak_l(
                "coins-granted-notification",
                buffer="system",
                amount=amount,
                balance=new_balance,
            )

        self._return_to_admin_root(admin, "grant_coins")

    # ------------------------------------------------------------------ #
    # Infiltrado Word Pairs Management                                  #
    # ------------------------------------------------------------------ #

    def _show_infiltrado_words_menu(self, user: NetworkUser) -> None:
        """Show Infiltrado word pairs management hub."""
        if user.trust_level < ADMIN_TRUST_LEVEL:
            user.speak_l("admin-only-action", buffer="system")
            self.server._nav_back(user)
            return

        total_pairs = InfiltradoWordManager.count_pairs()
        total_cats = len(InfiltradoWordManager.get_categories())
        items = [
            MenuItem(
                text=Localization.get(user.locale, "admin-infiltrado-add-pair"),
                id="add_pair",
            ),
            MenuItem(
                text=Localization.get(
                    user.locale, "admin-infiltrado-manage-categories", total=total_cats
                ),
                id="manage_categories",
            ),
            MenuItem(
                text=Localization.get(
                    user.locale, "admin-infiltrado-list-pairs", total=total_pairs
                ),
                id="list_pairs",
            ),
            MenuItem(text=Localization.get(user.locale, "back"), id="back"),
        ]
        user.show_menu(
            ADMIN_INFILTRADO_WORDS_MENU,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {
            "menu": ADMIN_INFILTRADO_WORDS_MENU,
        }

    async def _handle_infiltrado_words_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        """Handle selection in Infiltrado word pairs hub."""
        if selection_id == "add_pair":
            self.server.enter_input_state(user, ADMIN_INFILTRADO_ADD_WORD1_INPUT)
            user.show_editbox(
                "infiltrado_add_word1",
                Localization.get(user.locale, "admin-infiltrado-prompt-word1"),
            )
        elif selection_id == "manage_categories":
            self.server._nav_push(user, self._show_infiltrado_categories_menu)
        elif selection_id == "list_pairs":
            self.server._nav_push(user, self._show_infiltrado_pairs_list_menu, 1, None)
        elif selection_id == "back":
            self.server._nav_back(user)

    def _show_infiltrado_pairs_list_menu(
        self, user: NetworkUser, page: int = 1, category: str | None = None
    ) -> None:
        """Show paginated list of word pairs, optionally filtered by category."""
        if user.trust_level < ADMIN_TRUST_LEVEL:
            user.speak_l("admin-only-action", buffer="system")
            self.server._nav_back(user)
            return

        pairs = InfiltradoWordManager.get_pairs_by_category(category)
        page_size = 20
        paginated = paginate_sequence(pairs, page, page_size=page_size)

        items: list[MenuItem] = []
        if category:
            items.append(
                MenuItem(
                    text=Localization.get(
                        user.locale,
                        "admin-infiltrado-category-pairs-title",
                        category=category,
                        total=len(pairs),
                    ),
                    id="",
                    read_only=True,
                )
            )

        if not pairs:
            items.append(
                MenuItem(
                    text=Localization.get(user.locale, "admin-infiltrado-empty-pairs"),
                    id="",
                    read_only=True,
                )
            )
        else:
            for pair in paginated.items:
                cat_tag = f" [{pair.category}]" if not category else ""
                items.append(
                    MenuItem(
                        text=f"{pair.id}. {pair.word1} / {pair.word2}{cat_tag}",
                        id=f"pair_{pair.id}",
                    )
                )

        if paginated.total_pages > 1:
            items.extend(
                pagination_menu_items(user.locale, paginated, include_refresh=True)
            )

        items.append(MenuItem(text=Localization.get(user.locale, "back"), id="back"))

        user.show_menu(
            ADMIN_INFILTRADO_PAIRS_LIST_MENU,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {
            "menu": ADMIN_INFILTRADO_PAIRS_LIST_MENU,
            "page": paginated.page,
            "total_pages": paginated.total_pages,
            "category": category,
        }

    async def _handle_infiltrado_pairs_list_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        """Handle selection in paginated pairs list."""
        category = state.get("category")
        if selection_id == "back":
            self.server._nav_back(user)
            return

        if is_page_navigation(selection_id) or selection_id in MENU_PAGE_IDS:
            current_page = state.get("page", 1)
            total_pages = state.get("total_pages", 1)
            target_page = page_for_selection(selection_id, current_page, total_pages)
            if target_page is not None:
                if is_page_refresh(selection_id):
                    announce_page_refresh(user)
                self._show_infiltrado_pairs_list_menu(user, target_page, category)
            return

        if selection_id.startswith("pair_"):
            try:
                pair_id = int(selection_id.split("_")[1])
                self.server._nav_push(user, self._show_infiltrado_pair_detail_menu, pair_id)
            except (ValueError, IndexError):
                pass

    def _show_infiltrado_pair_detail_menu(
        self, user: NetworkUser, pair_id: int
    ) -> None:
        """Show detail / actions menu for a specific word pair."""
        if user.trust_level < ADMIN_TRUST_LEVEL:
            user.speak_l("admin-only-action", buffer="system")
            self.server._nav_back(user)
            return

        pair = InfiltradoWordManager.get_pair_by_id(pair_id)
        if not pair:
            user.speak_l("admin-infiltrado-empty-pairs", buffer="system")
            self.server._nav_back(user)
            return

        items = [
            MenuItem(
                text=Localization.get(
                    user.locale,
                    "admin-infiltrado-pair-current-with-cat",
                    id=pair.id,
                    word1=pair.word1,
                    word2=pair.word2,
                    category=pair.category,
                ),
                id="",
                read_only=True,
            ),
            MenuItem(
                text=Localization.get(
                    user.locale, "admin-infiltrado-edit-word1", word=pair.word1
                ),
                id="edit_word1",
            ),
            MenuItem(
                text=Localization.get(
                    user.locale, "admin-infiltrado-edit-word2", word=pair.word2
                ),
                id="edit_word2",
            ),
            MenuItem(
                text=Localization.get(
                    user.locale, "admin-infiltrado-change-category", category=pair.category
                ),
                id="change_category",
            ),
            MenuItem(
                text=Localization.get(user.locale, "admin-infiltrado-delete-pair"),
                id="delete_pair",
            ),
            MenuItem(text=Localization.get(user.locale, "back"), id="back"),
        ]

        user.show_menu(
            ADMIN_INFILTRADO_PAIR_DETAIL_MENU,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {
            "menu": ADMIN_INFILTRADO_PAIR_DETAIL_MENU,
            "pair_id": pair_id,
        }

    async def _handle_infiltrado_pair_detail_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        """Handle edit/delete action for a word pair."""
        pair_id = state.get("pair_id")
        if not pair_id:
            self.server._nav_back(user)
            return

        pair = InfiltradoWordManager.get_pair_by_id(int(pair_id))
        if not pair:
            self.server._nav_back(user)
            return

        if selection_id == "edit_word1":
            self.server.enter_input_state(
                user,
                ADMIN_INFILTRADO_EDIT_WORD1_INPUT,
                pair_id=pair.id,
            )
            user.show_editbox(
                "infiltrado_edit_word1",
                Localization.get(
                    user.locale, "admin-infiltrado-prompt-edit-word1", word=pair.word1
                ),
                default_value=pair.word1,
            )
        elif selection_id == "edit_word2":
            self.server.enter_input_state(
                user,
                ADMIN_INFILTRADO_EDIT_WORD2_INPUT,
                pair_id=pair.id,
            )
            user.show_editbox(
                "infiltrado_edit_word2",
                Localization.get(
                    user.locale, "admin-infiltrado-prompt-edit-word2", word=pair.word2
                ),
                default_value=pair.word2,
            )
        elif selection_id == "change_category":
            self.server._nav_push(
                user, self._show_infiltrado_select_category_menu, None, None, int(pair.id)
            )
        elif selection_id == "delete_pair":
            InfiltradoWordManager.delete_pair(pair.id)
            user.speak_l("admin-infiltrado-pair-deleted", buffer="system")
            user.play_sound("menuenter.ogg")
            self.server._nav_back(user)
        elif selection_id == "back":
            self.server._nav_back(user)

    # ------------------------------------------------------------------ #
    # Categories Management                                              #
    # ------------------------------------------------------------------ #

    def _show_infiltrado_categories_menu(self, user: NetworkUser) -> None:
        """Show Infiltrado categories list and actions."""
        if user.trust_level < ADMIN_TRUST_LEVEL:
            user.speak_l("admin-only-action", buffer="system")
            self.server._nav_back(user)
            return

        categories = InfiltradoWordManager.get_categories()
        items = [
            MenuItem(
                text=Localization.get(user.locale, "admin-infiltrado-add-category"),
                id="add_category",
            )
        ]
        for cat in categories:
            cnt = InfiltradoWordManager.count_pairs_by_category(cat)
            items.append(
                MenuItem(
                    text=Localization.get(
                        user.locale, "admin-infiltrado-category-item", category=cat, count=cnt
                    ),
                    id=f"cat_{cat}",
                )
            )
        items.append(MenuItem(text=Localization.get(user.locale, "back"), id="back"))

        user.show_menu(
            ADMIN_INFILTRADO_CATEGORIES_MENU,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {
            "menu": ADMIN_INFILTRADO_CATEGORIES_MENU,
        }

    async def _handle_infiltrado_categories_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        """Handle selection in categories list."""
        if selection_id == "back":
            self.server._nav_back(user)
            return

        if selection_id == "add_category":
            self.server.enter_input_state(user, ADMIN_INFILTRADO_ADD_CATEGORY_INPUT)
            user.show_editbox(
                "infiltrado_add_category",
                Localization.get(user.locale, "admin-infiltrado-prompt-category-name"),
            )
            return

        if selection_id.startswith("cat_"):
            cat_name = selection_id[4:]
            self.server._nav_push(user, self._show_infiltrado_category_detail_menu, cat_name)

    def _show_infiltrado_category_detail_menu(
        self, user: NetworkUser, category: str
    ) -> None:
        """Show detail and options for a specific category."""
        if user.trust_level < ADMIN_TRUST_LEVEL:
            user.speak_l("admin-only-action", buffer="system")
            self.server._nav_back(user)
            return

        cnt = InfiltradoWordManager.count_pairs_by_category(category)
        items = [
            MenuItem(
                text=Localization.get(
                    user.locale, "admin-infiltrado-category-current", category=category, count=cnt
                ),
                id="",
                read_only=True,
            ),
            MenuItem(
                text=Localization.get(user.locale, "admin-infiltrado-list-category-pairs"),
                id="list_pairs",
            ),
            MenuItem(
                text=Localization.get(user.locale, "admin-infiltrado-add-pair-to-category"),
                id="add_pair_to_category",
            ),
            MenuItem(
                text=Localization.get(user.locale, "admin-infiltrado-rename-category"),
                id="rename_category",
            ),
        ]
        if category.lower() != "general":
            items.append(
                MenuItem(
                    text=Localization.get(user.locale, "admin-infiltrado-delete-category"),
                    id="delete_category",
                )
            )
        items.append(MenuItem(text=Localization.get(user.locale, "back"), id="back"))

        user.show_menu(
            ADMIN_INFILTRADO_CATEGORY_DETAIL_MENU,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {
            "menu": ADMIN_INFILTRADO_CATEGORY_DETAIL_MENU,
            "category": category,
        }

    async def _handle_infiltrado_category_detail_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        """Handle actions on a category."""
        cat = state.get("category")
        if not cat:
            self.server._nav_back(user)
            return

        if selection_id == "back":
            self.server._nav_back(user)
            return

        if selection_id == "list_pairs":
            self.server._nav_push(user, self._show_infiltrado_pairs_list_menu, 1, cat)
            return

        if selection_id == "add_pair_to_category":
            self.server.enter_input_state(
                user,
                ADMIN_INFILTRADO_ADD_WORD1_INPUT,
                draft_category=cat,
            )
            user.show_editbox(
                "infiltrado_add_word1",
                Localization.get(user.locale, "admin-infiltrado-prompt-word1"),
            )
            return

        if selection_id == "rename_category":
            self.server.enter_input_state(
                user,
                ADMIN_INFILTRADO_RENAME_CATEGORY_INPUT,
                category=cat,
            )
            user.show_editbox(
                "infiltrado_rename_category",
                Localization.get(user.locale, "admin-infiltrado-prompt-rename-category", category=cat),
                default_value=cat,
            )
            return

        if selection_id == "delete_category":
            if cat.lower() == "general":
                user.speak_l("admin-infiltrado-category-cannot-delete-general", buffer="system")
                return
            cnt = InfiltradoWordManager.count_pairs_by_category(cat)
            show_confirmation_menu(
                user,
                ADMIN_INFILTRADO_DELETE_CATEGORY_CONFIRM_MENU,
                prompt_key="admin-infiltrado-delete-category-confirm",
                prompt_kwargs={"category": cat, "count": cnt},
                confirm_choice=ConfirmationChoice("confirm", "confirm-yes"),
                cancel_choice=ConfirmationChoice("back", "confirm-no"),
                buffer="system",
            )
            self.server.user_states[user.username] = {
                "menu": ADMIN_INFILTRADO_DELETE_CATEGORY_CONFIRM_MENU,
                "category": cat,
            }
            return

    async def _handle_infiltrado_delete_category_confirm_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        """Handle confirmation of category deletion."""
        cat = state.get("category")
        if selection_id == "confirm" and cat:
            InfiltradoWordManager.delete_category(cat, reassign_to="General")
            user.speak_l(
                "admin-infiltrado-category-deleted", buffer="system", category=cat
            )
            user.play_sound("menuenter.ogg")
            self.server._nav_back(user)
        else:
            self.server._nav_back(user)

    def _show_infiltrado_select_category_menu(
        self,
        user: NetworkUser,
        draft_word1: str | None = None,
        draft_word2: str | None = None,
        pair_id: int | None = None,
        parent_frame: dict[str, Any] | None = None,
    ) -> None:
        """Show category selection picker for a pair."""
        if user.trust_level < ADMIN_TRUST_LEVEL:
            user.speak_l("admin-only-action", buffer="system")
            self.server._nav_back(user)
            return

        categories = InfiltradoWordManager.get_categories()
        items = []
        for cat in categories:
            items.append(
                MenuItem(
                    text=cat,
                    id=f"sel_cat_{cat}",
                )
            )
        items.append(
            MenuItem(
                text=Localization.get(user.locale, "admin-infiltrado-category-create-new"),
                id="create_new_cat",
            )
        )
        items.append(MenuItem(text=Localization.get(user.locale, "cancel"), id="cancel"))

        user.show_menu(
            ADMIN_INFILTRADO_SELECT_CATEGORY_MENU,
            items,
            multiletter=True,
            escape_behavior=EscapeBehavior.SELECT_LAST,
        )
        self.server.user_states[user.username] = {
            "menu": ADMIN_INFILTRADO_SELECT_CATEGORY_MENU,
            "draft_word1": draft_word1,
            "draft_word2": draft_word2,
            "pair_id": pair_id,
            "_parent_frame": parent_frame,
        }

    async def _handle_infiltrado_select_category_selection(
        self, user: NetworkUser, selection_id: str, state: dict[str, Any]
    ) -> None:
        """Handle category selection for a pair."""
        draft_w1 = state.get("draft_word1")
        draft_w2 = state.get("draft_word2")
        pair_id = state.get("pair_id")
        parent = state.get("_parent_frame")

        if selection_id == "cancel":
            if parent:
                self.server._restore_input_parent(user, state)
            else:
                self.server._nav_back(user)
            return

        if selection_id == "create_new_cat":
            self.server.enter_input_state(
                user,
                ADMIN_INFILTRADO_ADD_CATEGORY_INPUT,
                draft_word1=draft_w1,
                draft_word2=draft_w2,
                _parent_frame=parent,
            )
            user.show_editbox(
                "infiltrado_add_category",
                Localization.get(user.locale, "admin-infiltrado-prompt-category-name"),
            )
            return

        if selection_id.startswith("sel_cat_"):
            cat_name = selection_id[8:]
            if draft_w1 and draft_w2:
                pair = InfiltradoWordManager.add_pair(draft_w1, draft_w2, category=cat_name)
                user.speak_l(
                    "admin-infiltrado-pair-added",
                    buffer="system",
                    word1=pair.word1,
                    word2=pair.word2,
                    category=pair.category,
                )
                user.play_sound("menuenter.ogg")
            elif pair_id:
                pair = InfiltradoWordManager.update_pair(int(pair_id), category=cat_name)
                if pair:
                    user.speak_l(
                        "admin-infiltrado-pair-category-updated",
                        buffer="system",
                        category=cat_name,
                    )
                    user.play_sound("menuenter.ogg")

            if parent:
                self.server._restore_input_parent(user, state)
            else:
                self.server._nav_back(user)
