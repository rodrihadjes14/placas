"""
Publica una pieza aprobada (post estático, carrusel o Reel) en Instagram y en la página de Facebook
usando la Graph API de Meta. Reemplaza al escenario "Post On Social Media" de Make.

Uso:
    python publicar.py pieza.json <carpeta_estado>            publica
    python publicar.py pieza.json <carpeta_estado> --validar  solo revisa token, cuentas y archivos

pieza.json:
    id        ID de la fila en Aprobación (por ejemplo T62)
    formato   "Post estatico", "Carrusel" o "Reel" (columna FORMATO)
    caption   texto de la publicación (COPY o GUION, más los HASHTAGS)
    media     lista de direcciones: placas de IMAGENES (post y carrusel) o el VIDEO_URL (Reel).
              En un post, si la primera es un .mp4 (el post animado que arma publicar-pieza), se
              publica como video: Reel en Instagram (también aparece en el feed) y video en Facebook.
    redes     "IG,FB" por defecto

Variables de entorno: META_TOKEN (secreto META_PAGE_TOKEN), IG_USER_ID, FB_PAGE_ID, GRAPH_VERSION.

Deja el resultado en <carpeta_estado>/estado.json. Si una red ya figura publicada ahí, no la vuelve a
publicar: un reintento solo completa la red que faltó, nunca duplica.
"""
import datetime
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

VERSION = os.environ.get("GRAPH_VERSION", "v23.0")
BASE = f"https://graph.facebook.com/{VERSION}"
TOKEN = os.environ.get("META_TOKEN", "")
IG = os.environ.get("IG_USER_ID", "")
PAGINA = os.environ.get("FB_PAGE_ID", "")
_token_pagina = None


def pedir(url, datos=None, cabeceras=None, metodo=None):
    req = urllib.request.Request(url, data=datos, headers=cabeceras or {}, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            cuerpo = r.read().decode()
            return json.loads(cuerpo) if cuerpo else {}
    except urllib.error.HTTPError as e:
        cuerpo = e.read().decode(errors="replace")
        try:
            msg = json.loads(cuerpo)["error"]["message"]
        except Exception:
            msg = cuerpo[:300]
        raise RuntimeError(f"Graph API {e.code}: {msg}") from None


def graph(metodo, ruta, token=None, **params):
    params["access_token"] = token or TOKEN
    datos = urllib.parse.urlencode(params)
    if metodo == "GET":
        return pedir(f"{BASE}/{ruta}?{datos}")
    return pedir(f"{BASE}/{ruta}", datos.encode(), metodo="POST")


def token_pagina():
    """Token de la página, obtenido con el token del usuario del sistema (o el mismo si ya es de página)."""
    global _token_pagina
    if _token_pagina is None:
        try:
            _token_pagina = graph("GET", PAGINA, fields="access_token").get("access_token") or TOKEN
        except RuntimeError:
            _token_pagina = TOKEN
    return _token_pagina


# ---------- Instagram ----------

def esperar_contenedor(contenedor, minutos):
    limite = time.time() + minutos * 60
    while time.time() < limite:
        estado = graph("GET", contenedor, fields="status_code").get("status_code")
        if estado == "FINISHED":
            return
        if estado in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram no pudo procesar el archivo ({estado})")
        time.sleep(10)
    raise RuntimeError("Instagram tardó demasiado en procesar el archivo")


def es_video(url):
    return urllib.parse.urlparse(url).path.lower().endswith((".mp4", ".mov"))


def ig_post(media, caption):
    if es_video(media[0]):
        return ig_reel(media, caption)
    c = graph("POST", f"{IG}/media", image_url=media[0], caption=caption)["id"]
    esperar_contenedor(c, 3)
    return graph("POST", f"{IG}/media_publish", creation_id=c)["id"]


def ig_carrusel(media, caption):
    if not 2 <= len(media) <= 10:
        raise RuntimeError(f"Un carrusel de Instagram lleva de 2 a 10 imágenes y esta pieza tiene {len(media)}")
    hijos = []
    for url in media:
        h = graph("POST", f"{IG}/media", image_url=url, is_carousel_item="true")["id"]
        esperar_contenedor(h, 3)
        hijos.append(h)
    c = graph("POST", f"{IG}/media", media_type="CAROUSEL", children=",".join(hijos), caption=caption)["id"]
    esperar_contenedor(c, 3)
    return graph("POST", f"{IG}/media_publish", creation_id=c)["id"]


def ig_reel(media, caption):
    c = graph("POST", f"{IG}/media", media_type="REELS", video_url=media[0], caption=caption,
              share_to_feed="true")["id"]
    esperar_contenedor(c, 15)
    return graph("POST", f"{IG}/media_publish", creation_id=c)["id"]


# ---------- Facebook ----------

def fb_post(media, caption):
    if es_video(media[0]):
        return fb_video(media, caption)
    res = graph("POST", f"{PAGINA}/photos", token=token_pagina(), url=media[0], message=caption)
    return res.get("post_id") or res["id"]


def fb_video(media, caption):
    """Video común de la página (admite el formato vertical 4:5 de las placas, a diferencia del Reel)."""
    url = f"https://graph-video.facebook.com/{VERSION}/{PAGINA}/videos"
    datos = urllib.parse.urlencode({"access_token": token_pagina(), "file_url": media[0],
                                    "description": caption, "published": "true"}).encode()
    return pedir(url, datos, metodo="POST")["id"]


def fb_carrusel(media, caption):
    tok = token_pagina()
    fotos = [graph("POST", f"{PAGINA}/photos", token=tok, url=u, published="false")["id"] for u in media]
    params = {f"attached_media[{i}]": json.dumps({"media_fbid": f}) for i, f in enumerate(fotos)}
    return graph("POST", f"{PAGINA}/feed", token=tok, message=caption, **params)["id"]


def fb_reel(media, caption, registrar=None):
    tok = token_pagina()
    inicio = graph("POST", f"{PAGINA}/video_reels", token=tok, upload_phase="start")
    video_id = inicio["video_id"]
    subida = inicio.get("upload_url") or f"https://rupload.facebook.com/video-upload/{VERSION}/{video_id}"
    pedir(subida, b"", {"Authorization": f"OAuth {tok}", "file_url": media[0]}, metodo="POST")
    graph("POST", f"{PAGINA}/video_reels", token=tok, upload_phase="finish", video_id=video_id,
          video_state="PUBLISHED", description=caption)
    # Con "finish" aceptado, Facebook ya tiene el Reel y lo publica solo. Se registra el ID en este
    # momento para que, pase lo que pase con la consulta de estado, un reintento nunca lo vuelva a subir.
    if registrar:
        registrar(video_id)
    # La consulta de estado es solo informativa: justo después de "finish" Facebook puede responder
    # "Object ... does not exist" durante un rato (el 19/10 eso marcó como fallido un Reel que sí salió).
    limite = time.time() + 15 * 60
    while time.time() < limite:
        try:
            st = graph("GET", video_id, token=tok, fields="status").get("status", {})
        except RuntimeError as e:
            print(f"FB: consulta de estado no disponible todavía ({e}); se reintenta")
            time.sleep(15)
            continue
        if st.get("video_status") == "error":
            raise RuntimeError("Facebook no pudo procesar el Reel: " + json.dumps(st)[:200])
        if (st.get("publishing_phase") or {}).get("status") == "complete" or st.get("video_status") == "ready":
            return video_id
        time.sleep(10)
    print("FB: no se pudo confirmar el estado del Reel; se da por publicado porque Facebook aceptó la subida")
    return video_id


FUNCIONES = {
    "post": {"IG": ig_post, "FB": fb_post},
    "carrusel": {"IG": ig_carrusel, "FB": fb_carrusel},
    "reel": {"IG": ig_reel, "FB": fb_reel},
}


def tipo(formato):
    f = str(formato).strip().lower()
    if f.startswith("reel"):
        return "reel"
    if f.startswith("carrusel"):
        return "carrusel"
    if f.startswith("post"):
        return "post"
    raise RuntimeError(f"Formato no soportado: {formato!r}")


def tipo_seguro(formato):
    try:
        return tipo(formato)
    except RuntimeError:
        return ""


def validar(pieza):
    """Revisa sin publicar: token, cuentas y que los archivos estén accesibles."""
    print("Usuario del token:", graph("GET", "me", fields="id,name").get("name"))
    print("Instagram:", graph("GET", IG, fields="username").get("username"))
    print("Página:", graph("GET", PAGINA, token=token_pagina(), fields="name").get("name"))
    for url in pieza["media"]:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=60) as r:
            print("Archivo OK:", r.status, r.headers.get("Content-Type"), url)


