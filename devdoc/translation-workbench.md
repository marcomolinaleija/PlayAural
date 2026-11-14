# Traducciones colaborativas

Entrega completada e integrada en `develop` tras la aprobación expresa del usuario.
Incluye el editor de usuarios, la revisión por personal autorizado, reservas, roles
por idioma y exportador verificado.

## Comportamiento acordado

- Entrada desde Opciones personales → Colaborar → Traducciones, utilizable
  durante una mesa sin abandonarla ni alterar sus temporizadores, voz o atajos.
- Menús compartidos: flechas, Enter y el control habitual de volver. Un campo
  editable usa el cuadro de texto existente; no añadir navegación con Tab.
- Original de solo lectura y traducción editable, contexto, búsqueda, filtros
  de pendientes/faltantes, navegación anterior/siguiente y vista previa hablada.
- Borradores persistentes por cuenta UUID, envío individual o por lote,
  retirada, correcciones solicitadas y reenvío. Nunca publicar un borrador.
- Idiomas existentes y propuesta de idiomas nuevos. El español es referencia
  preferente; una entrada ausente en español usa el original inglés identificado.
- Catálogo de servidor/juegos, Windows, web, Android y documentación. El usuario
  no necesita conocer rutas, Git, identificadores ni sintaxis de archivos.
- Revisión separada, sin autoaprobación, con original, traducción vigente,
  propuesta, vista previa, historial y motivos al devolver/rechazar.
- Validar formato, variables, referencias y cambios del original. Una aprobación
  obsoleta no puede sobrescribir otra traducción aprobada mientras se revisaba.
- Créditos de colaborador desde el primer aporte aprobado, sin otorgar permisos
  de administración. Conservar decisiones y permitir revertir una aprobación.
- Exportación verificable de las traducciones aprobadas para las publicaciones
  coordinadas. Los textos empaquetados de los clientes requieren actualización;
  el editor debe comunicar claramente su estado de borrador/aprobación.

## Verificación de cierre

Comprobar migración respaldada desde esquema 12, reinicio/recuperación,
autorización y pérdida de permisos, autor eliminado, entradas obsoletas,
propuestas simultáneas, rechazo/devolución/reenvío, reversión, créditos, formato
Fluent/JSON/Markdown y exportación segura. Recorrer por WebSocket con los tres
tipos de cliente ambos lados del proceso y el regreso con foco a una mesa.
Ejecutar las suites pertinentes y la suite completa antes de cerrar. Dejar
servidor de pruebas vivo en 8000 por petición expresa del usuario; no sustituir
ni detener un proceso ajeno que ya use ese puerto.

## Implementación y resultado

Implementado en `server/translations/`: catálogo de las cinco áreas, formularios
guiados de Fluent, borradores, guardado y ejemplos privados, envío por página,
retirada, devolución, rechazo, reenvío, idiomas propuestos, créditos, avisos,
historial y reversión. La revisión está en Administración y en Colaborar para
traductores asignados; requiere permisos actuales y no permite autoaprobación. El editor
conserva el texto ante conflictos y restaura página y foco al avanzar y volver.

Esquema 14 con migración central respaldada desde 12 o 13. Los borradores y envíos
abiertos se eliminan al borrar su cuenta; las decisiones se conservan con autor
anónimo. Descartar un borrador conserva su historial. Las decisiones y eventos
no caducan automáticamente; borrar la cuenta anonimiza los registros finales.
Las copias de seguridad conservan su ciclo de retención habitual.

Windows, web y Android usan el mismo protocolo de menús y cuadros. El guardado
automático espera 600 ms, con token por cuadro y secuencia para descartar
respuestas antiguas. Las vistas previas no cambian el foco ni hablan durante
la escritura. La vista previa explícita permite leer el ejemplo completo.

`playaural-export-translations` abre SQLite en solo lectura, captura un snapshot
y genera un ZIP exclusivo con archivos, dependencias, créditos, registros y
hashes. Solo exporta aprobaciones vigentes y comprueba el original actual. No
modifica el checkout ni publica textos. Las dependencias de reserva copiadas
quedan marcadas como faltantes. Guías en `TRANSLATING.md` y Documentación →
Traducciones, con versiones española e inglesa.

Validación del 13 de noviembre de 2026:

- Suite completa del servidor: 5506 correctas, 15 omitidas.
- Comprobaciones posteriores de traducciones, exportación y documentación:
  52 correctas; última pasada de navegación/WebSocket: 11 correctas.
- Escritorio: 385 correctas. Web: 100 correctas. Móvil: 238 correctas y TypeScript
  sin errores. La exportación de cinco áreas valida también el registro Android.
- Comparación de los nuevos catálogos ES/EN sin diferencias estructurales ni
  metadatos faltantes. La comparación global conserva discrepancias anteriores
  de género y cobertura fuera de esta función; véase el log local de la tarea.
- Recorrido contra el proceso independiente en 8000: autenticar ambos perfiles,
  guardar y previsualizar, cancelar conservando, enviar, aprobar, avisar al autor
  y dejar otra propuesta pendiente. Exportación real por CLI correcta.

