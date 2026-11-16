"""Terminación de la placa vertical (placa.html): acercamiento lento, grano y sonido.

Uso: python terminar_placa.py entrada.mp4 salida.mp4

Va aparte de la plantilla por una razón concreta: el navegador acomoda el texto a la grilla de píxeles, así que
un zoom muy lento hecho dentro de la plantilla avanza a saltos de un píxel (se nota en los bordes rectos). Acá
el acercamiento se aplica sobre el cuadro ya dibujado, con interpolación de subpíxel, como un movimiento de
cámara. El grano se suma después del zoom para que no se agrande con él.

Sonidos (assets/sfx-placa, ya recortados al golpe y nivelados entre sí), en los mismos tiempos que la plantilla:
entrada 0 s, banda amarilla 0,70 s, llamado 1,19 s y salida 5,50 s.
"""
import os
import re
import subprocess
import sys

import numpy as np
from PIL import Image

AQUI = os.path.dirname(os.path.abspath(__file__))
SFX = os.path.join(AQUI, "assets", "sfx-placa")
ZOOM = 0.04           # acercamiento total a lo largo de la pieza
CENTRO = (0.30, 0.40)  # punto hacia el que se acerca (sobre el título)
GRANO = 0.11          # intensidad del grano (mezcla tipo "superponer")
SONIDOS = [("entrada.wav", 0.00), ("banda.wav", 0.70), ("llamado.wav", 1.19), ("salida.wav", 5.50)]


def datos(video):
    """Tamaño, cuadros por segundo y duración leídos de ffmpeg (ffprobe puede no estar)."""
    err = subprocess.run(["ffmpeg", "-hide_banner", "-i", video], capture_output=True, text=True).stderr
    w, h = map(int, re.search(r"Video:.*?\s(\d{3,5})x(\d{3,5})", err).groups())
    fps = float(re.search(r"([\d.]+)\s*fps", err).group(1))
    hh, mm, ss = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", err).groups()
    return w, h, fps, int(hh) * 3600 + int(mm) * 60 + float(ss)


def main(entrada, salida):
    w, h, fps, dur = datos(entrada)
    total = max(2, round(dur * fps))
    cx, cy = CENTRO[0] * w, CENTRO[1] * h

    lee = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-i", entrada, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           stdout=subprocess.PIPE)
    orden = ["ffmpeg", "-y", "-loglevel", "error",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", f"{fps:g}", "-i", "-"]
    filtros, mezcla = [], []
    for i, (nombre, t) in enumerate(SONIDOS):
        orden += ["-i", os.path.join(SFX, nombre)]
        ms = int(round(t * 1000))
        filtros.append(f"[{i + 1}:a]adelay={ms}|{ms}[a{i}]")
        mezcla.append(f"[a{i}]")
    filtros.append("".join(mezcla) + f"amix=inputs={len(SONIDOS)}:normalize=0,apad[a]")
    orden += ["-filter_complex", ";".join(filtros), "-map", "0:v", "-map", "[a]",
              "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p",
              "-c:a", "aac", "-b:a", "192k", "-t", f"{dur:.3f}", "-movflags", "+faststart", salida]
    escribe = subprocess.Popen(orden, stdin=subprocess.PIPE)

    gw, gh = w // 2, h // 2
    i = 0
    while True:
        crudo = lee.stdout.read(w * h * 3)
        if len(crudo) < w * h * 3:
            break
        s = 1 + ZOOM * min(i, total - 1) / (total - 1)
        cuadro = Image.frombytes("RGB", (w, h), crudo).transform(
            (w, h), Image.AFFINE, (1 / s, 0, cx - cx / s, 0, 1 / s, cy - cy / s), resample=Image.BICUBIC)
        base = np.asarray(cuadro, dtype=np.float32) / 255
        ruido = np.random.default_rng(i + 1).integers(0, 256, (gh, gw), dtype=np.uint8)
        g = (np.asarray(Image.fromarray(ruido).resize((w, h), Image.BILINEAR), dtype=np.float32) / 255)[..., None]
        sup = np.where(base < 0.5, 2 * base * g, 1 - 2 * (1 - base) * (1 - g))
        final = np.clip(base + GRANO * (sup - base), 0, 1)
        escribe.stdin.write((final * 255 + 0.5).astype(np.uint8).tobytes())
        i += 1
    escribe.stdin.close()
    lee.wait()
    if escribe.wait() != 0 or i == 0:
        sys.exit("No se pudo terminar la placa")
    print(f"placa terminada: {i} cuadros, {dur:.2f} s")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
