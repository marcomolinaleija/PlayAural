# Normas de la comunidad desde el foro

La portada conserva Conversaciones privadas y Actividad reciente como primeras
entradas, seguidas de Normas de la comunidad y los subforos. Las normas están
disponibles aunque una comunidad no tenga subforos. No dependen de una categoría,
un autor o un tema fijado en SQLite.

La entrada abre `community_rules` mediante el visor compartido de Documentación.
Tanto su etiqueta como el contenido siguen el idioma de la comunidad del foro,
independientemente del idioma de la interfaz. El visor conserva `doc_locale` al
restaurar navegación; Atrás/Escape devuelve el foco a la entrada de normas en
esa misma comunidad. Los documentos abiertos normalmente desde Documentación
siguen usando el idioma de la interfaz.

Se conserva una fuente por idioma en
`server/documentation/content/<idioma>/community_rules.md`, compartida con
Documentación. La lectura no crea temas, mensajes, votos, avisos ni registros
de aceptación. La apertura respeta los controles existentes de disponibilidad
del foro y acceso de la cuenta. No se cambia el esquema ni el protocolo.

Las siete versiones incluyen los mismos diez apartados, pruebas y reportes
falsificados, las medidas por incumplimiento y el aviso sobre el historial del
chat. No se incorpora una obligación de describir imágenes. Las traducciones
añadidas en esta entrega son asistidas por IA y no tienen revisión nativa
registrada.

`test_forum_rules.py` comprueba los siete idiomas, la independencia respecto a
la interfaz, restauración, foco al volver, comunidades sin subforos, controles
de acceso y lectura mediante WebSocket real con identificadores de cliente
Windows, web y móvil. Esto verifica el protocolo compartido; no constituye una
revisión gráfica o con dispositivos Android.