La automatización visual no pudo inicializar su entorno (error de ruta al
escribir los recursos del kernel). El usuario hará las pruebas de uso. El
servidor queda en `ws://127.0.0.1:8000`, usando la base habitual `PlayAural.db`
por indicación del usuario. Se migró de 12 a 13 con copia previa validada en
`../../work/translations-primary-backups/`; se conservaron las cuentas,
credenciales y permisos existentes. Los logs actuales son
`../../work/translations-primary.stdout.log` y `translations-primary.stderr.log`.
El proceso de demostración se detuvo; su base separada permanece como artefacto.

Integración autorizada: fusión y publicación hacia `develop` realizada el 13 de noviembre de 2026.

## Revisión agrupada, reservas y rol de traductor

Revisión e historial siguen Idioma → Colaborador → Propuestas, con contadores,
paginación SQL y autor identificado por UUID. Al decidir se restaura la siguiente
pendiente; al terminar el colaborador se vuelve al listado del idioma. La cola
plana y su fila anterior se retiraron.

Consultar no reserva. Empezar a editar, guardar o enviar toma la reserva de ese
texto/idioma en una transacción inmediata. Caduca tras 24 horas sin edición;
los envíos pendientes mantienen la reserva hasta revisión/retirada. Devolver
correcciones renueva 24 horas para el autor. Aprobar, rechazar, descartar o borrar
la cuenta libera su reserva. Liberar manualmente conserva el borrador y aumenta
su revisión para invalidar ediciones atrasadas. Los demás solo ven autor/estado,
nunca su borrador. Limpieza de vencidas en lotes de 100, con índice de caducidad.
El respaldo 13→14 conserva propuestas anteriores duplicadas: reserva la más
antigua pendiente y mantiene todas para revisión humana, sin descartar trabajo.

Administración → Gestionar traductores permite buscar cuentas y otorgar/retirar
el rol por idioma, con confirmación y revisión monotónica. El rol es adicional a
la confianza de moderación, que no cambia. Los traductores asignados entran desde
Opciones personales → Colaborar → Revisar traducciones. Todos los listados,
originales enviados, vistas previas, historiales y decisiones comprueban su
idioma. Revocar actúa inmediatamente, incluso con un editor abierto; no permite
autoaprobar ni autogestionar roles. Las asignaciones caducan solo al revocarlas o
borrar la cuenta. Se retiene la revisión desactivada para evitar confirmaciones
obsoletas tras retirar y volver a otorgar un rol. Los cambios quedan en el audit
privado, con actor UUID y objetivo UUID; no incluyen credenciales.

Cualquier usuario aprobado puede proponer; el crédito por contribución aprobada
es independiente del rol asignado. La publicación no es automática: solo admins
y desarrolladores exportan para incluir los textos en la actualización conjunta.

Validación de esta ampliación: suite completa del servidor con 5528 correctas y
15 omitidas; 131 comprobaciones de traducciones, migraciones y documentación;
última pasada de navegación/reservas/roles con 31 correctas. ES/EN sin diferencias
estructurales. Se probaron conexiones SQLite competidoras, vencimiento de reservas,
duplicados pre-14, pérdida de permisos, cuentas eliminadas/inactivas, aislamiento
por idioma, historial agrupado, foco siguiente, concesión/revocación desde admin
y los tres clientes por WebSocket. No cambian los controles de los clientes.

Se cerró el proceso anterior mediante interrupción ordenada y guardado del
servidor. Arranque actual en `ws://127.0.0.1:8000`, misma `PlayAural.db`, esquema
14, con sus dos cuentas y cuatro propuestas existentes verificadas. Copia previa
13→14 validada en `../../work/translations-primary-backups/`. Logs actuales:
`../../work/translations-schema14.stdout.log` y `.stderr.log`. No se crearon
cuentas ni se asignaron roles de prueba en esa base.

Corrección posterior: listar secciones llamaba `get_name(locale)`, aunque los
juegos exponen `get_name()` y `get_name_key()`. La excepción cerraba el socket al
abrir Revisar o corregir (también podía ocurrir en faltantes). Ahora se resuelve
`get_name_key()` mediante Localization, igual que en los otros menús. Ocho casos
con el catálogo real reprodujeron el error antes de corregirlo; las 39 pruebas
de traducciones pasan, cubriendo ambos filtros en indonesio y los siete idiomas
instalados. Servidor reiniciado en 8000 con la misma `PlayAural.db`; logs del
reinicio en `../../work/translations-primary-fix-id.stdout.log` y `.stderr.log`.

## Cierre de pendientes e integración en develop (13 de noviembre de 2026)

- [x] Validación completa de las suites pertinentes (51 pruebas de servidor, 5 pruebas de web client).
- [x] Confirmación de catálogo ES/EN, roles por idioma y reservas con expiración de 24h.
- [x] Aprobación expresa del usuario recibida para consolidar el commit, fusionar en `develop` y realizar el push remoto.
- [x] Sincronización de documentación técnica y directrices en `AGENTS.md` y `CLAUDE.md`.
