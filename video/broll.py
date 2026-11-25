"""
TikTok solo con b-roll (desde el 03/11/2026): video vertical armado 100 % con clips de la pestaña BRoll, la voz del
estudio (audio de ElevenLabs), subtítulos karaoke en mayúscula y el gancho arriba como título: entra animado en el
primer segundo (bandas amarillas que barren, pie óptico) y queda fijo; la tapa se arma aparte con el título completo. Es el formato de las cuentas de caso real con monto (ej. @derechosart). No usa HeyGen.

Recibe un JSON (variable de entorno PAYLOAD o archivo en el primer argumento) con:
    id         ID de la fila en la pestaña Aprobación (FORMATO TikTok)
    audio_url  dirección del audio de ElevenLabs (o un archivo local, para pruebas)
    tiempos    palabras con sus tiempos: [{"w": "Cobró", "s": 0.0, "e": 0.38}, ...]
    animado    columna ANIMADO de la fila: {"gancho": {"grande": "Cobró $ 28.000.000 por un corte en la cara",
               "pie": "ACCIDENTE IN ITINERE - ART"},   (pie desde el 03/11/2026: tipo de caso y ART, en blanco)
               "broll": [{"ancla": "primeras palabras de la oración", "clip": "B08", "url": "https://..."}, ...]}
               Un clip por oración, en el orden del guion. Cada clip cubre desde su oración hasta que empieza el
               siguiente; el primero arranca en el segundo 0. Los tramos largos se parten en tomas de hasta
               TOMA_MAX segundos que avanzan dentro del mismo clip y alternan el encuadre (normal / acercamiento),
               para que el video tenga cortes seguidos como los de la competencia.
    sfx        opcional, true por defecto: whoosh en cada cambio de clip y caja registradora con el monto del gancho
    billetes   opcional, true por defecto: lluvia de billetes al comienzo si el gancho trae "$ monto"

    Opcionales dentro de "animado" (24/11/2026, primero en T150; si faltan, todo funciona como antes):
    gancho.hasta   ancla (primeras palabras de una oración): el título del gancho sale de pantalla cuando empieza esa
                   oración. Desde el 25/11/2026, si falta, sale cuando empieza la segunda oración del guion; con
                   gancho.fijo = true queda todo el video, como antes. La tapa sigue llevando el título completo.
    gancho.pie     desde el 25/11/2026 el pie (tipo de caso) va solo si la fila lo trae: ya no se completa solo.
    gancho.sin_pie true: el gancho va sin pie aunque la fila lo traiga.
    placas         [{"ancla": "...", "texto": "..."}]: bloques de texto con el mismo estilo del título, que se van
                   alternando arriba: cada uno entra con su ancla (con un click) y sale cuando entra el siguiente;
                   el último queda hasta el final.

Deja final.mp4 y portada.jpg (primer cuadro del b-roll con el título completo) en la carpeta de trabajo.
"""
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.request

import componer as c

AQUI = c.AQUI
TRABAJO = c.TRABAJO

TOMA_MAX = 3.2          # segundos máximos de cada toma antes de un corte
TOMA_MIN = 1.2          # una toma más corta se une a la anterior
ACERCAMIENTO = 1.12
FPS = 30
TITULO_ARRIBA = 250     # debajo del encabezado de TikTok
TITULO_TAM = 78         # achicado el 03/11/2026 (antes 92)
SUB_Y = 1120            # parte superior de los subtítulos (zona media, lejos de los botones de TikTok)
SUB_TAM = 88
SUB_MAX_PALABRAS = 3
SUB_MAX_CARACTERES = 18
OSCURECER = 0.18        # velo oscuro sobre el b-roll para que se lean el título y los subtítulos
INTRO = 0.5             # segundos con el título solo antes de la voz: así el primer cuadro (la tapa) no lleva subtítulos
# Todas las tomas salen con los mismos datos de color (12/11/2026). Los clips de la biblioteca vienen distintos (unos
# sin datos de color, otros marcados bt709); si las tomas los heredan, ffmpeg 8 rearma los filtros del montaje final
# cuando cambian a mitad del fondo y descarta cuadros: el video de T120 quedó de 14,7 s con un audio de 24,9 s y
# se congelaba en el segundo 15.
COLOR_FILTRO = "setparams=range=tv:colorspace=bt709:color_primaries=bt709:color_trc=bt709"
COLOR_SALIDA = ["-color_range", "tv", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]


