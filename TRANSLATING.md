# Translating PlayAural

PlayAural is an audio-first game platform, so translations are part of the
accessibility experience. A good translation should be clear when heard through
speech, not only when read visually.

In this fork, Spanish (`es`) is the required authoring language. The translation
editor uses Spanish originals and identifies entries that only have an English
original. English remains the runtime fallback for missing strings and manuals.

## Contribute Inside PlayAural

Open **Personal and options → Contribute → Translations**, choose a language,
then choose missing texts or corrections. Pick a section and a text. The editor
has a read-only original and an editable translation. It works while you remain
at a table, using the existing arrows, Enter and Back controls. Inside a text
box, the normal text-editing keys still apply. Plurals and gender variants are
presented as separate fields; keep the placeholders shown in each original.

Drafts save automatically after a brief typing pause and when you leave the
field. The private preview updates without changing anybody else's interface.
Use **Preview** to read the rendered example. **My proposals** resumes your work
after reconnecting, shows decisions and allows submitting the editable drafts
on the current page together. Submission validates the entire batch first.
Withdraw a pending proposal to edit it. Returned work includes a reason and can
be corrected and submitted again. A new proposal can reuse rejected work.

Starting an edit reserves that text in that language. Reading it does not.
Other contributors see who is working on it, without access to their draft.
Reservations expire after 24 hours without editing activity; pending submissions
remain reserved until a decision or withdrawal. Requested changes renew the
author's reservation. **Release reservation and keep draft** makes the text
available to others without deleting your work. Approval, rejection, discard and
account deletion release the corresponding reservation. Conflicting or expired
edits never overwrite another author's proposal.

You can propose a new language using its standard language code, name and native
name. Its first approved translation confirms the language. The first approved
contribution adds translator credit; it does not grant an administrative role.

Administrators and developers open **Administration → Review translations**.
The queue and reviewed history are grouped by language, then contributor, with
counts and pages. Decisions return to the next pending proposal, or to the
contributor list when that contributor has no pending work.
They compare the original, installed/approved translation and proposal, preview
the result, and approve, request changes or reject. Returning or rejecting work
requires a reason. Reviewers cannot approve their own proposals. Reviewed history
allows reverting the current approval; it cannot overwrite a later decision.
Authors receive a notice and can find decisions in **My proposals**.

Any approved user may propose translations. Administrators/developers grant or
revoke the **translator** role per account and language from **Administration →
Manage translators**. Search for an account, select a language and confirm.
Assigned translators open **Personal and options → Contribute → Review
translations** and may review only their assigned languages. They gain no
moderation or account-management privileges, cannot review their own work, and
lose review access immediately on revocation. First-contribution credit remains
separate from this appointed role. Role changes are recorded in the private audit.

Approval means **approved for the next update**. All clients ship together;
approval alone does not change live catalogs or install a new interface language.
Source or target changes require the author to update the comparison before
resubmitting. Conflicting edits retain the unsaved text for an explicit choice.

## Prepare Approved Work for Release

With the current server environment, export as an approved administrator or
developer account:

```powershell
uv run --project server --locked playaural-export-translations --database PlayAural.db --reviewer ReviewerName --output approved-translations.zip
```

The tool reads a consistent SQLite snapshot, exports only current approved
translations, validates formatting and dependencies, and writes a new ZIP with
checksums, locale metadata, credits and client registries. It never overwrites an
existing output, changes the database or edits the checkout. Extract into a
staging checkout, inspect the diff and manifest, run locale comparisons and all
affected client checks, then include the files in the coordinated release.
Copied fallback dependencies remain explicitly marked as untranslated.

## Where Strings Live

- Server and game strings: `server/locales/<locale>/*.ftl`
- Server translator metadata: `server/locales/<locale>/metadata.json`
- Server documentation and game manuals:
  `server/documentation/content/<locale>/**/*.md`
