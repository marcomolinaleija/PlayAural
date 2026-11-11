# Mexican Monopoly: compact board and turn-flow corrections

The current default is **50 spaces, 24 cities, and eight familiar colors**.
The user allowed 50 or 60; a 60-space prototype with four cities per group
made completion harder and a deterministic simulation reached 1,213 turns
without construction. The 50-space layout restores uniform three-city groups
without expanding bot trade logic. Seed 812 completed in 214 turns in a
zero-presentation-delay diagnostic simulation.

## Current behavior

| Feedback | Implementation |
| --- | --- |
| Automatic rent, default On | `automatic_rent` is a declared BoolOption. The existing debt/payment engine transfers rent exactly once. Insolvency stays with the tenant; utility rent still waits for its fresh roll. Off restores owner collection/waiver. |
| Optional time limit | `turn_timer` choices are `0`, `20`, `30`, `40`, `60`, `120`, with Unlimited as the default. The MenuOption explicitly binds `$value` through `value_key="value"`. |
| Roll closes the turn | `_finish_landing()` advances only after the full landing has resolved and no extra roll is pending. Purchases, auctions, utility rolls, cards, and debts are not abandoned. Doubles keep the required next roll. |
| Management before rolling | Existing management/trade actions stay available before rolling. Bots now do these tasks before their final roll; otherwise automatic turn completion would remove their construction opportunity. Optional off-turn interruptions are restricted, but required auction/debt responders may still manage assets. |
| Mexican names | Electricity is CFE, water is CONAGUA, and tax spaces identify SAT. These are thematic game names, not claims that the institutions are privately ownable utilities or descriptions of real tax calculations. |
| Less speech | Private message-key mapping removes the non-double disclaimer and shortens jail and visiting announcements, for actor and observers. Roll actions omit verbose help descriptions and use the shared Roll dice label in jail. The classic game's catalogs and narration remain unchanged. |
| 5 houses & up to 2 hotels | Complete color groups build up to five houses per city before converting to a hotel (`houses_per_hotel=5`). Major metropolitan and tourist hubs (`tijuana`, `monterrey`, `guadalajara`, `mexico_city`, `cancun`) allow a second hotel (`max_hotels=2`) once every city in the group has its first hotel. |
| Rebalanced MXN economy | Cities scale from 160 to 960 MXN (building costs 120 to 500 MXN), metro stations cost 400 MXN (rents 60/120/240/480), airports cost 500 MXN (rents 80/160/320/640), utilities cost 360 MXN (10x/24x dice total), and SAT taxes charge 450/250 MXN to match 3,000 starting cash and 400 Go salary. |
| Optional auctions & 1-2-3 gavel | `auctions_enabled` (default `True`) lets tables skip auctions when a purchase is declined. When enabled, `auction_timer` (`3`, `5`, `8`, `10`, `15` seconds, default `5`) runs a live "going once, going twice, going three times" gavel where any active bidder can bid or leave, new bids reset the count, and the property goes unsold if nobody bids. |
| Escalating jail fine | `jail_counts` tracks each player's imprisonments in the current match and prices the fine at `100 * 2**(count - 1)` pesos (100 first time, 200 second, 400 third, doubling on each subsequent entry). |
| Mexican folklore cards & SAT strict jail | `mexico50` expands `Suerte` and `Caja de Comunidad` to 26 cards each with Mexican folklore events (SAT tax audit, SAT refund, false harassment accusations, El Torito breathalyzer, CFE meter wiretap, megabache, office tanda, CETES/Buen Fin, quinceañera sponsorship, Rosca de Reyes/Candelaria tamales, remittances, predial, Lotería Nacional, and Cancún trip). `chance_sat_audit` charges 20% of cash (minimum 300 MXN) and sends the player to jail for 2 mandatory turns (`sat_jail_turns`) with bail and jail-free cards disabled and rent collection frozen while in SAT custody. |
| Cobro de piso & Operativo de la Marina | Triggered by cards (`chance_cobro_de_piso`, `community_cobro_de_piso`) or random turn-start events (`_maybe_trigger_random_cobro_event`), `cobro_de_piso_active` deducts protection-racket cuts from all rents collected by property owners: 5% on normal properties (undeveloped cities, metros, airports, utilities), 10% with 1-2 houses, 15% with 3-5 houses, 30% with 1 hotel, and 50% at maximum hotels (2 hotels on major hubs or all 3 properties of a color group at max hotels). Cleared by Marina raid cards (`chance_marina_operativo`, `community_marina_operativo`) or random Marina operations. |

