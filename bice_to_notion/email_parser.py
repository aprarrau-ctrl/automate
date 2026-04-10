"""
Parser de emails HTML de Banco BICE.

Estrategia universal: recorre todos los <tr> con dos <td> para construir
un dict {label: value}, luego extrae los campos por email type.
"""
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from .gmail_client import RawEmail

logger = logging.getLogger(__name__)

# ── Mapeo de meses en español ─────────────────────────────────────────────────
_MONTHS = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4,
    "may": 5, "jun": 6, "jul": 7, "ago": 8,
    "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}

# ── Tipos de movimiento ───────────────────────────────────────────────────────
TYPE_TRANSFER_OUT = "Transferencia"
TYPE_TRANSFER_IN  = "Ingreso"
TYPE_EXPENSE      = "Gasto"


@dataclass
class BiceMovement:
    gmail_id: str
    subject: str
    movement_type: str          # Transferencia | Ingreso | Gasto
    amount: int                 # Entero en CLP (ej. 150000)
    transaction_date: datetime  # Con timezone UTC
    merchant: str               # Nombre contraparte o comercio
    operation_number: str       # Número de operación (para dedup secundario)
    notes: str                  # Texto libre con detalles extra
    raw_fields: dict = field(default_factory=dict, repr=False)


def parse_email(email: RawEmail) -> BiceMovement | None:
    """Parsea un RawEmail y devuelve un BiceMovement, o None si no se reconoce."""
    subject = email.subject.lower()

    if "hicimos la transferencia" in subject:
        return _parse_transfer_out(email)
    elif "recibiste una transferencia" in subject:
        return _parse_transfer_in(email)
    elif "enviamos tu pago a servipag" in subject:
        return _parse_servipag(email)
    elif "confirmaci" in subject and "pago de tarjeta" in subject:
        return _parse_card_payment(email)
    elif "dep" in subject and ("remuneraci" in subject or "sueldo" in subject or "ingreso" in subject):
        return _parse_transfer_in(email)
    else:
        logger.warning("Tipo de email no reconocido: '%s'", email.subject)
        return None


# ── Parsers por tipo ──────────────────────────────────────────────────────────

def _parse_transfer_out(email: RawEmail) -> BiceMovement | None:
    fields = _extract_table_fields(email.body_html)
    try:
        amount = _parse_amount(fields.get("Monto", ""))
        date = _parse_date(fields, email.received_at)
        destination_name = fields.get("Nombre", fields.get("nombre", "Desconocido"))
        op_number = _clean_value(fields.get("Número de operación", fields.get("numero de operacion", "")))

        notes_parts = [
            f"Op: {op_number}" if op_number else "",
            f"RUT destino: {fields.get('RUT', fields.get('rut', ''))}" ,
            f"Banco destino: {fields.get('Banco', fields.get('banco', ''))}",
            f"Tipo cuenta destino: {fields.get('Tipo de cuenta', '')}",
            f"N° cuenta destino: {_clean_account(fields.get('Número de cuenta', ''))}",
            f"Cuenta origen: {fields.get('Tipo de cuenta_origen', '')} {_clean_account(fields.get('Número de cuenta_origen', ''))}",
        ]
        notes = "\n".join(p for p in notes_parts if p.strip().split(": ", 1)[-1])

        return BiceMovement(
            gmail_id=email.id,
            subject=email.subject,
            movement_type=TYPE_TRANSFER_OUT,
            amount=amount,
            transaction_date=date,
            merchant=destination_name,
            operation_number=op_number,
            notes=notes,
            raw_fields=fields,
        )
    except Exception:
        logger.exception("Error parseando transferencia enviada (id=%s)", email.id)
        return None


