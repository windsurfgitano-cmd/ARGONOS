# ARGON — sistema de diseño

Referencias: `mockup-escritorio-4k.png` (escritorio completo) y `hoja-componentes-4k.png` (piezas sueltas), generados con Higgsfield el 2026-10-15.

## Regla principal

**Superficies en verde phthalo casi negro. Lo interactivo en violeta argón.** El verde menta es para texto secundario y estados "en marcha".

## Paleta

De la hoja de componentes, y medida en los píxeles del mockup.

| Token | Color | Uso |
|---|---|---|
| Phthalo 900 | `#07160F` | Fondo del terminal y del escritorio |
| Superficie ventana | `#041A18` | Fondo de ventanas (medido `#020C0D`–`#022122`) |
| Barra de título | `#052322` | Headerbars |
| Barra lateral | `#03191C` | Sidebars |
| Phthalo 700 | `#0B2A1F` | Tarjetas, vidrio del dock |
| Phthalo 500 | `#0F3F2D` | Bordes activos |
| Phthalo 300 | `#14835C` | Botón secundario, borde del botón del orbe |
| Menta | `#CFE9DD` | Texto del terminal, bordes al 10–15 % |
| Verde estado | `#3EE0A0` | Puntos "en marcha" / "en la red" |
| Violeta 600 | `#7A5CF0` | Botón principal, interruptores encendidos |
| Violeta 500 | `#A48BFF` | Orbe, cursor, acento |
| Violeta 300 | `#C9B7FF` | Texto de acento sobre fondo oscuro |
| Selección | `#3E2F96` | Fila seleccionada (medido `#352A86`–`#42329D`) |
| Error | `#FF5D6D` | Botón destructivo |

## Componentes y cómo se implementa cada uno

| Componente | En el mockup | Implementación | Estado |
|---|---|---|---|
| Fondo | Humo verde + cinta de plasma violeta + logo | `herramientas/plasma.py --smoke 0.6 --logo marca/wordmark.png`, reproducido con Hanabi | Hecho |
| Panel superior | Vidrio verde, reloj al centro, orbe a la derecha | Blur my Shell `pipeline_argon` + orbe ARGON | Hecho |
| Números de escritorio en el panel | Círculos numerados, el activo en verde | Requiere una extensión de espacios de trabajo | Pendiente |
| Orbe y su menú | Vidrio, puntos verdes de estado, botón con borde verde | Extensión `argon@argonos` | Hecho |
| Notificaciones, menús, configuración rápida | Vidrio verde con borde menta | Capa añadida al final del CSS de Marble-argon-dark | Hecho |
| Dock | Vidrio verde oscuro, borde menta, punto violeta bajo apps abiertas | Dash2Dock Animated | Hecho |
| Anillo violeta bajo el ícono con hover | Halo violeta brillante | La extensión del dock no tiene esa opción | Pendiente |
| Ventanas | Fondo negro verdoso, borde menta fino, selección violeta | `~/.config/gtk-4.0/gtk.css` | Hecho |
| Terminal | Fondo `#07160F`, texto menta, cursor violeta, translúcido | Paleta `argon` de Ptyxis + Blur my Shell | Hecho |
| Íconos | Carpetas violeta, redondeados | Colloid-Purple-Dark | Hecho |
| Barra de comandos | Vidrio, orbe, plan en pasos | Etapa 3 | Pendiente |

## Medidas observadas (a 2560×1440)

- Panel: ~32 px de alto, ancho completo.
- Radio de ventanas: ~14 px. Radio de menús y notificaciones: ~16 px. Dock: forma de píldora.
- Bordes: 1 px de menta al 10–15 % de opacidad.
- Íconos del dock: ~56 px, el ampliado ~1,4×.
