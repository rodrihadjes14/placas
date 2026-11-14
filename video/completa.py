"""
Reel grabado a pantalla completa (desde el 14/11/2026): el abogado se filma leyendo el guion y el video final lo
muestra a pantalla completa todo el tiempo, con bloques de texto arriba de la cabeza, hasta dos clips de b-roll y
subtítulos. Es la unión de los dos montajes que ya existían:

  - de grabado.py toma la primera mitad: transcribe la grabación, ubica cada oración del guion, corta las pausas y
    les pone tiempo a las palabras del guion;
  - de componer.py toma la segunda: el modo de texto animado (bloques de gancho, frases clave y CTA, b-roll,
    subtítulos en mayúscula con pop in, efectos de sonido y tapa).

No recorta la silueta ni dibuja gráficos de fondo: para eso está grabado.py.

Recibe un JSON (variable de entorno PAYLOAD o archivo en el primer argumento):
    id        ID de la fila (AD-01, T130)
    video_id  identificador de esta composición; el resultado se sube como final-<id>-<video_id>
    video     archivo de la grabación (si falta, usa la variable de entorno ORIGEN)
    guion     el guion textual que se leyó
    animado   textos de pantalla y b-roll, con el formato de la columna ANIMADO:
              {"gancho": {"chica", "grande"[, "pie"]}, "claves": [{"chica", "grande", "ancla"}], "cta": {"chica", "grande"},
               "broll": [{"ancla", "clip", "url"}], "titulo_fijo": true|false, "broll_libre": true|false}
              Con "broll_libre": true admite hasta seis clips, y cada uno entra cuando se dice su ancla.
              Con "titulo_fijo": true el bloque del gancho queda arriba durante todo el video (título de los
              anuncios y Reels de caso) y no se muestran frases clave ni CTA.
    zoom      opcional, true por defecto: acerca el encuadre hasta dejar al abogado de la cadera para arriba (arranca
              con el cuadro entero y en poco más de un segundo llega; después queda fijo). false lo apaga.
    sfx       opcional, true por defecto.
    billetes  opcional, true por defecto: lluvia de billetes cuando el gancho trae un monto ("$ 23.000.000").

Deja final.mp4, portada.jpg e informe.json en la carpeta de trabajo (CARPETA_TRABAJO).
"""
import difflib
import json
import os
import pathlib
import sys

import grabado as g
import componer as montaje

W, H = 1080, 1920

# Acercamiento (desde el 14/11/2026): el abogado se graba de cuerpo entero y el Reel lo muestra de la cadera para arriba.
ZOOM_SEGUNDOS = 1.2           # lo que tarda el acercamiento, al empezar el video; después queda fijo
ZOOM_CABEZA = 670             # altura (px de 1920) donde queda la parte de arriba de la cabeza: deja lugar al texto
ZOOM_CADERA = 1890            # altura donde queda la cadera: casi en el borde de abajo
ZOOM_CADERA_EN_CABEZAS = 2.75 # el borde de abajo queda a 2,75 "cabezas" (como las mide detectar_persona) de la parte de arriba de la cabeza: cadera y arranque de las piernas
ZOOM_MAX = 2.6                # tope del acercamiento
ZOOM_MINIMO = 1.08            # por debajo de esto no vale la pena acercar


def tamano_de(archivo):
    """(ancho, alto) con que se ve el video, ya girado si el teléfono lo grabó de costado."""
    import re
    import subprocess
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(archivo)], capture_output=True, text=True).stderr
    m = re.search(r"Video:.*?(\d{3,5})x(\d{3,5})", r)
    if not m:
        return W, H
    ancho, alto = int(m.group(1)), int(m.group(2))
    if re.search(r"rotation of -?(90|270)", r) or re.search(r"rotate\s*:\s*(90|270)", r):
        ancho, alto = alto, ancho
    return ancho, alto


