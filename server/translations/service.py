"""Durable drafts, optimistic review and credits; never writes source files."""

from contextlib import contextmanager
import json
import time

from ..users.roles import ADMIN_TRUST_LEVEL
from ..menu_pagination import PaginatedMenuPage, clamp_page
from .catalog import Catalog, default_catalog
from .models import MAX_BATCH, MAX_NOTE, MAX_OPEN_PROPOSALS, OPEN_STATES, PAGE_SIZE, TranslationError, fingerprint
from .forms import forms, assemble, needs_forms, form_unit
from .validation import clean_text, example, language_code, validate, parse, structure
from .reservations import Reservations, RESERVATION_SECONDS
from .roles import TranslatorRoles


class TranslationService:
    def __init__(self, database, catalog: Catalog | None = None, clock=time.time):
        self.db = database
        self._catalog = catalog
        self.clock = clock
        self.reservations = Reservations(self)
        self.roles = TranslatorRoles(self)

    @property
    def catalog(self):
        if self._catalog is None:
            self._catalog = default_catalog()
        return self._catalog

    @property
    def connection(self):
        return self.db._conn

    @contextmanager
    def atomic(self):
        with self.db._transaction(immediate=True):
            yield

    def account(self, viewer, *, reviewer=False, writing=False):
        account = self.db.get_user_by_uuid(viewer)
        if not account or not account.approved or self.db.get_active_ban(account.username):
            raise TranslationError('translation-error-account')
        if writing and self.db.get_active_mute(account.username):
            raise TranslationError('translation-error-muted')
        if reviewer:
            self.roles.require_review(viewer)
        return account

    def languages(self, viewer):
        self.account(viewer)
        languages = {code: {**row, 'status': 'installed'} for code, row in self.catalog.languages().items()}
        for row in self.connection.execute('SELECT * FROM translation_languages ORDER BY code'):
            if row['code'] not in languages:
                languages[row['code']] = dict(row)
        return languages

    def language(self, viewer, code):
        languages = self.languages(viewer)
        if code not in languages:
            raise TranslationError('translation-error-language')
        return languages[code]

    def create_language(self, viewer, code, name, native_name):
        code = language_code(code)
        name = clean_text(name, limit=80).strip()
        native_name = clean_text(native_name, limit=80).strip()
        with self.atomic():
            self.account(viewer, writing=True)
            if code in self.languages(viewer):
                raise TranslationError('translation-error-language-exists')
            if self.connection.execute('SELECT COUNT(*) FROM translation_languages').fetchone()[0] >= 100:
                raise TranslationError('translation-error-limit')
            if self.connection.execute("SELECT COUNT(*) FROM translation_languages WHERE creator_uuid = ? AND status = 'proposed'", (viewer,)).fetchone()[0] >= 5:
                raise TranslationError('translation-error-limit')
            self.connection.execute('''INSERT INTO translation_languages(code, name, native_name, creator_uuid, created_at)
                VALUES (?, ?, ?, ?, ?)''', (code, name, native_name, viewer, int(self.clock())))
        return code

    def installed_value(self, language, unit_id):
        unit = self.catalog.get(unit_id)
        return self.catalog.current(unit, language)

    def current(self, language, unit_id):
        row = self.connection.execute('SELECT * FROM translation_accepted WHERE language = ? AND unit_id = ?', (language, unit_id)).fetchone()
        if row is not None and row['source_hash'] == self.catalog.get(unit_id).source_hash:
            return row['value']
        return self.installed_value(language, unit_id)

    def accepted_revision(self, language, unit_id):
        row = self.connection.execute('SELECT revision FROM translation_accepted WHERE language = ? AND unit_id = ?', (language, unit_id)).fetchone()
        return row[0] if row else 0

    def baseline(self, language, unit_id):
        return fingerprint(str(self.accepted_revision(language, unit_id)) + '\0' + self.current(language, unit_id))

    def proposals(self, viewer, *, language=None, pending=False):
        self.account(viewer, reviewer=pending)
        where, params = ("status = 'pending'", []) if pending else ('author_uuid = ?', [viewer])
        if language:
            self.language(viewer, language)
            if pending:
                self.roles.require_review(viewer, language)
            where += ' AND language = ?'
            params.append(language)
        if pending and self.account(viewer).trust_level < ADMIN_TRUST_LEVEL:
            assigned = sorted(self.roles.languages(viewer))
            where += ' AND language IN (' + ','.join('?' for _ in assigned) + ')'
            params.extend(assigned)
        return [dict(row) for row in self.connection.execute(
            'SELECT * FROM translation_proposals WHERE ' + where + ' ORDER BY updated_at DESC, id DESC', params)]

    def proposal_page(self, viewer, *, language=None, review=False, history=False, page=1, author=None):
        self.account(viewer, reviewer=review)
        where = "status IN ('approved', 'rejected', 'reverted')" if review and history else "status = 'pending'" if review else 'author_uuid = ?'
        params = [] if review else [viewer]
        if language:
            self.language(viewer, language)
            if review:
                self.roles.require_review(viewer, language)
            where += ' AND language = ?'
            params.append(language)
        if review and author is not None:
            where += " AND COALESCE(author_uuid, 'deleted') = ?"
            params.append(author)
        if review:
            account = self.account(viewer)
            if account.trust_level < ADMIN_TRUST_LEVEL:
                assigned = sorted(self.roles.languages(viewer))
                where += ' AND language IN (' + ','.join('?' for _ in assigned) + ')'
                params.extend(assigned)
        total = self.connection.execute('SELECT COUNT(*) FROM translation_proposals WHERE ' + where, params).fetchone()[0]
        page = clamp_page(page, total, PAGE_SIZE)
        rows = [dict(row) for row in self.connection.execute('SELECT * FROM translation_proposals WHERE ' + where +
                ' ORDER BY updated_at DESC, id DESC LIMIT ? OFFSET ?', [*params, PAGE_SIZE, (page - 1) * PAGE_SIZE])]
        return PaginatedMenuPage(rows, page, total, PAGE_SIZE)

    def review_groups(self, viewer, *, language='', history=False, page=1):
        """Count only submitted work, grouped by language then immutable author."""
        self.account(viewer, reviewer=True)
        where = "p.status IN ('approved', 'rejected', 'reverted')" if history else "p.status = 'pending'"
        params = []
        if self.account(viewer).trust_level < ADMIN_TRUST_LEVEL:
            assigned = sorted(self.roles.languages(viewer))
            where += ' AND p.language IN (' + ','.join('?' for _ in assigned) + ')'
            params.extend(assigned)
        if language:
            self.language(viewer, language)
            self.roles.require_review(viewer, language)
            where += ' AND p.language = ?'
            params.append(language)
            query = """SELECT COALESCE(p.author_uuid, 'deleted') AS author_id,
                COALESCE(u.username, '') AS author, COUNT(*) AS count
                FROM translation_proposals p LEFT JOIN users u ON u.uuid = p.author_uuid
                WHERE """ + where + ' GROUP BY p.author_uuid ORDER BY author COLLATE NOCASE, author_id'
        else:
            query = 'SELECT p.language, COUNT(*) AS count FROM translation_proposals p WHERE ' + where + ' GROUP BY p.language ORDER BY p.language'
        total = self.connection.execute('SELECT COUNT(*) FROM (' + query + ')', params).fetchone()[0]
        page = clamp_page(page, total, PAGE_SIZE)
        rows = [dict(row) for row in self.connection.execute(query + ' LIMIT ? OFFSET ?', [*params, PAGE_SIZE, (page - 1) * PAGE_SIZE])]
        return PaginatedMenuPage(rows, page, total, PAGE_SIZE)

    def open_statuses(self, viewer, language):
        self.language(viewer, language)
        return {row['unit_id']: row['status'] for row in self.connection.execute('''SELECT unit_id, status
            FROM translation_proposals WHERE author_uuid = ? AND language = ?
            AND status IN ('draft', 'pending', 'changes_requested')''', (viewer, language))}

    def get(self, viewer, proposal_id, *, review=False):
        self.account(viewer, reviewer=review)
        row = self.connection.execute('SELECT * FROM translation_proposals WHERE id = ?', (proposal_id,)).fetchone()
        if row is None or (not review and row['author_uuid'] != viewer):
            raise TranslationError('translation-error-proposal')
        if review and row['status'] not in {'pending', 'approved', 'rejected', 'reverted'}:
            raise TranslationError('translation-error-proposal')
        if review:
            self.roles.require_review(viewer, row['language'])
        return dict(row)

    def revision(self, row, expected):
        if type(expected) is not int or row['revision'] != expected:
            raise TranslationError('translation-error-changed')

    def _event(self, proposal_id, actor, action, **values):
        self.connection.execute('''INSERT INTO translation_events(proposal_id, actor_uuid, action, value_json, created_at)
            VALUES (?, ?, ?, ?, ?)''', (proposal_id, actor, action, json.dumps(values, ensure_ascii=False), int(self.clock())))

    def draft(self, viewer, language, unit_id, *, copy_from=None):
        """Idempotent opening; each author owns at most one editable proposal."""
        with self.atomic():
            account = self.account(viewer, writing=True)
            self.language(viewer, language)
            unit = self.catalog.get(unit_id)
            previous = self.get(viewer, copy_from) if copy_from is not None else None
            if previous and (previous['language'] != language or previous['unit_id'] != unit_id
                             or previous['status'] not in {'approved', 'rejected', 'withdrawn', 'reverted'}):
                raise TranslationError('translation-error-proposal')
            row = self.connection.execute('''SELECT * FROM translation_proposals
                WHERE author_uuid = ? AND language = ? AND unit_id = ?
                AND status IN ('draft', 'pending', 'changes_requested')''', (viewer, language, unit_id)).fetchone()
            if row:
                return dict(row)
            count = self.connection.execute('''SELECT COUNT(*) FROM translation_proposals
                WHERE author_uuid = ? AND status IN ('draft', 'pending', 'changes_requested')''', (viewer,)).fetchone()[0]
            if count >= MAX_OPEN_PROPOSALS:
                raise TranslationError('translation-error-limit')
            now = int(self.clock())
            initial = previous['value'] if previous else self.current(language, unit_id)
            cursor = self.connection.execute('''INSERT INTO translation_proposals
                (author_uuid, author_name, language, unit_id, source_text, source_hash, base_hash, value, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                (viewer, account.username, language, unit_id, unit.original, unit.source_hash,
                 self.baseline(language, unit_id), initial, now, now))
            proposal_id = cursor.lastrowid
            current = initial
            if current and needs_forms(unit):
                try:
                    values = {form.id: form.value for form in forms(unit, current)}
                except TranslationError:
                    values = {}
                self.connection.execute('UPDATE translation_proposals SET forms_json = ? WHERE id = ?', (json.dumps(values, ensure_ascii=False), proposal_id))
            self._event(proposal_id, viewer, 'created')
            return self.get(viewer, proposal_id)

    def save(self, viewer, proposal_id, value, expected):
        value = clean_text(value, empty=True)
        with self.atomic():
            self.account(viewer, writing=True)
            row = self.get(viewer, proposal_id)
            self.revision(row, expected)
            if row['status'] not in {'draft', 'changes_requested'}:
                raise TranslationError('translation-error-readonly')
            self.reservations.claim(row)
            self.connection.execute('''UPDATE translation_proposals SET value = ?, revision = revision + 1,
                updated_at = ? WHERE id = ?''', (value, int(self.clock()), proposal_id))
            return self.get(viewer, proposal_id)

    def refresh_source(self, viewer, proposal_id, expected):
        """Keep the user's work while explicitly accepting a newer comparison base."""
        with self.atomic():
            self.account(viewer, writing=True)
            row = self.get(viewer, proposal_id)
            self.revision(row, expected)
            if row['status'] not in {'draft', 'changes_requested'}:
                raise TranslationError('translation-error-readonly')
            unit = self.catalog.get(row['unit_id'])
            self.reservations.claim(row)
            self.connection.execute('''UPDATE translation_proposals SET source_text = ?, source_hash = ?, base_hash = ?,
                revision = revision + 1, updated_at = ? WHERE id = ?''',
                (unit.original, unit.source_hash, self.baseline(row['language'], unit.id), int(self.clock()), proposal_id))
            self._event(proposal_id, viewer, 'source_refreshed', source=unit.original)
            return self.get(viewer, proposal_id)

    def save_form(self, viewer, proposal_id, form_id, value, expected):
        value = clean_text(value, empty=True)
        with self.atomic():
            self.account(viewer, writing=True)
            row = self.get(viewer, proposal_id)
            self.revision(row, expected)
            if row['status'] not in {'draft', 'changes_requested'}:
                raise TranslationError('translation-error-readonly')
            unit = self.catalog.get(row['unit_id'])
            if form_id not in {form.id for form in forms(unit)}:
                raise TranslationError('translation-error-unit')
            self.reservations.claim(row)
            values = json.loads(row['forms_json'])
            values[form_id] = value
            assembled = clean_text(assemble(unit, values), empty=True)
            self.connection.execute('''UPDATE translation_proposals SET value = ?, forms_json = ?,
                revision = revision + 1, updated_at = ? WHERE id = ?''',
                (assembled, json.dumps(values, ensure_ascii=False), int(self.clock()), proposal_id))
            return self.get(viewer, proposal_id)

    def _check_current(self, row):
        unit = self.catalog.get(row['unit_id'])
        if row['source_hash'] != unit.source_hash:
            raise TranslationError('translation-error-source-changed')
        if row['base_hash'] != self.baseline(row['language'], unit.id):
            raise TranslationError('translation-error-target-changed')
        return unit

    def submit(self, viewer, proposals):
        """Validate the complete batch before changing any submission state."""
        if not proposals or len(proposals) > MAX_BATCH or len({p[0] for p in proposals}) != len(proposals):
            raise TranslationError('translation-error-batch')
        with self.atomic():
            self.account(viewer, writing=True)
            rows = []
            for proposal_id, expected in proposals:
                row = self.get(viewer, proposal_id)
                self.revision(row, expected)
                if row['status'] not in {'draft', 'changes_requested'}:
                    raise TranslationError('translation-error-readonly')
                unit = self._check_current(row)
                self._validate_forms(unit, row)
                validate(unit, row['value'])
                if row['value'].strip() == self.current(row['language'], unit.id).strip():
                    raise TranslationError('translation-error-unchanged')
                self.reservations.claim(row)
                rows.append(row)
            for row in rows:
                self.connection.execute('''UPDATE translation_proposals SET status = 'pending',
                    revision = revision + 1, updated_at = ? WHERE id = ?''', (int(self.clock()), row['id']))
                self._event(row['id'], viewer, 'submitted', value=row['value'], source=row['source_text'], source_hash=row['source_hash'])
                self.connection.execute('UPDATE translation_reservations SET expires_at = 0 WHERE proposal_id = ?', (row['id'],))
        return len(rows)

    def _validate_forms(self, unit, row):
        if needs_forms(unit):
            values = json.loads(row['forms_json'])
            missing = [form.id for form in forms(unit) if form.id not in values or not values[form.id].strip()]
            if missing:
                raise TranslationError('translation-error-forms', count=len(missing))
            assemble(unit, values, validate_fields=True)

    def withdraw(self, viewer, proposal_id, expected):
        with self.atomic():
            self.account(viewer, writing=True)
            row = self.get(viewer, proposal_id)
            self.revision(row, expected)
            if row['status'] not in OPEN_STATES:
                raise TranslationError('translation-error-readonly')
            # A pending proposal becomes editable again; saved text is retained.
            self.connection.execute('''UPDATE translation_proposals SET status = 'draft', revision = revision + 1,
                updated_at = ? WHERE id = ?''', (int(self.clock()), proposal_id))
            self._event(proposal_id, viewer, 'withdrawn')
            self.connection.execute('UPDATE translation_reservations SET expires_at = ? WHERE proposal_id = ?',
                                    (int(self.clock()) + RESERVATION_SECONDS, proposal_id))
            return self.get(viewer, proposal_id)

    def discard(self, viewer, proposal_id, expected):
        with self.atomic():
            self.account(viewer, writing=True)
            row = self.get(viewer, proposal_id)
            self.revision(row, expected)
            if row['status'] not in {'draft', 'changes_requested'}:
                raise TranslationError('translation-error-readonly')
            self.connection.execute('''UPDATE translation_proposals SET status = 'withdrawn', revision = revision + 1,
                updated_at = ? WHERE id = ?''', (int(self.clock()), proposal_id))
            self._event(proposal_id, viewer, 'discarded')
            self.reservations.drop(row)

    def review(self, viewer, proposal_id, expected, decision, note=''):
        if decision not in {'approved', 'changes_requested', 'rejected'}:
            raise TranslationError('translation-error-decision')
        note = clean_text(note, limit=MAX_NOTE, empty=decision == 'approved').strip()
        with self.atomic():
            self.account(viewer, reviewer=True, writing=True)
            row = self.get(viewer, proposal_id, review=True)
            self.revision(row, expected)
            if row['status'] != 'pending':
                raise TranslationError('translation-error-readonly')
            if row['author_uuid'] == viewer:
                raise TranslationError('translation-error-self-review')
            if row['author_uuid'] is None:
                raise TranslationError('translation-error-account')
            if decision == 'approved':
                self.account(row['author_uuid'])
                unit = self._check_current(row)
                self._validate_forms(unit, row)
                validate(unit, row['value'])
                previous = self.connection.execute('SELECT * FROM translation_accepted WHERE language = ? AND unit_id = ?', (row['language'], unit.id)).fetchone()
                self.connection.execute('''INSERT INTO translation_accepted(language, unit_id, value, source_hash, proposal_id, revision)
                    VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(language, unit_id) DO UPDATE SET
                    value = excluded.value, source_hash = excluded.source_hash, proposal_id = excluded.proposal_id, revision = excluded.revision''',
                    (row['language'], unit.id, row['value'], unit.source_hash, proposal_id, (previous['revision'] if previous else 0) + 1))
                self._event(proposal_id, viewer, 'approved', previous=dict(previous) if previous else None,
                            value=row['value'], note=note)
                self.connection.execute("UPDATE translation_languages SET status = 'approved', revision = revision + 1 WHERE code = ?", (row['language'],))
            else:
                self._event(proposal_id, viewer, decision, note=note, value=row['value'])
            self.connection.execute('''UPDATE translation_proposals SET status = ?, reviewer_uuid = ?, note = ?, notice_pending = 1,
                revision = revision + 1, updated_at = ? WHERE id = ?''',
                (decision, viewer, note, int(self.clock()), proposal_id))
            if decision == 'changes_requested':
                self.connection.execute('UPDATE translation_reservations SET expires_at = ? WHERE proposal_id = ?',
                                        (int(self.clock()) + RESERVATION_SECONDS, proposal_id))
            else:
                self.reservations.drop(row)
        return dict(self.connection.execute('SELECT * FROM translation_proposals WHERE id = ?', (proposal_id,)).fetchone())

    def revert(self, viewer, proposal_id, expected, *, accepted_revision=None):
        """Revert only the still-current approval, retaining all audit records."""
        with self.atomic():
            self.account(viewer, reviewer=True, writing=True)
            row = self.get(viewer, proposal_id, review=True)
            if row['author_uuid'] == viewer:
                raise TranslationError('translation-error-self-review')
            self.revision(row, expected)
            accepted = self.connection.execute('SELECT * FROM translation_accepted WHERE language = ? AND unit_id = ?', (row['language'], row['unit_id'])).fetchone()
            if row['status'] != 'approved' or not accepted or accepted['proposal_id'] != proposal_id:
                raise TranslationError('translation-error-changed')
            if accepted_revision is not None and accepted['revision'] != accepted_revision:
                raise TranslationError('translation-error-changed')
            event = self.connection.execute("SELECT value_json FROM translation_events WHERE proposal_id = ? AND action = 'approved' ORDER BY id DESC LIMIT 1", (proposal_id,)).fetchone()
            previous = json.loads(event[0])['previous']
            unit = self.catalog.units.get(row['unit_id'])
            value = previous['value'] if previous and unit else self.installed_value(row['language'], row['unit_id']) if unit else ''
            source_hash = previous['source_hash'] if previous and unit else unit.source_hash if unit else ''
            self.connection.execute('''UPDATE translation_accepted SET value = ?, source_hash = ?, proposal_id = ?, revision = revision + 1
                WHERE language = ? AND unit_id = ?''',
                (value, source_hash, previous['proposal_id'] if previous and unit else None, row['language'], row['unit_id']))
            self.connection.execute("UPDATE translation_proposals SET status = 'reverted', notice_pending = 1, revision = revision + 1, updated_at = ? WHERE id = ?", (int(self.clock()), proposal_id))
            self._event(proposal_id, viewer, 'reverted')

    def notice_count(self, viewer):
        self.account(viewer)
        return self.connection.execute('SELECT COUNT(*) FROM translation_proposals WHERE author_uuid = ? AND notice_pending = 1', (viewer,)).fetchone()[0]

    def mark_seen(self, viewer, proposal_id):
        self.get(viewer, proposal_id)
        with self.atomic():
            self.connection.execute('UPDATE translation_proposals SET notice_pending = 0 WHERE id = ? AND author_uuid = ?', (proposal_id, viewer))

    def credits(self, viewer, language):
        self.language(viewer, language)
        return [dict(row) for row in self.connection.execute('''SELECT u.uuid, u.username, COUNT(*) AS contributions
            FROM translation_proposals p JOIN users u ON u.uuid = p.author_uuid
            WHERE p.language = ? AND p.status = 'approved' GROUP BY u.uuid, u.username ORDER BY u.username''', (language,))]

    def history(self, viewer, proposal_id, *, review=False):
        self.get(viewer, proposal_id, review=review)
        return [dict(row) for row in self.connection.execute('''SELECT e.action, e.value_json, e.created_at, u.username
            FROM translation_events e LEFT JOIN users u ON u.uuid = e.actor_uuid
            WHERE proposal_id = ? ORDER BY e.id DESC LIMIT 100''', (proposal_id,))]

    def preview(self, viewer, proposal_id, *, review=False, variant='other', form_id=None):
        row = self.get(viewer, proposal_id, review=review)
        unit = self.catalog.get(row['unit_id'])
        if form_id is not None:
            form = next((form for form in forms(unit) if form.id == form_id), None)
            if form is None:
                raise TranslationError('translation-error-unit')
            unit = form_unit(unit, form)
            row['value'] = json.loads(row['forms_json']).get(form_id, '')
        resources = {}
        if unit.kind == 'fluent':
            index = {u.key: u for u in self.catalog.units.values() if u.domain == unit.domain}
            pending = [unit]
            while pending:
                dependency = pending.pop()
                if dependency.key in resources:
                    continue
                value = row['value'] if dependency.id == unit.id else self.current(row['language'], dependency.id) or dependency.original
                resources[dependency.key] = value
                info = structure(parse(dependency, value))
                keys = {key for key, _ in info['messages']} | {'-' + key for key, _ in info['terms']}
                pending.extend(index[key] for key in keys if key in index and key not in resources)
        return example(unit, row['value'], row['language'], variant=variant, resources=resources)