def bajar(origen, destino):
    if pathlib.Path(str(origen)).is_file():
        destino.write_bytes(pathlib.Path(str(origen)).read_bytes())
    else:
        urllib.request.urlretrieve(str(origen), destino)
    return destino


def tramos(items, palabras, total):
    """[(desde, hasta, url, clip)] uno por clip, en orden, cubriendo de 0 a total sin huecos."""
    inicios = c.inicios_de_oracion(palabras)
    ubicados = []
    for k, it in enumerate(items):
        t = c.ubicar_ancla(it.get("ancla", ""), palabras) if it.get("ancla") else None
        if t is None:                      # ancla que no aparece: toma la oración con su mismo número de orden
            t = inicios[k] if k < len(inicios) else None
        if t is None:
            print(f"Aviso: no se ubicó el clip {it.get('clip')!r}; no se usa")
            continue
        ubicados.append((t, it))
    ubicados.sort(key=lambda x: x[0])
    res = []
    for k, (t, it) in enumerate(ubicados):
        desde = 0.0 if k == 0 else t
        if res and desde - res[-1][0] < TOMA_MIN:      # dos clips casi juntos: queda el primero
            print(f"Aviso: el clip {it.get('clip')!r} queda muy pegado al anterior; no se usa")
            continue
        res.append([desde, None, it["url"], it.get("clip", "")])
    for k in range(len(res)):
        res[k][1] = res[k + 1][0] if k + 1 < len(res) else total
    return [tuple(r) for r in res]


def tomas(tramos_, archivos):
    """Parte cada tramo en tomas. Devuelve [(archivo, desde_en_el_clip, largo, acercar, clip)]."""
    res, n = [], 0
    for (desde, hasta, _, clip), archivo in zip(tramos_, archivos):
        largo = hasta - desde
        partes = max(1, int(-(-largo // TOMA_MAX)))
        if partes > 1 and largo / partes < TOMA_MIN:
            partes -= 1
        dur = c.duracion(archivo)
        paso = largo / partes
        pos = 0.0
        for _ in range(partes):
            if pos + paso > dur - 0.05:        # el clip no alcanza: vuelve al comienzo (con el otro encuadre)
                pos = 0.0
            res.append((archivo, round(pos, 3), round(paso, 3), n % 2 == 1, clip))
            pos += paso
            n += 1
    return res


def armar_toma(i, toma):
    archivo, ss, largo, acercar, _ = toma
    destino = TRABAJO / f"toma-{i:02d}.mp4"
    escala = ACERCAMIENTO if acercar else 1.0
    w, h = int(1080 * escala) // 2 * 2, int(1920 * escala) // 2 * 2
    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", f"{ss:.3f}", "-i", str(archivo),
        "-t", f"{largo:.3f}", "-an",
        "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps={FPS},format=yuv420p,"
               + COLOR_FILTRO,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", *COLOR_SALIDA, str(destino),
    ], check=True)
    # si el clip terminó antes, se estira el último cuadro hasta completar el largo pedido
    real = c.duracion(destino)
    if real < largo - 0.04:
        estirado = TRABAJO / f"toma-{i:02d}b.mp4"
        subprocess.run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(destino),
            "-vf", f"tpad=stop_mode=clone:stop_duration={largo - real + 0.05:.3f}," + COLOR_FILTRO,
            "-t", f"{largo:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", *COLOR_SALIDA, str(estirado),
        ], check=True)
        destino = estirado
    return destino


