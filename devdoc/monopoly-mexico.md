# Mexico Monopoly edition: integration audit

This records the initial 40-space edition. The subsequently approved,
independent 80-space game is documented in [Mexican Monopoly](mexicopoly-80.md).
The initial edition remains for compatibility with its existing saves.

Mexico is a selectable board in the existing Monopoly game, not a second
rules engine. Select **Monopoly > Board > Mexico** in the waiting lobby.
This audit covers the integration needed for this edition; it is not a
platform-wide security, deployment, or screen-reader certification.

## Integration findings

| Area | Owner and decision |
| --- | --- |
| Registration | `server/games/monopoly/game.py` imports board modules before constructing `MonopolyOptions`. The existing board selector discovers their immutable definitions. No new game id or migration is needed. |
| Rules | `standard_layout.py` and `standard_cards.py` supply the existing 40-space layout, deed economy, and decks. `rules.py` and `MonopolyGame` remain the only gameplay authority. |
| Content | `server/games/monopoly/mexico.py` owns stable space ids, region labels, terminology, currency, and card destinations. |
| Accessibility | Existing menu actions, information panels, actor/observer announcements, brief announcements, and unified audio apply. No new narration paths, keybinds, media, or client-specific packets were introduced. |
| Persistence | Existing `options.board_id`, UUID-owned property states, positions, deck order, and sequence state provide the save contract. The immutable board definition is not copied into each save. |
| Clients | Desktop, web, and mobile consume the same server menus. No application or sound-pack version bump is needed for this source-only feature. |
| Localization | All new content keys exist in EN, VI, and ES. Existing parameterized card text receives Mexican destinations and themed property kinds. Vietnamese additions require native review. |

## Board and geography

Keep 40 spaces to preserve classic movement probabilities and the existing
economy. There are 22 buildable cities, four metro stations, two airports,
and the usual 12 non-ownable spaces. Prices are game values, not a ranking
of cities' actual wealth or land prices.

| Color | Broad region | Cities in board order |
| --- | --- | --- |
| Brown | Baja California | Tijuana, Mexicali |
| Light blue | Northwest and northern interior | Hermosillo, Chihuahua, Ciudad Juárez |
| Pink | Northeast | Saltillo, Monterrey, Tampico |
| Orange | Central plateau | Aguascalientes, Zacatecas, San Luis Potosí |
| Red | West and Bajío | Guadalajara, León, Morelia |
| Yellow | Central Mexico | Querétaro, Toluca, Ciudad de México |
| Green | East and south | Puebla, Veracruz, Oaxaca de Juárez |
| Dark blue | Yucatán Peninsula | Mérida, Cancún |

These are broad neighboring regions, not official regional boundaries or a
continuous transport route. The four station squares do not imply a physical
connection between metro systems.

- Cuauhtémoc belongs to Metrorrey in Monterrey.
- Juárez belongs to Guadalajara's SITEUR light rail, not to the CDMX Metro.
- Tacubaya and Pantitlán belong to the CDMX Metro.
- Monterrey International Airport is identified as being in Apodaca, Nuevo León.
- Benito Juárez International Airport is the Mexico City airport. AIFA is not included.

The stations occupy the four railroad positions and keep rents of 25, 50,
100, or 200. The airports occupy the two utility positions and keep the
4-times/10-times fresh-dice rent calculation, 150 purchase price, and 75
mortgage value. No airport flight or metro travel shortcut is introduced.

Starting cash remains 1,500, Go salary 200, jail fine 50, taxes 200 and 100,
and the Bank has 32 houses and 12 hotels. All optional variations stay off
by default. Only the destinations of movement cards are rebound to Mexican
spaces; amounts, effects, repairs, penalties, and card narration are unchanged.

## Geographic references

Official sources checked for this edition on 2026-11-01:

- [INEGI: state divisions and capitals](https://cuentame.inegi.org.mx/imprime_tu_mapa/doc/nal-division_estatal_con_capitales-byn.pdf).
- [CDMX Metro: station inventory](https://www.metro.cdmx.gob.mx/tramites-y-servicios/accesibilidad-en-estaciones) and [Pantitlán](https://www.metro.cdmx.gob.mx/la-red/linea-1/pantitlan).
- [Metrorrey: official site and Cuauhtémoc customer-service location](https://www.metrorrey.mx/).
- [SITEUR: Juárez transfer station](https://www.siteur.gob.mx/index.php?Itemid=106&catid=15%3Aservicios&id=3%3Atarjeta-electr%C3%B3nica&option=com_content&view=article).
- [OMA: Monterrey Airport address in Apodaca](https://www.oma.aero/globales/contacto.html).
- [AICM: Benito Juárez airport address](https://www.aicm.com.mx/contact).

## Verification and later work

`server/tests/test_monopoly_mexico.py` checks exact regional membership,
classic economic parity, movement-card destinations, station and airport
rents, construction constraints, multilingual selection for each client type,
and serialization. The existing Monopoly suite also exercises every registered
board, including bot completion, content validation, and localization.

Run from the repository root:

```powershell
uv run --project server --extra dev python -m pytest server/tests/test_monopoly.py server/tests/test_monopoly_mexico.py -q
uv run --project server --extra dev python server/tools/compare_locales.py vi es
```

Human keyboard, touch, screen-reader, audio, and multiplayer playtesting remain
separate checks. Later Mexican cards, penalties, and other custom narration
belong in this board's data and locale keys; do not change shared decks or
defaults merely to customize this edition. Expanding the board beyond 40 spaces
would need a separately agreed layout and balance review.

Rollback consists of removing `mexico.py`, its import, its dedicated tests and
locale/manual additions, and the corresponding expected-board-list entries.
Do not remove this board while saved Mexico games still need to be loaded.

### Validation record: 2026-11-01

- Full server suite: **4,823 passed, 6 skipped** with `-n 4` (105.24 seconds).
  The initial run had nine administration-script failures because Windows
  resolved `bash` to the unconfigured WSL launcher. Prepending the installed
  Git Bash directories to the test process's PATH made all ten tests in that
  module pass, followed by the successful full-suite rerun. No global PATH or
  application source change was needed for this environment issue.
- Mexico-specific tests: **16 passed**, including a final focused rerun after
  aligning the desktop test's client type with the actual `python` protocol
  id and checking all movement-card narration in EN, VI, and ES.
- Fluent comparison for VI and ES: exit 0; only existing select/plural review
  warnings, with no blocking missing, obsolete, duplicate, metadata, variable,
  or attribute issues.
- Diff and new-file whitespace checks passed.
- Local server started on loopback with an isolated SQLite database and an
  explicit disabled voice capability. HTTP 200, WebSocket handshake/ping, and
  the Spanish web login/registration UI were checked. No user account was
  created and no authenticated browser gameplay was claimed. The checkout has
  no optional `packet_schema.json`; the web client's existing permissive
  fallback runs after three 404 probes. That pre-existing deployment detail
  was not changed as part of this board edition.
- `uv` prepared `server/.venv` and installed the editable server package for
  testing. No distributable desktop/mobile application build, commit, push,
  branch integration, or production publication was performed.