def main():
    pieza = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    carpeta = pathlib.Path(sys.argv[2])
    if "--validar" in sys.argv:
        validar(pieza)
        return
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / "estado.json"
    estado = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}
    redes = [r.strip().upper() for r in str(pieza.get("redes") or "IG,FB").split(",") if r.strip()]
    errores = []
    try:
        t = tipo(pieza["formato"])
        if not pieza.get("media"):
            raise RuntimeError("La pieza no tiene imágenes ni video")
        if not TOKEN:
            raise RuntimeError("Falta el secreto META_PAGE_TOKEN en GitHub")
        for red in redes:
            clave = red.lower() + "_id"
            if estado.get(clave):
                continue
            try:
                funcion = FUNCIONES[t][red]
                if funcion is fb_reel:
                    def registrar(vid, clave=clave):
                        estado[clave] = vid
                        ruta.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")
                    estado[clave] = funcion(pieza["media"], pieza.get("caption", ""), registrar)
                else:
                    estado[clave] = funcion(pieza["media"], pieza.get("caption", ""))
                print(f"{red}: publicada ({estado[clave]})")
                ruta.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as e:
                errores.append(f"{red}: {e}")
                print(f"{red}: error: {e}")
    except Exception as e:
        errores.append(str(e))
    listo = not errores and all(estado.get(r.lower() + "_id") for r in redes)
    # El video del post animado queda registrado para que el envío a TikTok use el mismo archivo
    if pieza.get("media") and es_video(pieza["media"][0]) and tipo_seguro(pieza.get("formato")) == "post":
        estado["video"] = pieza["media"][0]
    estado.update({
        "id": pieza.get("id"),
        "formato": pieza.get("formato"),
        "estado": "publicado" if listo else "error",
        "error": " | ".join(errores),
        "fecha": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    ruta.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.exit(0 if listo else 1)


if __name__ == "__main__":
    main()
