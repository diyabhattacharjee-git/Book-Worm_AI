"""Outgoing email over SMTP (free with e.g. a Gmail app password or Brevo's free tier).

Without SMTP settings, development/test environments print the message to the
server log and keep it in an in-memory outbox (used by tests). Production
refuses to "send" without SMTP so codes are never silently lost.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from collections import deque
from email.message import EmailMessage

from app.core.config import get_settings

logger = logging.getLogger("bookworm.mailer")

# Development/test only: last messages "sent" without SMTP.
OUTBOX: deque[dict] = deque(maxlen=50)


class EmailNotConfigured(Exception):
    pass


class EmailSendFailed(Exception):
    pass


def send_email(to: str, subject: str, text: str, html: str | None = None) -> None:
    s = get_settings()
    # Safety: automated tests never send real email, whatever is configured.
    if not s.smtp_configured or s.app_env.lower() == "test":
        if s.is_production:
            raise EmailNotConfigured("Email delivery is not configured")
        OUTBOX.append({"to": to, "subject": subject, "text": text})
        logger.warning("email not sent (SMTP not configured); development copy follows",
                       extra={"data": {"to": to, "subject": subject, "body": text}})
        return
    msg = EmailMessage()
    msg["From"] = s.smtp_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    try:
        if s.smtp_port == 465:
            with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port, timeout=15, context=ssl.create_default_context()) as smtp:
                if s.smtp_username:
                    smtp.login(s.smtp_username, s.smtp_password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as smtp:
                if s.smtp_use_tls:
                    smtp.starttls(context=ssl.create_default_context())
                if s.smtp_username:
                    smtp.login(s.smtp_username, s.smtp_password)
                smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        logger.error("email send failed", extra={"data": {"error": type(exc).__name__}})
        raise EmailSendFailed("Could not send the email right now") from exc
