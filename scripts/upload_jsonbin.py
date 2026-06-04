"""
Script para subir los datos iniciales (usuarios.json, reservas.json, canchas.json)
a un bin de JSONBin.io.

Uso:
  python3 scripts/upload_jsonbin.py

Antes de ejecutar:
  1. Crear cuenta en https://jsonbin.io
  2. Copiar tu X-Master-Key desde tu perfil
  3. Crear un nuevo bin vacio (puede tener {} adentro al principio)
  4. Copiar el Bin ID del bin recien creado
  5. Exportar las variables:
       export JSONBIN_BIN_ID=tu-bin-id
       export JSONBIN_MASTER_KEY=tu-master-key
"""
import json
import os
import sys
from pathlib import Path

import httpx

BIN_ID = os.environ.get("JSONBIN_BIN_ID")
MASTER_KEY = os.environ.get("JSONBIN_MASTER_KEY")

if not BIN_ID or not MASTER_KEY:
    print("ERROR: faltan variables de entorno JSONBIN_BIN_ID y JSONBIN_MASTER_KEY.")
    print("Exportalas asi:")
    print("  export JSONBIN_BIN_ID=tu-bin-id")
    print("  export JSONBIN_MASTER_KEY=tu-master-key")
    sys.exit(1)

DATA = Path(__file__).resolve().parent.parent / "data"

record = {
    "usuarios": json.loads((DATA / "usuarios.json").read_text(encoding="utf-8")),
    "reservas": json.loads((DATA / "reservas.json").read_text(encoding="utf-8")),
    "canchas": json.loads((DATA / "canchas.json").read_text(encoding="utf-8")),
}

print(f"Subiendo a JSONBin (bin {BIN_ID})...")
print(f"  - {len(record['usuarios'])} usuarios")
print(f"  - {len(record['reservas'])} reservas")
print(f"  - {len(record['canchas'])} canchas")

r = httpx.put(
    f"https://api.jsonbin.io/v3/b/{BIN_ID}",
    headers={
        "X-Master-Key": MASTER_KEY,
        "Content-Type": "application/json",
    },
    json=record,
    timeout=30.0,
)

if r.status_code == 200:
    print("\nOK: datos subidos correctamente.")
    print(f"Verificar en: https://jsonbin.io/app/bins/{BIN_ID}")
else:
    print(f"\nERROR ({r.status_code}): {r.text}")
    sys.exit(1)
