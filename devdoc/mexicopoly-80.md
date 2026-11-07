# Mexican Monopoly: independent 80-space game

Historical implementation record. The current default and subsequent human
feedback corrections are described in [the compact-game audit](mexicopoly-playtest.md).
The 80-space definition is retained for existing saved matches only.

Select **Mexican Monopoly** (Spanish: **Monopolio México**) directly in Play.
Its type id is `mexicopoly`. The classic `monopoly` game and its earlier
40-space Mexico edition remain available, including their saved games.

## Integration boundary

The user approved a separate 80-space derivative on 2026-11-01. This is a
functional source integration, not a branch merge or production release.

| Responsibility | Owner |
| --- | --- |
| Identity, fixed board, options type | `server/games/mexicopoly/game.py` |
| Layout, economy, regions, decks, terminology | `server/games/mexicopoly/board.py` |
| Shared turn, purchase, rent, auction, mortgage, trade, jail, debt, building, bot, audio, and accessible menu logic | Existing `MonopolyGame` and its helpers |
| Independent content and card text | `server/locales/{en,vi,es}/mexicopoly.ftl` |
| Player instructions | `server/documentation/content/{en,vi,es}/games/mexicopoly.md` |
| Integration and extended-board regressions | `server/tests/test_mexicopoly.py` |

The board is validated but **not** added to the classic board registry. Its
fixed `board_id=mexico80` is serialized without option metadata, so the classic
board selector is absent and forged selection actions cannot change it.
Pre-start validation checks the polymorphic `game.board`; bonus help also uses
the actual game's board. Those are the only shared-engine adaptations.

Registered game identity already owns table reconstruction, results, ratings,
statistics, documentation lookup, and game preference overrides. The derivative
reuses those paths with its own id rather than creating parallel persistence.
Positions, ownership by UUID, deck order, pending decisions, and sequences use
the existing dataclass save contract and containing table/save lifecycle.
No new external service, client protocol, asset, or sound-pack version is needed.

## Layout and initial economy

There are exactly **80 spaces**:

- 48 cities, in 16 three-city regions;
- eight metro stations and four airports, in separate transit groups;
- two utilities: electricity and water;
- six Chance spaces and six Community Chest spaces;
- Go, Jail, Free Parking, and Go to Jail at indices 0, 20, 40, and 60;
- two tax spaces.

Regions progress from Baja California and Baja California Sur through Sonora,
Chihuahua, La Laguna/Coahuila, the northeast, central plateau, north Pacific,
west/Bajío, central and south-central Mexico, south Pacific, Chiapas, Gulf and
southeast, Yucatán Peninsula, and the Mexican Caribbean. The player manuals list
all 48 cities. These are broad themed groups, not official regional boundaries,
connected railway lines, or a literal road itinerary.

The 16 regions reuse eight familiar deed-value tiers, each applied to two
regions. Values are owned in the new content module, not read from a classic
board at runtime. They are not claims about real land prices or city wealth.

| Item | Extended game |
| --- | --- |
| Starting cash / Go salary | 3,000 / 400 Mexican pesos |
| Bank houses / hotels | 64 / 24, finite |
| Jail fine / income tax / luxury tax | 50 / 200 / 100 |
| Metro and airport purchase / mortgage | 200 / 100 |
| Rent for 1 through 8 metros | 25, 50, 100, 200, 250, 300, 350, 400 |
| Rent for 1 through 4 airports | 25, 50, 100, 200 |
| Utility purchase / mortgage / rent | 150 / 75 / fresh dice total times 4 or 10 |
| Optional rules | Five inherited switches, all Off |

Starting liquidity, Go income, and building supply are doubled to account for
the longer circuit and more development groups. Existing card amounts, fines,
interest, building rules, and two-dice movement remain. This is a playable
initial economy, **not a certification of classic-equivalent probabilities,
duration, or competitive balance**; human testing should evaluate those.

Each deck still has 16 cards. Their text keys are private to `mexicopoly`, while
their current effects come from the shared contemporary deck builders. Named
destinations are valid spaces on this board. A nearest-transit card can reach
either a metro station or an airport, charging the destination group's rent.
Supplementary cards, protection-money events, and city-specific random effects
are **not implemented** in this phase.

