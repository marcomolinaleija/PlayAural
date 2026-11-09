game-name-infiltrado = El Infiltrado
infiltrado-desc = Juego de deducción social y palabras secretas. Descubre al infiltrado antes de que sea tarde.

infiltrado-set-clue-mode = Modo de pistas: { $mode }
infiltrado-select-clue-mode = Selecciona el modo de dar pistas
infiltrado-option-changed-clue-mode = Modo de pistas establecido en { $mode }.
infiltrado-desc-clue-mode = Elige si las pistas se dan solo por voz o si se permite escribirlas para guardarlas en el historial.
infiltrado-mode-voice = Solo voz
infiltrado-mode-text-and-voice = Texto y voz

infiltrado-set-undercover-count = Infiltrados: { $count }
infiltrado-select-undercover-count = Selecciona la cantidad de infiltrados
infiltrado-option-changed-undercover-count = Cantidad de infiltrados establecida en { $count }.
infiltrado-desc-undercover-count = Número de infiltrados en la partida (1 o 2).
infiltrado-undercover-1 = 1 Infiltrado
infiltrado-undercover-2 = 2 Infiltrados

infiltrado-set-mr-white = Incluir a Mr. White: { $enabled }
infiltrado-select-mr-white = ¿Deseas incluir a Mr. White?
infiltrado-option-changed-mr-white = Mr. White establecido en { $enabled }.
infiltrado-desc-mr-white = Añade un jugador que no recibe ninguna palabra y debe deducirla para ganar.
infiltrado-mr-white-yes = Sí
infiltrado-mr-white-no = No

infiltrado-set-turn-timer = Tiempo por turno: { $seconds }
infiltrado-select-turn-timer = Selecciona el tiempo límite por turno
infiltrado-option-changed-turn-timer = Tiempo por turno establecido en { $seconds }.
infiltrado-desc-turn-timer = Tiempo máximo para dar la pista en cada turno.
infiltrado-timer-0 = Sin límite
infiltrado-timer-30 = 30 segundos
infiltrado-timer-45 = 45 segundos
infiltrado-timer-60 = 60 segundos

infiltrado-set-vote-timer = Tiempo de votación: { $seconds }
infiltrado-select-vote-timer = Selecciona el tiempo límite de votación
infiltrado-option-changed-vote-timer = Tiempo de votación establecido en { $seconds }.
infiltrado-desc-vote-timer = Tiempo para debatir y votar a quién expulsar.
infiltrado-vote-timer-30 = 30 segundos
infiltrado-vote-timer-45 = 45 segundos
infiltrado-vote-timer-60 = 60 segundos
infiltrado-vote-timer-90 = 90 segundos

infiltrado-set-clue-rounds = Rondas de pistas antes de votar: { $count }
infiltrado-select-clue-rounds = Selecciona la cantidad de rondas de pistas antes de votar
infiltrado-option-changed-clue-rounds = Rondas de pistas antes de votar establecido en { $count }.
infiltrado-desc-clue-rounds = Número de rondas completas de pistas que da cada jugador antes de iniciar la fase de votación.
infiltrado-clue-rounds-1 = 1 ronda
infiltrado-clue-rounds-2 = 2 rondas
infiltrado-clue-rounds-3 = 3 rondas
infiltrado-clue-rounds-4 = 4 rondas
infiltrado-clue-rounds-5 = 5 rondas

infiltrado-action-word-said = Ya dije mi palabra
infiltrado-action-word-said-voice = Ya dije mi palabra (solo voz)
infiltrado-action-give-clue-text = Escribir mi pista
infiltrado-prompt-enter-clue = Escribe tu pista para esta ronda:
infiltrado-action-check-secret-word = Consultar mi palabra secreta
infiltrado-action-check-clues-history = Consultar historial de pistas
infiltrado-action-check-alive-players = Consultar jugadores vivos
infiltrado-action-vote-suspect = Votar sospechoso a expulsar
infiltrado-prompt-vote-suspect = Selecciona al jugador que deseas expulsar:
infiltrado-vote-target-label = Expulsar a { $player }
infiltrado-action-mr-white-guess = Adivinar la palabra secreta de los ciudadanos
infiltrado-prompt-mr-white-guess = Escribe la palabra secreta que crees que tienen los ciudadanos:

infiltrado-game-started = ¡Comienza la partida de El Infiltrado! Se han asignado los roles y las palabras secretas. Ronda 1 de pistas.
infiltrado-private-civilian-word = Tu palabra secreta es: { $word }. Eres un Ciudadano. Da una pista que describa tu palabra sin ser demasiado evidente.
infiltrado-private-undercover-word = Tu palabra secreta es: { $word }. Eres un Infiltrado. Intenta pasar desapercibido entre los ciudadanos.
infiltrado-private-mr-white = ¡Eres Mr. White! No tienes ninguna palabra secreta. Escucha con atención las pistas de los demás para que no sospechen de ti.

