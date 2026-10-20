# Placas animadas (HyperFrames)

Plantillas HTML + GSAP que HyperFrames convierte en video. La tarea diaria solo completa los textos;
el diseño (Bricolage Grotesque, neutros y amarillo) queda fijo en la plantilla.

- `post.html`: post estático animado, 1080x1350, 8 s. Misma placa que la JPG (texto, resaltado amarillo,
  pie con logo) más un cierre de contacto por WhatsApp. Sin asteriscos resalta la última oración.
  Lo usa `publicar-pieza` solo: toma el primer párrafo del copy y el fondo de la JPG aprobada,
  lo renderiza, lo sube a Cloudinary y publica el video (Reel en Instagram, video en Facebook).
  Si el render falla, el post sale con la imagen estática.
- `carrusel.html`: diapositiva animada 1080x1350, 7 s. Gráfico opcional: grilla de días.
  Hoy no se usa: los carruseles se publican con las placas estáticas.
- `reel.html`: capa gráfica del Reel en pantalla dividida, 1080x1920 (paneles arriba, avatar abajo).
  Tres paneles: 1) gancho + afirmación; 2) un gráfico que explica la misma afirmación (`grafico`:
  contra, pasos, dato, dias o trayecto); 3) cierre con WhatsApp.
  Con `vista_previa: true` muestra un avatar de muestra y subtítulos; con `false` la mitad inferior
  queda transparente y se exporta en MOV con alfa para superponerla al video de HeyGen.

En las afirmaciones, la frase entre *asteriscos* se resalta en amarillo.

Render local:

    npx --yes hyperframes@0.8.173 render . -c post.html --variables-file ejemplos/post-rechazo.json -o post.mp4
    npx --yes hyperframes@0.8.173 render . -c carrusel.html --variables-file ejemplos/carrusel-dias.json -o carrusel.mp4
    npx --yes hyperframes@0.8.173 render . -c reel.html --variables-file ejemplos/reel-itinere.json -o reel.mp4
    npx --yes hyperframes@0.8.173 render . -c reel.html --format mov --variables '{"vista_previa":false}' -o capa.mov

En GitHub: Actions > "Render animado" > Run workflow (o repository_dispatch `render-animado`).

## Reel en pantalla dividida (componer-video)

Si el payload de `componer-video` trae la clave `animado` (ver `ejemplos/payload-componer.json`),
`video/componer.py` arma el Reel así: el avatar arranca a pantalla completa mientras dice el gancho,
al terminar la primera oración baja a la mitad inferior y arriba entra el panel 1; el panel 2 entra con la
primera oración que empieza al menos 2,5 s después (normalmente la tercera) y el CTA cuando empieza la
última oración. Esos tiempos salen solos de `tiempos`. En este modo no se
usan las placas de PLACAS_VIDEO ni la placa de contacto. Sin `animado`, todo funciona como antes.
