"""E-Mail-Versand ueber die Microsoft Graph API (Outlook).

Authentifizierung per Client-Credentials-Flow (App-Registrierung mit
Application-Permission `Mail.Send`). Es ist keine Benutzerinteraktion noetig.
"""

from __future__ import annotations

import logging

import requests

from pingmonitor.config import GraphConfig

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
_SCOPE = "https://graph.microsoft.com/.default"
_SENDMAIL_URL = "https://graph.microsoft.com/v1.0/users/{sender}/sendMail"
_TIMEOUT = 30  # Sekunden fuer HTTP-Aufrufe


class NotifierError(Exception):
    """Fehler bei Authentifizierung oder Versand ueber Graph."""


class GraphNotifier:
    def __init__(self, cfg: GraphConfig):
        self._cfg = cfg

    def _get_token(self) -> str:
        url = _TOKEN_URL.format(tenant=self._cfg.tenant_id)
        try:
            resp = requests.post(
                url,
                data={
                    "client_id": self._cfg.client_id,
                    "client_secret": self._cfg.client_secret,
                    "scope": _SCOPE,
                    "grant_type": "client_credentials",
                },
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise NotifierError(f"Token-Abruf fehlgeschlagen: {exc}") from exc

        token = resp.json().get("access_token")
        if not token:
            raise NotifierError("Antwort enthielt kein access_token.")
        return token

    def send(self, recipients: list[str], subject: str, body: str) -> None:
        """Versendet eine reine Text-E-Mail an alle Empfaenger.

        Raises:
            NotifierError: bei Auth- oder Versandfehlern.
        """
        token = self._get_token()
        message = {
            "message": {
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "toRecipients": [
                    {"emailAddress": {"address": addr}} for addr in recipients
                ],
            },
            "saveToSentItems": "true",
        }

        url = _SENDMAIL_URL.format(sender=self._cfg.sender)
        try:
            resp = requests.post(
                url,
                headers={"Authorization": f"Bearer {token}"},
                json=message,
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise NotifierError(f"E-Mail-Versand fehlgeschlagen: {exc}") from exc

        logger.info("Alarm-E-Mail versandt an %s.", ", ".join(recipients))
