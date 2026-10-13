"""
Genera la placa de una historia (JPG 1080x1920) a partir de un JSON.

Uso:
    python generar.py historia.json salida.jpg

El JSON trae los campos de la pestaña Historias:
    id        ID de la historia (por ejemplo T63)
    tipo      dato | mito | recordatorio | pregunta (define la etiqueta de arriba)
    texto     frase principal; la frase clave va entre *asteriscos* y se resalta en amarillo
    detalle   opcional: una o dos oraciones de apoyo
    fondo     carbon | hueso | blanco | amarillo

Si el texto no entra en la zona segura de la historia, termina con error en lugar de
publicar una placa cortada.
"""
import json
import pathlib
import sys

from playwright.sync_api import sync_playwright

AQUI = pathlib.Path(__file__).resolve().parent
PLANTILLA = (AQUI / "plantilla.html").as_uri()


def generar(historia, destino):
    destino = pathlib.Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        nav = pw.chromium.launch()
        pag = nav.new_page(viewport={"width": 1080, "height": 1920})
        pag.add_init_script("window.HISTORIA = " + json.dumps(historia, ensure_ascii=False) + ";")
        pag.goto(PLANTILLA)
        pag.evaluate("document.fonts.ready")
        pag.wait_for_function("document.getElementById('logo').complete")
        desborde = pag.evaluate(
            "() => { const c = document.getElementById('contenido'); return c.scrollHeight > c.clientHeight + 1; }"
        )
        if desborde:
            nav.close()
            raise SystemExit("El texto de la historia no entra en la placa: acortá TEXTO o DETALLE.")
        pag.screenshot(path=str(destino), type="jpeg", quality=92)
        nav.close()
    return destino


if __name__ == "__main__":
    datos = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(generar(datos, sys.argv[2] if len(sys.argv) > 2 else "historia.jpg"))