- Desktop client strings: `client/locales/<locale>/client.ftl`
- Web client strings: `web_client/locales/<locale>.js`
- Web language metadata: `web_client/locales/manifest.js`
- Mobile client strings: `mobile_client/locales/<locale>/client.json`
- Mobile language metadata: `mobile_client/locales/metadata.json`

When adding a new mobile language, update `mobile_client/locales/metadata.json`
and run:

```bash
cd mobile_client
cmd /c npm run generate:locales
```

For server languages, keep `languages.ftl` in place. It provides localized
language names for each viewer, while `metadata.json` stores translator credit
and whether the language is an official PlayAural default. A server metadata
file should look like this:

```json
{
  "code": "fr",
  "name": "French",
  "native_name": "Français",
  "translators": ["Translator name"],
  "official": false
}
```

## Fluent Files

Server and desktop strings use Mozilla Fluent (`.ftl`). Keep the key name the
same and translate only the value:

```ftl
game-started = The game has started.
score-line = { $player } has { $score } points.
```

Rules:

- Do not rename, remove, or translate data-bearing variables such as
  `{ $player }`, `{ $score }`, or a value passed to `NUMBER(...)`.
- A variable used only as the first argument to `GENDER_TERM(...)` is a
  grammatical selector rather than displayed data. You may omit that selector
  when your natural translation does not need gender, but do not rename it,
  replace it with a different selector, or remove any player/game information
  along with it.
- Keep every plural/select arm in the original.
- Keep message attributes such as `.label` when the original has them.
- Do not define the same Fluent key twice, even in different files. The server
  loads each locale as one namespace, so duplicate ids can silently shadow the
  string a player should hear.
- Translate the whole sentence naturally. Do not preserve English word order if
  it sounds unnatural in your language.
- Make speech output concise and understandable. Very long menu labels are hard
  to navigate with a screen reader.
- Reuse parameterized source strings when they already exist. For example, a
  single `{ $status }` option label is easier to maintain than separate "on"
  and "off" sentences.
- Keep identical short labels separate when their UI context is different, such
  as a login password field versus a registration password field. Context helps
  translators choose the right wording.

## Web and Mobile Files

Web and mobile strings use JavaScript or JSON objects with placeholders such as
`{player}`:

```json
"chat-private": "Private message from {player}: {message}"
```

Rules:

- Keep each placeholder name exactly the same.
- Do not add HTML. The web client treats server and translation text as plain
  text for safety.
- Keep button labels short and action-focused.

## Perspective Rules

Gameplay broadcasts must respect listener perspective:

- The acting player hears first person, for example "You drew a card."
- Other players and spectators hear third person, for example
  "Rory drew a card."

Do not merge these into one generic key when the actor can hear the message.
The English and translated files must keep the same key structure and
variables for both forms.

## Documentation Rules

Documentation is player-facing. Before translating or writing a manual, read a
finished manual in the same language and follow its structure and tone.

- Write for beginners.
- Explain what the player does, hears, chooses, and wins.
- Do not write changelog-style notes or development details.
- Keep the English and translated documents synchronized in structure and
  meaning.
- Use the same game names and UI terms that appear in the matching locale
  files.

If a translated document is missing, PlayAural falls back to the English
document so players never receive an empty manual.

## Validation

Run the server locale comparison tool before submitting a translation:

```bash
uv run --project server --extra dev python server/tools/compare_locales.py vi
```

Replace `vi` with your locale code, or omit the locale code to check every
non-English server locale. The tool reports:

- missing files and keys
- obsolete files and keys
- duplicate Fluent keys in one file or across files in the same locale
- missing data-bearing variables, extra variables, and renamed or unknown
  gender selectors; an unused `GENDER_TERM(...)` selector may be omitted
- attribute mismatches
- plural/select arm differences for review

Fix every blocking issue unless a maintainer confirms that the English source
string should change instead. Review plural/select differences carefully:
languages that do not inflect plurals may intentionally use one natural
sentence, but translations must still preserve every variable needed by the
English source.

## Contributor Credits

When a language is added or significantly maintained, update the supported
language metadata in the README and client manifests so translators receive
visible credit.
