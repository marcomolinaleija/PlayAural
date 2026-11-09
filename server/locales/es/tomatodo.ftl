game-name-tomatodo = Toma Todo (Pirinola)

tomatodo-set-coin-unit = Valor de la unidad: { $unit } monedas
tomatodo-select-coin-unit = Selecciona el valor de cada unidad en monedas
tomatodo-option-changed-coin-unit = Valor de la unidad establecido en { $unit } monedas.
tomatodo-desc-coin-unit = Define cuántas monedas del monedero equivale cada unidad (Pon 1, Toma 1, etc.).
tomatodo-unit-1 = 1 moneda
tomatodo-unit-5 = 5 monedas
tomatodo-unit-10 = 10 monedas
tomatodo-unit-25 = 25 monedas
tomatodo-unit-50 = 50 monedas

tomatodo-set-ante = Apuesta inicial: { $ante } { $ante ->
    [one] unidad
   *[other] unidades
}
tomatodo-select-ante = Selecciona la apuesta inicial por jugador
tomatodo-option-changed-ante = Apuesta inicial establecida en { $ante } { $ante ->
    [one] unidad
   *[other] unidades
}.
tomatodo-desc-ante = Unidades que cada jugador aporta al pozo al inicio del juego.
tomatodo-ante-1 = 1 unidad
tomatodo-ante-2 = 2 unidades

tomatodo-set-rounds = Límite de rondas: { $rounds }
tomatodo-select-rounds = Selecciona el número de rondas o juego continuo
tomatodo-option-changed-rounds = Límite de rondas establecido en { $rounds }.
tomatodo-desc-rounds = Termina la partida al alcanzar este número de rondas o continúa hasta que quede un solo jugador con monedas.
tomatodo-rounds-continuous = Continuo (hasta el último jugador)
tomatodo-rounds-10 = 10 rondas
tomatodo-rounds-15 = 15 rondas
tomatodo-rounds-20 = 20 rondas

tomatodo-set-speed = Velocidad del giro: { $speed }
tomatodo-select-speed = Selecciona la velocidad del giro de la pirinola
tomatodo-option-changed-speed = Velocidad del giro establecida en { $speed }.
tomatodo-desc-speed = Elige entre giro rápido (3.5 segundos) o giro completo tradicional (11 segundos).
tomatodo-speed-fast = Rápido (3.5 segundos)
tomatodo-speed-full = Completo (11 segundos)

tomatodo-action-spin = Girar la pirinola
tomatodo-action-check-pot = Consultar pozo
tomatodo-action-check-balances = Consultar monedas de los jugadores
tomatodo-action-check-last-spin = Consultar último giro

tomatodo-pot-started = Comienza la partida de Toma Todo. Cada jugador aporta { $ante } monedas. El pozo inicial es de { $pot } monedas.
tomatodo-result-pon-1 = { $player } giró la pirinola y sacó: Pon 1. Pone { $coins } monedas al pozo. Total en pozo: { $pot }.
tomatodo-result-pon-2 = { $player } giró la pirinola y sacó: Pon 2. Pone { $coins } monedas al pozo. Total en pozo: { $pot }.
tomatodo-result-toma-1 = { $player } giró la pirinola y sacó: Toma 1. Toma { $coins } monedas del pozo. Quedan { $pot } monedas.
tomatodo-result-toma-2 = { $player } giró la pirinola y sacó: Toma 2. Toma { $coins } monedas del pozo. Quedan { $pot } monedas.
tomatodo-result-todos-ponen = ¡Todos ponen! Cada jugador aporta { $unit } monedas. Total en pozo: { $pot }.
tomatodo-result-toma-todo = ¡TOMA TODO! { $player } se lleva todo el pozo de { $coins } monedas.
tomatodo-pot-empty = El pozo está vacío.
tomatodo-pot-replenished = El pozo se agotó. Todos los jugadores activos ponen { $unit } monedas. Nuevo pozo: { $pot }.
tomatodo-player-bankrupt = ¡{ $player } se ha quedado sin monedas y queda en bancarrota!
tomatodo-game-won-last-standing = ¡{ $winner } es el único sobreviviente con { $coins } monedas y gana la partida!
tomatodo-game-won-rounds = ¡Fin de las rondas! { $winner } gana la partida con { $coins } monedas.
tomatodo-game-tie-rounds = ¡Fin de las rondas! Empate entre { $winners } con { $coins } monedas cada uno.

tomatodo-check-pot-info = El pozo acumulado tiene { $pot } monedas ({ $unit } monedas por unidad).
tomatodo-player-balance = { $player }: { $coins } monedas
tomatodo-player-balance-bankrupt = { $player }: en bancarrota (0 monedas)
tomatodo-no-last-spin = Aún no se ha realizado ningún giro.
tomatodo-last-spin-info = El último giro fue de { $player }: sacó { $face }.

tomatodo-face-pon_1 = Pon 1
tomatodo-face-pon_2 = Pon 2
tomatodo-face-toma_1 = Toma 1
tomatodo-face-toma_2 = Toma 2
tomatodo-face-todos_ponen = Todos ponen
tomatodo-face-toma_todo = Toma todo

tomatodo-error-insufficient-coins = { $player } no tiene suficientes monedas en su monedero (tiene { $coins }, se requieren al menos { $required }).
tomatodo-error-player-bankrupt = Estás en bancarrota y no puedes girar la pirinola.
tomatodo-error-bots-not-supported = Toma Todo se juega con monedas del monedero y no admite bots. Todos los jugadores deben ser humanos.