def renderizar_titulo(texto, destino, pie=""):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        pag = nav.new_page(viewport={"width": 1080, "height": 1920})
        pag.add_init_script("window.TITULO = " + json.dumps(
            {"texto": texto, "tam": TITULO_TAM, "arriba": TITULO_ARRIBA, "pie": pie}, ensure_ascii=False) + ";")
        pag.goto((AQUI / "titulo.html").as_uri())
        pag.evaluate("document.fonts.ready")
        pag.wait_for_function("window.LISTO === true")
        pag.screenshot(path=str(destino), omit_background=True)      # título completo: imagen fija para la tapa
        # Entrada animada (15/11/2026): un cuadro por imagen hasta que el título queda completo; ffmpeg repite el último.
        carpeta = destino.parent / destino.stem          # titulo.png → titulo/, placa-1.png → placa-1/
        carpeta.mkdir(exist_ok=True)
        for viejo in carpeta.glob("*.png"):
            viejo.unlink()
        cuadros = int(float(pag.evaluate("window.DURA || 0")) * FPS) + 2
        for f in range(cuadros):
            pag.evaluate("t => window.setT(t)", f / FPS if f < cuadros - 1 else 99)
            pag.screenshot(path=str(carpeta / f"{f:03d}.png"), omit_background=True)
        nav.close()
    return destino, carpeta


def subtitulos_mayuscula(palabras, destino):
    c.TAM, c.MAX_PALABRAS, c.MAX_CARACTERES = SUB_TAM, SUB_MAX_PALABRAS, SUB_MAX_CARACTERES
    visibles = [dict(p, w=str(p["w"]).upper()) for p in c.palabras_para_subtitulos(palabras)]
    c.escribir_ass(visibles, destino, SUB_Y)
    return destino


def efectos(tramos_, titulo, datos, clicks=()):
    """[(segundo, archivo, volumen)]: caja registradora con el monto (si lo hay) y whoosh en cada cambio de clip."""
    if not datos.get("sfx", True):
        return []
    tomas_ = c.tomas_sfx()
    semilla = c.semilla_sfx(datos)
    usados, res = {}, []

    def agregar(tipo, momento):
        lista = tomas_.get(tipo) or []
        if not lista:
            return
        k = usados.get(tipo, 0)
        usados[tipo] = k + 1
        archivo, pico = lista[(semilla + k) % len(lista)]
        res.append((round(max(0.0, momento - pico), 3), archivo, c.SFX_VOLUMEN[tipo]))

    if c.MONTO.search(titulo):
        agregar("caja", INTRO + 0.15)
    for desde, *_ in tramos_[1:]:
        agregar("whoosh", desde)
    for t in clicks:                       # entrada de cada placa alternada
        agregar("click", t + 0.12)
    return sorted(res)


