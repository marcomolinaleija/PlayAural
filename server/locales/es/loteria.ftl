game-name-loteria = Lotería Mexicana

loteria-pattern-chorro = Cualquier línea o chorro
loteria-pattern-cuatro-esquinas = Cuatro esquinas
loteria-pattern-centro = Cuadro central
loteria-pattern-cuadro-chico = Cuadro chico (cualquier 2x2)
loteria-pattern-lleno = Tabla llena

loteria-call-interval-5 = 5 segundos
loteria-call-interval-10 = 10 segundos
loteria-call-interval-15 = 15 segundos
loteria-call-interval-20 = 20 segundos
loteria-call-interval-30 = 30 segundos

loteria-verses-with-verses = Con coplas tradicionales
loteria-verses-names-only = Solo nombres de cartas

loteria-set-pattern = Patrón para ganar: { $pattern }
loteria-select-pattern = Selecciona el patrón para ganar:
loteria-option-changed-pattern = El patrón para ganar ahora es { $pattern }.
loteria-desc-pattern = El patrón que una tabla debe completar para ganar: cualquier línea (fila, columna o diagonal), cuatro esquinas, cuadro central (2x2 en el centro), cuadro chico (cualquier 2x2) o tabla llena.

loteria-set-call-interval = Cantar cada { $seconds }
loteria-select-call-interval = Selecciona el intervalo de canto:
loteria-option-changed-interval = Ahora se cantará una carta cada { $seconds }.
loteria-desc-call-interval = Cuánto espera el gritón entre cada carta anunciada (por defecto 15, rango de 5 a 30 segundos).

loteria-set-verses = Modo de canto: { $mode }
loteria-select-verses = Selecciona el modo de canto:
loteria-option-changed-verses = El modo de canto ahora es { $mode }.
loteria-desc-verses = Si se incluyen las coplas y versos tradicionales del gritón al cantar cada carta o únicamente su número y nombre.

loteria-set-bet = Apuesta por jugador: { $coins } monedas
loteria-select-bet = Selecciona la cantidad de monedas a apostar:
loteria-option-changed-bet = La apuesta por jugador se cambió a { $coins } monedas.
loteria-desc-bet = Cantidad de monedas virtuales que cada jugador aporta al pozo acumulado.
loteria-bet-0 = Amistoso (sin apuesta)
loteria-bet-10 = 10 monedas
loteria-bet-25 = 25 monedas
loteria-bet-50 = 50 monedas
loteria-bet-100 = 100 monedas

loteria-error-insufficient-coins = { $player } no tiene suficientes monedas para apostar ({ $coins } de { $required } necesarias).
loteria-pot-started = Se inició la partida con una apuesta de { $bet } monedas por jugador. Pozo acumulado: { $pot } monedas.
loteria-winner-won-pot = ¡{ $player } se lleva el pozo de { $pot } monedas!
loteria-pot-refunded = Se agotó la baraja sin ganador. Se han devuelto las apuestas de { $bet } monedas a cada jugador.
loteria-action-check-pot = Ver el pozo de monedas
loteria-check-pot-info = El pozo acumulado actual es de { $pot } monedas (apuesta de { $bet } monedas por jugador).

loteria-cell-marked = { $card }, con frijol.
loteria-cell-unmarked = { $card }, sin marcar.
loteria-you-already-won = Ya ganaste la Lotería en esta ronda.

loteria-you-mark = Pusiste frijolito en { $card }.
loteria-you-unmark = Quitaste frijolito de { $card }.

loteria-claim-loteria = ¡Cantar Buenas!
loteria-repeat-call = Repetir la última carta
loteria-check-called = Ver cartas cantadas
loteria-no-calls-yet = Todavía no se ha cantado ninguna carta.
loteria-claim-in-progress = Se está revisando otra tabla en este momento. Intenta de nuevo en un momento.
loteria-claim-in-progress-you = Tu tabla ya se está revisando.
loteria-claim-wait-for-call = Espera a que se anuncie la carta que está saliendo, luego intenta de nuevo.
loteria-claim-unchanged = Tu tabla no ha cambiado desde que fue rechazada. Pon o quita un frijolito o espera a la siguiente carta antes de volver a reclamar.
loteria-checking-claim-you = ¡Cantas Buenas! Revisando tu tabla...
loteria-checking-claim = ¡{ $player } canta Buenas! Revisando su tabla...
loteria-whose-turn-checking = Revisando la tabla de { $player }...
loteria-whose-turn-checking-you = Se está revisando tu tabla...
loteria-whose-turn-checking-card = Se está revisando una tabla de Lotería...
loteria-whose-turn-drawing = Barajando la siguiente carta...
loteria-whose-turn-waiting = { $seconds ->
    [one] Próxima carta en { $seconds } segundo.
   *[other] Próxima carta en { $seconds } segundos.
}
loteria-claim-incorrect-you = Tabla incorrecta. ¡No son buenas!
loteria-claim-incorrect = La tabla de { $player } es incorrecta. ¡No son buenas!
loteria-claim-incomplete-you = Todavía no tienes el patrón completo.
loteria-claim-incomplete = { $player } todavía no tiene el patrón completo.
loteria-marked-card-not-called = Marcaste { $card }, pero todavía no ha salido de la baraja.

