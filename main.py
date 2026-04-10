#!/usr/bin/env python3
"""
Punto de entrada principal.
Busca emails de Banco BICE en Gmail y los registra en Notion.

Uso:
    python main.py

Cron (cada 15 minutos):
    */15 * * * * cd /ruta/al/proyecto && python main.py >> data/sync.log 2>&1
"""
import logging
import sys
from datetime import datetime, timezone

# Configurar logging antes de importar módulos que lo usan
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> int:
    logger.info("=" * 60)
    logger.info("Iniciando sincronización BICE → Notion")
    logger.info("Fecha/hora: %s", datetime.now(timezone.utc).isoformat())

    # Importar aquí para que los errores de config aparezcan con logging ya activo
    try:
        from bice_to_notion import config
        from bice_to_notion.gmail_client import GmailClient
        from bice_to_notion.email_parser import parse_email
        from bice_to_notion.notion_writer import NotionWriter
        from bice_to_notion.deduplicator import Deduplicator
    except EnvironmentError as e:
        logger.error("Error de configuración: %s", e)
        return 1

    dedup = Deduplicator(config.PROCESSED_IDS_PATH)
    gmail = GmailClient(config.CREDENTIALS_PATH, config.TOKEN_PATH)
    notion = NotionWriter()

    # Obtener emails
    emails = gmail.fetch_bice_emails(lookback_days=config.GMAIL_LOOKBACK_DAYS)

    stats = {"processed": 0, "skipped": 0, "errors": 0, "already_done": 0}

    for email in emails:
        # 1. Deduplicación primaria: por Gmail message ID
        if dedup.is_processed(email.id):
            stats["already_done"] += 1
            continue

        # 2. Parsear email
        movement = parse_email(email)
        if movement is None:
            logger.warning("No se pudo parsear email '%s' (id=%s)", email.subject, email.id)
            stats["errors"] += 1
            # Marcar como procesado para no reintentar en cada ejecución
            dedup.mark_processed(email.id)
            continue

        # 3. Deduplicación secundaria: por número de operación en Notion
        if movement.operation_number and notion.already_exists(movement.operation_number):
            logger.info(
                "Operación %s ya existe en Notion, saltando.",
                movement.operation_number,
            )
            dedup.mark_processed(email.id)
            stats["skipped"] += 1
            continue

        # 4. Crear página en Notion
        page_id = notion.create_page(movement)
        if page_id:
            dedup.mark_processed(email.id)
            stats["processed"] += 1
        else:
            stats["errors"] += 1

    logger.info(
        "Sincronización completada: %d nuevos | %d saltados | %d ya procesados | %d errores",
        stats["processed"],
        stats["skipped"],
        stats["already_done"],
        stats["errors"],
    )
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
