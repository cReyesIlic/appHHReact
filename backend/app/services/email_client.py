"""Cliente de email via Azure Communication Services (ACS).

Config via env vars (App Settings en Azure / .env local):
  ACS_CONNECTION_STRING   = endpoint=https://<acs-resource>.communication.azure.com/;accesskey=...
  ACS_SENDER_ADDRESS      = DoNotReply@<dominio>.azurecomm.net  (o dominio custom verificado)
  EMAIL_REPORT_RECIPIENTS = email1@shimin.cl,email2@shimin.cl  (lista CSV)

Si no están configurados, los métodos hacen "soft skip" sin tirar — devuelven {"sent": False, "reason": ...}.
"""

from __future__ import annotations

import os
from typing import Any


class EmailClient:
    def __init__(
        self,
        connection_string: str | None = None,
        sender: str | None = None,
        default_recipients: list[str] | None = None,
    ) -> None:
        self.connection_string = connection_string or os.getenv("ACS_CONNECTION_STRING", "")
        self.sender = sender or os.getenv("ACS_SENDER_ADDRESS", "")
        rcpt_csv = ",".join(default_recipients or []) or os.getenv("EMAIL_REPORT_RECIPIENTS", "")
        self.default_recipients = [r.strip() for r in rcpt_csv.split(",") if r.strip()]

    @property
    def configured(self) -> bool:
        return bool(self.connection_string and self.sender)

    def send(
        self,
        subject: str,
        plain_text: str,
        html: str | None = None,
        to: list[str] | None = None,
        cc: list[str] | None = None,
        reply_to: list[str] | None = None,
    ) -> dict:
        recipients = to or self.default_recipients
        if not self.configured:
            return {"sent": False, "reason": "ACS_CONNECTION_STRING / ACS_SENDER_ADDRESS no configurados"}
        if not recipients:
            return {"sent": False, "reason": "Sin destinatarios (define EMAIL_REPORT_RECIPIENTS o pasa to=...)"}

        try:
            from azure.communication.email import EmailClient as ACSEmailClient
        except ImportError:
            return {"sent": False, "reason": "azure-communication-email no instalado"}

        try:
            client = ACSEmailClient.from_connection_string(self.connection_string)
            message: dict[str, Any] = {
                "senderAddress": self.sender,
                "recipients": {
                    "to": [{"address": r} for r in recipients],
                },
                "content": {
                    "subject": subject[:255],
                    "plainText": plain_text,
                },
            }
            if html:
                message["content"]["html"] = html
            if cc:
                message["recipients"]["cc"] = [{"address": r} for r in cc]
            if reply_to:
                message["replyTo"] = [{"address": r} for r in reply_to]
            poller = client.begin_send(message)
            result = poller.result()
            status = getattr(result, "status", None) or (result.get("status") if isinstance(result, dict) else None)
            message_id = getattr(result, "id", None) or (result.get("id") if isinstance(result, dict) else None)
            return {
                "sent": str(status).lower() in {"succeeded", "ok", "running", "succeeded."},
                "status": str(status),
                "messageId": message_id,
                "recipients": recipients,
            }
        except Exception as exc:  # noqa: BLE001
            return {"sent": False, "reason": f"{type(exc).__name__}: {exc}"}