loteria-last-call = Última carta cantada: { $number }: { $card }.
loteria-last-call-with-rhyme = Última carta cantada: { $number }: { $card } — { $rhyme }

loteria-status-called-count = { $count } de { $total } cartas cantadas.
loteria-status-called-entry = { $number }: { $card }

loteria-game-start = ¡Comienza la Lotería Mexicana! Patrón: { $pattern }. Se cantará una carta cada { $interval } segundos. ¡Corre y se va corriendo! Marca tu tabla y presiona B para cantar Buenas cuando la tengas.
loteria-game-start-touch = ¡Comienza la Lotería Mexicana! Patrón: { $pattern }. Se cantará una carta cada { $interval } segundos. ¡Corre y se va corriendo! Marca tu tabla y usa Cantar Buenas cuando la tengas.
loteria-game-start-spectator = ¡Comienza la Lotería Mexicana! Patrón: { $pattern }. Se cantará una carta cada { $interval } segundos. ¡Corre y se va corriendo!

loteria-card-called = ¡{ $number }: { $card }!
loteria-card-called-with-rhyme = ¡{ $number }: { $card }! { $rhyme }

loteria-claim-correct-you = ¡Sí! ¡Buenas! Tu tabla es correcta. ¡Ganas con { $cards }!
loteria-claim-correct = ¡Sí! ¡Buenas! La tabla de { $player } es correcta. ¡Gana con { $cards }!
loteria-claim-correct-no-cards-you = ¡Sí! ¡Buenas! Tu tabla es correcta. ¡Ganas la Lotería!
loteria-claim-correct-no-cards = ¡Sí! ¡Buenas! La tabla de { $player } es correcta. ¡Gana la Lotería!
loteria-deck-exhausted = Se cantaron las 54 cartas de la baraja. La ronda termina aquí.

loteria-error-invalid-interval = "{ $value }" no es un intervalo de canto válido.
loteria-error-invalid-pattern = { $value } no es un patrón para ganar reconocido.
loteria-error-invalid-verses = { $value } no es un modo de canto reconocido.

loteria-end-calls = { $count ->
    [one] Se cantó { $count } carta en esta ronda.
   *[other] Se cantaron { $count } cartas en esta ronda.
}
loteria-end-winner-line = Ganador: { $player }
loteria-end-no-winner = No se cantaron Buenas válidas en esta ronda.

