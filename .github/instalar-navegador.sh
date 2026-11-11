#!/usr/bin/env bash
# Instala el navegador de Playwright sin que la instalación pueda colgar el flujo: primero con los paquetes del
# sistema (usa apt, con tope de cuatro minutos) y, si no responde, solo el navegador (el equipo de GitHub ya trae
# las bibliotecas que necesita).
set -u
PY=$(command -v python || command -v python3)
timeout -k 10 240 "$PY" -m playwright install --with-deps chromium || "$PY" -m playwright install chromium