infiltrado-secret-word-reminder-civilian = Tu palabra secreta es: { $word }. Rol: Ciudadano.
infiltrado-secret-word-reminder-undercover = Tu palabra secreta es: { $word }. Rol: Infiltrado.
infiltrado-secret-word-reminder-mr-white = Rol: Mr. White. ¡No tienes palabra secreta! Debes deducirla.

infiltrado-clue-given-voice = { $player } dio su pista por voz.
infiltrado-clue-given-text = { $player } dio su pista: { $clue }
infiltrado-clue-timeout = Se agotó el tiempo de { $player } para dar su pista.

infiltrado-voting-phase-started = Todos han dado su pista en la ronda { $round }. ¡Comienza la fase de debate y votación! Tienen { $seconds } segundos para debatir y votar.
infiltrado-voting-phase-started-no-timer = Todos han dado su pista en la ronda { $round }. ¡Comienza la fase de debate y votación! Debatan y seleccionen a quién expulsar.
infiltrado-player-voted-feedback = Has votado para expulsar a { $target }. Esperando al resto de jugadores...
infiltrado-player-voted-public = { $player } ha emitido su voto.

infiltrado-voting-tie = ¡Empate en la votación! { $players } recibieron { $votes } votos cada uno. Nadie es expulsado en esta ronda.
infiltrado-player-eliminated = { $player } ha recibido la mayoría de votos ({ $votes } votos) y es expulsado de la mesa.
infiltrado-revealed-civilian = { $player } era un Ciudadano inocente.
infiltrado-revealed-undercover = ¡{ $player } era un Infiltrado! Han descubierto a un impostor.
infiltrado-revealed-mr-white = { $player } era Mr. White. ¡Atención! Mr. White tiene una oportunidad para adivinar la palabra secreta de los ciudadanos.

infiltrado-mr-white-guessed-correct = ¡INCREÍBLE! { $player } (Mr. White) adivinó correctamente la palabra secreta: '{ $word }'. ¡Mr. White gana la partida!
infiltrado-mr-white-guessed-wrong = { $player } (Mr. White) intentó adivinar con '{ $guess }', pero la palabra de los ciudadanos era '{ $word }'. ¡Ha fallado y queda eliminado!

infiltrado-win-civilians = ¡VICTORIA DE LOS CIUDADANOS! Todos los infiltrados han sido eliminados. La palabra de los ciudadanos era '{ $civilian_word }' y la de los infiltrados era '{ $undercover_word }'.
infiltrado-win-undercovers = ¡VICTORIA DE LOS INFILTRADOS! Los infiltrados han logrado igualar en número a los ciudadanos. La palabra de los ciudadanos era '{ $civilian_word }' y la de los infiltrados era '{ $undercover_word }'.
infiltrado-win-mr-white = ¡VICTORIA DE MR. WHITE! { $player } adivinó la palabra de los ciudadanos y se alza con la victoria en solitario.

infiltrado-next-round = Comienza la ronda { $round } de pistas con los { $count } jugadores supervivientes.
infiltrado-next-clue-round = Comienza la ronda { $round } de pistas ({ $cycle_round } de { $total_cycle } antes de la votación).

infiltrado-turn-info-you = Es tu turno. Quedan { $seconds } segundos.
infiltrado-turn-info-you-no-timer = Es tu turno. Sin límite de tiempo.
infiltrado-turn-info-other = Es turno de { $player }. Quedan { $seconds } segundos.
infiltrado-turn-info-other-no-timer = Es turno de { $player }. Sin límite de tiempo.
infiltrado-turn-info-voting = Fase de votación. Quedan { $seconds } segundos para debatir y votar.
infiltrado-turn-info-voting-no-timer = Fase de votación. Debatan y emitan su voto sin límite de tiempo.
infiltrado-turn-info-mr-white = Turno de Mr. White ({ $player }) para intentar adivinar la palabra secreta.

infiltrado-history-title = Historial de pistas:
infiltrado-history-empty = Aún no se han registrado pistas en esta partida.
infiltrado-history-round-header = Ronda { $round }:
infiltrado-history-entry = { $player }: { $clue }

infiltrado-alive-players-title = Jugadores en la mesa:
infiltrado-alive-player-entry = { $player }: Activo (Vivo)
infiltrado-eliminated-player-entry = { $player }: Expulsado ({ $role })

infiltrado-role-label-civilian = Ciudadano
infiltrado-role-label-undercover = Infiltrado
infiltrado-role-label-mr_white = Mr. White

infiltrado-error-min-players = Se requieren al menos 3 jugadores para jugar a El Infiltrado.
infiltrado-error-need-5-for-two-undercovers = Se necesitan al menos 5 jugadores para jugar con 2 infiltrados.
infiltrado-error-need-4-for-mr-white = Se necesitan al menos 4 jugadores para incluir a Mr. White.
infiltrado-error-already-voted = Ya has emitido tu voto en esta ronda.
infiltrado-error-not-in-voting = La partida no se encuentra en fase de votación.
infiltrado-error-not-your-turn = No es tu turno para dar una pista.

