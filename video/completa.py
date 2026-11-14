"""
Reel grabado a pantalla completa (desde el 14/11/2026): el abogado se filma leyendo el guion y el video final lo
muestra a pantalla completa todo el tiempo, con bloques de texto arriba de la cabeza, hasta dos clips de b-roll y
subtítulos. Es la unión de los dos montajes que ya existían:

  - de grabado.py toma la primera mitad: transcribe la grabación, ubica cada oración del guion, corta las pausas y
    les pone tiempo a las palabras del guion;
  - de componer.py toma la segunda: el modo de texto animado (bloques de gancho, frases clave y CTA, b-roll,
    subtítulos en mayúscula con pop in, efectos de sonido y tapa).

No recorta la silueta ni dibuja gráficos de fondo: para eso está grabado.py.

Recibe un JSON (variable de entorno PAYLOAD o archivo en el primer argumento):
    id        ID de la fila (AD-01, T130)
    video_id  identificador de esta composición; el resultado se sube como final-<id>-<video_id>
    video     archivo de la grabación (si falta, usa la variable de entorno ORIGEN)
    guion     el guion textual que se leyó
    animado   textos de pantalla y b-roll, con el formato de la columna ANIMADO:
              {"gancho": {"chica", "grande"[, "pie"]}, "claves": [{"chica", "grande", "ancla"}], "cta": {"chica", "grande"},
               "broll": [{"ancla", "clip", "url"}], "titulo_fijo": true|false}
              Con "titulo_fijo": true el bloque del gancho queda arriba durante todo el video (título de los
              anuncios y Reels de caso) y no se muestran frases clave ni CTA.
    sfx       opcional, true por defecto.
    billetes  opcional, true por defecto: lluvia de billetes cuando el gancho trae un monto ("$ 23.000.000").

Deja final.mp4, portada.jpg e informe.json en la carpeta de trabajo (CARPETA_TRABAJO).
"""
import difflib
import json
import os
import pathlib
import sys

import grabado as g
import componer as montaje

W, H = 1080, 1920


def armar(datos):
    trabajo = g.TRABAJO
    trabajo.mkdir(parents=True, exist_ok=True)
    try:
        _armar(datos, trabajo)
    except BaseException as err:
        import traceback
        g.etapa("ERROR", error=str(err)[:500], traza=traceback.format_exc()[-1500:])
        raise


def _armar(datos, trabajo):
    origen = datos.get("video") or os.environ.get("ORIGEN")
    orac = g.oraciones(datos["guion"])
    g.etapa("Preparando la grabación")
    src = trabajo / "src.mp4"
    g.correr("ffmpeg", "-v", "error", "-y", "-i", origen, "-vf",
             f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}",
             "-r", g.FPS, "-c:v", "libx264", "-preset", "veryfast", "-crf", 15, "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "192k", src)
    g.correr("ffmpeg", "-v", "error", "-y", "-i", src, "-ac", 1, "-ar", 16000, trabajo / "src.wav")
    total = g.duracion_de(src)

    g.etapa("Transcribiendo y ubicando las oraciones del guion", duracion_original=round(total, 2))
    pal = g.transcribir(trabajo / "src.wav")
    ubic = g.ubicar_oraciones(orac, pal)
    tramos = g.tramos_de_corte(ubic, pal, g.silencios(trabajo / "src.wav"), total)
    g.etapa("Cortando", tramos=[[round(a, 2), round(b, 2), k] for a, b, k in tramos])
    corte, voz = trabajo / "corte.mp4", trabajo / "voz.wav"
    lapsos = g.cortar(src, tramos, corte, voz)
    g.correr("ffmpeg", "-v", "error", "-y", "-i", voz, "-ac", 1, "-ar", 16000, trabajo / "corte.wav")
    final_t = lapsos[-1][1]
    for nombre, archivo in (("video", corte), ("audio", voz)):
        if abs(g.duracion_de(archivo) - final_t) > 0.25:
            raise RuntimeError(f"El corte salió mal: el {nombre} dura {g.duracion_de(archivo):.2f} s y debería durar {final_t:.2f} s")
    print(f"Pausas cortadas: de {total:.1f} s a {final_t:.1f} s. Verificando contra el guion")

    pal2 = g.transcribir(trabajo / "corte.wav")
    palabras, parecido = g.palabras_del_guion(orac, pal2, lapsos)
    avisos = []
    parecida = lambda x, y: difflib.SequenceMatcher(None, x, y).ratio() >= 0.6
    for k, o in enumerate(orac):                       # ¿el corte se comió el arranque o el final de una oración?
        d = min((l[0] for l in lapsos if l[2] == k), default=None)
        h = max((l[1] for l in lapsos if l[2] == k), default=None)
        dichas = [g.normalizar(p["w"]) for p in pal2 if d is not None and d - 0.15 <= p["s"] < h - 0.02]
        obj = g.fichas(o)
        if dichas and obj and not any(parecida(obj[0], x) for x in dichas[:2]):
            avisos.append(f"Revisar el arranque de la oración {k + 1}: {o}")
        if dichas and obj and not any(parecida(obj[-1], x) for x in dichas[-2:]):
            avisos.append(f"Revisar el final de la oración {k + 1}: {o}")
    for k, u in enumerate(ubic):
        if not u:
            avisos.append(f"No se encontró la oración {k + 1}: {orac[k]}")
        elif u[2] < 0.7:
            avisos.append(f"La oración {k + 1} no coincide bien con el guion ({u[2]:.0%}): {orac[k]}")

    g.etapa("Uniendo el video cortado con la voz")
    entrada = trabajo / "completa.mp4"
    g.correr("ffmpeg", "-v", "error", "-y", "-i", corte, "-i", voz, "-map", "0:v", "-map", "1:a",
             "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", entrada)

    animado = datos.get("animado") or {}
    if isinstance(animado, str):
        animado = json.loads(animado)
    tiempos = [{"w": p["w"], "s": round(float(p["s"]), 3), "e": round(float(p["e"]), 3)} for p in palabras]
    g.etapa("Componiendo: texto de pantalla, b-roll y subtítulos",
            bloques=len(animado.get("claves") or []) + bool(animado.get("gancho")) + bool(animado.get("cta")),
            broll=len(animado.get("broll") or []), titulo_fijo=bool(animado.get("titulo_fijo")))
    para_montaje = {"id": datos.get("id"), "video_id": datos.get("video_id"), "animado": animado,
                    "sfx": datos.get("sfx", True), "billetes": datos.get("billetes", True)}
    montaje.componer_texto(para_montaje, entrada, tiempos, montaje.duracion(entrada))

    final = trabajo / "final.mp4"
    if abs(g.duracion_de(final) - final_t) > 0.4:
        raise RuntimeError("El video final no dura lo que debería")
    informe = {"id": datos.get("id"), "modo": "pantalla completa", "duracion_original": round(total, 2),
               "duracion_final": round(final_t, 2), "parecido_con_guion": round(parecido, 3),
               "transcripcion_final": " ".join(p["w"] for p in pal2),
               "oraciones": [{"texto": o, "parecido": round(u[2], 3) if u else 0} for o, u in zip(orac, ubic)],
               "tramos": [[round(a, 2), round(b, 2), k] for a, b, k in tramos],
               "etapas": g.ETAPAS, "avisos": avisos, "revisar": bool(avisos) or parecido < 0.85}
    (trabajo / "informe.json").write_text(json.dumps(informe, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(informe, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    crudo = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8") if len(sys.argv) > 1 else os.environ["PAYLOAD"]
    armar(json.loads(crudo))
