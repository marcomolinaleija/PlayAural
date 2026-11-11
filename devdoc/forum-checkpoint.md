# Estado guardado del foro — 6 de noviembre de 2026

## Disponibilidad global — 11 de noviembre

Se añadió Foro: Activado/Desactivado en Administración → Moderación y sanciones
→ Moderación del chat, para administradores y desarrolladores. Es persistente,
no oculta la entrada del menú principal y, mientras está desactivado, esa entrada
solo devuelve un aviso. Se conservan los borradores locales, pero no se puede
publicar ni acceder de nuevo a los adjuntos. Validación y alcance en
[forum-availability.md](forum-availability.md): 5238 pruebas del servidor
aprobadas y 15 omitidas. Sin cambios de esquema o clientes.

## Editor compacto de mensajes

Por preferencia del usuario, el editor sigue el patrón de los subforos:
un elemento editable por campo, con formato Título: contenido y Mensaje:
contenido. Responder y editar muestran solo Mensaje. Se eliminó la vista previa
separada y la explicación repetida al entrar. El foco vuelve al campo editado.
La fila de mensaje muestra un resumen de hasta 160 caracteres; el editbox
conserva el texto completo, incluidas sus líneas, hasta 8000 caracteres.
Validación: 119 pruebas del foro aprobadas, 3 omitidas; registro externo
`forum-validation/compact-composer-final.log`. Comparación EN/VI/ES sin
diferencias bloqueantes. Sin cambio de esquema ni archivos de clientes.

## Gestión de subforos — 10 de noviembre

Se añadieron creación, edición y eliminación para administradores y
desarrolladores desde Foro → Gestionar subforos. Eliminar un subforo con temas
requiere elegir dónde conservarlos y confirmar. El esquema 7 separa los privados
de las categorías públicas; sus mensajes y participantes no se exponen a esta
gestión. Validación y decisiones en [forum-categories.md](forum-categories.md).
El servidor normal se ejecuta con la base `PlayAural.db` en el puerto 8000;
los archivos del foro usan el puerto 8001. No usar la demo para la revisión del
usuario. Móvil continúa pausado.

## Carpeta de trabajo actual — preferencia del usuario

El usuario pidió trabajar en una sola carpeta cambiando de ramas, sin worktrees
adicionales. El foro está ahora en la rama `feature/forum-foundation` del checkout
principal:
`C:\Users\leija\Documents\Codex\2026-10-31\re\outputs\PlayAural`.
La carpeta separada `PlayAural-forum` fue retirada después de comprobar que no
contenía cambios pendientes. Sus archivos locales ignorados se conservaron en
`C:\Users\leija\Documents\Codex\2026-10-31\re\work\forum-validation\checkout-transition-20261110`.
Para continuar, usar `git switch feature/forum-foundation` en la carpeta
principal. Móvil sigue pausado. Las referencias al worktree separado en los
informes anteriores describen el lugar histórico donde se realizaron las pruebas.

## Sincronización autorizada con develop — 10 de noviembre

El estado anterior se guardó en commits locales y en la rama
`backup/forum-before-develop-20261110`. Se incorpora `origin/develop` (`8eef1c42`)
exclusivamente en la rama del foro. El estado y la validación de esta base se
documentan en [forum-develop-sync.md](forum-develop-sync.md). Móvil permanece
pausado y la revisión interactiva de escritorio sigue pendiente.

## Pruebas retomadas y cierre de etapa — 10 de noviembre

El usuario indicó continuar las pruebas para cerrar esta etapa por ahora. Se
completaron las suites del servidor (4914 aprobadas, 6 omitidas), escritorio
(324) y web (88), los recorridos web de aprobación/privados/encuesta, el paquete
del servidor y un ensayo de restauración con acceso HTTP. El informe vigente
es [forum-validation.md](forum-validation.md), con sus evidencias y límites.

