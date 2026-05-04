"""IMAP poller — email fiókok lekérdezése, mentés, osztályozás.

Minden aktív `EmailAccount`-ot sorra vesz:
  1. IMAP-on UNSEEN (vagy UID > last_poll_uid) emaileket szed le
  2. Menti az `incoming_emails` + `email_attachments` táblákba
  3. Csatolmányokat fájlba írja (uploads/inbox/YYYY-MM-DD/feladó/)
  4. Végigfuttatja a 4-lépcsős classifier pipeline-on
  5. Frissíti az account `last_poll_at` / `last_poll_uid` mezőit
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from imap_tools import AND, MailBox, MailboxLoginError, MailMessage
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.jobs.email_classifier import apply_classification, classify_email
from app.modules.jobs.email_crypto import decrypt_password
from app.modules.jobs.email_models import (
    EmailAccount,
    EmailAttachment,
    IncomingEmail,
)
from app.modules.jobs.models import Job  # noqa: F401 – kell a jobs_jobs FK-hoz
from app.modules.jobs.virus_scanner import scan_attachment
from app.shared.config import settings
from app.shared.models import utcnow

log = logging.getLogger(__name__)

# Első poll esetén ennyi levelet hozzunk le (függetlenül SEEN-től), hogy a
# meglévő mailfiók tartalma ne maradjon ki. A következő polltól UID-alapú
# inkrementális.
INITIAL_FETCH_LIMIT = 50


def _safe_filename(name: str) -> str:
    """Fájlnév tisztítása — csak biztonságos karakterek."""
    # Csak alfanumerikus + . - _ és szóköz
    clean = "".join(c if (c.isalnum() or c in ".-_ ") else "_" for c in name)
    return clean.strip() or "unnamed"


def _attachment_dir(from_address: str) -> Path:
    """Csatolmány könyvtár: uploads/inbox/YYYY-MM-DD/feladó-sanitized/"""
    today = utcnow().strftime("%Y-%m-%d")
    safe_sender = _safe_filename(from_address.split("@")[0])[:30]
    base = settings.upload_dir / "inbox" / today / safe_sender
    base.mkdir(parents=True, exist_ok=True)
    return base


def _parse_date(msg: MailMessage) -> datetime:
    """Email dátum kinyerése, fallback: most."""
    if msg.date:
        # imap_tools datetime-ot ad, de lehet aware → naive UTC-re konvertáljuk
        dt = msg.date
        if dt.tzinfo is not None:
            from datetime import UTC

            dt = dt.astimezone(UTC).replace(tzinfo=None)
        return dt
    return utcnow()


def _already_fetched(db: Session, account_id: int, message_id: str | None) -> bool:
    """Ellenőrzi hogy ez az email már le van-e mentve (duplikáció-védelem)."""
    if not message_id:
        return False
    return (
        db.execute(
            select(IncomingEmail.id).where(
                IncomingEmail.account_id == account_id,
                IncomingEmail.message_id == message_id,
            )
        ).scalar_one_or_none()
        is not None
    )


def _save_email(
    db: Session, account: EmailAccount, msg: MailMessage
) -> IncomingEmail | None:
    """Egy IMAP üzenetet ment el az adatbázisba + csatolmányait fájlba.

    Return: az IncomingEmail, vagy None ha duplikátum.
    """
    message_id = msg.headers.get("message-id", [""])[0] if msg.headers else None
    if _already_fetched(db, account.id, message_id):
        log.debug("Kihagyva (duplikátum): %s", message_id)
        return None

    # Feladó kinyerése
    from_addr = msg.from_ or ""
    from_name: str | None = None
    if msg.from_values:
        from_name = msg.from_values.name or None
        from_addr = msg.from_values.email or from_addr

    # Címzett
    to_addr = msg.to[0] if msg.to else account.email_address

    # Reply / thread
    in_reply_to = msg.headers.get("in-reply-to", [""])[0] if msg.headers else None
    references = msg.headers.get("references", [""])[0] if msg.headers else None
    # Thread ID: az első message-id a references-ből (a szál gyökere)
    thread_id = None
    if references:
        refs = references.strip().split()
        thread_id = refs[0] if refs else None
    elif in_reply_to:
        thread_id = in_reply_to

    incoming = IncomingEmail(
        account_id=account.id,
        message_id=message_id,
        from_address=from_addr,
        from_name=from_name,
        to_address=to_addr,
        subject=msg.subject or None,
        body_text=msg.text or None,
        body_html=msg.html or None,
        received_at=_parse_date(msg),
        in_reply_to=in_reply_to,
        thread_id=thread_id,
        imap_uid=str(msg.uid) if msg.uid else None,
    )
    db.add(incoming)
    db.flush()  # ID-t kapjon, mielőtt csatolmányokat adunk hozzá

    # ── Csatolmányok ──
    if msg.attachments:
        att_dir = _attachment_dir(from_addr)
        for att in msg.attachments:
            filename = att.filename or "unnamed"
            safe_name = _safe_filename(filename)
            # Ütközés-védelelem: ha létezik, sorszámot adunk
            dest = att_dir / safe_name
            counter = 1
            while dest.exists():
                stem = dest.stem
                suffix = dest.suffix
                dest = att_dir / f"{stem}_{counter}{suffix}"
                counter += 1

            dest.write_bytes(att.payload)

            db_att = EmailAttachment(
                email_id=incoming.id,
                filename=filename,
                content_type=att.content_type,
                size_bytes=len(att.payload),
                storage_path=str(dest.relative_to(settings.upload_dir)),
            )
            db.add(db_att)
            db.flush()
            scan_attachment(db_att, Path(settings.upload_dir))

    db.flush()
    return incoming


def poll_account(db: Session, account: EmailAccount) -> int:
    """Egy IMAP fiók lekérdezése — letölti az új emaileket, osztályozza.

    Return: feldolgozott emailek száma.
    """
    log.info("Polling: %s (%s)", account.label, account.email_address)

    try:
        password = decrypt_password(account.imap_password_encrypted)
    except ValueError:
        log.error("Nem sikerült visszafejteni a jelszót: %s", account.label)
        return 0

    count = 0
    is_first_poll = not account.last_poll_uid
    try:
        with MailBox(account.imap_host, account.imap_port).login(
            account.imap_user, password
        ) as mailbox:
            if is_first_poll:
                # Első poll — az utolsó N levelet hozzuk le függetlenül SEEN-től.
                # Egy aktívan használt fiókban minden mail már olvasott, ezért a
                # `seen=False` szűrő üres inboxot eredményezne. A reverse=True +
                # limit a legfrissebb leveleket adja vissza.
                fetch_kwargs = {
                    "criteria": "ALL",
                    "mark_seen": False,
                    "bulk": True,
                    "reverse": True,
                    "limit": INITIAL_FETCH_LIMIT,
                }
                log.info(
                    "Első poll: %s — utolsó %d levél lehúzása",
                    account.label,
                    INITIAL_FETCH_LIMIT,
                )
            else:
                # Inkrementális: csak az újakat (UID > last_poll_uid)
                fetch_kwargs = {
                    "criteria": AND(uid=f"{int(account.last_poll_uid) + 1}:*"),
                    "mark_seen": False,
                    "bulk": True,
                }

            max_uid = int(account.last_poll_uid or "0")

            for msg in mailbox.fetch(**fetch_kwargs):
                incoming = _save_email(db, account, msg)
                if incoming is None:
                    continue

                # Osztályozás
                result = classify_email(db, incoming)
                apply_classification(incoming, result)

                # UID tracking
                if msg.uid:
                    uid_int = int(msg.uid)
                    if uid_int > max_uid:
                        max_uid = uid_int

                count += 1

            # Account utolsó poll frissítés
            account.last_poll_at = utcnow()
            if max_uid > int(account.last_poll_uid or "0"):
                account.last_poll_uid = str(max_uid)
            elif is_first_poll and max_uid == 0:
                # Üres mailbox az első pollnál — jelöljük "0"-val,
                # hogy a következő polltól már UID-alapú legyen
                account.last_poll_uid = "0"

            db.commit()

    except MailboxLoginError:
        log.error("IMAP login sikertelen: %s (%s)", account.label, account.imap_user)
    except Exception:
        log.exception("IMAP poll hiba: %s", account.label)
        db.rollback()

    log.info("Polling kész: %s — %d új email", account.label, count)
    return count


def poll_all_accounts(db: Session) -> int:
    """Minden aktív email fiókot végigkérdez.

    Return: összes feldolgozott email szám.
    """
    accounts = (
        db.execute(select(EmailAccount).where(EmailAccount.active.is_(True)))
        .scalars()
        .all()
    )

    if not accounts:
        log.debug("Nincs aktív email fiók — kihagyás.")
        return 0

    total = 0
    for account in accounts:
        total += poll_account(db, account)

    return total