# Las 54 cartas tradicionales
loteria-card-1 = El gallo
loteria-rhyme-1 = El que le cantó a San Pedro no le volverá a cantar.
loteria-card-2 = El diablo
loteria-rhyme-2 = Pórtate bien cuatito, si no te lleva el coloradito.
loteria-card-3 = La dama
loteria-rhyme-3 = Puliendo el paso, por toda la calle Real.
loteria-card-4 = El catrín
loteria-rhyme-4 = Don Ferruco en la alameda, su bastón quería tirar.
loteria-card-5 = El paraguas
loteria-rhyme-5 = Para el sol y para el agua.
loteria-card-6 = La sirena
loteria-rhyme-6 = Con el canto de sirena, no te vayas a marear.
loteria-card-7 = La escalera
loteria-rhyme-7 = Súbeme paso a pasito, no te vayas a caer.
loteria-card-8 = La botella
loteria-rhyme-8 = La herramienta del borracho.
loteria-card-9 = El barril
loteria-rhyme-9 = Tanto bebió el albañil, que quedó como un barril.
loteria-card-10 = El árbol
loteria-rhyme-10 = El que a buen árbol se arrima, buena sombra le cobija.
loteria-card-11 = El melón
loteria-rhyme-11 = Me lo das o me lo quitas.
loteria-card-12 = El valiente
loteria-rhyme-12 = Por qué le corres cobarde, trayendo tan buen puñal.
loteria-card-13 = El gorrito
loteria-rhyme-13 = Ponle su gorrito al nene, no se vaya a resfriar.
loteria-card-14 = La muerte
loteria-rhyme-14 = La muerte siriquisiaca, tirulina, lina, lina.
loteria-card-15 = La pera
loteria-rhyme-15 = El que espera desespera.
loteria-card-16 = La bandera
loteria-rhyme-16 = Verde, blanco y colorado, la bandera del soldado.
loteria-card-17 = El bandolón
loteria-rhyme-17 = Tocando su bandolón, está el mariachi en el mesón.
loteria-card-18 = El violoncello
loteria-rhyme-18 = Creciendo se fue hasta el cielo, y como no fue violón, tuvo que ser violoncello.
loteria-card-19 = La garza
loteria-rhyme-19 = Al otro lado del río tengo mi garza querendona.
loteria-card-20 = El pájaro
loteria-rhyme-20 = Tú me traes a paso largo, cantando de rama en rama.
loteria-card-21 = La mano
loteria-rhyme-21 = La mano de un criminal.
loteria-card-22 = La bota
loteria-rhyme-22 = Una bota es igual que la otra.
loteria-card-23 = La luna
loteria-rhyme-23 = El farol de los enamorados.
loteria-card-24 = El cotorro
loteria-rhyme-24 = Perico cotorro loro, pides la pata y te dan un peso.
loteria-card-25 = El borracho
loteria-rhyme-25 = ¡Ah qué borracho tan necio, ya no lo puedo aguantar!
loteria-card-26 = El negrito
loteria-rhyme-26 = El que se comió el azúcar.
loteria-card-27 = El corazón
loteria-rhyme-27 = No me extrañes corazón, que al rato vuelvo.
loteria-card-28 = La sandía
loteria-rhyme-28 = La barriga que Juan tenía, era fruta y no sandía.
loteria-card-29 = El tambor
loteria-rhyme-29 = No te arrugues cuero viejo, que te quiero pa' tambor.
loteria-card-30 = El camarón
loteria-rhyme-30 = Camarón que se duerme, se lo lleva la corriente.
loteria-card-31 = Las jaras
loteria-rhyme-31 = Las jaras del indio Adán, donde pegan sangre dan.
loteria-card-32 = El músico
loteria-rhyme-32 = El músico trompas de hule.
loteria-card-33 = La araña
loteria-rhyme-33 = Atarántamela a palos, no me la dejes llegar.
loteria-card-34 = El soldado
loteria-rhyme-34 = Uno, dos y tres, el soldado p'al cuartel.
loteria-card-35 = La estrella
loteria-rhyme-35 = La guía de los marineros.
loteria-card-36 = El cazo
loteria-rhyme-36 = El caso que te hago es poco.
loteria-card-37 = El mundo
loteria-rhyme-37 = Este mundo es una bola, y nosotros una bola de tontos.
loteria-card-38 = El apache
loteria-rhyme-38 = ¡Ah Chihuahua! ¡Cuánto apache con pantalón y huarache!
loteria-card-39 = El nopal
loteria-rhyme-39 = Al que todos van a ver, cuando tiene que comer.
loteria-card-40 = El alacrán
loteria-rhyme-40 = El que con la cola pica, muy malo debe de ser.
loteria-card-41 = La rosa
loteria-rhyme-41 = Rosita, Rosaura, ven que te quiero abrazar.
loteria-card-42 = La calavera
loteria-rhyme-42 = Al pasar por el panteón, me encontré una calavera.
loteria-card-43 = La campana
loteria-rhyme-43 = Tú con la campana y yo con el badajo.
loteria-card-44 = El cantarito
loteria-rhyme-44 = Tanto va el cántaro al agua, que se quiebra y te moja.
loteria-card-45 = El venado
loteria-rhyme-45 = El que brinca los matorrales.
loteria-card-46 = El sol
loteria-rhyme-46 = La cobija de los pobres.
loteria-card-47 = La corona
loteria-rhyme-47 = El sombrero de los reyes.
loteria-card-48 = La chalupa
loteria-rhyme-48 = Rema y rema va Lupita, sentadita en su chalupa.
loteria-card-49 = El pino
loteria-rhyme-49 = Fresco y oloroso, en todo tiempo hermoso.
loteria-card-50 = El pescado
loteria-rhyme-50 = El que por la boca muere, aunque mudo fuere.
loteria-card-51 = La palma
loteria-rhyme-51 = Sube a la palma y bájame un coco.
loteria-card-52 = La maceta
loteria-rhyme-52 = El que nace pa' maceta, no pasa del corredor.
loteria-card-53 = El arpa
loteria-rhyme-53 = Arpa vieja de mi suegra, ya no sirves pa' tocar.
loteria-card-54 = La rana
loteria-rhyme-54 = Al ver a la verde rana, qué brinco pegó tu hermana.

