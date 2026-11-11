#!/usr/bin/env bash
# Deja ffmpeg disponible para el flujo sin que la instalación pueda colgarlo.
# El 11/11/2026 "apt-get install ffmpeg" quedó trabado en GitHub y los montajes esperaban 40 minutos hasta que se
# cancelaban solos. Ahora apt tiene dos minutos y medio; si no responde, se usa el ffmpeg que trae el paquete de
# Python imageio-ffmpeg (no incluye ffprobe: los programas del repo leen la duración con ffmpeg si ffprobe falta).
set -u
if command -v ffmpeg >/dev/null; then ffmpeg -version | head -1; exit 0; fi
if sudo timeout -k 10 150 bash -c 'export DEBIAN_FRONTEND=noninteractive; apt-get update -qq && apt-get install -y -qq ffmpeg' \
   && command -v ffmpeg >/dev/null; then
  ffmpeg -version | head -1; exit 0
fi
echo "apt no respondió: se usa el ffmpeg de imageio-ffmpeg"
PY=$(command -v python || command -v python3)
"$PY" -m pip install -q imageio-ffmpeg || "$PY" -m pip install -q --break-system-packages imageio-ffmpeg || exit 1
mkdir -p "$RUNNER_TEMP/bin"
ln -sf "$("$PY" -c 'import imageio_ffmpeg; print(imageio_ffmpeg.get_ffmpeg_exe())')" "$RUNNER_TEMP/bin/ffmpeg"
echo "$RUNNER_TEMP/bin" >> "$GITHUB_PATH"
"$RUNNER_TEMP/bin/ffmpeg" -version | head -1