Móvil continúa pausado. La revisión interactiva de escritorio quedó pendiente
por un fallo de composición gráfica y entrada de teclado del entorno; la suite
automatizada sí pasó. No confundir ese límite con un recorrido nativo completado.
Las instrucciones de pausa general que siguen describen el punto histórico del
6 de noviembre, anterior a la autorización de retomar estas pruebas.

## Pausa anterior por cuota — punto histórico

El usuario pidió detener todo el trabajo en un punto estratégico porque la cuota
está cerca de agotarse. El objetivo completo queda en pausa hasta que indique
continuar. La pausa de móvil indicada abajo sigue vigente por separado.

Punto de continuación: el código y las pruebas de medios web están guardados.
Se preparó la revisión real de escritorio con un perfil temporal y el arranque
del cliente confirmó conexión y menús accesibles. La revisión de adjuntos y
aprobaciones en escritorio todavía no se ejecutó. La demo ahora crea una cuenta
`ForumModerator` y fija explícitamente los demás usuarios en nivel ordinario,
porque el registro inicial les otorgaba privilegios de desarrollador y habría
invalidado la prueba de aprobación. También se desactiva la caché de sus archivos
estáticos para revisar el código actual.

Para retomar escritorio: iniciar la demo con
`PLAYAURAL_FORUM_MEDIA_APPROVAL=1`, iniciar el arnés externo
`forum-validation/run-desktop-demo.py` y probar carga → envío a revisión →
aprobación desde ForumModerator → publicación explícita por el autor. El arnés
usa un perfil temporal, no guarda contraseñas en el llavero y registra las
solicitudes de voz sin interrumpir el lector del usuario. La próxima revisión
debe confirmar que conserva el borrador y el foco; después abrir imagen/video.

Se cerraron los procesos locales de prueba al hacer esta pausa. No iniciar
validaciones, demos, compilaciones ni trabajo móvil hasta recibir la instrucción
de continuar; móvil requiere además que el usuario indique retomarlo.

## Indicación vigente del usuario

«Puedes dejar móvil por ahora, pero guarda el estado actual».

El trabajo móvil queda en pausa. No continuar sus cambios, reparar sus
dependencias, compilar Android ni iniciar el emulador hasta que el usuario
indique retomarlo. El código actual se conserva; esta pausa no descarta el
trabajo de móvil ni cambia el alcance pendiente del foro.

## Ubicación del código

- Worktree: `C:\Users\leija\Documents\Codex\2026-10-31\re\outputs\PlayAural-forum`.
- Rama: `feature/forum-foundation`.
- Commit base: `4f0c22637a193d1be5a6548baaa03bb3187fe188`.
- La segunda entrega está en cambios locales, incluidos archivos nuevos.
  Todavía no se ha integrado, publicado ni marcado como terminada.
- La copia de seguridad del punto actual se guarda en
  `C:\Users\leija\Documents\Codex\2026-10-31\re\work\forum-validation\checkpoints`.
  Incluye archivos modificados/nuevos, parche Git, estado y manifiesto con
  comprobaciones SHA-256. Para reconstruirla se necesita el commit base.

## Funciones implementadas

Adjuntos privados por HTTP autenticado, visor de imágenes, reproductores de
audio/video, subtítulos de texto incluidos en el video, descarga explícita,
encuestas, conversaciones privadas con invitación, gestión de participantes,
aprobación opcional de archivos, vencimiento de cargas y respaldos con los
archivos publicados. El contenido aparece antes de las acciones y el contexto
se anuncia al entrar sin añadir filas de ayuda repetidas.

Las conversaciones privadas guardadas aparecen en la colección personal solo
mientras se conserva la membresía. Los respaldos completos siguen siendo
obligatorios si se desactiva el servicio HTTP y existen archivos publicados.

## Evidencia reciente

- Audio web: carga real, preparación, vista previa, inicio explícito, velocidad,
  descarga, publicación y apertura del archivo publicado. Abre pausado y restaura
  el foco al cerrar.
- Imagen web: carga, descripción accesible, zoom con desplazamiento, publicación
  y apertura del archivo publicado. La imagen de prueba es de 800 por 600 píxeles.
