# Disponibilidad del foro — 11 de noviembre de 2026

Administradores y desarrolladores aprobados pueden cambiar **Foro: Activado /
Desactivado** en Administración → Moderación y sanciones → Moderación del chat,
junto a los controles existentes del chat global y del chat de voz.
La autorización comprueba el rol de la sesión y el registro actual por UUID,
incluidas aprobación y ausencia de veto. No cambia los permisos de los otros
controles del chat, que mantienen sus reglas anteriores.

La configuración usa `forum_enabled`, un booleano en `server_settings`. Por
defecto está activado. Se guarda antes de cambiar el estado en memoria y se
incluye en los respaldos centrales existentes. No añade esquema ni registros
por cuenta. Un valor persistido inválido deja el acceso desactivado; si guardar
falla, se informa al operador y se mantiene el estado anterior.

La entrada Foro sigue visible. Elegirla mientras está desactivado solo envía
`forum-unavailable` al buffer del sistema: no abre un menú ni agrega un frame
a la navegación. Al reactivarse vuelve a abrir el foro normalmente.

Las acciones nuevas de las vistas ya abiertas también se rechazan. Se permite
editar el título y cuerpo de un borrador local, volver atrás, cancelar y
descartar explícitamente, pero no publicar, votar, gestionar categorías ni enviar
invitaciones privadas. Las vistas ya recibidas pueden seguir visibles mientras
la persona cancela o vuelve; no se expulsa ni borra su borrador por el cambio.

Las credenciales de medios no se emiten mientras está desactivado. Las
credenciales existentes no autorizan nuevas descargas, HEAD, sesiones HTTP,
reservas ni cargas: se devuelve 503 con `forum-unavailable`. Las transferencias
en curso comprueban la disponibilidad entre bloques. La preparación que ya
comenzó puede terminar sin reconstruir la interfaz cerrada; mantenimiento,
respaldos y caducidad normal siguen funcionando. No se elimina contenido
publicado ni se alteran membresías, votos, guardados o lectura.

## Validación

Suite completa del servidor: **5238 aprobadas, 15 omitidas**, 214,98 segundos,
con dos procesos. Registro externo: `forum-validation/forum-availability-server-final.log`.
Los catálogos del foro EN/VI/ES conservan claves y variables compatibles.

Las pruebas nuevas cubren administradores y desarrolladores, permisos
revocados, escritura fallida, configuración inválida, persistencia, aviso sin
navegación, borrador retenido y bloqueos HTTP. Los recorridos por WebSocket real
usan clientes `python` y `web`: un administrador desactiva el foro, una
publicación abierta se rechaza, otra persona solo recibe el aviso desde el menú
principal y, tras reactivar, se publica el mismo borrador sin perder su texto.

El control se carga en el servidor normal con `PlayAural.db` y puerto 8000;
no necesita una demo ni cambios en los clientes. Móvil continúa pausado.
