"""
Arma la versión animada de un post estático y la sube a Cloudinary.

Uso (desde la raíz del repositorio):
    python animado/animar_post.py <ID> <url_de_la_placa_jpg> "<texto de la placa>"

Toma el fondo de la placa JPG aprobada (el neutro más cercano al color de su esquina), renderiza
animado/post.html con ese texto y ese fondo, sube el MP4 a Cloudinary y lo registra en
publicaciones/<ID>/animado.json ({"video": url, "imagen": jpg, "fecha": ...}).
Imprime la dirección del video. Lo usan los workflows animar-post y publicar-pieza.
"""
import datetime
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.request

NEUTROS = {"blanco": (255, 255, 255), "hueso": (244, 241, 236), "carbon": (27, 26, 25)}
VERSION = "hyperframes@0.8.173"


def fondo_de(imagen):
    try:
        from PIL import Image
        with urllib.request.urlopen(imagen, timeout=60) as r:
            px = Image.open(io.BytesIO(r.read())).convert("RGB").getpixel((20, 20))
        return min(NEUTROS, key=lambda k: sum((a - b) ** 2 for a, b in zip(px, NEUTROS[k])))
    except Exception as e:
        print("No se pudo leer el fondo de la placa, se usa hueso:", e, file=sys.stderr)
        return "hueso"


def main():
    ident, imagen, titulo = sys.argv[1].strip().upper(), sys.argv[2].strip(), sys.argv[3].strip()
    if not re.fullmatch(r"T\d{1,4}", ident):
        raise SystemExit(f"ID inválido: {ident!r}")
    if not titulo:
        raise SystemExit("Falta el texto de la placa")
    raiz = pathlib.Path(__file__).resolve().parent.parent
    tmp = pathlib.Path(os.environ.get("RUNNER_TEMP") or tempfile.mkdtemp())
    variables = {"titulo": titulo, "fondo": fondo_de(imagen)}
    (tmp / "post-variables.json").write_text(json.dumps(variables, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(variables, ensure_ascii=False), file=sys.stderr)

    salida = tmp / "post.mp4"
    subprocess.run(["npx", "--yes", VERSION, "browser", "ensure"], cwd=raiz / "animado", check=True,
                   stdout=subprocess.DEVNULL)
    subprocess.run(["npx", "--yes", VERSION, "render", ".", "-c", "post.html", "--format", "mp4",
                    "--variables-file", str(tmp / "post-variables.json"), "-o", str(salida), "--quiet"],
                   cwd=raiz / "animado", check=True)

    sufijo = os.environ.get("GITHUB_RUN_ID") or datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    res = subprocess.run(["curl", "-sS", "--fail-with-body",
                          "-F", f"file=@{salida}", "-F", "upload_preset=make-audio",
                          "-F", f"public_id=animado-{ident}-post-{sufijo}",
                          "https://api.cloudinary.com/v1_1/dy2gpxfsz/video/upload"],
                         check=True, capture_output=True, text=True)
    url = json.loads(res.stdout)["secure_url"]

    carpeta = raiz / "publicaciones" / ident
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "animado.json").write_text(json.dumps({
        "video": url, "imagen": imagen, "titulo": titulo, "fondo": variables["fondo"],
        "fecha": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(url)


if __name__ == "__main__":
    main()
