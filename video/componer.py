"""
Compone el video final: video de HeyGen + placas + subtítulos con la palabra activa resaltada.

Recibe un JSON (por la variable de entorno PAYLOAD o como archivo en el primer argumento) con:
    id         ID de la fila en la pestaña Aprobación
    video_id   ID del video en HeyGen
    video_url  dirección del video terminado en HeyGen
    placas     lista de placas (formato de la columna PLACAS_VIDEO), puede venir vacía
    tiempos    lista de palabras con sus tiempos: [{"w": "Tenés", "s": 0.12, "e": 0.41}, ...]

Deja el resultado en final.mp4 (en la carpeta de trabajo).
"""
import json
import os
import pathlib
import re
import subprocess
import sys
import unicodedata
import urllib.request

from render import render

AQUI = pathlib.Path(__file__).resolve().parent
TRABAJO = pathlib.Path(os.environ.get("CARPETA_TRABAJO", "trabajo")).resolve()

# Subtítulos (estilo B: blanco con la palabra activa en amarillo cálido)
FUENTE = "Inter ExtraBold"
TAM = 58
BLANCO = "&H00FFFFFF"
AMARILLO = "&H003FD2FF"      # #FFD23F en formato BGR de ASS
CONTORNO = "&H001A1B1C"      # #1C1B1A
SOMBRA = "&H73000000"
POS_Y = 1170                 # parte superior del subtítulo, sobre el pecho
MAX_PALABRAS = 5
MAX_CARACTERES = 28

# Placas
DURACION_MAX_PLACA = 6.0
FUNDIDO = 0.3


def normalizar(t):
    t = unicodedata.normalize("NFD", str(t).lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9ñ ]", "", t).strip()


def ubicar_ancla(ancla, palabras):
    """Devuelve el segundo en que empieza la primera palabra del ancla, o None."""
    buscadas = [w for w in normalizar(ancla).split() if w]
    dichas = [normalizar(p["w"]) for p in palabras]
    n = len(buscadas)
    if not n:
        return None
    for i in range(len(dichas) - n + 1):
        if dichas[i:i + n] == buscadas:
            return float(palabras[i]["s"])
    return None


def agrupar(palabras):
    """Arma bloques cortos de subtítulo: cortan en puntuación, pausas o largo máximo."""
    bloques, actual = [], []
    for i, p in enumerate(palabras):
        actual.append(p)
        largo = len(" ".join(x["w"] for x in actual))
        siguiente = palabras[i + 1] if i + 1 < len(palabras) else None
        pausa = siguiente is not None and float(siguiente["s"]) - float(p["e"]) > 0.4
        cierra = re.search(r"[.,;:?!…]$", p["w"]) is not None
        if siguiente is None or cierra or pausa or len(actual) >= MAX_PALABRAS or largo >= MAX_CARACTERES:
            bloques.append(actual)
            actual = []
    return bloques


def t_ass(seg):
    seg = max(0.0, seg)
    h = int(seg // 3600)
    m = int(seg % 3600 // 60)
    s = seg % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def limpiar(t):
    return str(t).replace("{", "").replace("}", "").replace("\\", "")


def escribir_ass(palabras, destino):
    cab = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{FUENTE},{TAM},{BLANCO},{BLANCO},{CONTORNO},{SOMBRA},0,0,0,0,100,100,0,0,1,4,2,8,140,140,{POS_Y},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lineas = []
    for bloque in agrupar(palabras):
        fin_bloque = float(bloque[-1]["e"]) + 0.15
        for j, p in enumerate(bloque):
            ini = float(p["s"])
            fin = float(bloque[j + 1]["s"]) if j + 1 < len(bloque) else fin_bloque
            texto = " ".join(
                ("{\\c" + AMARILLO + "&}" + limpiar(x["w"]) + "{\\c" + BLANCO + "&}") if k == j else limpiar(x["w"])
                for k, x in enumerate(bloque)
            )
            lineas.append(f"Dialogue: 0,{t_ass(ini)},{t_ass(fin)},Sub,,0,0,0,,{texto}")
    destino.write_text(cab + "\n".join(lineas) + "\n", encoding="utf-8")


def duracion(video):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(video)],
        capture_output=True, text=True, check=True,
    )
    return float(r.stdout.strip())


def ventanas_placas(placas, palabras, total):
    """Calcula desde y hasta qué segundo se ve cada placa. Las que no ubica, las descarta con aviso."""
    ubicadas = []
    for p in placas:
        t = ubicar_ancla(p.get("ancla", ""), palabras)
        if t is None:
            print(f"Aviso: no encontré el ancla '{p.get('ancla')}' en la voz; esa placa no se muestra")
            continue
        ubicadas.append((t, p))
    ubicadas.sort(key=lambda x: x[0])
    res = []
    for i, (t, p) in enumerate(ubicadas):
        hasta = min(t + DURACION_MAX_PLACA, total - 0.1)
        if i + 1 < len(ubicadas):
            hasta = min(hasta, ubicadas[i + 1][0] - 0.05)
        if hasta - t >= 1.0:
            res.append((t, hasta, p))
    return res


def componer(datos):
    TRABAJO.mkdir(parents=True, exist_ok=True)
    entrada = TRABAJO / "entrada.mp4"
    print("Descargando el video de HeyGen")
    urllib.request.urlretrieve(datos["video_url"], entrada)
    total = duracion(entrada)

    palabras = [p for p in (datos.get("tiempos") or []) if str(p.get("w", "")).strip()]
    placas = datos.get("placas") or []
    if isinstance(placas, str):
        placas = json.loads(placas) if placas.strip() else []

    ventanas = ventanas_placas(placas, palabras, total)
    pngs = render([v[2] for v in ventanas], TRABAJO / "placas") if ventanas else []

    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(entrada)]
    for png in pngs:
        cmd += ["-loop", "1", "-i", str(png)]

    filtros = ["[0:v]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[v0]"]
    ultimo = "v0"
    for i, ((desde, hasta, _), png) in enumerate(zip(ventanas, pngs), start=1):
        filtros.append(
            f"[{i}:v]format=rgba,fade=t=in:st={desde:.2f}:d={FUNDIDO}:alpha=1,"
            f"fade=t=out:st={hasta - FUNDIDO:.2f}:d={FUNDIDO}:alpha=1[p{i}]"
        )
        filtros.append(f"[{ultimo}][p{i}]overlay=0:0:enable='between(t,{desde:.2f},{hasta:.2f})':shortest=1[v{i}]")
        ultimo = f"v{i}"

    if palabras:
        ass = TRABAJO / "subtitulos.ass"
        escribir_ass(palabras, ass)
        fuentes = str(AQUI / "fuentes").replace(":", "\\:")
        filtros.append(f"[{ultimo}]subtitles={ass.as_posix()}:fontsdir={fuentes}[vf]")
        ultimo = "vf"

    salida = TRABAJO / "final.mp4"
    cmd += [
        "-filter_complex", ";".join(filtros), "-map", f"[{ultimo}]", "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-t", f"{total:.2f}", str(salida),
    ]
    print("Componiendo:", len(ventanas), "placas,", len(palabras), "palabras de subtítulo")
    subprocess.run(cmd, check=True)
    return salida


if __name__ == "__main__":
    if len(sys.argv) > 1:
        datos = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    else:
        datos = json.loads(os.environ["PAYLOAD"])
    print(componer(datos))
