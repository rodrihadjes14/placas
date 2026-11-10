"""
Compone un "Reel grabado": el abogado se filma leyendo el guion (con pausas entre oración y oración) y este
programa arma el video final (desde el 10/11/2026).

Qué hace, en orden:
  1. Transcribe la grabación con el tiempo de cada palabra y ubica cada oración del guion (si una oración se dijo
     más de una vez, se queda con la última toma completa).
  2. Corta las pausas: conserva cada oración con un margen mínimo y descarta lo que queda en el medio.
  3. Vuelve a transcribir el video ya cortado y lo compara con el guion (informe.json avisa si falta algo).
  4. Arma el Reel: gancho a pantalla completa con su bloque de texto, desarrollo con el abogado recortado (silueta)
     en la esquina inferior izquierda y los gráficos animados de fondo, y cierre otra vez a pantalla completa.
     Subtítulos en mayúscula con pop in y la palabra activa resaltada durante todo el video.

Recibe un JSON (variable de entorno PAYLOAD o archivo en el primer argumento):
    id        ID de la fila (T114)
    video     archivo de la grabación (si falta, usa la variable de entorno ORIGEN)
    guion     el guion textual que se leyó
    etiqueta  texto del rótulo fijo que se ve arriba durante los gráficos ("ENFERMEDAD PROFESIONAL · ART")
    gancho    {"chica", "grande"[, "pie"]}: bloque de texto del gancho
    cierre    [{"ancla", "chica", "grande"[, "pie"]}, ...]: bloques de texto del cierre; cada uno entra con su ancla
              (primeras palabras de una oración del guion). El primero marca el fin de los gráficos.
    graficos  [{"ancla", "tipo", ...}]: gráficos del desarrollo; cada uno entra cuando se dice su ancla y dura hasta
              el siguiente. Tipos (plantillas de grabado.html):
                tachado  {chica, grande, sello[, icono, cuando_sello]}       una tarjeta y un sello que la cruza
                numero   {chica, numero, grande[, cuando]}                    un número grande y una frase
                causa    {chica, desde, etiqueta, hasta[, icono_desde, icono_hasta]}   A → flecha → B
                lista    {titulo (con *resaltado*), items: [{texto[, detalle, icono, cuando]}]}   hasta 3 tarjetas
              Cada elemento aparece cuando se dice su propio texto (o lo que diga "cuando"); si no se encuentra,
              entra escalonado. Iconos: cruz, peso, herramienta, documento, dolor.
    sfx       opcional, true por defecto: click al aparecer cada bloque o gráfico y whoosh al achicarse/agrandarse.

Deja final.mp4 e informe.json en la carpeta de trabajo (CARPETA_TRABAJO).
"""
import difflib
import json
import os
import pathlib
import re
import subprocess
import sys
import unicodedata

import numpy as np
from PIL import Image, ImageFilter

AQUI = pathlib.Path(__file__).resolve().parent
TRABAJO = pathlib.Path(os.environ.get("CARPETA_TRABAJO", "trabajo")).resolve()
SFX = AQUI / "sfx"
W, H, FPS = 1080, 1920, 30
K = 1.2                       # la grabación se trabaja 1,2 veces más grande que el cuadro para acercar sin perder nitidez
SW, SH = round(W * K), round(H * K)
ESCALA_SILUETA = 0.62         # tamaño del abogado recortado respecto del cuadro
MARGEN_ANTES, MARGEN_DESPUES = 0.12, 0.15
PAUSA_INTERNA = 0.55          # pausas más largas que esto dentro de una oración también se cortan
SFX_VOLUMEN = {"whoosh": 0.40, "click": 0.35}


def correr(*args):
    subprocess.run([str(a) for a in args], check=True)


def normalizar(t):
    t = unicodedata.normalize("NFD", str(t).lower())
    return re.sub(r"[^a-z0-9ñ]", "", "".join(c for c in t if unicodedata.category(c) != "Mn"))