- Video web: carga, apertura pausada, reproducción por teclado, subtítulos
  visibles, entrada en pantalla completa, publicación y reapertura. Se amplía al
  espacio del visor para que los archivos pequeños no oculten los controles.
- Capturas fuera del repositorio: `web-audio-player.png`,
  `web-audio-published.png`, `web-image-viewer.png`, `web-video-captions.png`,
  `web-video-fullscreen.png` y `web-visual-published.png`, en la carpeta de
  validación indicada arriba.
- Última suite web completa: 86 pruebas aprobadas antes de los últimos cambios
  de pantalla completa. Las 11 pruebas de medios web aprobaron después de añadir
  la protección de Escape para pantalla completa; falta repetir la suite completa
  con el código final.
- Escritorio: 324 pruebas aprobadas y un arnés nativo verificó MP3/MP4, pausa
  inicial, reproducción explícita, velocidad y búsqueda. Falta el recorrido
  completo del cliente de escritorio con los adjuntos del foro.
- Servidor: pruebas dirigidas de privacidad, aprobación, credenciales, HTTP,
  migración, mantenimiento y respaldos aprobadas. La suite completa de esta
  entrega se canceló cuando el usuario reportó lentitud; sigue pendiente.

## Punto exacto de móvil, en pausa

Los módulos nuevos están en `mobile_client/src/forum/` y la integración en
`src/app/PlayAuralApp.tsx`. Los últimos cambios separan la cancelación de un
reproductor de las cargas del borrador, comprueban autorización antes de montar
el reproductor y usan el desplazamiento de foco compartido. La selección por
gestos utiliza identificadores estables y avanza antes del siguiente render.
Hay manejo de salida de pantalla completa antes de cerrar el reproductor.

Se aprobaron 72 pruebas dirigidas de navegación/transporte/reproductor antes
de los últimos ajustes de foco. Las 15 pruebas del reproductor aprobaron después
de esos ajustes. La comprobación de tipos de los módulos de medios aprobó con
una superposición de dependencias de solo lectura; no equivale a una instalación
móvil reparada ni a la comprobación completa de la aplicación.

La instalación de dependencias quedó repartida entre estas dos carpetas al
cancelar un traslado anterior:

- `mobile_client/node_modules`, en este worktree de C:.
- `D:\pa-forum-01a1afb7\node_modules`.

Ambas son directorios físicos. No eliminar ni reemplazar ninguno suponiendo que
es un enlace. El código fuente no se trasladó. El directorio Android permanece
en el worktree. Las dependencias del checkout original no se modificaron.

La comprobación normal de tipos falla por dependencias faltantes en C:, entre
ellas los tipos de React y el deslizador, presentes en D:. El arnés externo
`forum-validation/typecheck-media.cjs` pudo leer ambas ubicaciones sin mover
archivos y detectó un valor inicial incompleto en el evento de tiempo de video;
ese problema de código quedó corregido. Falta reparar la instalación al retomar.

No se produjo un APK. El intento anterior también encontró límites de longitud
de rutas de Windows. Sigue pendiente la validación real de Android, el manejo
de errores de audio del SDK y sus controles/subtítulos/pantalla completa con
autovoz y lector del sistema. No hay una compilación ni un emulador activo.

## Pendientes del resto del foro

- Completar la revisión de escritorio y de la aprobación/privados en interfaz.
- Revisar el orden de Escape al salir de pantalla completa en navegador: el
  navegador integrado cerró también el diálogo durante la prueba anterior a la
  protección añadida; la protección tiene pruebas unitarias, pero su recorrido
  final aún necesita verificación real.
- Ejecutar las comprobaciones completas requeridas antes de integrar cambios.
- Construir e inspeccionar el paquete del servidor, y verificar la recuperación
  operativa de respaldos. S3/B2 no se ha configurado ni probado con una cuenta real.

El servidor de demostración local está detenido. Ninguna cuenta o base de datos
de producción fue usada. Consultar también `forum-enhancements.md` y
`forum-deployment.md` para detalles técnicos y de operación.
