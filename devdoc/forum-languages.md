# Public forum communities by language

Schema **9** assigns a fixed `language` to each public subforum. A topic and its
posts inherit that language through `category_id`; there is no duplicated topic,
attachment, ballot or account store. Existing public content and category ids
remain in Spanish. New communities start with independent Community, Questions
and help, and Ideas and feedback categories for English, Vietnamese, Arabic,
Persian, Indonesian and Portuguese. Default labels follow the community's
language, with normal localization fallback; custom names remain literal.

`forum_language_preferences` stores an explicit account-UUID selection. Before
an explicit choice, the account's interface locale chooses the initial community
(supported base locale, otherwise English). This setting is separate from general
user preferences and does not change interface language. Account deletion removes
it through the existing user foreign key; ordinary backups retain it.

The forum home has a bottom action, Forum language, and announces its language
on entry. Selection uses existing menus across desktop and web. List navigation,
page refresh, search input restoration and category administration retain their
language context in navigation frames. Topic/post entry announces the language
of the actual content. No client protocol or native mobile work is required.

## Query and administration boundaries

The service resolves/validates a language for every public listing. Repository
queries scope categories, recent topics, unread topics, search, public saved
topics and their counts to that language. Private conversations and saved private
threads remain membership-scoped and appear regardless of community selection.
Existing bilateral blocks continue to apply in every community.

Language is a browsing context, not an additional access restriction. An existing
public topic/post id can still be opened by an otherwise admitted account,
including from moderation. Opening it announces its own community without
rewriting the reader's saved choice. Existing attachment and poll ACLs remain
authoritative. Account-level write/report/media quotas span all languages.

Administrators create subforums in the language of the opened editor, even if a
different preference is selected before saving. Duplicate names and the 64-category
limit are evaluated within that language. Editing never changes category language.
Deleting a populated subforum only offers destinations of the same language;
the service also rejects cross-language destinations. Restored message drafts
publish through their original category/topic id rather than the current choice.

Reports share the existing staff queue. New immutable evidence records the
content language; old version-1 evidence without that field belongs to Spanish,
matching the migration. Staff see the reported language beside its saved title
and body. Private content remains excluded from reporting.

## Migration and verification

The central migration validates the real schema-8 contract, creates a verified
pre-migration database backup, and adds the category column, language index and
preference table in one transaction. It keeps all old ids, custom names,
descriptions, revisions, posts, polls, bookmarks and read positions. Deleted
Spanish defaults stay deleted. New language defaults are inserted only when the
column is first added; restarting never resurrects deleted communities/categories.
The protected internal private category's language is unused by private queries.

The schema-9 preference upsert and DDL stay within the SQLite 3.25 baseline.
Legacy canonical validation omits the new language constraints and tables.
Historical forum fixtures explicitly use Spanish so their original stable ids
continue to exercise the same behavior.

`server/tests/test_forum_languages.py` covers initial defaults, persisted choice,
all public list modes, distinct category ids, independent private membership,
blocks, bookmarks/read positions, scoped administration, frozen drafts, report
language snapshots, account deletion, verified schema-8 migration, rollback/retry
and real desktop/web WebSocket selection and administration.

Validation on 2026-11-11: **5,287 server tests passed, 15 skipped** (`-n 2`).
The affected language/navigation/category/report/availability/migration suites
also passed **110 tests**, including real WebSocket `python` and `web` clients.
No native mobile build, dependency repair or emulator was started.
