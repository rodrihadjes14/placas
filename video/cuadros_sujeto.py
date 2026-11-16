"""
Herramienta de una sola vez: extrae cuadros limpios (sin placas ni subtítulos) de una grabación de Drive
alrededor de una palabra dicha, para elegir la imagen del sujeto que se usa de fondo en las tapas.
Sube cada cuadro a Cloudinary como sujeto-<ID>-cand-<NN>.jpg y deja la lista en informe.json.
"""
import json, os, pathlib, subprocess, sys
from faster_whisper import WhisperModel

datos = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
origen = os.environ["ORIGEN"]
trabajo = pathlib.Path(os.environ.get("CARPETA_TRABAJO", "/tmp/trabajo"))
palabra = datos.get("palabra", "corte").lower()
wav = trabajo / "audio.wav"
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", origen, "-ac", "1", "-ar", "16000", str(wav)], check=True)
modelo = WhisperModel("small", device="cpu", compute_type="int8")
import wave, numpy as np
with wave.open(str(wav)) as fw:
    audio = np.frombuffer(fw.readframes(fw.getnframes()), dtype=np.int16).astype(np.float32) / 32768
segs, _ = modelo.transcribe(audio, language="es", word_timestamps=True, vad_filter=True)
palabras = [(w.word.strip().lower().strip(",.¿?"), w.start, w.end) for s in segs for w in s.words]
hit = next((p for p in palabras if palabra in p[0]), None)
print("Palabras:", palabras[:40])
if not hit:
    sys.exit(f"No se encontró la palabra {palabra}")
desde, hasta = max(0, hit[1] - 0.6), hit[2] + 0.6
subidos, t, n = [], desde, 0
while t <= hasta:
    f = trabajo / f"cand-{n:02d}.jpg"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", origen, "-frames:v", "1", "-q:v", "2", str(f)], check=True)
    pid = f"sujeto-{datos['id']}-cand-{n:02d}"
    subprocess.run(["curl", "-sS", "-F", f"file=@{f}", "-F", "upload_preset=make-audio", "-F", f"public_id={pid}",
                    "https://api.cloudinary.com/v1_1/dy2gpxfsz/image/upload"], check=False)
    subidos.append({"n": n, "t": round(t, 2), "public_id": pid})
    t += 0.08
    n += 1
(trabajo / "informe.json").write_text(json.dumps({"id": datos["id"], "solo_cuadros": True, "palabra": hit,
                                                  "cuadros": subidos}, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(subidos))
