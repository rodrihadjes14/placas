# Placas animadas (HyperFrames)

Plantillas HTML + GSAP que HyperFrames convierte en video. La tarea diaria solo completa los textos;
el diseño (Bricolage Grotesque, neutros y amarillo) queda fijo en la plantilla.

- `post.html`: post estático animado, 1080x1350, 8 s. Misma placa que la JPG (texto, resaltado amarillo,
  pie con logo) más un cierre que invita a comentar o a mandar un mensaje privado. Sin asteriscos resalta la última oración.
  Se arma al graficar: ExportadorCarruseles.gs dispara el workflow `animar-post` (texto = primer
  párrafo del COPY, fondo = el de la JPG), que lo sube a Cloudinary y deja
  `publicaciones/<ID>/animado.json`; el exportador copia ese link a la columna ANIMADO para revisarlo.
  Al publicar, `publicar-pieza` usa ese mismo video (si falta, lo arma en el momento con
  `animar_post.py`) y lo publica como Reel en Instagram y video en Facebook; TikTok recibe el mismo.
  Si todo falla, el post sale con la imagen estática.
- `carrusel.html`: diapositiva animada 1080x1350, 7 s. Gráfico opcional: grilla de días.
  Hoy no se usa: los carruseles se publican con las placas estáticas.
- `texto.html`: capa de texto animado del Reel (desde el 30/10/2026). El avatar queda a pantalla completa
  y arriba de la cabeza aparecen bloques de dos líneas: una chica en minúscula (fondo blanco, letras negras)
  y una grande en mayúscula sobre banda amarilla, en el gancho, en las frases clave y en el CTA.
  `componer.py` calcula los tiempos y la altura según la cara; se exporta en MOV con alfa.
- `reel.html`: (en desuso desde el 30/10/2026) capa gráfica del Reel en pantalla dividida, 1080x1920 (paneles arriba, avatar abajo).
  Tres paneles: 1) gancho + afirmación; 2) un gráfico que explica la misma afirmación (`grafico`:
  contra, pasos, dato, dias o trayecto); 3) cierre con la llamada a la acción de la pieza (mensaje privado, comentarios o compartir; `cta_icono`: mensaje, comentario o compartir).
  Con `vista_previa: true` muestra un avatar de muestra y subtítulos; con `false` la mitad inferior
  queda transparente y se exporta en MOV con alfa para superponerla al video de HeyGen.

En las afirmaciones, la frase entre *asteriscos* se resalta en amarillo.

Render local:

    npx --yes hyperframes@0.8.173 render . -c post.html --variables-file ejemplos/post-rechazo.json -o post.mp4
    npx --yes hyperframes@0.8.173 render . -c carrusel.html --variables-file ejemplos/carrusel-dias.json -o carrusel.mp4
    npx --yes hyperframes@0.8.173 render . -c reel.html --variables-file ejemplos/reel-itinere.json -o reel.mp4
    npx --yes hyperframes@0.8.173 render . -c reel.html --format mov --variables '{"vista_previa":false}' -o capa.mov

En GitHub: Actions > "Render animado" > Run workflow (o repository_dispatch `render-animado`).

## Reel con texto animado (componer-video)

Si el payload de `componer-video` trae la clave `animado`, `video/componer.py` deja el avatar a pantalla
completa (con el acercamiento alternado en los cortes de escena, como siempre) y le superpone `texto.html`:

    {"gancho": {"chica": "alta médica", "grande": "¿Te dieron el alta y todavía te duele?"},
     "claves": [{"chica": "puede ser", "grande": "un alta prematura", "ancla": "Un alta al mes"}],
     "cta": {"chica": "¿te pasó?", "grande": "Dejanos tu mensaje por privado"}}

El gancho se ve mientras se lo dice; cada frase clave entra con su `ancla` (primeras palabras de una oración
del guion) o, si no la encuentra, con la oración siguiente, y dura hasta 4,5 s; el CTA entra con la última
oración y queda hasta el final. Los bloques van entre el encabezado de Reels y la cabeza del avatar, y los
subtítulos karaoke a la altura del pecho. Ya no hay pantalla dividida.

Prueba local de la capa sola:

    npx --yes hyperframes@0.8.173 render . -c texto.html -o texto.mp4
