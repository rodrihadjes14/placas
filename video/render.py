"""
Genera las placas de video (PNG 1080x1920 con fondo transparente) a partir de un JSON.

Uso:
    python render.py ejemplos.json salida/

El JSON es una lista de placas con el mismo formato de la columna PLACAS_VIDEO.
Cada placa se guarda como placa-01.png, placa-02.png, etc.

Campos internos opcionales (los agrega componer.py):
    _top        posición vertical de la placa en píxeles
    _compacta   true para la versión chica (sobre el pecho)
"""
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

AQUI = pathlib.Path(__file__).resolve().parent
PLANTILLA = (AQUI / "plantilla.html").as_uri()


def render(placas, carpeta, prefijo="placa"):
    """Devuelve una lista de dicts: {ruta, arriba, abajo, alto, recortada}."""
    carpeta = pathlib.Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    res = []
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        for i, placa in enumerate(placas, start=1):
            pag = nav.new_page(viewport={"width": 1080, "height": 1920})
            pag.add_init_script("window.PLACA = " + json.dumps(placa, ensure_ascii=False) + ";")
            pag.goto(PLANTILLA)
            pag.evaluate("document.fonts.ready")
            caja = pag.eval_on_selector(
                ".placa",
                "e => { const r = e.getBoundingClientRect(); return {arriba: r.top, abajo: r.bottom, alto: r.height, recortada: e.scrollHeight > e.clientHeight + 1}; }",
            )
            destino = carpeta / f"{prefijo}-{i:02d}.png"
            pag.screenshot(path=str(destino), omit_background=True)
            caja["ruta"] = destino
            res.append(caja)
            pag.close()
        nav.close()
    return res


if __name__ == "__main__":
    datos = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    for r in render(datos, sys.argv[2] if len(sys.argv) > 2 else "salida"):
        aviso = "  (texto demasiado largo, acortalo)" if r["recortada"] else ""
        print(f"{r['ruta']}  alto {r['alto']:.0f}px{aviso}")
