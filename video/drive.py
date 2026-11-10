"""
Baja de Google Drive la grabación de un Reel grabado.

Busca en la carpeta "Grabaciones Reels" (variable CARPETA_DRIVE) el archivo que se llama como el ID de la fila
(T114.MOV, t114.mp4, ...) y lo guarda en la ruta del segundo argumento. Usa la cuenta de servicio cuya clave está
en el secreto GOOGLE_DRIVE_SA; esa cuenta solo puede leer esa carpeta.

    python drive.py T114 /ruta/origen.mov
"""
import json
import os
import pathlib
import sys

import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account

API = "https://www.googleapis.com/drive/v3/files"


def bajar(fila, destino):
    cred = service_account.Credentials.from_service_account_info(
        json.loads(os.environ["GOOGLE_DRIVE_SA"]), scopes=["https://www.googleapis.com/auth/drive.readonly"])
    cred.refresh(Request())
    cab = {"Authorization": f"Bearer {cred.token}"}
    carpeta = os.environ["CARPETA_DRIVE"]
    r = requests.get(API, headers=cab, timeout=60, params={
        "q": f"'{carpeta}' in parents and trashed = false", "fields": "files(id,name,size,modifiedTime)", "pageSize": 200})
    r.raise_for_status()
    archivos = [a for a in r.json().get("files", []) if pathlib.Path(a["name"]).stem.strip().lower() == fila.strip().lower()]
    if not archivos:
        sys.exit(f"No hay ninguna grabación llamada {fila} en la carpeta de Drive")
    a = max(archivos, key=lambda x: x["modifiedTime"])
    print(f"Bajando {a['name']} ({int(a.get('size', 0)) / 1e6:.0f} MB)")
    with requests.get(f"{API}/{a['id']}", headers=cab, params={"alt": "media"}, stream=True, timeout=600) as d:
        d.raise_for_status()
        with open(destino, "wb") as f:
            for trozo in d.iter_content(1 << 20):
                f.write(trozo)


if __name__ == "__main__":
    bajar(sys.argv[1], sys.argv[2])
