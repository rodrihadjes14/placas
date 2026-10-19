# Placas animadas (HyperFrames)

Plantillas HTML + GSAP que HyperFrames convierte en video. La tarea diaria solo completa los textos;
el diseño (Bricolage Grotesque, neutros y amarillo) queda fijo en la plantilla.

- `carrusel.html`: diapositiva animada 1080x1350, 7 s. Gráfico opcional: grilla de días.
- `reel.html`: capa gráfica del Reel en pantalla dividida, 1080x1920 (gráfico arriba, avatar abajo).
  Con `vista_previa: true` muestra un avatar de muestra y subtítulos; con `false` la mitad inferior
  queda transparente y se exporta en MOV con alfa para superponerla al video de HeyGen.

En las afirmaciones, la frase entre *asteriscos* se resalta en amarillo.

Render local:

    npx --yes hyperframes@0.8.173 render . -c carrusel.html --variables-file ejemplos/carrusel-dias.json -o carrusel.mp4
    npx --yes hyperframes@0.8.173 render . -c reel.html --variables-file ejemplos/reel-itinere.json -o reel.mp4
    npx --yes hyperframes@0.8.173 render . -c reel.html --format mov --variables '{"vista_previa":false}' -o capa.mov

En GitHub: Actions > "Render animado" > Run workflow (o repository_dispatch `render-animado`).
