"""
Publica una historia (imagen JPG ya subida a una URL pública) en Instagram y en la página de Facebook
usando la Graph API de Meta, y deja el resultado en un archivo estado.json.

Uso:
    python publicar.py <ID> <URL_IMAGEN> <carpeta_estado> [IG,FB]

Variables de entorno:
    META_TOKEN      token del usuario del sistema publicador-historias o de la página (secreto META_PAGE_TOKEN)
    IG_USER_ID      cuenta de Instagram profesional del estudio
    FB_PAGE_ID      página de Facebook del estudio
    GRAPH_VERSION   versión de la Graph API (por defecto v23.0)

Si estado.json ya registra una red como publicada, no la vuelve a publicar: así un reintento manual
nunca duplica la historia en la red que ya salió bien.
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


def graph(metodo, ruta, token=None, **params):
    params["access_token"] = token or TOKEN
    datos = urllib.parse.urlencode(params).encode()
    if metodo == "GET":
        req = urllib.request.Request(f"{BASE}/{ruta}?{datos.decode()}")
    else:
        req = urllib.request.Request(f"{BASE}/{ruta}", data=datos, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        cuerpo = e.read().decode(errors="replace")
        try:
            msg = json.loads(cuerpo)["error"]["message"]
        except Exception:
            msg = cuerpo[:300]
        raise RuntimeError(f"Graph API {e.code}: {msg}") from None


def publicar_instagram(url):
    contenedor = graph("POST", f"{IG}/media", image_url=url, media_type="STORIES")["id"]
    for _ in range(30):
        estado = graph("GET", contenedor, fields="status_code").get("status_code")
        if estado == "FINISHED":
            break
        if estado in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram no pudo procesar la imagen ({estado})")
        time.sleep(5)
    return graph("POST", f"{IG}/media_publish", creation_id=contenedor)["id"]


def token_pagina():
    # El secreto puede ser un token de usuario del sistema o un token de pagina. Las publicaciones en
    # la pagina exigen token de pagina: si el secreto no lo es, se pide el de la pagina con el.
    try:
        tok = graph("GET", PAGINA, fields="access_token").get("access_token")
    except RuntimeError:
        tok = None
    return tok or TOKEN


def publicar_facebook(url):
    tok = token_pagina()
    foto = graph("POST", f"{PAGINA}/photos", token=tok, url=url, published="false")["id"]
    res = graph("POST", f"{PAGINA}/photo_stories", token=tok, photo_id=foto)
    return res.get("post_id") or res.get("id") or foto


def main():
    ident, url, carpeta = sys.argv[1], sys.argv[2], pathlib.Path(sys.argv[3])
    redes = [r.strip().upper() for r in (sys.argv[4] if len(sys.argv) > 4 else "IG,FB").split(",") if r.strip()]
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / "estado.json"
    estado = json.loads(ruta.read_text(encoding="utf-8")) if ruta.exists() else {}
    estado.update({"id": ident, "imagen": url})
    errores = []

    if not TOKEN:
        errores.append("Falta el secreto META_PAGE_TOKEN en GitHub")
    else:
        for red, funcion, clave in (("IG", publicar_instagram, "ig_id"), ("FB", publicar_facebook, "fb_id")):
            if red not in redes or estado.get(clave):
                continue
            try:
                estado[clave] = funcion(url)
                print(f"{red}: publicada ({estado[clave]})")
            except Exception as e:
                errores.append(f"{red}: {e}")
                print(f"{red}: error: {e}")

    listo = all(estado.get(c) for r, c in (("IG", "ig_id"), ("FB", "fb_id")) if r in redes)
    estado["estado"] = "publicado" if listo else "error"
    estado["error"] = " | ".join(errores)
    estado["fecha"] = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ruta.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")
    sys.exit(0 if listo else 1)


if __name__ == "__main__":
    main()