def _parse_transfer_in(email: RawEmail) -> BiceMovement | None:
    fields = _extract_table_fields(email.body_html)
    try:
        amount = _parse_amount(fields.get("Monto", ""))
        date = _parse_date(fields, email.received_at)
        origin_name = fields.get("Nombre", fields.get("nombre", fields.get("Empresa", "Desconocido")))
        op_number = _clean_value(fields.get("Número de operación", fields.get("numero de operacion", "")))

        notes_parts = [
            f"Op: {op_number}" if op_number else "",
            f"RUT origen: {fields.get('RUT', fields.get('rut', ''))}",
            f"Banco origen: {fields.get('Banco', fields.get('banco', ''))}",
        ]
        notes = "\n".join(p for p in notes_parts if p.strip().split(": ", 1)[-1])

        return BiceMovement(
            gmail_id=email.id,
            subject=email.subject,
            movement_type=TYPE_TRANSFER_IN,
            amount=amount,
            transaction_date=date,
            merchant=origin_name,
            operation_number=op_number,
            notes=notes,
            raw_fields=fields,
        )
    except Exception:
        logger.exception("Error parseando transferencia recibida (id=%s)", email.id)
        return None


def _parse_servipag(email: RawEmail) -> BiceMovement | None:
    fields = _extract_table_fields(email.body_html)
    try:
        amount = _parse_amount(fields.get("Monto", ""))
        date = _parse_date(fields, email.received_at)
        merchant = fields.get("Empresa", fields.get("empresa", fields.get("Nombre", "Servipag")))
        op_number = _clean_value(fields.get("Número de operación", fields.get("numero de operacion", "")))

        notes_parts = [
            f"Op: {op_number}" if op_number else "",
            f"Servicio: {fields.get('Servicio', fields.get('servicio', ''))}",
            f"N° cliente: {fields.get('Número de cliente', fields.get('numero de cliente', ''))}",
        ]
        notes = "\n".join(p for p in notes_parts if p.strip().split(": ", 1)[-1])

        return BiceMovement(
            gmail_id=email.id,
            subject=email.subject,
            movement_type=TYPE_EXPENSE,
            amount=amount,
            transaction_date=date,
            merchant=merchant,
            operation_number=op_number,
            notes=notes,
            raw_fields=fields,
        )
    except Exception:
        logger.exception("Error parseando pago Servipag (id=%s)", email.id)
        return None


def _parse_card_payment(email: RawEmail) -> BiceMovement | None:
    fields = _extract_table_fields(email.body_html)
    try:
        amount = _parse_amount(
            fields.get("Monto", fields.get("Total pagado", fields.get("Monto pagado", "")))
        )
        date = _parse_date(fields, email.received_at)
        merchant = fields.get("Banco", fields.get("banco", "Pago tarjeta"))
        op_number = _clean_value(fields.get("Número de operación", fields.get("numero de operacion", "")))

        notes_parts = [
            f"Op: {op_number}" if op_number else "",
            f"Tarjeta: {fields.get('Tarjeta', fields.get('tarjeta', ''))}",
            f"N° tarjeta: {fields.get('Número de tarjeta', '')}",
        ]
        notes = "\n".join(p for p in notes_parts if p.strip().split(": ", 1)[-1])

        return BiceMovement(
            gmail_id=email.id,
            subject=email.subject,
            movement_type=TYPE_EXPENSE,
            amount=amount,
            transaction_date=date,
            merchant=merchant,
            operation_number=op_number,
            notes=notes,
            raw_fields=fields,
        )
    except Exception:
        logger.exception("Error parseando pago tarjeta (id=%s)", email.id)
        return None


# ── Utilidades de parsing ─────────────────────────────────────────────────────

