"""Stable forum surfaces registered with the shared navigation framework."""

HOME = "forum_home"
TOPICS = "forum_topics"
THREAD = "forum_thread"
POST = "forum_post"
COMPOSER = "forum_composer"
DISCARD = "forum_discard"
MODERATE = "forum_moderate"
TITLE_INPUT = "forum_title_input"
BODY_INPUT = "forum_body_input"
SEARCH_INPUT = "forum_search_input"
INPUT_IDS = frozenset({TITLE_INPUT, BODY_INPUT, SEARCH_INPUT})
MENU_IDS = frozenset({HOME, TOPICS, THREAD, POST, COMPOSER, DISCARD, MODERATE,
                      TITLE_INPUT, BODY_INPUT, SEARCH_INPUT})
CONFIRMATION_IDS = frozenset({DISCARD, MODERATE})
