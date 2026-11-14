# Sincronización del foro con develop — 10 de noviembre de 2026

Se incorporó `origin/develop` en `feature/forum-foundation`, dentro del worktree
`PlayAural-forum`, por autorización del usuario. El destino de esta integración
es exclusivamente la rama del foro. El worktree `PlayAural` y su rama local
`develop` conservan el estado registrado antes de comenzar.

## Referencias y recuperación

- Develop incorporado: `8eef1c42ff2fe9c74206ca446ff67e2f5394abae`.
- Avance móvil guardado sin declararlo terminado: `15b5611f`.
- Adjuntos, encuestas, privados y cierre anterior guardados: `d47684d2`.
- Rama de recuperación anterior al merge: `backup/forum-before-develop-20261110`.

Los dos commits de guardado convierten los cambios locales anteriores en
historial recuperable. El merge conserva los commits originales de ambos lados.
La copia ZIP anterior continúa disponible; el cierre de esta sincronización
añade un bundle Git de la rama, verificable con `git bundle verify` y recuperable
sobre un repositorio que contenga el historial de `origin/develop` indicado arriba.

## Resolución de compatibilidad

Ambas ramas habían utilizado el esquema SQLite 4 para contratos diferentes:
develop para monederos y el foro para discusiones públicas. El foro usó después
el esquema 5 para privados, encuestas y adjuntos. El contrato combinado ahora
es la versión 6.

Antes de cualquier respaldo o modificación, la actualización distingue el
contrato histórico por versión y tablas, y valida sus tablas, columnas,
restricciones, índices y disparadores. Una base incompleta o alterada se rechaza;
no se reconstruye. La migración conserva el respaldo previo validado y aplica
los cambios en una transacción. Un fallo revierte la creación del monedero y
permite reintentar usando el mismo respaldo verificado.

Se conservaron las dependencias de voz de develop junto con las de archivos del
foro, regenerando el lock. El service worker conserva la revalidación de develop,
excluye los adjuntos privados de la caché y usa una nueva revisión de caché.
El conflicto móvil se limitó a conservar la limpieza de medios del foro también
al recibir la nueva orden de cambio de servidor.

## Validación

Los registros están en
`C:\Users\leija\Documents\Codex\2026-10-31\re\work\forum-validation\develop-sync`.

- Migración y mantenimiento: 72 pruebas aprobadas.
- Escritorio completo: 333 aprobadas.
- Web completo: 89 aprobadas.
- Flujos sociales afectados: 191 aprobadas.
- Servidor completo final: 5201 aprobadas, 15 omitidas; 187,51 segundos,
  dos procesos. Registro: `server-final.log`.
- Tres ensayos adicionales con código extraído de los commits históricos reales:
  develop con monederos (19 tablas), foro público v4 (24 tablas) y foro privado
  v5 (32 tablas). Todas las filas preexistentes se conservaron sin cambios al
  migrar a v6; cada actualización produjo un respaldo previo.
- Wheel construido, CRC e inclusión de los 29 recursos requeridos comprobados;
  CLI ejecutado desde el paquete extraído y aislado de la fuente. También se
  comprobó que el paquete contiene el esquema 6.

El wheel sincronizado está en `develop-sync/dist/`, tiene 5923277 bytes y SHA-256
`7bf58db49ab6bfa3fb1a8baf76597b1c15d803aa1a0560b6998bdbc24c3f9baa`.
El lock combinado también pasó `uv lock --project server --check`.

El primer recorrido completo encontró dos expectativas antiguas: Ctrl+U abría
participantes de mesa y las invitaciones rechazaban no amigos. Ambos fallos se
reprodujeron con `origin/develop` sin modificar, aislado del foro. Las pruebas
actualizadas comprueban la lista global sin perder la mesa y la invitación a no
amigos con consentimiento explícito, sin incorporación automática. Se actualizó
la explicación de los atajos en README y las guías.

Los catálogos del foro EN/VI/ES no tienen diferencias bloqueantes. La comparación
global devuelve errores ya presentes en develop: tres catálogos de juegos que
faltan en vietnamita, claves faltantes y diferencias de variables fuera del foro.
Todos los catálogos ajenos al foro son idénticos a los de develop; estos problemas
quedan registrados sin convertir esta sincronización en una revisión de traducción.
Los avisos de espacios en blanco al comparar contra la base antigua también
proceden de archivos incorporados desde develop. El diff propio contra develop
se revisa sin esos avisos.

## Estado pendiente

Móvil continúa en pausa: no se instalaron dependencias móviles, no se ejecutaron
sus pruebas y no se inició Android ni el emulador. La revisión interactiva nativa
de adjuntos y accesibilidad sigue pendiente por la limitación gráfica registrada
en [forum-validation.md](forum-validation.md). No se realizó una nueva revisión
interactiva de los clientes tras esta sincronización.

Esta operación no publica una entrega, no sube ramas y no incorpora el foro en
develop o main. Las pruebas del cierre anterior corresponden a la base anterior;
los resultados de este documento son los aplicables a la rama sincronizada.
