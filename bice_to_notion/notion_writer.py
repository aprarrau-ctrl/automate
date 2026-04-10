"""
Escribe movimientos bancarios en la base de datos de Notion.
"""
import logging

from notion_client import Client
from notion_client.errors import APIResponseError

from . import config
from .email_parser import BiceMovement

logger = logging.getLogger(__name__)


class NotionWriter:
    def __init__(self):
        self._client = Client(auth=config.NOTION_TOKEN)
        self._db_id = config.NOTION_DATABASE_ID

    def already_exists(self, operation_number: str) -> bool:
        """Verifica si ya existe una página con este número de operación en Notas."""
        if not operation_number:
            return False
        try:
            response = self._client.databases.query(
                database_id=self._db_id,
                filter={
                    "property": config.PROP_NOTES,
                    "rich_text": {"contains": f"Op: {operation_number}"},
                },
            )
            return len(response.get("results", [])) > 0
        except APIResponseError as e:
            # Si la propiedad no existe o hay error de filtro, no bloqueamos
            logger.warning("No se pudo verificar duplicado en Notion: %s", e)
            return False

    def create_page(self, movement: BiceMovement) -> str | None:
        """
        Crea una página en Notion con los datos del movimiento.
        Devuelve el ID de la página creada, o None si hubo error.
        """
        title = _build_title(movement)
        properties = _build_properties(movement, title)

        try:
            page = self._client.pages.create(
                parent={"database_id": self._db_id},
                properties=properties,
            )
            page_id = page["id"]
            logger.info("Página creada en Notion: %s | %s", page_id, title)
            return page_id
        except APIResponseError as e:
            logger.error("Error al crear página en Notion para '%s': %s", title, e)
            return None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _build_title(movement: BiceMovement) -> str:
    type_label = {
        "Transferencia": "Transferencia a",
        "Ingreso":       "Transferencia de",
        "Gasto":         "Pago a",
    }.get(movement.movement_type, movement.movement_type)

    amount_fmt = f"${movement.amount:,.0f}".replace(",", ".")
    return f"{type_label} {movement.merchant} - {amount_fmt}"


def _build_properties(movement: BiceMovement, title: str) -> dict:
    """
    Construye el dict de propiedades para la API de Notion.
    Usa los nombres configurados en config.py.
    Omite silenciosamente las propiedades que no estén en la BD
    (Notion lanzará APIResponseError solo si el nombre no existe,
    por eso capturamos el error en create_page y lo reportamos).
    """
    iso_date = movement.transaction_date.strftime("%Y-%m-%dT%H:%M:%S+00:00")

    props: dict = {
        config.PROP_TITLE: {
            "title": [{"text": {"content": title}}]
        },
        config.PROP_AMOUNT: {
            "number": movement.amount
        },
        config.PROP_DATE: {
            "date": {"start": iso_date}
        },
        config.PROP_TYPE: {
            "select": {"name": movement.movement_type}
        },
        config.PROP_BANK: {
            "select": {"name": "Otro"}
        },
        config.PROP_SOURCE: {
            "select": {"name": "Automático"}
        },
    }

    if movement.merchant:
        props[config.PROP_MERCHANT] = {
            "rich_text": [{"text": {"content": movement.merchant[:2000]}}]
        }

    if movement.notes:
        props[config.PROP_NOTES] = {
            "rich_text": [{"text": {"content": movement.notes[:2000]}}]
        }

    return props