def fichas(texto):
    return [n for n in (normalizar(w) for w in str(texto).split()) if n]


def oraciones(guion):
    return [o.strip() for o in re.split(r"(?<=[.?!])\s+", guion.strip()) if o.strip()]


def silencios(wav):
    r = subprocess.run(["ffmpeg", "-i", str(wav), "-af", "silencedetect=noise=-32dB:d=0.4", "-f", "null", "-"],
                       capture_output=True, text=True).stderr
    ini = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r)]
    fin = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r)]
    return list(zip(ini, fin + [1e9] * (len(ini) - len(fin))))


_modelo = None


def transcribir(wav):
    global _modelo
    import wave
    from faster_whisper import WhisperModel
    if _modelo is None:
        _modelo = WhisperModel(os.environ.get("MODELO_WHISPER", "small"), device="cpu", compute_type="int8")
    with wave.open(str(wav)) as f:
        audio = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    segs, _ = _modelo.transcribe(audio, language="es", word_timestamps=True, vad_filter=True)
    return [{"w": w.word.strip(), "s": float(w.start), "e": float(w.end)} for s in segs for w in s.words if w.word.strip()]


def ubicar_oraciones(orac, pal):
    """Para cada oración del guion, el tramo de palabras transcriptas que mejor la dice: (desde, hasta, parecido).
    Se recorre de la última a la primera y se elige siempre la toma más tardía, así una oración repetida queda
    con su última versión."""
    tk = [normalizar(p["w"]) for p in pal]
    limite, res = len(tk), [None] * len(orac)
    for k in range(len(orac) - 1, -1, -1):
        obj = fichas(orac[k])
        n, cands = len(obj), []
        for i in range(limite):
            for largo in {n, n - 1, n + 1, n - 2, n + 2}:
                if largo >= 1 and i + largo <= limite:
                    cands.append((difflib.SequenceMatcher(None, obj, tk[i:i + largo]).ratio(), i, largo))
        if not cands:
            continue
        buenos = [c for c in cands if c[0] >= 0.8]
        if buenos:
            tarde = max(c[1] for c in buenos)
            r, i, largo = max((c for c in buenos if tarde - c[1] <= 2), key=lambda c: (c[0], c[1]))
        else:
            r, i, largo = max(cands)
        res[k] = (i, i + largo, r)
        limite = i
    return res


def tramos_de_corte(ubic, pal, sil, total):
    """Tramos del video original que se conservan: [(desde, hasta, oración)], sin las pausas."""
    tramos, piso = [], 0.0
    for k, u in enumerate(ubic):
        if not u:
            continue
        a, b = pal[u[0]]["s"], pal[u[1] - 1]["e"]
        # El arranque y el final se llevan hasta la pausa más cercana: la transcripción puede marcar la primera
        # palabra antes de tiempo, o dejar afuera del tramo una palabra que entendió distinto que el guion.
        antes = [s for s in sil if s[0] <= a - 0.02 and a - 1.2 <= s[1] <= pal[u[0]]["e"] + 0.4 and s[1] >= piso - 0.2]
        previas = [s[1] for s in antes if s[1] <= a + 0.25]
        ini = ((max(previas) if previas else max(s[1] for s in antes)) - MARGEN_ANTES) if antes else a - 0.1
        tope = pal[ubic[k + 1][0]]["s"] if k + 1 < len(ubic) and ubic[k + 1] else total
        despues = [s for s in sil if pal[u[1] - 1]["s"] <= s[0] <= b + 1.2 and s[0] <= tope + 0.2]
        posteriores = [s[0] for s in despues if s[0] >= b - 0.1]
        fin = ((min(posteriores) if posteriores else min(s[0] for s in despues)) + MARGEN_DESPUES) if despues else b + 0.12
        ini, fin = max(ini, piso, 0.0), min(fin, total)
        cortes = [(s[0] + MARGEN_DESPUES, s[1] - MARGEN_ANTES) for s in sil
                  if s[0] > ini + 0.2 and s[1] < fin - 0.2 and s[1] - s[0] >= PAUSA_INTERNA]
        x = ini
        for c0, c1 in sorted(cortes):
            if c0 - x > 0.2:
                tramos.append((x, c0, k))
            x = max(x, c1)
        if fin - x > 0.2:
            tramos.append((x, fin, k))
        piso = fin
    return tramos


