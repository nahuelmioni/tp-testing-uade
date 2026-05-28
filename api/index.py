"""Entrypoint para Vercel. Reexporta la app FastAPI definida en main.py."""
import sys
from pathlib import Path

# Aseguramos que la raiz del proyecto este en el path para importar main.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import app  # noqa: E402, F401
