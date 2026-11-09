game-name-loteria = Mexican Loteria

loteria-pattern-chorro = Any line
loteria-pattern-cuatro-esquinas = Four corners
loteria-pattern-centro = Center square
loteria-pattern-cuadro-chico = Small square (any 2x2)
loteria-pattern-lleno = Full board

loteria-call-interval-5 = 5 seconds
loteria-call-interval-10 = 10 seconds
loteria-call-interval-15 = 15 seconds
loteria-call-interval-20 = 20 seconds
loteria-call-interval-30 = 30 seconds

loteria-verses-with-verses = With traditional verses
loteria-verses-names-only = Card names only

loteria-set-pattern = Winning pattern: { $pattern }
loteria-select-pattern = Select the winning pattern:
loteria-option-changed-pattern = The winning pattern is now { $pattern }.
loteria-desc-pattern = The pattern that a board must complete to win: any line (row, column, or diagonal), four corners, center square (2x2 in the center), small square (any 2x2), or full board.

loteria-set-call-interval = Call every { $seconds }
loteria-select-call-interval = Select the call interval:
loteria-option-changed-interval = A card will now be called every { $seconds }.
loteria-desc-call-interval = How long the caller waits between drawn cards (default 15, range 5 to 30 seconds).

loteria-set-verses = Calling mode: { $mode }
loteria-select-verses = Select the calling mode:
loteria-option-changed-verses = Calling mode is now { $mode }.
loteria-desc-verses = Whether traditional caller verses and rhymes are included when calling each card or only the card number and name.

loteria-set-bet = Bet per player: { $coins } coins
loteria-select-bet = Select the amount of coins to bet:
loteria-option-changed-bet = The bet per player was changed to { $coins } coins.
loteria-desc-bet = Amount of virtual coins each player puts into the pot.
loteria-bet-0 = Friendly (no bet)
loteria-bet-10 = 10 coins
loteria-bet-25 = 25 coins
loteria-bet-50 = 50 coins
loteria-bet-100 = 100 coins

loteria-error-insufficient-coins = { $player } does not have enough coins to bet ({ $coins } of { $required } needed).
loteria-pot-started = Game started with a bet of { $bet } coins per player. Pot: { $pot } coins.
loteria-winner-won-pot = { $player } wins the pot of { $pot } coins!
loteria-pot-refunded = The deck ran out without a winner. Bets of { $bet } coins were refunded to each player.
loteria-action-check-pot = Check the coin pot
loteria-check-pot-info = The current pot is { $pot } coins (bet of { $bet } coins per player).

loteria-cell-marked = { $card }, marked with bean.
loteria-cell-unmarked = { $card }, unmarked.
loteria-you-already-won = You already won this round of Loteria.

loteria-you-mark = Placed bean on { $card }.
loteria-you-unmark = Removed bean from { $card }.

loteria-claim-loteria = Call Loteria!
loteria-repeat-call = Repeat the last card
loteria-check-called = Check called cards
loteria-no-calls-yet = No cards have been called yet.
loteria-claim-in-progress = Another board is being checked right now. Try again in a moment.
loteria-claim-in-progress-you = Your board is already being checked.
loteria-claim-wait-for-call = Wait for the card being drawn to be announced, then try again.
loteria-claim-unchanged = Your board has not changed since it was rejected. Place or remove a bean or wait for the next card before claiming again.
loteria-checking-claim-you = You call Loteria! Checking your board...
loteria-checking-claim = { $player } calls Loteria! Checking their board...
loteria-whose-turn-checking = Checking { $player }'s board...
loteria-whose-turn-checking-you = Your board is being checked...
loteria-whose-turn-checking-card = A Loteria board is being checked...
loteria-whose-turn-drawing = Shuffling the next card...
loteria-whose-turn-waiting = { $seconds ->
    [one] Next card in { $seconds } second.
   *[other] Next card in { $seconds } seconds.
}
loteria-claim-incorrect-you = Incorrect board. Not a valid win!
loteria-claim-incorrect = { $player }'s board is incorrect. Not a valid win!
loteria-claim-incomplete-you = You do not have the complete pattern yet.
loteria-claim-incomplete = { $player } does not have the complete pattern yet.
loteria-marked-card-not-called = You marked { $card }, but it has not been called yet.

