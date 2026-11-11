# Cierre de pruebas de esta etapa — 10 de noviembre de 2026

Se retomaron las pruebas de escritorio, web y servidor por indicación del usuario.
Móvil conserva su pausa y su código pendiente. No se inició Android ni se reparó
su instalación de dependencias.

## Resultados automatizados

| Comprobación | Resultado |
| --- | --- |
| Suite completa del servidor, dos procesos | 4914 aprobadas, 6 omitidas; 235,54 segundos |
| Suite completa de escritorio | 324 aprobadas; 21,74 segundos |
| Suite completa web | 88 aprobadas |
| Comparación de idiomas EN/VI/ES | Sin diferencias bloqueantes; advertencias plurales anteriores fuera del foro |
| Construcción del wheel del servidor | Aprobada |
| Inspección del wheel | 29 archivos requeridos del foro, traducciones y manuales presentes; CRC correcto |
| Ayuda del CLI desde el paquete extraído y aislado del código fuente | Aprobada, incluidas las opciones HTTP de adjuntos |
| Restauración de respaldo en destinos nuevos | Aprobada, con lectura HTTP real del archivo recuperado |

El archivo del servidor es
`playaural_server-1.0.5.3+marco.1-py3-none-any.whl`, de 5700467 bytes.
SHA-256: `e583164182a03c36ef54e333829c5008799a29366cfd2bf9de2ea1faffdb3e91`.

Los registros y artefactos están fuera del repositorio, en
`C:\Users\leija\Documents\Codex\2026-10-31\re\work\forum-validation`:
`server-final.log`, `desktop-final.log`, `web-final.log`, `locale-final.log`,
`restore-final.log`, `wheel-final.log` y `dist-final/`.

## Recorridos reales en navegador

Se utilizaron cuentas y datos desechables del servidor de demostración local,
con la aprobación de adjuntos habilitada.

### Archivo sometido a revisión

1. Un autor ordinario preparó título, mensaje y una imagen.
2. Antes de elegir Publicar, la imagen indicaba que requería revisión y la cola
   del moderador estaba vacía.
3. Publicar envió el archivo a revisión y conservó el mensaje como borrador.
   El foco permaneció en Publicar.
4. Otra cuenta abrió y visualizó la imagen, y confirmó su aprobación.
5. El autor recibió el estado listo para publicar, conservando texto y foco.
   La aprobación no publicó el mensaje.
6. El autor eligió Publicar otra vez. El mensaje mostró texto, adjunto y después
   acciones. La imagen abrió desde el mensaje y el foco regresó al adjunto al
   cerrar el visor.

Evidencia: `approval-final-published.png`.

### Conversación privada con encuesta

1. Se preparó un borrador dirigido a otra cuenta, con título, mensaje y encuesta.
2. La otra cuenta no recibió una invitación mientras existía solo el borrador.
3. Publicar envió la invitación. Antes de aceptarla, la otra cuenta solo pudo
   aceptar, rechazar o volver atrás; no vio el mensaje ni la encuesta. Esto se
   comprobó incluso usando la cuenta administradora como destinataria.
4. Aceptar habilitó los mensajes y la encuesta. La cuenta destinataria no recibió
   los controles de edición del autor.
5. Seleccionar una respuesta la marcó como pendiente. Enviar voto confirmó el
   voto y mostró un voto en la primera opción, cero en la segunda y una persona
   participante.

Evidencia: `private-poll-final.png`. La privacidad, retirada de miembros,
aprobación privada y revocación de archivos también tienen cobertura en las
pruebas del servidor.

La revisión anterior verificó audio, imagen y video con subtítulos, reproducción
explícita, zoom, descarga y apertura tras publicar. Sus capturas se conservan en
la misma carpeta de validación.

## Restauración comprobada

Se creó una conversación privada con dos miembros, encuesta votada, archivo,
guardado y posición de lectura. El respaldo completo se verificó, se restauró en
una base y un directorio de objetos vacíos y se abrió con el servidor actual.

Se conservaron membresía, voto, guardado, lectura y checksum del archivo. El HTTP
del servidor restaurado entregó exactamente los bytes esperados al miembro
(200) y rechazó a una cuenta ajena (404). El ensayo usó almacenamiento local;
S3/B2 sigue sin una validación con credenciales reales.

## Límite de la revisión de escritorio

El cliente real arrancó con perfil temporal, autenticó la cuenta de prueba y
expuso sus menús por accesibilidad. La captura nativa falló con el error de
composición de escritorio deshabilitada, y las teclas no llegaron al control.
Por ello no se declara completado el recorrido interactivo de adjuntos y
aprobación en escritorio. Se solicitó confirmar una sesión gráfica activa.

La suite de escritorio sí pasó completa. El arnés nativo anterior verificó
MP3/MP4, pausa inicial, reproducción, búsqueda y velocidad, pero no sustituye
el recorrido interactivo pendiente ni una revisión manual con lector de pantalla.
También permanece pendiente confirmar Escape desde pantalla completa en un
navegador normal; su protección tiene pruebas automatizadas.

## Ajustes de la preparación de pruebas

La demo conserva a ForumModerator como desarrollador inicial y crea autores
ordinarios. Así respeta la protección del último desarrollador y permite probar
la aprobación sin que el autor tenga privilegios de moderación. Sus archivos
estáticos se sirven sin caché para revisar la fuente actual.

La primera pasada web encontró que faltaba stb-vorbis en las dependencias
compartidas. Se retiró únicamente el enlace del worktree y se instaló allí el
package-lock web, con scripts deshabilitados. El checkout original no se modificó.
La instalación móvil de C:/D: permanece intacta.

El código sigue en `feature/forum-foundation`, con cambios locales. Esta revisión
no integra ramas, publica un despliegue ni convierte la entrega móvil en terminada.
Las demos de esta sesión se cerraron y se guarda una nueva copia del estado.
