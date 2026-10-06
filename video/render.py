"""
Genera las placas de video (PNG 1080x1920 con fondo transparente) a partir de un JSON.

Uso:
    python render.py ejemplos.json salida/

El JSON es una lista de placas con el mismo formato de la columna PLACAS_VIDEO.
Cada placa se guarda como placa-01.png, placa-02.png, etc.
Si la placa supera la zona permitida (no puede tapar la cabeza del avatar), el script avisa.
"""
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

AQUI = pathlib.Path(__file__).resolve().parent
PLANTILLA = (AQUI / "plantilla.html").as_uri()
LIMITE_INFERIOR = 740  # px: por debajo empieza la cabeza del avatar


def render(placas, carpeta):
    carpeta = pathlib.Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    generadas = []
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        pag = nav.new_page(viewport={"width": 1080, "height": 1920})
        for i, placa in enumerate(placas, start=1):
            pag.add_init_script("window.PLACA = " + json.dumps(placa, ensure_ascii=False) + ";")
            pag.goto(PLANTILLA)
            pag.evaluate("document.fonts.ready")
            caja = pag.eval_on_selector(".placa", "e => { const r = e.getBoundingClientRect(); return {abajo: r.bottom, alto: e.scrollHeight, visible: e.clientHeight}; }")
            if caja["abajo"] > LIMITE_INFERIOR or caja["alto"] > caja["visible"]:
                print(f"Aviso: la placa {i} es demasiado larga, acortá el texto ({caja})")
            destino = carpeta / f"placa-{i:02d}.png"
            pag.screenshot(path=str(destino), omit_background=True)
            generadas.append(destino)
            pag.close()
            pag = nav.new_page(viewport={"width": 1080, "height": 1920})
        nav.close()
    return generadas


if __name__ == "__main__":
    datos = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    for ruta in render(datos, sys.argv[2] if len(sys.argv) > 2 else "salida"):
        print(ruta)