def cortar(origen, tramos, destino):
    """Une los tramos (cuadros enteros). Devuelve [(desde, hasta, oración)] en el tiempo del video cortado."""
    salida, t, partes = [], 0.0, []
    for a, b, k in tramos:
        n = max(1, round((b - a) * FPS))
        a = round(a * FPS) / FPS
        b = a + n / FPS
        partes.append(f"between(t,{a:.4f},{b - 0.5 / FPS:.4f})")
        salida.append((t, t + n / FPS, k))
        t += n / FPS
    sel = "+".join(partes)
    correr("ffmpeg", "-v", "error", "-y", "-i", origen, "-vf", f"select='{sel}',setpts=N/{FPS}/TB",
           "-af", f"aselect='{sel}',asetpts=N/SR/TB", "-r", FPS,
           "-c:v", "libx264", "-preset", "veryfast", "-crf", 15, "-c:a", "aac", "-b:a", "192k", destino)
    return salida


def palabras_del_guion(orac, pal, lapsos):
    """Les pone tiempo a las palabras del guion (que son las que se muestran) según la transcripción del video
    cortado. Devuelve (palabras [{w, s, e, o}], parecido global)."""
    guion = [(w, k) for k, o in enumerate(orac) for w in o.split() if normalizar(w)]
    a, b = [normalizar(w) for w, _ in guion], [normalizar(p["w"]) for p in pal]
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    t = [None] * len(a)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for d in range(i2 - i1):
                t[i1 + d] = pal[j1 + d]["s"]
        elif tag == "replace" and j2 > j1:
            for d in range(i2 - i1):
                t[i1 + d] = pal[min(j2 - 1, j1 + d * (j2 - j1) // (i2 - i1))]["s"]
    limites = {}
    for d, h, k in lapsos:
        limites[k] = (min(limites.get(k, (d, h))[0], d), max(limites.get(k, (d, h))[1], h))
    res = []
    for i, (w, k) in enumerate(guion):
        res.append({"w": w, "s": t[i], "o": k})
    for k in set(x["o"] for x in res):               # completa las que no se encontraron y encierra cada oración
        grupo = [x for x in res if x["o"] == k]
        d, h = limites.get(k, (0, 0))
        conocidos = [(i, x["s"]) for i, x in enumerate(grupo) if x["s"] is not None and d - 0.05 <= x["s"] < h]
        puntos = [(-1, d)] + conocidos + [(len(grupo), h)]
        for i, x in enumerate(grupo):
            izq = max(p for p in puntos if p[0] <= i) if any(p[0] == i for p in conocidos) else max(p for p in puntos if p[0] < i)
            der = min(p for p in puntos if p[0] > i)
            x["s"] = izq[1] if izq[0] == i else izq[1] + (der[1] - izq[1]) * (i - izq[0]) / (der[0] - izq[0])
        grupo[0]["s"] = max(d, min(grupo[0]["s"], d + 0.25)) if len(grupo) else d
    res.sort(key=lambda x: (x["o"], x["s"]))
    for i, x in enumerate(res):
        fin_o = limites.get(x["o"], (0, x["s"] + 0.4))[1]
        x["e"] = res[i + 1]["s"] if i + 1 < len(res) and res[i + 1]["o"] == x["o"] else fin_o
    return res, sm.ratio()


def subtitulos(pal):
    grupos, cur = [], []
    for i, w in enumerate(pal):
        sig = pal[i + 1] if i + 1 < len(pal) else None
        cur.append(w)
        txt = " ".join(x["w"] for x in cur)
        if sig is None or sig["o"] != w["o"] or w["w"][-1] in ".,?!" or len(cur) >= 3 or len(txt) + 1 + len(sig["w"]) > 17:
            grupos.append(cur)
            cur = []
    return [{"s": g[0]["s"], "e": g[-1]["e"], "words": [{"w": x["w"].upper().strip(".,;:"), "s": x["s"], "e": x["e"]} for x in g]}
            for g in grupos]


def cuando(frase, pal, desde=0.0, hasta=1e9):
    """Segundo en que empieza a decirse la frase (sus primeras palabras) entre desde y hasta, o None."""
    obj = fichas(frase)[:4]
    tk = [normalizar(p["w"]) for p in pal]
    for n in range(len(obj), 0, -1):
        for i in range(len(tk) - n + 1):
            if tk[i:i + n] == obj[:n] and desde - 0.01 <= pal[i]["s"] < hasta:
                return pal[i]["s"]
        if n <= 2:
            break
    return None


def linea_de_tiempo(datos, pal, lapsos, total):
    inicio_o = {}
    for d, h, k in lapsos:
        inicio_o.setdefault(k, d)
    def a_oracion(t):                                  # si cae cerca del arranque de una oración, usa ese arranque
        cerca = [d for d in inicio_o.values() if abs(d - t) <= 0.35]
        return min(cerca, key=lambda d: abs(d - t)) if cerca else t
    avisos = []
    graf = []
    for g in datos.get("graficos") or []:
        t = cuando(g.get("ancla", ""), pal)
        if t is None:
            avisos.append(f"No se encontró el ancla del gráfico: {g.get('ancla')}")
            continue
        graf.append((a_oracion(t), g))
    graf.sort(key=lambda x: x[0])
    cierres = []
    for c in datos.get("cierre") or []:
        t = cuando(c.get("ancla", ""), pal)
        if t is None:
            avisos.append(f"No se encontró el ancla del cierre: {c.get('ancla')}")
            continue
        cierres.append((a_oracion(t), c))
    cierres.sort(key=lambda x: x[0])
    pip = [graf[0][0], cierres[0][0] if cierres else total] if graf else [total, total]
    escenas = []
    for i, (s, g) in enumerate(graf):
        e = graf[i + 1][0] if i + 1 < len(graf) else pip[1]
        b = lambda frase, desde=s, alt=None: (lambda r: r if r is not None else alt)(cuando(frase, pal, desde, e) if frase else None)
        tipo = g.get("tipo")
        if tipo == "tachado":
            t = {"entra": s + 0.08, "sello": b(g.get("cuando_sello") or g.get("sello"), s, s + 0.5)}
            t["sello"] = min(max(t["sello"] - 0.1, s + 0.3), e - 0.4)
        elif tipo == "numero":
            n = b(g.get("cuando") or g.get("grande"), s, s + 0.6)
            t = {"chica": s + 0.05, "numero": max(s + 0.2, n - 0.1), "grande": max(s + 0.5, n + 0.2)}
        elif tipo == "causa":
            d = b(g.get("desde"), s, s + 0.6)
            q = b(g.get("etiqueta"), d, d + 0.6)
            t = {"desde": max(s + 0.15, d - 0.15), "etiqueta": q, "hasta": max(q + 0.3, b(g.get("hasta"), q, q + 0.6) - 0.15)}
        elif tipo == "lista":
            items, det, x = [], [], s
            for j, it in enumerate(g.get("items") or []):
                ti = b(it.get("cuando") or it.get("texto"), x, max(x, s + 0.8) + (1.0 if j else 0.0))
                items.append(max(s + 0.3, ti - 0.1))
                det.append(b(it.get("detalle"), ti, ti + 0.8))
                x = ti + 0.2
            t = {"items": items, "detalles": det}
        else:
            avisos.append(f"Tipo de gráfico desconocido: {tipo}")
            continue
        escenas.append({"tipo": tipo, "s": s, "e": e, "d": g, "t": t})
    bloques = []
    if datos.get("gancho"):
        fin_gancho = pip[0] if graf else next((h for d, h, k in lapsos if k == 0), total)
        bloques.append(dict(datos["gancho"], s=0.0, e=fin_gancho - 0.02))
    for i, (s, c) in enumerate(cierres):
        e = cierres[i + 1][0] if i + 1 < len(cierres) else total + 0.2
        bloques.append(dict(c, s=s + (0.35 if i == 0 and graf else 0.0), e=e))
    return {"etiqueta": datos.get("etiqueta", ""), "pip": pip, "escenas": escenas, "bloques": bloques}, avisos


def dibujar_capas(tl, n, f1, f2):
    from playwright.sync_api import sync_playwright
    for capa in ("bg", "fg"):
        (TRABAJO / capa).mkdir(exist_ok=True)
    with sync_playwright() as p:
        nav = p.chromium.launch(args=["--allow-file-access-from-files"])
        for capa, cuadros in (("bg", range(f1, f2)), ("fg", range(n))):
            pag = nav.new_page(viewport={"width": W, "height": H})
            pag.goto(f"file://{AQUI / 'grabado.html'}?layer={capa}")
            pag.evaluate("d => setData(d)", tl)
            pag.wait_for_timeout(400)
            for f in cuadros:
                pag.evaluate("t => setT(t)", f / FPS)
                if capa == "bg":
                    pag.screenshot(path=str(TRABAJO / "bg" / f"{f:05d}.jpg"), type="jpeg", quality=92)
                else:
                    pag.screenshot(path=str(TRABAJO / "fg" / f"{f:05d}.png"), omit_background=True)
            pag.close()
        nav.close()


def suave(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def mezcla(a, b, p):
    return a + (b - a) * p


def componer_cuadros(corte, tl, lapsos, n, f1, f2, destino):
    from rembg import new_session, remove
    hay_pip = f2 > f1
    sesion = new_session("u2net_human_seg") if hay_pip else None
    # acercamientos de las oraciones a pantalla completa: se alternan empuje lento y encuadre más cerrado
    oracion_en = lambda t: next((k for d, h, k in lapsos if d - 1e-6 <= t < h), lapsos[-1][2])
    ini_o, fin_o = {}, {}
    for d, h, k in lapsos:
        ini_o.setdefault(k, d)
        fin_o[k] = h
    orden = {k: i for i, k in enumerate(sorted(set(k for *_, k in lapsos if not (tl["pip"][0] - 0.01 <= ini_o[k] < tl["pip"][1] - 0.01))))}

    def zoom(f):
        t = f / FPS
        if hay_pip and f1 <= f < f2:
            return K
        k = oracion_en(t)
        if orden.get(k, 0) % 2 == 0:
            return mezcla(1.16, 1.23, (t - ini_o[k]) / max(0.1, fin_o[k] - ini_o[k]))
        return 1.27

    def P(f):
        if not hay_pip or f < f1:
            return 0.0
        if f < f2:
            return suave((f - f1) / 15)
        return 1 - suave((f - f2) / 13)

    lee = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(corte), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    escribe = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                                "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", str(destino)],
                               stdin=subprocess.PIPE)
    previa, z_pip = None, K
    for f in range(n):
        crudo = lee.stdout.read(SW * SH * 3)
        if len(crudo) < SW * SH * 3:
            break
        src = Image.frombuffer("RGB", (SW, SH), crudo, "raw", "RGB", 0, 1)
        p = P(f)
        z = zoom(f) if p <= 0 else z_pip
        if p <= 0:
            z_pip = zoom(min(n - 1, f + 1)) if f + 1 == f1 else z_pip
        w0, h0 = W / z, H / z
        x0, y0 = (W - w0) / 2, H - h0
        base = src.resize((W, H), Image.LANCZOS, box=(x0 * K, y0 * K, (x0 + w0) * K, (y0 + h0) * K))
        if p <= 0:
            lienzo = base
        else:
            fondo = Image.open(TRABAJO / "bg" / f"{f:05d}.jpg").convert("RGB")
            lienzo = Image.blend(base, fondo, min(1.0, p * 1.7))
            s = mezcla(z, ESCALA_SILUETA, p)
            ox, oy = mezcla(-x0 * z, -30, p), mezcla(-y0 * z, H - H * ESCALA_SILUETA, p)
            m = np.asarray(remove(src.resize((540, 960), Image.BILINEAR), session=sesion, only_mask=True).convert("L"), np.float32) / 255
            m = np.clip((m - 0.45) / 0.45, 0, 1)
            if previa is not None:
                m = 0.65 * m + 0.35 * previa
            previa = m
            tam = (round(W * s), round(H * s))
            mascara = Image.fromarray((m * 255).astype(np.uint8)).resize(tam, Image.BICUBIC).filter(ImageFilter.GaussianBlur(1.2))
            sombra = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            sombra.paste((28, 28, 28, int(70 * p)), (round(ox) + 14, round(oy) + 10), mascara)
            lienzo = Image.alpha_composite(lienzo.convert("RGBA"), sombra.filter(ImageFilter.GaussianBlur(18))).convert("RGB")
            lienzo.paste(src.resize(tam, Image.LANCZOS), (round(ox), round(oy)), mascara)
        capa = Image.open(TRABAJO / "fg" / f"{f:05d}.png")
        escribe.stdin.write(Image.alpha_composite(lienzo.convert("RGBA"), capa).convert("RGB").tobytes())
    escribe.stdin.close()
    escribe.wait()
    lee.kill()


def sumar_audio(video, corte, tl, datos, destino):
    eventos = []
    if datos.get("sfx", True):
        try:
            meta = json.loads((SFX / "sfx.json").read_text(encoding="utf-8"))
        except Exception:
            meta = {}
        m = re.search(r"\d+", str(datos.get("id", "")))
        semilla, usados = (int(m.group()) if m else 0), {}
        def agregar(tipo, momento):
            tomas = sorted(SFX.glob(f"{tipo}-*.mp3"))
            if tomas:
                a = tomas[(semilla + usados.get(tipo, 0)) % len(tomas)]
                usados[tipo] = usados.get(tipo, 0) + 1
                eventos.append((max(0.0, momento - float(meta.get(a.name, {}).get("pico", 0))), a, SFX_VOLUMEN[tipo]))
        for b in tl["bloques"]:
            agregar("click", b["s"] + 0.12)
        for e in tl["escenas"]:
            agregar("click", e["s"] + 0.15)
        if tl["escenas"]:
            agregar("whoosh", tl["pip"][0] + 0.1)
            agregar("whoosh", tl["pip"][1] + 0.1)
    orden = ["ffmpeg", "-v", "error", "-y", "-i", video, "-i", corte]
    for _, a, _ in eventos:
        orden += ["-i", a]
    if eventos:
        f = "".join(f"[{i + 2}:a]adelay={int(t * 1000)}:all=1,volume={v}[e{i}];" for i, (t, _, v) in enumerate(eventos))
        f += "[1:a]" + "".join(f"[e{i}]" for i in range(len(eventos))) + f"amix=inputs={len(eventos) + 1}:normalize=0:duration=first[a]"
        orden += ["-filter_complex", f, "-map", "0:v", "-map", "[a]"]
    else:
        orden += ["-map", "0:v", "-map", "1:a"]
    correr(*orden, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", destino)


def componer(datos):
    TRABAJO.mkdir(parents=True, exist_ok=True)
    origen = datos.get("video") or os.environ.get("ORIGEN")
    orac = oraciones(datos["guion"])
    print("Preparando la grabación")
    src = TRABAJO / "src.mp4"
    correr("ffmpeg", "-v", "error", "-y", "-i", origen, "-vf", f"scale={SW}:{SH}:force_original_aspect_ratio=increase,crop={SW}:{SH}",
           "-r", FPS, "-c:v", "libx264", "-preset", "veryfast", "-crf", 15, "-c:a", "aac", "-b:a", "192k", src)
    correr("ffmpeg", "-v", "error", "-y", "-i", src, "-ac", 1, "-ar", 16000, TRABAJO / "src.wav")
    total = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(src)],
                                 capture_output=True, text=True).stdout)
    print("Transcribiendo y ubicando las oraciones del guion")
    pal = transcribir(TRABAJO / "src.wav")
    ubic = ubicar_oraciones(orac, pal)
    tramos = tramos_de_corte(ubic, pal, silencios(TRABAJO / "src.wav"), total)
    corte = TRABAJO / "corte.mp4"
    lapsos = cortar(src, tramos, corte)
    correr("ffmpeg", "-v", "error", "-y", "-i", corte, "-ac", 1, "-ar", 16000, TRABAJO / "corte.wav")
    final_t = lapsos[-1][1]
    print(f"Pausas cortadas: de {total:.1f} s a {final_t:.1f} s. Verificando contra el guion")
    pal2 = transcribir(TRABAJO / "corte.wav")
    palabras, parecido = palabras_del_guion(orac, pal2, lapsos)
    tl, avisos = linea_de_tiempo(datos, palabras, lapsos, final_t)
    tl["subs"] = subtitulos(palabras)
    parecida = lambda x, y: difflib.SequenceMatcher(None, x, y).ratio() >= 0.6
    for k, o in enumerate(orac):                       # ¿el corte se comió el arranque o el final de una oración?
        d, h = min((l[0] for l in lapsos if l[2] == k), default=None), max((l[1] for l in lapsos if l[2] == k), default=None)
        dichas = [normalizar(p["w"]) for p in pal2 if d is not None and d - 0.15 <= p["s"] < h - 0.02]
        obj = fichas(o)
        if dichas and obj and not any(parecida(obj[0], x) for x in dichas[:2]):
            avisos.append(f"Revisar el arranque de la oración {k + 1}: {o}")
        if dichas and obj and not any(parecida(obj[-1], x) for x in dichas[-2:]):
            avisos.append(f"Revisar el final de la oración {k + 1}: {o}")
    for k, u in enumerate(ubic):
        if not u:
            avisos.append(f"No se encontró la oración {k + 1}: {orac[k]}")
        elif u[2] < 0.7:
            avisos.append(f"La oración {k + 1} no coincide bien con el guion ({u[2]:.0%}): {orac[k]}")
    n = round(final_t * FPS)
    hay = bool(tl["escenas"])
    f1, f2 = (round(tl["pip"][0] * FPS), min(n, round(tl["pip"][1] * FPS))) if hay else (n, n)
    print("Dibujando gráficos, textos y subtítulos")
    dibujar_capas(tl, n, f1, min(n, f2 + 14) if hay else n)
    print("Componiendo")
    componer_cuadros(corte, tl, lapsos, n, f1, f2, TRABAJO / "mudo.mp4")
    sumar_audio(TRABAJO / "mudo.mp4", corte, tl, datos, TRABAJO / "final.mp4")
    informe = {"id": datos.get("id"), "duracion_original": round(total, 2), "duracion_final": round(final_t, 2),
               "parecido_con_guion": round(parecido, 3), "transcripcion_final": " ".join(p["w"] for p in pal2),
               "oraciones": [{"texto": o, "parecido": round(u[2], 3) if u else 0} for o, u in zip(orac, ubic)],
               "avisos": avisos, "revisar": bool(avisos) or parecido < 0.85}
    (TRABAJO / "informe.json").write_text(json.dumps(informe, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(informe, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    crudo = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8") if len(sys.argv) > 1 else os.environ["PAYLOAD"]
    componer(json.loads(crudo))