loteria-last-call = Last card called: { $number }: { $card }.
loteria-last-call-with-rhyme = Last card called: { $number }: { $card } — { $rhyme }

loteria-status-called-count = { $count } of { $total } cards called.
loteria-status-called-entry = { $number }: { $card }

loteria-game-start = Mexican Loteria begins! Pattern: { $pattern }. A new card will be called every { $interval } seconds. Mark your board and press B to call Loteria when complete!
loteria-game-start-touch = Mexican Loteria begins! Pattern: { $pattern }. A new card will be called every { $interval } seconds. Mark your board and select Call Loteria when complete!
loteria-game-start-spectator = Mexican Loteria begins! Pattern: { $pattern }. A new card will be called every { $interval } seconds.

loteria-card-called = { $number }: { $card }!
loteria-card-called-with-rhyme = { $number }: { $card }! { $rhyme }

loteria-claim-correct-you = Valid win! Your board is correct. You win with { $cards }!
loteria-claim-correct = Valid win! { $player }'s board is correct. Wins with { $cards }!
loteria-claim-correct-no-cards-you = Valid win! Your board is correct. You win Loteria!
loteria-claim-correct-no-cards = Valid win! { $player }'s board is correct. Wins Loteria!
loteria-deck-exhausted = All 54 cards have been called. The round ends here.

loteria-error-invalid-interval = "{ $value }" is not a valid call interval.
loteria-error-invalid-pattern = { $value } is not a recognized winning pattern.
loteria-error-invalid-verses = { $value } is not a recognized calling mode.

loteria-end-calls = { $count ->
    [one] { $count } card was called this round.
   *[other] { $count } cards were called this round.
}
loteria-end-winner-line = Winner: { $player }
loteria-end-no-winner = No valid Loteria claim was made this round.