def _extract_table_fields(html: str) -> dict[str, str]:
    """
    Construye un dict {label: value} a partir de todas las tablas HTML.
    Cuando hay claves duplicadas (ej. "Número de cuenta" para origen y destino),
    la segunda aparición se guarda con sufijo _2, _3, etc.
    Para el caso específico origen/destino de transferencias, se usan sufijos _origen/_destino.
    """
    soup = BeautifulSoup(html, "lxml")
    result: dict[str, str] = {}
    seen_keys: dict[str, int] = {}

    for tr in soup.find_all("tr"):
        tds = [td for td in tr.find_all("td", recursive=False)]
        if len(tds) < 2:
            continue
        label = _clean_value(tds[0].get_text())
        value = _clean_value(tds[1].get_text())
        if not label or not value:
            continue

        if label not in result:
            result[label] = value
            seen_keys[label] = 1
        else:
            count = seen_keys[label] + 1
            seen_keys[label] = count
            result[f"{label}_{count}"] = value

    # Heurística: en transferencias enviadas, las primeras repeticiones son destino
    # y hay secciones "Cuenta de origen" / "Cuenta de destino" en el HTML.
    # Renombramos las claves duplicadas de forma más legible si detectamos ambos contextos.
    _rename_origin_destination_fields(soup, result)

    return result


def _rename_origin_destination_fields(soup: BeautifulSoup, fields: dict[str, str]) -> None:
    """
    Busca secciones con texto 'origen' y 'destino' en el HTML para renombrar
    campos duplicados de cuentas de forma más descriptiva.
    """
    # Buscar celdas que contengan "origen" o "destino"
    for td in soup.find_all("td"):
        text = td.get_text(strip=True).lower()
        if "cuenta de origen" in text:
            # El siguiente <tr> con Tipo de cuenta / Número de cuenta es de origen
            parent = td.find_parent("tr")
            if parent:
                for sibling in parent.find_next_siblings("tr"):
                    tds = sibling.find_all("td", recursive=False)
                    if len(tds) >= 2:
                        label = _clean_value(tds[0].get_text())
                        value = _clean_value(tds[1].get_text())
                        if label in ("Tipo de cuenta", "Número de cuenta") and f"{label}_origen" not in fields:
                            fields[f"{label}_origen"] = value
                    else:
                        break


def _parse_amount(raw: str) -> int:
    """Convierte '$150.000' → 150000."""
    cleaned = re.sub(r"[^\d]", "", raw)
    if not cleaned:
        raise ValueError(f"No se pudo parsear monto: '{raw}'")
    return int(cleaned)


def _parse_date(fields: dict[str, str], fallback: datetime) -> datetime:
    """
    Busca un campo de fecha en el dict y lo parsea.
    Formato esperado: '10 abr 2026 - 12:56 h'
    Fallback: fecha de recepción del email.
    """
    # Buscar campo que parezca fecha
    for key in fields:
        if re.search(r"\d{1,2}\s+[a-záéíóú]{3}\s+\d{4}", fields[key], re.IGNORECASE):
            dt = _parse_bice_datetime(fields[key])
            if dt:
                return dt

    # Buscar en el texto completo de los campos
    for value in fields.values():
        dt = _parse_bice_datetime(value)
        if dt:
            return dt

    logger.debug("No se encontró fecha en campos, usando fecha de recepción del email")
    return fallback


def _parse_bice_datetime(text: str) -> datetime | None:
    """
    Parsea '10 abr 2026 - 12:56 h' → datetime (UTC).
    También acepta '10 abr 2026 - 12:56' sin ' h'.
    """
    pattern = r"(\d{1,2})\s+([a-záéíóú]{3})\s+(\d{4})\s*[-–]\s*(\d{2}):(\d{2})"
    m = re.search(pattern, text, re.IGNORECASE)
    if not m:
        return None
    day, month_str, year, hour, minute = m.groups()
    month = _MONTHS.get(month_str.lower())
    if not month:
        return None
    try:
        # Se asume hora local de Chile (UTC-3 o UTC-4 según DST).
        # Por simplicidad se guarda sin offset; Notion mostrará la hora como está.
        return datetime(int(year), month, int(day), int(hour), int(minute), tzinfo=timezone.utc)
    except ValueError:
        return None


def _clean_value(text: str) -> str:
    return " ".join(text.split()).strip()


def _clean_account(account: str) -> str:
    """Elimina guiones de números de cuenta: '24-71350-4' → '24713504'."""
    return account.replace("-", "").strip()
