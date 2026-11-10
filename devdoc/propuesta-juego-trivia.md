# Propuesta de Diseño: Juego de Trivia / Concurso para PlayAural

## 1. Visión General
Un juego de preguntas y respuestas (**Trivia / Concurso de TV**) diseñado desde cero para lectores de pantalla en **PlayAural** (`server/games/trivia/`), aprovechando:
- **Locutor animado con ElevenLabs (`eleven_v4`)**: La voz expresiva de presentador de televisión (`George` / `Brian` con reverberación de estudio `small_room` o `hall` mediante [`elevenlabs_tts.py`](../server/game_utils/elevenlabs_tts.py)) para dar ambiente de programa en vivo.
- **Posicionamiento espacial 3D en Cosmos (HRTF)**:
  - El **Presentador** se ubica al frente-centro elevado `(0.0, 1.8, 0.45)`.
  - Los **pulsadores (buzzers)** y respuestas de cada concursante suenan desde la posición de su asiento (`seat_of=player`).
  - La música de tensión y el reloj de cuenta regresiva se sitúan en el escenario central.

---

## 2. Modalidades de Juego (`MenuOption`)
1. **Todos Responden (Simultáneo con bono de velocidad)**:
   - Todos los jugadores activos eligen en secreto su respuesta (`A`, `B`, `C` o `D`) antes de que termine el reloj (p. ej., 15 o 20 segundos).
   - Nadie escucha lo que eligieron los demás hasta que todos hayan respondido o se agote el tiempo (aislamiento por jugador con `refresh_menus(player)`).
   - Al cerrarse el tiempo, el presentador revela las respuestas y otorga **100 puntos base + bono por rapidez** (hasta +50 puntos).
2. **Pulsador Rápido (Modo Buzzer / Duelo)**:
   - Se anuncia la pregunta y las 4 opciones.
   - El primero en presionar su pulsador (`Espacio` o botón táctil en la parte superior del menú) toma la palabra durante 8 segundos.
   - Si acierta, suma puntos; si falla, resta puntos y el rebote queda abierto para los demás jugadores.
3. **Escalera de Premios (Estilo *¿Quién quiere ser millonario?* por turnos o cooperativo)**:
   - Preguntas de dificultad creciente con **3 comodines** por jugador/equipo:
     - **50/50**: Elimina dos opciones incorrectas del menú de turno.
     - **Cambio de pregunta**: Sustituye la pregunta actual por otra de la misma categoría.
     - **Doble oportunidad**: Permite un segundo intento si la primera opción falla.

---

## 3. Categorías y Banco de Preguntas
- Categorías configurables en las opciones de mesa (`BoolOption` o `MenuOption`):
  - **Cultura General**
  - **Historia y Geografía**
  - **Ciencia y Naturaleza**
  - **Cine, Música y Entretenimiento**
  - **Deportes y Videojuegos**
  - **México y Latinoamérica**
- Almacenamiento en archivos JSON estructurados por idioma (`server/games/trivia/questions_es.json`, etc.) con validación de no repetición durante la misma partida (`used_question_ids: list[str]`).
- Opción futura de generar paquetes temáticos adicionales bajo demanda o mediante herramientas administrativas.

---

## 4. Catálogo de Voces del Presentador (ElevenLabs `eleven_v4`)
Gracias a [`server/game_utils/elevenlabs_tts.py`](../server/game_utils/elevenlabs_tts.py), podemos generar un catálogo de frases fijas del presentador (opcional vía `natural_voices: bool = True`):

| Archivo | Frase sugerida | Momento |
|---|---|---|
| `host_welcome.ogg` | *"¡Bienvenidos al gran duelo de Trivia! Preparen sus mentes, que comienza la primera ronda."* | Inicio de partida (`on_start`) |
| `host_cat_history.ogg` | *"Categoría: Historia y Geografía. Escuchen con atención."* | Anuncio de categoría |
| `host_cat_science.ogg` | *"Categoría: Ciencia y Naturaleza. Vamos con la pregunta."* | Anuncio de categoría |
| `host_cat_entertainment.ogg` | *"Categoría: Cine, Música y Entretenimiento."* | Anuncio de categoría |
| `host_cat_general.ogg` | *"Categoría: Cultura General. ¡Corre tiempo!"* | Anuncio de categoría |
| `host_time_up.ogg` | *"¡Tiempo fuera! Nadie más puede responder. Veamos la respuesta correcta."* | Fin del temporizador |
| `host_all_locked.ogg` | *"¡Respuestas aseguradas! Momento de la verdad..."* | Todos respondieron |
| `host_correct_all.ogg` | *"¡Impresionante! Todos acertaron esta pregunta."* | Pleno de aciertos |
| `host_correct_one.ogg` | *"¡Respuesta correcta! Esos puntos suben al marcador."* | Al menos un acierto |
| `host_wrong_all.ogg` | *"¡Nadie acertó! Esa pregunta sí que estaba difícil."* | Cero aciertos |
| `host_lifeline_5050.ogg` | *"¡Comodín cincuenta-cincuenta! Quitamos dos respuestas incorrectas."* | Uso de comodín 50/50 |
| `host_final_round.ogg` | *"¡Última pregunta de la noche! Los puntos valen el doble."* | Ronda final |
| `host_game_over.ogg` | *"¡Se acabó el concurso! Tenemos a nuestro gran campeón de la noche."* | Fin de partida |

*(Nota: el texto específico de cada pregunta y de las opciones `A, B, C, D` siempre se lee por el lector de pantalla mediante `speak_l(..., buffer="game")` para garantizar lectura inmediata, repetible con atajos de teclado y 100% accesible).*

---

## 5. Accesibilidad y Controles (Teclado y Clientes Táctiles)
- **Menú de turno**:
  - En modo pulsador, el botón **`¡Pulsar para responder!`** aparece primero para clientes táctiles.
  - Opciones de respuesta con IDs estables (`answer_a`, `answer_b`, `answer_c`, `answer_d`) que conservan el foco cuando se actualiza el estado.
- **Atajos de teclado (`KeybindState.ACTIVE`)**:
  - `q`: Repetir la pregunta actual y su categoría (`include_spectators=True`).
  - `o`: Escuchar de nuevo las 4 opciones disponibles (`include_spectators=True`).
  - `1`, `2`, `3`, `4`: Seleccionar directamente las opciones `A`, `B`, `C`, `D`.
  - `c`: Usar comodín (abre selector `MenuInput` con los comodines disponibles).
  - `r`: Consultar tiempo restante de la pregunta actual (`include_spectators=True`).
  - `s`: Consultar marcador y rachas en un `live_status_box`.

---

## 6. Integración Opcional con Monedero del Servidor (Futuro)
- Compatible con premios de monedas virtuales por aciertos en racha o bote acumulado para el ganador de la noche (usando límites de emisión diaria para evitar inflación).
