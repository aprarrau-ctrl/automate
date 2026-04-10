"""
Cliente Gmail que autentica via OAuth2 y busca correos de Banco BICE.
"""
import base64
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
BICE_SENDER = "reply@info.bice.cl"


@dataclass
class RawEmail:
    id: str
    subject: str
    body_html: str
    received_at: datetime  # UTC


class GmailClient:
    def __init__(self, credentials_path: Path, token_path: Path):
        self._credentials_path = credentials_path
        self._token_path = token_path
        self._service = self._authenticate()

    def _authenticate(self):
        creds = None

        if self._token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self._token_path), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refrescando token de Gmail...")
                creds.refresh(Request())
            else:
                if not self._credentials_path.exists():
                    raise FileNotFoundError(
                        f"No se encontró {self._credentials_path}\n"
                        "Descarga las credenciales OAuth2 desde Google Cloud Console "
                        "y guárdalas como credentials.json en la raíz del proyecto."
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self._credentials_path), SCOPES
                )
                creds = flow.run_local_server(port=0)

            self._token_path.write_text(creds.to_json())
            logger.info("Token guardado en %s", self._token_path)

        return build("gmail", "v1", credentials=creds)

    def fetch_bice_emails(self, lookback_days: int = 30) -> list[RawEmail]:
        """Devuelve todos los correos de BICE de los últimos `lookback_days` días."""
        after_date = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y/%m/%d")
        query = f"from:{BICE_SENDER} after:{after_date}"

        logger.info("Buscando emails BICE con query: %s", query)
        results = (
            self._service.users()
            .messages()
            .list(userId="me", q=query, maxResults=500)
            .execute()
        )
        messages = results.get("messages", [])
        logger.info("Encontrados %d emails de BICE", len(messages))

        emails = []
        for msg_meta in messages:
            raw = self._get_email(msg_meta["id"])
            if raw:
                emails.append(raw)
        return emails

    def _get_email(self, msg_id: str) -> RawEmail | None:
        try:
            msg = (
                self._service.users()
                .messages()
                .get(userId="me", id=msg_id, format="full")
                .execute()
            )
            subject = self._get_header(msg, "Subject")
            body_html = self._extract_html(msg["payload"])
            received_at = self._parse_internal_date(msg.get("internalDate", "0"))
            return RawEmail(id=msg_id, subject=subject, body_html=body_html, received_at=received_at)
        except Exception:
            logger.exception("Error obteniendo email %s", msg_id)
            return None

    @staticmethod
    def _get_header(msg: dict, name: str) -> str:
        headers = msg.get("payload", {}).get("headers", [])
        for h in headers:
            if h["name"].lower() == name.lower():
                return h["value"]
        return ""

    @staticmethod
    def _extract_html(payload: dict) -> str:
        """Extrae el cuerpo HTML del mensaje de forma recursiva."""
        mime_type = payload.get("mimeType", "")
        body_data = payload.get("body", {}).get("data", "")

        if mime_type == "text/html" and body_data:
            return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")

        for part in payload.get("parts", []):
            result = GmailClient._extract_html(part)
            if result:
                return result

        # Fallback a text/plain si no hay HTML
        if mime_type == "text/plain" and body_data:
            return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="replace")

        return ""

    @staticmethod
    def _parse_internal_date(internal_date_ms: str) -> datetime:
        ts = int(internal_date_ms) / 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc)
