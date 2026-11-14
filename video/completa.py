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
               "broll": [{"ancla", "clip", "url"}], "titulo_fijo": true|false, "broll_libre": true|false}
              Con "broll_libre": true admite hasta seis clips, y cada uno entra cuando se dice su ancla.
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
VOZ_DESDE_HZ = 1000           # la voz se busca por encima de esta frecuencia
VOZ_PAUSA = 0.30              # segundos sin voz para que cuente como pausa


def silencios_de_voz(wav):
    """Pausas del audio medidas solo en las frecuencias altas (más de 1 kHz), donde hay voz pero no respiración.

    El detector de grabado.py mide el volumen total: una respiración o un golpe de aire después de la última palabra
    suena y se toma como parte de la oración, así que el corte queda hasta un segundo tarde (14/11/2026, anuncios
    AD-02 y AD-03). Esos ruidos están por debajo de 1 kHz; la voz siempre tiene energía por encima. El umbral es
    relativo al volumen de la propia grabación. Devuelve [(desde, hasta)] como grabado.silencios()."""
    import wave
    import numpy as np
    with wave.open(str(wav)) as f:
        sr = f.getframerate()
        x = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    n = int(sr * 0.02)
    ventana, frec = np.hanning(2 * n), np.fft.rfftfreq(2 * n, 1 / sr)
    alta = frec >= VOZ_DESDE_HZ
    energia = np.array([10 * np.log10((np.abs(np.fft.rfft(x[i:i + 2 * n] * ventana)) ** 2)[alta].sum() / (n * n) + 1e-10)
                        for i in range(0, len(x) - 2 * n, n)])
    if not len(energia):
        return []
    umbral = max(np.percentile(energia, 95) - 32, np.percentile(energia, 10) + 10)
    mudo, res, i = energia < umbral, [], 0
    while i < len(mudo):
        if mudo[i]:
            j = i
            while j < len(mudo) and mudo[j]:
                j += 1
            if (j - i) * 0.02 >= VOZ_PAUSA:
                res.append((round(i * 0.02 + 0.01, 3), round(j * 0.02 + 0.01, 3)))
            i = j
        else:
            i += 1
    return res


def ajustar_finales(ubic, pal, sil):
    """La transcripción a veces estira la última palabra de una oración hasta después de la respiración. Acá se la
    termina donde de verdad se calla la voz, para que tramos_de_corte() corte ahí."""
    for u in ubic:
        if not u:
            continue
        p = pal[u[1] - 1]
        minimo = p["s"] + min(0.5, 0.045 * len(g.normalizar(p["w"])))
        candidatas = [s0 for s0, _ in sil if s0 >= minimo]
        if candidatas and candidatas[0] < p["e"]:
            p["e"] = candidatas[0]


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
    pausas = silencios_de_voz(trabajo / "src.wav")
    ajustar_finales(ubic, pal, pausas)
    tramos = g.tramos_de_corte(ubic, pal, pausas, total)
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
