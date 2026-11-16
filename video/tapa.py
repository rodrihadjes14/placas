"""
Tapa (cover) del Reel grabado: una imagen diseñada para que el Reel se lea bien en la grilla del perfil y en el feed.

En los informativos (16/11/2026) el fondo es una imagen fija del abogado sin placas ni subtítulos (carpeta sujetos/,
rotan si hay varias). En los de caso real toma un cuadro del gancho en el instante en que la cara está más relajada.
En los dos le suma la etiqueta del tema arriba y el gancho en letras grandes abajo (tapa.html). Deja portada.jpg en la carpeta de trabajo;
el flujo la sube a Cloudinary como final-<ID>-<VIDEO_ID>-portada y el publicador la usa como tapa en Instagram y Facebook.
"""
import pathlib
import re
import urllib.request

from PIL import Image

AQUI = pathlib.Path(__file__).resolve().parent
MODELO_CARA = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
ZOOM = 1.2                                    # mismo encuadre que el gancho del video
SUJETOS = AQUI / "sujetos"                    # imágenes limpias del abogado para las tapas de los informativos


def es_caso(datos):
    """Los Reels de caso real llevan el pie con el tipo de caso ("ACCIDENTE DE TRABAJO - ART") debajo del monto."""
    gancho = datos.get("tapa") or datos.get("gancho") or {}
    return datos.get("tipo") == "caso" or bool(gancho.get("pie"))


def sujeto_para(datos):
    """Imagen del sujeto para la tapa de un informativo (16/11/2026): el abogado sin placas ni subtítulos, ya encuadrado
    a 1080x1920. Si hay varias en sujetos/, rotan según el número del ID de la fila. None si no corresponde o no hay."""
    if es_caso(datos) or datos.get("tapa_sujeto") is False:
        return None
    imagenes = sorted(p for p in SUJETOS.glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    if not imagenes:
        return None
    m = re.search(r"\d+", str(datos.get("id", "")))
    return imagenes[(int(m.group()) if m else 0) % len(imagenes)]


def tension_cara(video, tiempos, trabajo):
    """Puntaje de tensión del gesto para cada tiempo (0 = cara relajada, ojos abiertos, boca cerrada). None donde no hay cara."""
    import cv2
    import mediapipe as mp
    from mediapipe.tasks import python as mpt
    from mediapipe.tasks.python import vision
    modelo = trabajo / "face_landmarker.task"
    if not modelo.exists():
        urllib.request.urlretrieve(MODELO_CARA, modelo)
    detector = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=mpt.BaseOptions(model_asset_path=str(modelo)), output_face_blendshapes=True, num_faces=1))
    cap = cv2.VideoCapture(str(video))
    res = []
    for t in tiempos:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
        ok, cuadro = cap.read()
        r = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(cuadro, cv2.COLOR_BGR2RGB))) if ok else None
        if not r or not r.face_blendshapes:
            res.append(None)
            continue
        b = {c.category_name: c.score for c in r.face_blendshapes[0]}
        par = lambda n: (b.get(n + "Left", 0) + b.get(n + "Right", 0)) / 2
        parpadeo = par("eyeBlink")
        mirada = par("eyeLookDown") + par("eyeLookUp") + b.get("eyeLookOutLeft", 0) + b.get("eyeLookOutRight", 0)
        res.append(b.get("jawOpen", 0) + par("mouthSmile") + par("mouthStretch") + b.get("mouthPucker", 0)
                   + b.get("mouthFunnel", 0) + 0.6 * b.get("browInnerUp", 0) + 0.6 * par("browDown") + par("mouthFrown")
                   + (3.0 * parpadeo if parpadeo > 0.3 else 0.5 * parpadeo) + 0.4 * mirada)
    cap.release()
    return res


