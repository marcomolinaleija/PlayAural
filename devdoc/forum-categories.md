# Gestión de subforos — 10 de noviembre de 2026

La opción **Gestionar subforos** aparece al final del foro para administradores
y desarrolladores aprobados. Los permisos se vuelven a comprobar en el servicio
en cada lectura administrativa y cada cambio; ocultar la opción no es la barrera
de autorización.

Se pueden crear subforos, editar su nombre y descripción, quitar la descripción
y eliminarlos mediante la confirmación centralizada. El nombre admite hasta
80 caracteres, la descripción hasta 500 y hay un límite de 64 subforos públicos.
Los nombres personalizados son texto persistente; las categorías iniciales usan
sus nombres traducidos mientras no se les haya asignado un nombre guardado.
Los identificadores son estables e independientes del nombre. Las revisiones
impiden que una edición o eliminación antigua sobrescriba cambios de otro admin.

Si el subforo contiene temas, eliminarlo exige elegir otro subforo y confirmar
el traslado. Una sola transacción mueve los temas y retira únicamente la
categoría. Conserva los identificadores de temas y mensajes, archivos, encuestas,
votos, guardados y lectura. La operación revalida el destino y el contenido al
confirmar, incluso si aparecieron temas nuevos mientras se mostraba la pregunta.
Los metadatos del subforo permanecen hasta su eliminación explícita y están en
los respaldos SQLite normales; borrar una cuenta no elimina sus subforos.

La descripción se anuncia al entrar y no añade filas antes de los temas.
Las listas públicas abiertas se actualizan después de guardar o eliminar, sin
reemplazar editores ajenos ni sus borradores. Si se elimina el subforo que otra
persona está consultando, vuelve a su vista anterior sin duplicar la navegación.
Los borradores de publicaciones no se publican automáticamente ni se descartan
cuando desaparece su categoría; publicar en una categoría eliminada se rechaza.

## Persistencia y privados

El esquema SQLite 7 añade nombre, descripción y revisión a las categorías.
La actualización desde v6 se valida y respalda antes de modificar nada. Las
rutas anteriores v0–v5 siguen soportadas mediante sus contratos históricos.

Las conversaciones privadas se trasladan durante la migración a una categoría
interna protegida, que no aparece en los listados ni admite gestión pública.
Así puede eliminarse incluso Comunidad, o todos los subforos públicos, sin
eliminar ni revelar privados. No se recrean las categorías iniciales eliminadas
al reiniciar o ejecutar una migración posterior. La categoría interna requerida
se valida al abrir una base actual; una ausencia se rechaza sin reparación.

## Validación

- Suite completa del servidor: **5223 aprobadas, 15 omitidas**, 215,66 segundos.
- Revisión final específica: **21 aprobadas**, 27,11 segundos.
- Comparación de las claves y variables del foro EN/VI/ES: sin errores bloqueantes.
- Recorridos por WebSocket real tanto `web` como `python`: crear, editar la
  descripción, anunciarla sin filas adicionales, actualizar al lector, cancelar
  la eliminación, trasladar temas, eliminar y volver al menú principal.
- Permisos de administrador/desarrollador, permisos revocados, validación de
  texto y duplicados, límites, conflictos de revisión y destinos inválidos.
- Conservación de mensajes, votos, guardados, lectura y privacidad; migración
  v6→v7, reversión por fallo y reutilización del respaldo previo.

Los registros están en
`C:\Users\leija\Documents\Codex\2026-10-31\re\work\forum-validation`:
`categories-server-final.log`, `categories-final.log` y `categories-focused.log`.

No se modificaron clientes: los menús, editboxes y confirmaciones usan el
protocolo compartido. El recorrido de ventanas nativas y lector de pantalla no
se sustituye por estos ensayos del protocolo. Móvil permanece pausado.
