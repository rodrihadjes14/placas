# placas

Montaje y publicación de las piezas de redes de Estudio Canaro. Las tareas de contenidos escriben cada pieza en la planilla `copy-social-media`; el Apps Script de la planilla (proyecto CargadorTemas) dispara los workflows de este repositorio cuando la pieza se aprueba.

Actualizado el 26/11/2026.

## En uso

| Pieza | Workflow | Código | Lo dispara |
| --- | --- | --- | --- |
| Reel B-roll (caso real) | `componer-broll.yml` | `video/broll.py`, con `video/titulo.html` (gancho y placas) y funciones de `video/componer.py` | `TikTokBroll.gs`, cuando la fila queda aprobada |
| Reel grabado (informativo) | `componer-grabado.yml` | `video/grabado.py`, `video/grabado.html`, `video/tapa.py`, `video/tapa.html`, `video/drive.py` | `ReelGrabado.gs`, cuando la grabación está en la carpeta de Drive |
| Publicación en Instagram y Facebook | `publicar-pieza.yml` | `publicacion/publicar.py` | `Publicador.gs`, a la hora de PROGRAMADA |
| Historias | `publicar-historia.yml` | `historia/generar.py`, `historia/plantilla.html`, `historia/publicar.py` | `Historias.gs`, a la hora de PROGRAMADA |
| Anuncios grabados a pantalla completa | `componer-completa.yml` | `video/completa.py` (usa `grabado.py` y `componer.py`) | A mano; no es parte del flujo diario |

Las placas de los Carruseles las arma el Apps Script (`ExportadorCarruseles.gs`) y las sube a las carpetas `T<número>/` de este repositorio.

## Carpetas

- `video/`: montaje de los Reels. `sfx/` son los efectos de sonido, `fuentes/` las tipografías y `sujetos/` las imágenes del abogado para la tapa.
- `publicacion/` y `historia/`: publicación por la API de Meta.
- `publicaciones/` e `historias/`: el estado que deja cada publicación. No se editan a mano.
- `T<número>/`: placas de Carruseles ya exportadas.
- `animado/`: plantillas de HyperFrames. De acá el flujo usa `texto.html` y `billetes.html` (desde `video/componer.py`); el resto está en la lista de abajo.
- `docs/`: páginas públicas que pide TikTok (términos y privacidad).

## Sin uso en el flujo actual

Quedaron de etapas anteriores y ninguna pieza de hoy pasa por ellos:

- `componer-video.yml` y el modo con avatar de `video/componer.py`: Reels con avatar de HeyGen, cortados el 09/11/2026.
- `animar-post.yml`, `animado/post.html` y `animado/animar_post.py`: posts estáticos animados; ya no se generan posts estáticos (`publicar-pieza.yml` todavía conserva la rama que los publicaba).
- `render-animado.yml`, `animado/placa.html` y `animado/terminar_placa.py`: placa animada suelta; ninguna pieza la usa.
- `animado/reel.html` y `animado/carrusel.html`: pantalla dividida y diapositiva animada, reemplazadas.
- `video/render.py` y `video/plantilla.html`: placas superpuestas de los primeros Reels.