def elegir_instante(video, desde, hasta, trabajo):
    """Segundo del gancho con la cara más relajada; si no se puede analizar, el medio del gancho."""
    inicio, fin = desde + 0.15, max(desde + 0.2, hasta - 0.2)
    tiempos = [round(inicio + 0.08 * k, 2) for k in range(int((fin - inicio) / 0.08) + 1)] or [inicio]
    elegido = tiempos[len(tiempos) // 2]
    try:
        puntajes = tension_cara(video, tiempos, trabajo)
        suaves = []
        for i, p in enumerate(puntajes):                 # se suaviza con los vecinos para no caer en un cuadro de transición
            vecinos = [x for x in puntajes[max(0, i - 1):i + 2] if x is not None]
            suaves.append(None if p is None else 0.6 * p + 0.4 * (sum(vecinos) / len(vecinos)))
        validos = [(s, t) for s, t in zip(suaves, tiempos) if s is not None]
        if validos:
            puntaje, elegido = min(validos)
            print(f"Tapa: segundo {elegido} (tensión del gesto {puntaje:.3f} entre {len(validos)} cuadros)")
        else:
            print("Aviso: no se detectó la cara para la tapa; se usa el medio del gancho")
    except Exception as e:
        print(f"Aviso: no se pudo analizar la cara para la tapa ({e}); se usa el medio del gancho")
    return elegido


def cara_en(imagen, trabajo):
    """Dónde está la cara en la imagen: (alto de la frente, alto del mentón), como fracción del alto. None si no se ve."""
    import mediapipe as mp
    import numpy as np
    from mediapipe.tasks import python as mpt
    from mediapipe.tasks.python import vision
    detector = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=mpt.BaseOptions(model_asset_path=str(trabajo / "face_landmarker.task")), num_faces=1))
    r = detector.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(np.asarray(imagen.convert("RGB")))))
    if not r.face_landmarks:
        return None
    ys = [p.y for p in r.face_landmarks[0]]
    return min(ys), max(ys)


def armar(video, desde, hasta, datos, trabajo, ancho=1080, alto=1920, zoom_base=ZOOM):
    """Arma portada.jpg a partir del video ya cortado. Devuelve el segundo elegido.
    El encuadre se ajusta a la cara: si el abogado quedó bajo en el cuadro, se acerca la imagen para que el mentón
    quede por encima del texto del gancho; si ni así alcanza, el gancho sube y va debajo de la etiqueta."""
    import subprocess
    trabajo = pathlib.Path(trabajo)
    sujeto = sujeto_para(datos)
    if sujeto:                                   # informativo: imagen fija del sujeto, ya encuadrada (sin acercar)
        t, zoom_base = None, 1.0
        src = Image.open(sujeto).convert("RGB")
        print(f"Tapa: imagen del sujeto {sujeto.name}")
        modelo = trabajo / "face_landmarker.task"
        if not modelo.exists():
            urllib.request.urlretrieve(MODELO_CARA, modelo)
    else:                                        # caso real: cuadro del gancho con la cara más relajada
        t = elegir_instante(video, desde, hasta, trabajo)
        crudo = trabajo / "tapa-cuadro.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", str(crudo)], check=True)
        src = Image.open(crudo).convert("RGB")
    k = src.width / ancho
    gancho = datos.get("tapa") or datos.get("gancho") or {}
    fondo = trabajo / "tapa-fondo.jpg"
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            nav = p.chromium.launch(args=["--allow-file-access-from-files"])
        except Exception:
            nav = p.chromium.launch(channel="chrome", args=["--allow-file-access-from-files"])
        pag = nav.new_page(viewport={"width": ancho, "height": alto})
        pag.goto(f"file://{AQUI / 'tapa.html'}")
        m = pag.evaluate("d => setData(d)", {"etiqueta": datos.get("etiqueta", ""), "chica": gancho.get("chica", ""),
                                             "grande": gancho.get("grande", "")})
        z, arriba = zoom_base, False
        try:
            cara = cara_en(src, trabajo)
        except Exception as e:
            cara = None
            print(f"Aviso: no se pudo ubicar la cara para encuadrar la tapa ({e})")
        if cara:
            frente, menton = cara[0] * src.height, cara[1] * src.height
            en_tapa = lambda y, zz: alto - (src.height - y) * zz / k          # alto en la tapa de un punto de la grabación
            if en_tapa(menton, z) > m["arriba"] - 36:                          # el texto taparía la cara
                hace_falta = (alto - (m["arriba"] - 36)) * k / max(1.0, src.height - menton)
                if hace_falta <= zoom_base * 1.3 and en_tapa(frente, hace_falta) - 0.35 * (menton - frente) * hace_falta / k > m["bajo_etiqueta"]:
                    z = hace_falta
                else:
                    arriba = True
            print(f"Tapa: acercamiento {z:.2f}, gancho {'arriba' if arriba else 'abajo'}")
        w0, h0 = ancho / z, alto / z
        x0, y0 = (ancho - w0) / 2, alto - h0
        src.resize((ancho, alto), Image.LANCZOS, box=(x0 * k, y0 * k, (x0 + w0) * k, (y0 + h0) * k)).save(fondo, quality=95)
        pag.evaluate("([u, a]) => setFondo(u, a)", [f"file://{fondo}", arriba])
        pag.wait_for_timeout(300)
        pag.screenshot(path=str(trabajo / "portada.jpg"), type="jpeg", quality=93)
        nav.close()
    return t
