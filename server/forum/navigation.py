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
EXTRAS = 'forum_extras'
POLL_EDITOR = 'forum_poll_editor'
POLL = 'forum_poll'
POLL_CLOSE = 'forum_poll_close'
POLL_QUESTION_INPUT = 'forum_poll_question_input'
POLL_OPTIONS_INPUT = 'forum_poll_options_input'
INVITATIONS = 'forum_invitations'
INVITATION = 'forum_invitation'
MEMBERS = 'forum_members'
LEAVE = 'forum_leave'
REMOVE_MEMBER = 'forum_remove_member'
RECIPIENTS_INPUT = 'forum_recipients_input'
INVITE_INPUT = 'forum_invite_input'
ATTACHMENT = 'forum_attachment'
MEDIA_DESCRIPTION_INPUT = 'forum_media_description_input'
PENDING_MEDIA = 'forum_pending_media'
REVIEW_MEDIA = 'forum_review_media'
CONFIRM_MEDIA_REVIEW = 'forum_confirm_media_review'
CATEGORIES = 'forum_categories'
CATEGORY_EDITOR = 'forum_category_editor'
CATEGORY_DESTINATION = 'forum_category_destination'
CATEGORY_DELETE = 'forum_category_delete'
CATEGORY_NAME_INPUT = 'forum_category_name_input'
CATEGORY_DESCRIPTION_INPUT = 'forum_category_description_input'
CATEGORY_MENU_IDS = frozenset({CATEGORIES, CATEGORY_EDITOR, CATEGORY_DESTINATION, CATEGORY_DELETE})
CATEGORY_INPUT_IDS = frozenset({CATEGORY_NAME_INPUT, CATEGORY_DESCRIPTION_INPUT})
POLL_INPUT_IDS = frozenset({POLL_QUESTION_INPUT, POLL_OPTIONS_INPUT})
PRIVATE_INPUT_IDS = frozenset({RECIPIENTS_INPUT, INVITE_INPUT})
EXTENSION_MENU_IDS = frozenset({EXTRAS, POLL_EDITOR, POLL, POLL_CLOSE, INVITATIONS, INVITATION, MEMBERS, LEAVE, REMOVE_MEMBER,
                                ATTACHMENT, PENDING_MEDIA, REVIEW_MEDIA, CONFIRM_MEDIA_REVIEW})
INPUT_IDS = frozenset({TITLE_INPUT, BODY_INPUT, SEARCH_INPUT, MEDIA_DESCRIPTION_INPUT}) | POLL_INPUT_IDS | PRIVATE_INPUT_IDS | CATEGORY_INPUT_IDS
MENU_IDS = frozenset({HOME, TOPICS, THREAD, POST, COMPOSER, DISCARD, MODERATE,
                      TITLE_INPUT, BODY_INPUT, SEARCH_INPUT}) | INPUT_IDS | EXTENSION_MENU_IDS | CATEGORY_MENU_IDS
CONFIRMATION_IDS = frozenset({DISCARD, MODERATE, POLL_CLOSE, LEAVE, REMOVE_MEMBER, CONFIRM_MEDIA_REVIEW, CATEGORY_DELETE})
