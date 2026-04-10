"""
Carga y valida la configuración desde el archivo .env.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Carga el .env desde la raíz del proyecto (un nivel arriba de este módulo)
_ROOT = Path(__file__).parent.parent
load_dotenv(_ROOT / ".env")


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise EnvironmentError(
            f"Variable de entorno requerida no encontrada: {name}\n"
            f"Copia .env.example a .env y completa los valores."
        )
    return value


# ── Notion ────────────────────────────────────────────────────────────────────
NOTION_TOKEN: str = _require("NOTION_TOKEN")
NOTION_DATABASE_ID: str = _require("NOTION_DATABASE_ID")

# Nombres de propiedades en la BD (con valores por defecto)
PROP_TITLE: str    = os.getenv("NOTION_PROP_TITLE",    "Descripción")
PROP_AMOUNT: str   = os.getenv("NOTION_PROP_AMOUNT",   "Monto")
PROP_DATE: str     = os.getenv("NOTION_PROP_DATE",     "Fecha")
PROP_TYPE: str     = os.getenv("NOTION_PROP_TYPE",     "Tipo")
PROP_BANK: str     = os.getenv("NOTION_PROP_BANK",     "Banco")
PROP_MERCHANT: str = os.getenv("NOTION_PROP_MERCHANT", "Comercio")
PROP_SOURCE: str   = os.getenv("NOTION_PROP_SOURCE",   "Fuente")
PROP_NOTES: str    = os.getenv("NOTION_PROP_NOTES",    "Notas")

# ── Gmail ─────────────────────────────────────────────────────────────────────
GMAIL_LOOKBACK_DAYS: int = int(os.getenv("GMAIL_LOOKBACK_DAYS", "30"))

# Rutas de archivos (relativas a la raíz del proyecto)
CREDENTIALS_PATH = _ROOT / "credentials.json"
TOKEN_PATH = _ROOT / "token.json"
PROCESSED_IDS_PATH = _ROOT / "data" / "processed_ids.txt"