def componer_broll(datos):
    TRABAJO.mkdir(parents=True, exist_ok=True)
    animado = datos.get("animado") or {}
    if isinstance(animado, str):
        animado = json.loads(animado)
    palabras = [p for p in (datos.get("tiempos") or []) if str(p.get("w", "")).strip()]
    if isinstance(datos.get("tiempos"), str):
        palabras = [p for p in json.loads(datos["tiempos"]) if str(p.get("w", "")).strip()]
    if not palabras:
        raise SystemExit("Faltan los tiempos de las palabras")
    items = [b for b in (animado.get("broll") or []) if b.get("url")]
    if not items:
        raise SystemExit("ANIMADO no trae clips de b-roll")
    titulo = c._sin_asteriscos((animado.get("gancho") or {}).get("grande", "")) or ""

    audio = bajar(datos["audio_url"], TRABAJO / "voz.mp3")
    palabras = [dict(p, s=float(p["s"]) + INTRO, e=float(p["e"]) + INTRO) for p in palabras]
    total = round(max(c.duracion(audio) + INTRO, float(palabras[-1]["e"])) + 0.6, 2)

    tramos_ = tramos(items, palabras, total)
    archivos = {}
    for _, _, url, clip in tramos_:
        if url not in archivos:
            print("Descargando b-roll", clip or url)
            archivos[url] = bajar(url, TRABAJO / f"broll-{len(archivos)}.mp4")
    lista = tomas(tramos_, [archivos[u] for _, _, u, _ in tramos_])
    print("Tramos:", [(d, h, cl) for d, h, _, cl in tramos_])
    print("Tomas:", [(cl, ss, lg, "acercada" if ac else "normal") for _, ss, lg, ac, cl in lista])

    partes = [armar_toma(i, t) for i, t in enumerate(lista)]
    concat = TRABAJO / "tomas.txt"
    concat.write_text("".join(f"file '{p.as_posix()}'\n" for p in partes), encoding="utf-8")
    fondo = TRABAJO / "fondo.mp4"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
                    "-i", str(concat), "-c", "copy", str(fondo)], check=True)

    # -reinit_filter 0: aunque el fondo cambiara de datos a mitad de camino, los filtros no se rearman.
    entradas = ["-reinit_filter", "0", "-i", str(fondo), "-i", str(audio)]
    filtros = [f"[0:v]setpts=PTS-STARTPTS,drawbox=x=0:y=0:w=iw:h=ih:color=black@{OSCURECER}:t=fill[v0]"]
    ultimo = "v0"
    if datos.get("billetes", True) and c.MONTO.search(titulo):
        try:
            lluvia = c.renderizar_billetes(INTRO, c.semilla_sfx(datos), TRABAJO / "billetes.mov")
            entradas += ["-i", str(lluvia)]
            n = sum(1 for x in entradas if x == "-i") - 1
            filtros += [f"[{n}:v]format=yuva444p10le[lluvia]", f"[{ultimo}][lluvia]overlay=0:0:eof_action=pass[vl]"]
            ultimo = "vl"
        except Exception as e:            # la lluvia nunca frena el video
            print(f"Aviso: no se pudo armar la lluvia de billetes ({e})")
    gancho = animado.get("gancho") or {}
    if titulo:
        pie = "" if gancho.get("sin_pie") else str(gancho.get("pie", "") or "").strip()   # sin pie automático (25/11/2026)
        png, cuadros_titulo = renderizar_titulo(titulo, TRABAJO / "titulo.png", pie)
        entradas += ["-framerate", str(FPS), "-i", str(cuadros_titulo / "%03d.png")]
        n = sum(1 for x in entradas if x == "-i") - 1
        fin_gancho = c.ubicar_ancla(gancho["hasta"], palabras) if gancho.get("hasta") else None
        if gancho.get("hasta") and fin_gancho is None:
            print(f"Aviso: no se ubicó gancho.hasta {gancho['hasta']!r}; sale con la segunda oración")
        if fin_gancho is None and not gancho.get("fijo"):     # por defecto, el gancho sale con la segunda oración
            inicios = c.inicios_de_oracion(palabras)
            fin_gancho = inicios[1] if len(inicios) > 1 else None
        ventana = f":enable='between(t,0,{fin_gancho:.3f})'" if fin_gancho else ""
        filtros.append(f"[{ultimo}][{n}:v]overlay=0:0:eof_action=repeat{ventana}[vt]")
        ultimo = "vt"
    # Placas alternadas (24/11/2026): cada una entra animada en su ancla y sale cuando entra la siguiente.
    placas = []
    for pl in animado.get("placas") or []:
        t = c.ubicar_ancla(pl.get("ancla", ""), palabras) if pl.get("ancla") else None
        texto = c._sin_asteriscos(str(pl.get("texto", "") or "")).strip()
        if t is None or not texto:
            print(f"Aviso: no se ubicó la placa {pl.get('texto')!r}; no se usa")
            continue
        placas.append((t, texto))
    placas.sort()
    for k, (t, texto) in enumerate(placas):
        hasta = placas[k + 1][0] if k + 1 < len(placas) else total + 1
        _, cuadros = renderizar_titulo(texto, TRABAJO / f"placa-{k + 1}.png")
        entradas += ["-framerate", str(FPS), "-i", str(cuadros / "%03d.png")]
        n = sum(1 for x in entradas if x == "-i") - 1
        filtros.append(f"[{n}:v]setpts=PTS-STARTPTS+{t:.3f}/TB[pl{k}]")
        filtros.append(f"[{ultimo}][pl{k}]overlay=0:0:eof_action=repeat:enable='between(t,{t:.3f},{hasta:.3f})'[vp{k}]")
        ultimo = f"vp{k}"
    if placas:
        print("Placas:", [(round(t, 2), tx) for t, tx in placas])
    ass = subtitulos_mayuscula(palabras, TRABAJO / "subtitulos.ass")
    fuentes = str(AQUI / "fuentes").replace(":", "\\:")
    filtros.append(f"[{ultimo}]subtitles={ass.as_posix()}:fontsdir={fuentes}[vf]")
    ultimo = "vf"

    ms = int(INTRO * 1000)
    filtros.append(f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay={ms}|{ms},apad[voz]")
    audio_map = "[voz]"
    sonidos = efectos(tramos_, titulo, datos, [t for t, _ in placas])
    if sonidos:
        base = sum(1 for x in entradas if x == "-i")
        etiquetas = []
        for k, (t, archivo, vol) in enumerate(sonidos):
            entradas += ["-i", str(archivo)]
            ms = int(t * 1000)
            filtros.append(f"[{base + k}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={vol},"
                           f"adelay={ms}|{ms}[sfx{k}]")
            etiquetas.append(f"[sfx{k}]")
        filtros.append(f"[voz]{''.join(etiquetas)}amix=inputs={len(etiquetas) + 1}:duration=first:normalize=0,"
                       "alimiter=limit=0.95[audio]")
        audio_map = "[audio]"
        print("Efectos de sonido:", [(t, a.stem) for t, a, _ in sonidos])

    salida = TRABAJO / "final.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *entradas,
        "-filter_complex", ";".join(filtros), "-map", f"[{ultimo}]", "-map", audio_map,
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-t", f"{total:.2f}", str(salida),
    ], check=True)
    # Control: la imagen tiene que durar lo mismo que el audio. Si quedó corta, la corrida falla y el video no se sube.
    imagen = c.duracion_video(salida)
    if imagen < total - 0.5:
        raise SystemExit(f"El video quedó corto: {imagen:.1f} s de imagen para {total:.1f} s de audio")
    # Tapa: el primer cuadro del b-roll con el título completo y sin subtítulos. Desde el 15/11/2026 el título entra
    # animado, así que el primer cuadro del video ya no lo trae: la tapa se arma aparte con la imagen fija del título.
    # (TikTok muestra por defecto el primer cuadro del video; la tapa con título se elige al publicar el borrador.)
    if titulo:
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(fondo), "-i", str(png),
                        "-filter_complex",
                        f"[0:v]drawbox=x=0:y=0:w=iw:h=ih:color=black@{OSCURECER}:t=fill[v];[v][1:v]overlay=0:0",
                        "-frames:v", "1", "-q:v", "2", str(TRABAJO / "portada.jpg")], check=True)
    else:
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(salida),
                        "-frames:v", "1", "-q:v", "2", str(TRABAJO / "portada.jpg")], check=True)
    print(f"Listo: {len(tramos_)} clips, {len(lista)} tomas, {total:.1f} s")
    return salida


if __name__ == "__main__":
    if len(sys.argv) > 1:
        datos = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    else:
        datos = json.loads(os.environ["PAYLOAD"])
    print(componer_broll(datos))
