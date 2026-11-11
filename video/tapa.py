"""
Tapa (cover) del Reel grabado: una imagen diseñada para que el Reel se lea bien en la grilla del perfil y en el feed.

Toma un cuadro del gancho (el abogado a pantalla completa) en el instante en que la cara está más relajada, y le suma
la etiqueta del tema arriba y el gancho en letras grandes abajo (tapa.html). Deja portada.jpg en la carpeta de trabajo;
el flujo la sube a Cloudinary como final-<ID>-<VIDEO_ID>-portada y el publicador la usa como tapa en Instagram y Facebook.
"""
import pathlib
import urllib.request

from PIL import Image

AQUI = pathlib.Path(__file__).resolve().parent
MODELO_CARA = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
ZOOM = 1.2                                    # mismo encuadre que el gancho del video


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


def armar(video, desde, hasta, datos, trabajo, ancho=1080, alto=1920):
    """Arma portada.jpg a partir del video ya cortado. Devuelve el segundo elegido."""
    import subprocess
    trabajo = pathlib.Path(trabajo)
    t = elegir_instante(video, desde, hasta, trabajo)
    crudo = trabajo / "tapa-cuadro.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", str(crudo)], check=True)
    src = Image.open(crudo).convert("RGB")
    k = src.width / ancho
    w0, h0 = ancho / ZOOM, alto / ZOOM
    x0, y0 = (ancho - w0) / 2, alto - h0
    fondo = trabajo / "tapa-fondo.jpg"
    src.resize((ancho, alto), Image.LANCZOS, box=(x0 * k, y0 * k, (x0 + w0) * k, (y0 + h0) * k)).save(fondo, quality=95)
    gancho = datos.get("tapa") or datos.get("gancho") or {}
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        try:
            nav = p.chromium.launch(args=["--allow-file-access-from-files"])
        except Exception:
            nav = p.chromium.launch(channel="chrome", args=["--allow-file-access-from-files"])
        pag = nav.new_page(viewport={"width": ancho, "height": alto})
        pag.goto(f"file://{AQUI / 'tapa.html'}")
        pag.evaluate("d => setData(d)", {"fondo": f"file://{fondo}", "etiqueta": datos.get("etiqueta", ""),
                                          "chica": gancho.get("chica", ""), "grande": gancho.get("grande", "")})
        pag.wait_for_timeout(300)
        pag.screenshot(path=str(trabajo / "portada.jpg"), type="jpeg", quality=93)
        nav.close()
    return t