def detectar_persona(video, muestras=12):
    """Ubica al abogado en el video: {"x": centro de la cara, "cabeza", "menton"} en píxeles de 1080x1920, o None.
    Mide la cabeza igual que componer.detectar_cara() (con el pelo arriba y un margen debajo del mentón)."""
    import cv2
    cc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_alt2.xml")
    cap = cv2.VideoCapture(str(video))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    cajas = []
    for k in range(muestras):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * (k + 0.5) / muestras))
        ok, cuadro = cap.read()
        if not ok:
            continue
        gris = cv2.equalizeHist(cv2.cvtColor(cv2.resize(cuadro, (W, H)), cv2.COLOR_BGR2GRAY))
        for (x, y, w, h) in cc.detectMultiScale(gris, 1.1, 5, minSize=(90, 90)):
            cajas.append((int(x), int(y), int(w), int(h)))
    cap.release()
    if not cajas:
        return None
    mayor = max(c[3] for c in cajas)
    cajas = [c for c in cajas if c[3] >= 0.7 * mayor]         # descarta detecciones falsas chicas
    orden = sorted(cajas, key=lambda c: c[1])
    x, y, w, h = orden[len(orden) // 2]                       # la del medio: no depende de un cuadro raro
    return {"x": x + w / 2, "cabeza": max(0.0, y - 0.45 * h), "menton": min(float(H), y + 1.05 * h)}


def encuadre_de_cadera(persona):
    """Cuánto hay que acercar y hacia dónde para que el abogado quede de la cadera para arriba, con la cabeza a la
    altura ZOOM_CABEZA. Devuelve (zoom, fx, fy): fx y fy dicen qué parte de lo que sobra queda afuera a la izquierda
    y arriba (0 a 1). Zoom 1 quiere decir que ya está así de cerca o más."""
    alto_cabeza = max(1.0, persona["menton"] - persona["cabeza"])
    zoom = (ZOOM_CADERA - ZOOM_CABEZA) / (ZOOM_CADERA_EN_CABEZAS * alto_cabeza)
    zoom = min(ZOOM_MAX, zoom)
    if zoom < ZOOM_MINIMO:
        return 1.0, 0.5, 0.5
    sobra_x, sobra_y = W - W / zoom, H - H / zoom
    x0 = min(max(persona["x"] - (W / 2) / zoom, 0.0), sobra_x)
    y0 = min(max(persona["cabeza"] - ZOOM_CABEZA / zoom, 0.0), sobra_y)
    return zoom, x0 / sobra_x, y0 / sobra_y


def acercar(entrada, voz, salida, zoom, fx, fy):
    """Une el video cortado con la voz y, si zoom > 1, lo acerca: arranca con el cuadro entero, en ZOOM_SEGUNDOS llega
    al encuadre de la cadera para arriba y se queda ahí hasta el final."""
    if zoom <= 1.0:
        filtro = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1"
    else:
        t = f"min(t/{ZOOM_SEGUNDOS}\\,1)"
        z = f"(1+{zoom - 1:.4f}*{t}*{t}*(3-2*{t}))"               # entra y frena suave
        filtro = (f"scale=w='2*trunc({W}*{z}/2)':h='2*trunc({H}*{z}/2)':eval=frame:flags=bicubic,"
                  # x e y se calculan con el mismo zoom del instante (crop no se entera de que el cuadro cambió de tamaño)
                  f"crop={W}:{H}:x='{W}*({z}-1)*{fx:.4f}':y='{H}*({z}-1)*{fy:.4f}',setsar=1")
    g.correr("ffmpeg", "-v", "error", "-y", "-i", entrada, "-i", voz, "-map", "0:v", "-map", "1:a", "-vf", filtro,
             "-r", g.FPS, "-c:v", "libx264", "-preset", "veryfast", "-crf", 15, "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", "-shortest", salida)


def armar(datos):
    trabajo = g.TRABAJO
    trabajo.mkdir(parents=True, exist_ok=True)
    try:
        _armar(datos, trabajo)
    except BaseException as err:
        import traceback
        g.etapa("ERROR", error=str(err)[:500], traza=traceback.format_exc()[-1500:])
        raise


def _armar(datos, trabajo):
    origen = datos.get("video") or os.environ.get("ORIGEN")
    orac = g.oraciones(datos["guion"])
    g.etapa("Preparando la grabación")
    src = trabajo / "src.mp4"
    # Si la grabación tiene más resolución que 1080x1920 (4K), se trabaja con esa hasta el acercamiento: así el
    # acercamiento usa píxeles reales en vez de agrandar la imagen.
    con_zoom = datos.get("zoom", True)
    ancho_origen, alto_origen = tamano_de(origen)
    k = min(ZOOM_MAX, max(1.0, min(ancho_origen / W, alto_origen / H))) if con_zoom else 1.0
    wk, hk = 2 * round(W * k / 2), 2 * round(H * k / 2)
    g.correr("ffmpeg", "-v", "error", "-y", "-i", origen, "-vf",
             f"scale={wk}:{hk}:force_original_aspect_ratio=increase,crop={wk}:{hk}",
             "-r", g.FPS, "-c:v", "libx264", "-preset", "veryfast", "-crf", 15, "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", src)
    g.correr("ffmpeg", "-v", "error", "-y", "-i", src, "-ac", 1, "-ar", 16000, trabajo / "src.wav")
    total = g.duracion_de(src)

    g.etapa("Transcribiendo y ubicando las oraciones del guion", duracion_original=round(total, 2))
    pal = g.transcribir(trabajo / "src.wav")
    ubic = g.ubicar_oraciones(orac, pal)
    tramos, tramos_volumen = g.tramos_sin_respiracion(ubic, pal, trabajo / "src.wav", total)
    g.etapa("Cortando", tramos=[[round(a, 2), round(b, 2), k] for a, b, k in tramos])
    corte, voz = trabajo / "corte.mp4", trabajo / "voz.wav"
    lapsos = g.cortar(src, tramos, corte, voz)
    g.correr("ffmpeg", "-v", "error", "-y", "-i", voz, "-ac", 1, "-ar", 16000, trabajo / "corte.wav")
    final_t = lapsos[-1][1]
    for nombre, archivo in (("video", corte), ("audio", voz)):
        if abs(g.duracion_de(archivo) - final_t) > 0.25:
            raise RuntimeError(f"El corte salió mal: el {nombre} dura {g.duracion_de(archivo):.2f} s y debería durar {final_t:.2f} s")
    print(f"Pausas cortadas: de {total:.1f} s a {final_t:.1f} s. Verificando contra el guion")

    pal2 = g.transcribir(trabajo / "corte.wav")
    palabras, parecido = g.palabras_del_guion(orac, pal2, lapsos)
    avisos = []
    parecida = lambda x, y: difflib.SequenceMatcher(None, x, y).ratio() >= 0.6
    for k, o in enumerate(orac):                       # ¿el corte se comió el arranque o el final de una oración?
        d = min((l[0] for l in lapsos if l[2] == k), default=None)
        h = max((l[1] for l in lapsos if l[2] == k), default=None)
        dichas = [g.normalizar(p["w"]) for p in pal2 if d is not None and d - 0.15 <= p["s"] < h - 0.02]
        obj = g.fichas(o)
        if dichas and obj and not any(parecida(obj[0], x) for x in dichas[:2]):
            avisos.append(f"Revisar el arranque de la oración {k + 1}: {o}")
        if dichas and obj and not any(parecida(obj[-1], x) for x in dichas[-2:]):
            avisos.append(f"Revisar el final de la oración {k + 1}: {o}")
    for k, u in enumerate(ubic):
        if not u:
            avisos.append(f"No se encontró la oración {k + 1}: {orac[k]}")
        elif u[2] < 0.7:
            avisos.append(f"La oración {k + 1} no coincide bien con el guion ({u[2]:.0%}): {orac[k]}")

    zoom, fx, fy, persona = 1.0, 0.5, 0.5, None
    if con_zoom:
        try:
            persona = detectar_persona(corte)
            if persona:
                zoom, fx, fy = encuadre_de_cadera(persona)
            else:
                avisos.append("No se encontró la cara para acercar el encuadre: el video sale sin acercamiento")
        except Exception as err:                       # el acercamiento nunca frena el video
            avisos.append(f"No se pudo calcular el acercamiento: {str(err)[:200]}")
    g.etapa("Uniendo el video cortado con la voz" + (" y acercando" if zoom > 1 else ""), zoom=round(zoom, 2),
            origen=[ancho_origen, alto_origen], trabajo=[wk, hk], persona=persona)
    entrada = trabajo / "completa.mp4"
    acercar(corte, voz, entrada, zoom, fx, fy)

    animado = datos.get("animado") or {}
    if isinstance(animado, str):
        animado = json.loads(animado)
    tiempos = [{"w": p["w"], "s": round(float(p["s"]), 3), "e": round(float(p["e"]), 3)} for p in palabras]
    g.etapa("Componiendo: texto de pantalla, b-roll y subtítulos",
            bloques=len(animado.get("claves") or []) + bool(animado.get("gancho")) + bool(animado.get("cta")),
            broll=len(animado.get("broll") or []), titulo_fijo=bool(animado.get("titulo_fijo")))
    para_montaje = {"id": datos.get("id"), "video_id": datos.get("video_id"), "animado": animado,
                    "sfx": datos.get("sfx", True), "billetes": datos.get("billetes", True)}
    if persona and zoom > 1:
        # Dónde quedó la cara después del acercamiento: el texto y los subtítulos se ubican con eso, sin volver a
        # buscarla (al buscarla de nuevo sobre el video ya acercado puede confundirse con otra cosa).
        arriba = fy * (H - H / zoom)
        para_montaje["cara"] = {"cabeza": round((persona["cabeza"] - arriba) * zoom, 1),
                                "menton": round(min(float(H), (persona["menton"] - arriba) * zoom), 1)}
    montaje.componer_texto(para_montaje, entrada, tiempos, montaje.duracion(entrada))

    final = trabajo / "final.mp4"
    if abs(g.duracion_de(final) - final_t) > 0.4:
        raise RuntimeError("El video final no dura lo que debería")
    informe = {"id": datos.get("id"), "modo": "pantalla completa", "duracion_original": round(total, 2),
               "zoom": round(zoom, 2), "resolucion_origen": [ancho_origen, alto_origen],
               "nitidez": round(min(1.0, k / zoom), 2),     # 1 = el acercamiento usa píxeles reales; menos = imagen agrandada
               "duracion_final": round(final_t, 2), "parecido_con_guion": round(parecido, 3),
               "transcripcion_final": " ".join(p["w"] for p in pal2),
               "oraciones": [{"texto": o, "parecido": round(u[2], 3) if u else 0} for o, u in zip(orac, ubic)],
               "tramos": [[round(a, 2), round(b, 2), k] for a, b, k in tramos],
               "tramos_volumen": [[round(a, 2), round(b, 2), k] for a, b, k in tramos_volumen],
               "etapas": g.ETAPAS, "avisos": avisos, "revisar": bool(avisos) or parecido < 0.85}
    (trabajo / "informe.json").write_text(json.dumps(informe, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(informe, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    crudo = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8") if len(sys.argv) > 1 else os.environ["PAYLOAD"]
    armar(json.loads(crudo))