Named references: [CFE](https://ventanilla.energia.gob.mx/directorio),
[CONAGUA](https://www.gob.mx/conagua/es/articulos/programa-nacional-hidrico-pnh-2026-2030?idiom=es),
and [SAT](https://www.sat.gob.mx/).

## Layout and saved-game safety

`compact_board.py` defines `mexico50`. Its spaces are 24 cities, four metros,
four airports, two utilities, five Chance spaces, five Community Chest spaces,
two taxes, and four special corners. Each color owns three cities. All four
metros and all four airports retain their separate 25/50/100/200 rent schedules.
Starting cash, Go salary, card amounts, and building supplies are unchanged
from the existing Mexican game; this correction does not add further financial
or event rules.

`board.py` retains the exact immutable `mexico80` layout. The game resolves
the board from its serialized id; loading an 80-space save must never reinterpret
position 79, remove a deed, change a card destination, or remap ownership into
the 50-space layout. New fields have defaults for older saves. New tables use
50 spaces; restarting an old table preserves its cloned options, so create a
new table when switching from an old 80-space match to the compact game.

The earlier [80-space audit](mexicopoly-80.md) is historical, not the current
default configuration. The game identity remains `mexicopoly`, with statistics
separate from classic Monopoly. The classic 40-space Mexico edition is intact.

## Deadline policy

The primary countdown covers the turn owner's active decision time, including
management and trade drafting; opening those interfaces does not reset it.
Locked audio/gameplay sequences pause it. Required foreign players have a
separate response countdown, so the turn owner's time is not spent waiting on
someone else. Both countdowns and the active response context are serialized
as ticks using `PokerTurnTimer` and `TurnTimerMixin`, never process timestamps.

When time expires:

- roll or make the required jail roll automatically;
- decline an undecided purchase into the normal auction, or pass a bid;
- collect an unanswered manual rent request;
- close property management or cancel a trade draft;
- reject, never accept, an unanswered trade;
- keep received property mortgaged and settle its required interest;
- raise only the cash needed to pay a debt, or declare bankruptcy only when
  the shared rules establish insolvency.

An expired whole-turn budget stays exhausted across required transitions, so
changing phase cannot buy the same player another full turn allowance. Pending
inputs are discarded through the framework cleanup path before fallback, which
removes editboxes, selection locks, and stale action intent. Late input packets
cannot submit a cancelled trade. Public timer panels update through sealed
menu refreshes without direct menu painting.

## Verification and rollback boundary

`server/tests/test_mexicopoly_playtest.py` covers defaults, all deadlines, fresh
utility rolls, manual collection/waiver, insolvency, pending auctions, doubles,
concise speech, timer pauses, management without a reset, other players' clocks,
safe timeout liquidation, trade cancellation/rejection, and original saves.
`test_mexicopoly.py` now targets the compact default while preserving classic
compatibility and the real WebSocket create/add-bot/start flow without voice.

The compact board, derivative overrides, new options/message keys, manual and
test changes form one rollback boundary. Keep `board.py` and the legacy keys
needed by existing saves. Reverting never requires modifying saved databases,
account preferences, production services, or the classic game engine.

Vietnamese remains provisional pending native review. Automated checks do not
replace human screen-reader, audio, touch, and balance testing.

### Validation record (2026-11-01)

- Full server suite: 4,881 passed, 6 skipped; correction-specific suite: 30 passed.
- EN/VI/ES Fluent comparison passed, with existing plural/select review warnings.
- `git diff --check` passed; no build, commit, merge, or publication performed.
- Local server restarted cooperatively with the same separate database: 52 games,
  50 default spaces, automatic rent enabled, unlimited turns, and voice disabled.
  HTTP returned 200; WebSocket handshake/pong and SQLite quick check passed.
  The existing account was retained without reading credentials.
- Create a new table to use the compact board. Restarting a legacy table keeps
  its saved board id and options; existing 80-space saves are not remapped.