When those features are requested, add their content and effects in this game,
with declared serialized state, deterministic tests, and personal/public
announcements. Do not modify the shared classic deck or add speculative event
state now. Shared rules can be extracted further only when a real divergent
behavior calls for it; copying the whole Monopoly implementation is unnecessary.

## Geographic references

Names checked against official sources on 2026-11-01:

- [Metrorrey: Cuauhtémoc and Zaragoza](https://www.metrorrey.mx/).
- [SITEUR: Juárez and Ávila Camacho](https://siteur.gob.mx/index.php/forma-de-pago/preguntas-frecuentes). Ávila Camacho is labeled as Guadalajara metropolitan area rather than asserting its municipal boundary.
- [CDMX Metro station inventory](https://www.metro.cdmx.gob.mx/tramites-y-servicios/accesibilidad-en-estaciones) and [Zócalo/Tenochtitlan](https://www.metro.cdmx.gob.mx/la-red/linea-2/zocalo).
- [GAP: Tijuana airport](https://www.aeropuertosgap.com.mx/es/172-inversionistas/preguntas-frecuentes/303-concecion-aereopuertos.html).
- [OMA: Monterrey airport in Apodaca](https://www.oma.aero/globales/contacto.html).
- [AICM: Benito Juárez airport](https://www.aicm.com.mx/contact).
- [ASUR: Cancún airport](https://www.asur.com.mx/cancun-formulario-de-contacto).
- [INEGI: state divisions and capitals](https://cuentame.inegi.org.mx/imprime_tu_mapa/doc/nal-division_estatal_con_capitales-byn.pdf).

AIFA is excluded. Temporary station closures and real transport fares are not
game rules or promises of current transport service.

## Validation and rollback

Run focused tests before the full server suite and locale comparison:

```powershell
uv run --project server --extra dev python -m pytest server/tests/test_mexicopoly.py -q
uv run --project server --extra dev python -m pytest server/tests -q -n 4
uv run --project server --extra dev python server/tools/compare_locales.py vi es
```

On this Windows machine, prepend the installed Git Bash directories to the
test process's PATH for `sc.sh` tests; the WindowsApps Bash launcher points to
unconfigured WSL. Do not change global PATH or application code for that issue.
Vietnamese additions are provisional pending native review. Unit/protocol tests
do not certify real screen-reader, touch, audio, or human multiplayer behavior.

Rollback removes only the `mexicopoly` module, its registry entry, new locale
files/manuals/tests, catalog-count changes, and the two shared polymorphic
adaptations after checking for other dependents. Keep the previous 40-space
Mexico edition and its unrelated changes. Do not unregister `mexicopoly` while
its saved games/results still need retention: startup cleanup derives valid
game identities from the live registry.

### Verification record: 2026-11-01

- Focused game/classic/catalog/switch regressions: **320 passed**.
- Additional real WebSocket test: **1 passed**. It used a disposable in-memory
  database, authenticated a Web client, verified the disabled voice capability,
  navigated the Spanish catalog, created a Mexican Monopoly table, added a bot,
  started the 80-space game, and logged out through the normal protocol.
- Final complete server suite: **4,851 passed, 6 skipped** in 180.14 seconds,
  with `-n 4` and Git Bash on the test process's PATH.
- Both deterministic four-bot simulations finished with one UUID-owned winner.
  Save/result tests preserve the derivative options type, private board, deck
  order, pending sequence, property state, and separate result identity.
- EN, VI, and ES each contain **132 unique parsed keys** in the new catalog.
  Fluent comparison for VI/ES returned 0 with only existing select/plural review
  warnings; no blocking missing, obsolete, duplicate, metadata, variable, or
  attribute issues. New-file whitespace and Git diff checks passed.
- The existing local server was stopped cooperatively and restarted against
  the same database. Its startup reported 52 games, 80 Mexican spaces, and
  `voice_enabled=false`; its existing one account was retained. HTTP 200 and
  WebSocket handshake/pong were verified after restart. No existing user
  password was read and no account was added to that instance by the agent.
- No client application build, commit, branch merge, push, tag, deployment,
  production publication, or sound/version bump was performed. Human balance,
  screen-reader, touch, and listening verification remain separate tests.
