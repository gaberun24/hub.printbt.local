"""SMTP email küldő — közös SMTP szerver, fiók feladó-címmel."""

from __future__ import annotations

import logging
import mimetypes
import smtplib
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid
from email import encoders

from app.shared.config import settings

log = logging.getLogger(__name__)


def is_smtp_configured() -> bool:
    return bool(settings.smtp_host)


def send_email(
    from_label: str,
    from_address: str,
    to_address: str,
    subject: str,
    body_text: str,
    *,
    in_reply_to: str | None = None,
    references: str | None = None,
    attachments: list[tuple[str, bytes]] | None = None,
) -> str:
    """Email küldése a közös SMTP szerveren keresztül.

    attachments: lista (filename, file_bytes) tuple-ökből.
    Returns: az elküldött email Message-ID-ja.
    """
    if not settings.smtp_host:
        raise ValueError("SMTP szerver nincs konfigurálva (.env: SMTP_HOST).")

    msg = MIMEMultipart("mixed")
    msg["From"] = formataddr((from_label, from_address))
    msg["To"] = to_address
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=from_address.split("@")[-1])

    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = references or in_reply_to

    body_part = MIMEMultipart("alternative")
    body_part.attach(MIMEText(body_text, "plain", "utf-8"))
    html_body = body_text.replace("\n", "<br>")
    body_part.attach(MIMEText(html_body, "html", "utf-8"))
    msg.attach(body_part)

    for filename, file_data in (attachments or []):
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        maintype, subtype = content_type.split("/", 1)
        part = MIMEBase(maintype, subtype)
        part.set_payload(file_data)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(part)

    log.info("SMTP küldés: %s → %s (%s)", from_address, to_address, subject[:50])

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        if settings.smtp_password:
            server.login(settings.smtp_user or from_address, settings.smtp_password)
        server.sendmail(from_address, [to_address], msg.as_string())

    log.info("SMTP küldés sikeres: %s", msg["Message-ID"])
    return msg["Message-ID"]
