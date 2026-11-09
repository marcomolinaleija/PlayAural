game-name-tomatodo = Toma Todo (Pirinola)

tomatodo-set-coin-unit = Coin unit: { $unit } coins
tomatodo-select-coin-unit = Select coin value per unit
tomatodo-option-changed-coin-unit = Coin unit set to { $unit } coins.
tomatodo-desc-coin-unit = Sets how many virtual wallet coins each unit equals (Put 1, Take 1, etc.).
tomatodo-unit-1 = 1 coin
tomatodo-unit-5 = 5 coins
tomatodo-unit-10 = 10 coins
tomatodo-unit-25 = 25 coins
tomatodo-unit-50 = 50 coins

tomatodo-set-ante = Initial ante: { $ante } { $ante ->
    [one] unit
   *[other] units
}
tomatodo-select-ante = Select initial ante per player
tomatodo-option-changed-ante = Initial ante set to { $ante } { $ante ->
    [one] unit
   *[other] units
}.
tomatodo-desc-ante = Units contributed to the pot by each player at the start of the game.
tomatodo-ante-1 = 1 unit
tomatodo-ante-2 = 2 units

tomatodo-set-rounds = Round limit: { $rounds }
tomatodo-select-rounds = Select number of rounds or continuous play
tomatodo-option-changed-rounds = Round limit set to { $rounds }.
tomatodo-desc-rounds = End the game after this many rounds or play until only one player has coins.
tomatodo-rounds-continuous = Continuous (last player standing)
tomatodo-rounds-10 = 10 rounds
tomatodo-rounds-15 = 15 rounds
tomatodo-rounds-20 = 20 rounds

tomatodo-set-speed = Spin speed: { $speed }
tomatodo-select-speed = Select spin speed
tomatodo-option-changed-speed = Spin speed set to { $speed }.
tomatodo-desc-speed = Choose between fast spin (3.5 seconds) or traditional full spin (11 seconds).
tomatodo-speed-fast = Fast (3.5 seconds)
tomatodo-speed-full = Full (11 seconds)

tomatodo-action-spin = Spin the top
tomatodo-action-check-pot = Check pot
tomatodo-action-check-balances = Check player coins
tomatodo-action-check-last-spin = Check last spin

tomatodo-pot-started = Toma Todo begins! Each player antes { $ante } coins. Initial pot is { $pot } coins.
tomatodo-result-pon-1 = { $player } spun the top and got: Put 1. Puts { $coins } coins into the pot. Pot total: { $pot }.
tomatodo-result-pon-2 = { $player } spun the top and got: Put 2. Puts { $coins } coins into the pot. Pot total: { $pot }.
tomatodo-result-toma-1 = { $player } spun the top and got: Take 1. Takes { $coins } coins from the pot. Remaining pot: { $pot }.
tomatodo-result-toma-2 = { $player } spun the top and got: Take 2. Takes { $coins } coins from the pot. Remaining pot: { $pot }.
tomatodo-result-todos-ponen = Everyone puts! Each player adds { $unit } coins to the pot. Pot total: { $pot }.
tomatodo-result-toma-todo = TAKE ALL! { $player } takes the entire pot of { $coins } coins.
tomatodo-pot-empty = The pot is empty.
tomatodo-pot-replenished = The pot was emptied. All active players put { $unit } coins. New pot: { $pot }.
tomatodo-player-bankrupt = { $player } is out of coins and went bankrupt!
tomatodo-game-won-last-standing = { $winner } is the last player standing with { $coins } coins and wins the game!
tomatodo-game-won-rounds = Round limit reached! { $winner } wins with { $coins } coins.
tomatodo-game-tie-rounds = Round limit reached! Tie between { $winners } with { $coins } coins each.

tomatodo-check-pot-info = Current pot has { $pot } coins ({ $unit } coins per unit).
tomatodo-player-balance = { $player }: { $coins } coins
tomatodo-player-balance-bankrupt = { $player }: bankrupt (0 coins)
tomatodo-no-last-spin = No spin has been made yet.
tomatodo-last-spin-info = Last spin by { $player }: { $face }.

tomatodo-face-pon_1 = Put 1
tomatodo-face-pon_2 = Put 2
tomatodo-face-toma_1 = Take 1
tomatodo-face-toma_2 = Take 2
tomatodo-face-todos_ponen = Everyone puts
tomatodo-face-toma_todo = Take all

tomatodo-error-insufficient-coins = { $player } does not have enough coins in wallet ({ $coins } available, at least { $required } required).
tomatodo-error-player-bankrupt = You are bankrupt and cannot spin the top.
tomatodo-error-bots-not-supported = Toma Todo is played with wallet coins and does not support bots. All players must be humans.
