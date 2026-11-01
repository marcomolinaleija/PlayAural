# Trabajo en el fork con Git Flow

Este fork utiliza Git Flow. Los colaboradores con permiso de escritura pueden
subir y fusionar sus ramas directamente; no se exige abrir un pull request.
Las comprobaciones de compatibilidad deben pasar antes de integrar cambios.

## Ramas

| Rama | Uso | Se crea desde | Se integra en |
| --- | --- | --- | --- |
| `main` | Entregas aprobadas para producción | — | — |
| `develop` | Integración y siguiente entrega | `main` inicialmente | `release/*` |
| `feature/*` | Funciones y mejoras | `develop` | `develop` |
| `release/*` | Preparación y correcciones de una entrega | `develop` | `main` y `develop` |
| `hotfix/*` | Corrección urgente de producción | `main` | `main` y `develop` |

La rama predeterminada del repositorio sigue siendo `main`. Después de clonar,
cambiar a `develop` antes de empezar una función. No se necesita instalar una
extensión de Git Flow; los comandos normales de Git son suficientes.

## Empezar una función

Ejemplo para la edición mexicana de Monopoly:

```sh
git clone https://github.com/marcomolinaleija/PlayAural.git
cd PlayAural
git switch --track origin/develop
git pull --ff-only
git switch -c feature/monopoly-mexico
# Implementar y probar. Añadir explícitamente los archivos de la función.
git add RUTA_DEL_ARCHIVO
git commit -m "Add Mexican Monopoly edition"
git push -u origin feature/monopoly-mexico
```

El nombre es un ejemplo; la rama de Monopoly la crea quien implemente la
función. Leer `AGENTS.md` y `CLAUDE.md` para las reglas técnicas, de
accesibilidad, traducción y persistencia del proyecto.

Para integrar una función terminada, comprobar primero el CI de su commit.
Después:

```sh
git switch develop
git pull --ff-only
git merge --no-ff feature/monopoly-mexico
# Resolver cualquier conflicto y volver a ejecutar las pruebas afectadas.
git push origin develop
```

Si `develop` avanzó durante el trabajo, incorporarlo a la rama de función y
validar el resultado antes de integrarla. No sobrescribir trabajo concurrente.
Una función integrada en `develop` no se publica automáticamente.

## Preparar una entrega

Crear `release/<nombre-o-version>` desde `develop`. Durante su preparación,
limitarla a correcciones y tareas necesarias para la entrega. Con el CI correcto,
fusionar esa rama en `main` y también en `develop`, usando `--no-ff` para
conservar el punto de integración. Hacer `pull --ff-only` antes de cada fusión
y subir cada rama al terminar.

`main` representa fuentes aprobadas; la versión realmente activa se comprueba
en el `current.env` del VPS. El siguiente chequeo diario del coordinador
prepara la publicación del commit aprobado: CI, Windows, Android, firma,
artefactos, respaldo y promoción cuando no haya personas en mesas. Para pedir
una comprobación antes de la siguiente ejecución diaria, el operador puede
ejecutar `systemctl --user start playaural-update.service` en el VPS.

Una etiqueta `v<version>` identifica una entrega cuando se haya elegido su
versión y comprobado su publicación. No modificar marcadores de protocolo o
del paquete de sonidos solo por crear una rama; aplicar las reglas de
compatibilidad y versionado existentes.

## Corrección urgente

Crear `hotfix/<descripcion>` desde el `main` actualizado. Tras probarla,
fusionarla en `main` y en `develop`; si hay una entrega en preparación,
incorporar también la corrección a esa rama. Publicar sigue sujeto a las mismas
comprobaciones y copias de seguridad.

## Novedades del proyecto original

El coordinador utiliza `feature/upstream-*` para integrar el original y los
cambios aprobados de `main` sobre la base de `develop`. Conserva los tres
historiales y exige CI antes de avanzar `develop`. No abre un PR para exigir
una aprobación adicional ni fusiona esas novedades en `main`.

La integración termina en `develop`: no genera APK, ZIP ni reinicia el juego.
Las novedades pasan a producción cuando una persona las incluye en una entrega
y la fusiona en `main`.

La publicación de `main` usa su commit exacto, sin añadir novedades pendientes
del original ni cambios de `develop`. Si una compilación necesita correcciones,
el coordinador conserva producción y difiere la entrega. Resolverlas en
`develop` o en un `hotfix/*` e integrar un nuevo commit en `main`; la siguiente
comprobación diaria reconoce esa corrección y prepara un trabajo nuevo.

Los cambios del controlador de publicación y sus workflows son herramientas
de confianza. Su instalación en el VPS es una operación explícita del operador;
el agente que integra el original no puede modificarlos para eludir controles.

## Comprobaciones y limpieza

El CI se ejecuta al subir `main`, `develop`, `feature/*`, `release/*`,
`hotfix/*` y las ramas antiguas `automation/*`. Comprueba servidor, web,
escritorio y fuentes Android. Los PR opcionales también ejecutan CI.

Eliminar las ramas temporales solo cuando estén completamente incorporadas en
su destino; las de entrega y corrección urgente deben estar en `main` y
`develop`. Conservar siempre ambas ramas permanentes. Actualizar referencias
locales con `git fetch origin --prune`. No reescribir el historial compartido.
