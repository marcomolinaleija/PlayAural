game-name-infiltrado = Undercover
infiltrado-desc = Social deduction word game. Find the undercover before it is too late.

infiltrado-set-clue-mode = Clue mode: { $mode }
infiltrado-select-clue-mode = Select clue giving mode
infiltrado-option-changed-clue-mode = Clue mode set to { $mode }.
infiltrado-desc-clue-mode = Choose whether clues are given via voice only or text entry with history.
infiltrado-mode-voice = Voice only
infiltrado-mode-text-and-voice = Text and voice

infiltrado-set-undercover-count = Undercovers: { $count }
infiltrado-select-undercover-count = Select number of undercovers
infiltrado-option-changed-undercover-count = Undercover count set to { $count }.
infiltrado-desc-undercover-count = Number of undercovers in match (1 or 2).
infiltrado-undercover-1 = 1 Undercover
infiltrado-undercover-2 = 2 Undercovers

infiltrado-set-mr-white = Include Mr. White: { $enabled }
infiltrado-select-mr-white = Include Mr. White?
infiltrado-option-changed-mr-white = Mr. White set to { $enabled }.
infiltrado-desc-mr-white = Adds a player who gets no secret word and must deduce it to win.
infiltrado-mr-white-yes = Yes
infiltrado-mr-white-no = No

infiltrado-set-turn-timer = Turn time: { $seconds }
infiltrado-select-turn-timer = Select turn time limit
infiltrado-option-changed-turn-timer = Turn time set to { $seconds }.
infiltrado-desc-turn-timer = Maximum time to give clue on each turn.
infiltrado-timer-0 = No limit
infiltrado-timer-30 = 30 seconds
infiltrado-timer-45 = 45 seconds
infiltrado-timer-60 = 60 seconds

infiltrado-set-vote-timer = Voting time: { $seconds }
infiltrado-select-vote-timer = Select voting time limit
infiltrado-option-changed-vote-timer = Voting time set to { $seconds }.
infiltrado-desc-vote-timer = Time to discuss and vote on who to eliminate.
infiltrado-vote-timer-30 = 30 seconds
infiltrado-vote-timer-45 = 45 seconds
infiltrado-vote-timer-60 = 60 seconds
infiltrado-vote-timer-90 = 90 seconds

infiltrado-action-word-said = Word said
infiltrado-action-word-said-voice = Word said (voice only)
infiltrado-action-give-clue-text = Type my clue
infiltrado-prompt-enter-clue = Enter your clue for this round:
infiltrado-action-check-secret-word = Check my secret word
infiltrado-action-check-clues-history = Check clue history
infiltrado-action-check-alive-players = Check players at table
infiltrado-action-vote-suspect = Vote to eliminate suspect
infiltrado-prompt-vote-suspect = Select the player you want to eliminate:
infiltrado-vote-target-label = Eliminate { $player }
infiltrado-action-mr-white-guess = Guess civilians' secret word
infiltrado-prompt-mr-white-guess = Enter the civilians' secret word:

infiltrado-game-started = Undercover match started! Roles and secret words have been assigned. Round 1 of clues.
infiltrado-private-civilian-word = Your secret word is: { $word }. You are a Civilian. Give a clue describing your word without making it too obvious.
infiltrado-private-undercover-word = Your secret word is: { $word }. You are the Undercover. Blend in with the civilians.
infiltrado-private-mr-white = You are Mr. White! You have no secret word. Listen carefully to others' clues so they do not suspect you.

infiltrado-secret-word-reminder-civilian = Your secret word is: { $word }. Role: Civilian.
infiltrado-secret-word-reminder-undercover = Your secret word is: { $word }. Role: Undercover.
infiltrado-secret-word-reminder-mr-white = Role: Mr. White. You have no secret word! You must deduce it.

infiltrado-clue-given-voice = { $player } gave their clue by voice.
infiltrado-clue-given-text = { $player } gave their clue: { $clue }
infiltrado-clue-timeout = { $player }'s turn to give a clue timed out.

infiltrado-voting-phase-started = Everyone gave their clue in round { $round }. Voting phase begins! You have { $seconds } seconds to discuss and vote.
infiltrado-voting-phase-started-no-timer = Everyone gave their clue in round { $round }. Voting phase begins! Discuss and vote.
infiltrado-player-voted-feedback = You voted to eliminate { $target }. Waiting for other players...
infiltrado-player-voted-public = { $player } has cast their vote.

infiltrado-voting-tie = Vote tie! { $players } received { $votes } votes each. Nobody is eliminated this round.
infiltrado-player-eliminated = { $player } received the most votes ({ $votes } votes) and is eliminated from the table.
infiltrado-revealed-civilian = { $player } was an innocent Civilian.
infiltrado-revealed-undercover = { $player } was an Undercover! An impostor was discovered.
infiltrado-revealed-mr-white = { $player } was Mr. White. Attention! Mr. White has a chance to guess the civilians' secret word.

infiltrado-mr-white-guessed-correct = INCREDIBLE! { $player } (Mr. White) correctly guessed the secret word: '{ $word }'. Mr. White wins!
infiltrado-mr-white-guessed-wrong = { $player } (Mr. White) guessed '{ $guess }', but the secret word was '{ $word }'. He failed and is eliminated!

infiltrado-win-civilians = CIVILIANS WIN! All undercovers have been eliminated. Civilians' word was '{ $civilian_word }' and Undercover's word was '{ $undercover_word }'.
infiltrado-win-undercovers = UNDERCOVERS WIN! Undercovers have equaled the number of civilians. Civilians' word was '{ $civilian_word }' and Undercover's word was '{ $undercover_word }'.
infiltrado-win-mr-white = MR. WHITE WINS! { $player } guessed the secret word and claims solo victory.

infiltrado-next-round = Round { $round } of clues begins with { $count } surviving players.

infiltrado-history-title = Clue history:
infiltrado-history-empty = No clues have been recorded yet in this match.
infiltrado-history-round-header = Round { $round }:
infiltrado-history-entry = { $player }: { $clue }

infiltrado-alive-players-title = Players at table:
infiltrado-alive-player-entry = { $player }: Active (Alive)
infiltrado-eliminated-player-entry = { $player }: Eliminated ({ $role })

infiltrado-role-label-civilian = Civilian
infiltrado-role-label-undercover = Undercover
infiltrado-role-label-mr_white = Mr. White

infiltrado-error-min-players = At least 3 players are required to play Undercover.
infiltrado-error-need-5-for-two-undercovers = At least 5 players are required to play with 2 undercovers.
infiltrado-error-need-4-for-mr-white = At least 4 players are required to include Mr. White.
infiltrado-error-already-voted = You have already voted this round.
infiltrado-error-not-in-voting = The game is not in voting phase.
infiltrado-error-not-your-turn = It is not your turn to give a clue.