# 54 traditional cards
loteria-card-1 = The Rooster
loteria-rhyme-1 = He who sang for Saint Peter will not sing again.
loteria-card-2 = The Devil
loteria-rhyme-2 = Behave yourself buddy, or the red one will take you away.
loteria-card-3 = The Lady
loteria-rhyme-3 = Polishing her step down the Royal Street.
loteria-card-4 = The Dandy
loteria-rhyme-4 = Don Ferruco strolling in the park with his finest cane.
loteria-card-5 = The Umbrella
loteria-rhyme-5 = For the bright sun and for the heavy rain.
loteria-card-6 = The Mermaid
loteria-rhyme-6 = Do not lose your way with the siren's sweet song.
loteria-card-7 = The Ladder
loteria-rhyme-7 = Climb me step by step, do not slip and fall.
loteria-card-8 = The Bottle
loteria-rhyme-8 = The familiar tool of the tavern keeper.
loteria-card-9 = The Barrel
loteria-rhyme-9 = He drank so much that he ended up round like a barrel.
loteria-card-10 = The Tree
loteria-rhyme-10 = Whoever rests under a good tree enjoys great shade.
loteria-card-11 = The Melon
loteria-rhyme-11 = Either you give it to me or you take it away.
loteria-card-12 = The Brave Man
loteria-rhyme-12 = Why run away cowardly, carrying such a sharp blade.
loteria-card-13 = The Bonnet
loteria-rhyme-13 = Put the little bonnet on the baby so he stays warm.
loteria-card-14 = Death
loteria-rhyme-14 = Death comes dancing merrily along.
loteria-card-15 = The Pear
loteria-rhyme-15 = He who waits grows weary of waiting.
loteria-card-16 = The Flag
loteria-rhyme-16 = Green, white, and red, the brave soldier's flag.
loteria-card-17 = The Mandolin
loteria-rhyme-17 = Strumming the mandolin at the friendly inn.
loteria-card-18 = The Cello
loteria-rhyme-18 = Growing so tall, it had to be a cello.
loteria-card-19 = The Heron
loteria-rhyme-19 = Across the gentle river stands the lovely heron.
loteria-card-20 = The Bird
loteria-rhyme-20 = Singing merrily from branch to branch.
loteria-card-21 = The Hand
loteria-rhyme-21 = The outstretched hand of fate.
loteria-card-22 = The Boot
loteria-rhyme-22 = One leather boot is just like its mate.
loteria-card-23 = The Moon
loteria-rhyme-23 = The romantic lantern of lovers.
loteria-card-24 = The Parrot
loteria-rhyme-24 = Little parrot asking for a treat.
loteria-card-25 = The Drunkard
loteria-rhyme-25 = Oh what a stubborn drunk, nobody can put up with him!
loteria-card-26 = The Little Black Man
loteria-rhyme-26 = The sweet boy who ate the sugar.
loteria-card-27 = The Heart
loteria-rhyme-27 = Do not miss me dear heart, for I will return soon.
loteria-card-28 = The Watermelon
loteria-rhyme-28 = Cool and sweet slice on a sunny day.
loteria-card-29 = The Drum
loteria-rhyme-29 = Do not wrinkle old leather, you are meant for a drum.
loteria-card-30 = The Shrimp
loteria-rhyme-30 = A sleeping shrimp gets swept away by the river's rush.
loteria-card-31 = The Arrows
loteria-rhyme-31 = Swift and sharp arrows striking the mark.
loteria-card-32 = The Musician
loteria-rhyme-32 = The cheerful musician playing a lively song.
loteria-card-33 = The Spider
loteria-rhyme-33 = Knock it away with a stick, do not let it crawl close.
loteria-card-34 = The Soldier
loteria-rhyme-34 = One, two, and three, march to the barracks.
loteria-card-35 = The Star
loteria-rhyme-35 = The shining guide of night sailors.
loteria-card-36 = The Pot
loteria-rhyme-36 = The heavy copper kettle over the glowing embers.
loteria-card-37 = The World
loteria-rhyme-37 = Carrying the weight of the wide round world.
loteria-card-38 = The Apache
loteria-rhyme-38 = Galloping swiftly across the sunlit desert.
loteria-card-39 = The Prickly Pear Cactus
loteria-rhyme-39 = The prickly pear cactus, offering sustenance to all.
loteria-card-40 = The Scorpion
loteria-rhyme-40 = Watch out for the sharp sting in its tail.
loteria-card-41 = The Rose
loteria-rhyme-41 = A fragrant red blossom, but mind the sharp thorns.
loteria-card-42 = The Skull
loteria-rhyme-42 = Wandering through the old cemetery, a smiling skull.
loteria-card-43 = The Bell
loteria-rhyme-43 = Ringing loud and clear from the high church tower.
loteria-card-44 = The Pitcher
loteria-rhyme-44 = Water carried faithfully in the clay pitcher.
loteria-card-45 = The Deer
loteria-rhyme-45 = Leaping swiftly over the thick forest brush.
loteria-card-46 = The Sun
loteria-rhyme-46 = The warming blanket of the weary.
loteria-card-47 = The Crown
loteria-rhyme-47 = The golden crown upon the noble ruler's head.
loteria-card-48 = The Canoe
loteria-rhyme-48 = Rowing gently down the canals in a small wooden canoe.
loteria-card-49 = The Pine Tree
loteria-rhyme-49 = Fragrant and evergreen through winter and spring.
loteria-card-50 = The Fish
loteria-rhyme-50 = Swimming quietly through the clear river.
loteria-card-51 = The Palm Tree
loteria-rhyme-51 = Climb high up the palm tree and toss down a coconut.
loteria-card-52 = The Flowerpot
loteria-rhyme-52 = The colorful flowerpot cheering up the sunny courtyard.
loteria-card-53 = The Harp
loteria-rhyme-53 = Strumming old melodies on the strings of the harp.
loteria-card-54 = The Frog
loteria-rhyme-54 = Leaping high into the cool green reeds.

