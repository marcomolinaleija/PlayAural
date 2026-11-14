"""Translation overlays use the existing server menu/input navigation."""

COLLABORATE = 'collaborate_menu'
LANGUAGES = 'translation_languages'
DASHBOARD = 'translation_dashboard'
SECTIONS = 'translation_sections'
UNITS = 'translation_units'
EDITOR = 'translation_editor'
MINE = 'translation_mine'
REVIEW = 'translation_review'
REVIEW_AUTHORS = 'translation_review_authors'
REVIEW_ITEMS = 'translation_review_items'
TEAM = 'translation_team'
TEAM_MEMBER = 'translation_team_member'
TEAM_CONFIRM = 'translation_team_confirm'
HISTORY = 'translation_history'
CREDITS = 'translation_credits'
NEW_LANGUAGE = 'translation_new_language'
CONFIRM = 'translation_confirm'
CONFLICT = 'translation_conflict'
FORMS = 'translation_forms'
FORM_EDITOR = 'translation_form_editor'
TEXT_INPUT = 'translation_text_input'
READ_INPUT = 'translation_read_input'
NOTE_INPUT = 'translation_note_input'
SEARCH_INPUT = 'translation_search_input'
LANGUAGE_INPUT = 'translation_language_input'
INPUT_IDS = frozenset({TEXT_INPUT, READ_INPUT, NOTE_INPUT, SEARCH_INPUT, LANGUAGE_INPUT})
MENU_IDS = frozenset({CONFLICT, FORMS, FORM_EDITOR, COLLABORATE, LANGUAGES, DASHBOARD, SECTIONS, UNITS, EDITOR, MINE,
                      REVIEW, REVIEW_AUTHORS, REVIEW_ITEMS, TEAM, TEAM_MEMBER, TEAM_CONFIRM,
                      HISTORY, CREDITS, NEW_LANGUAGE, CONFIRM}) | INPUT_IDS
