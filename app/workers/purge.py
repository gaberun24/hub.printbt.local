"""Törölt emailek végleges eltávolítása (7 napos retention után).

A worker minden ciklusban meghívja. Ha nincs mit törölni, no-op.
A csatolmány-fájlokat is eltávolítja a fájlrendszerből.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.shared.config import settings
from app.shared.models import utcnow

log = logging.getLogger(__name__)

RETENTION_DAYS = 7


def purge_old_deleted_emails(db: Session) -> int:
    from app.modules.jobs.email_models import EmailAttachment, IncomingEmail

    cutoff = utcnow() - timedelta(days=RETENTION_DAYS)

    old_emails = (
        db.execute(
            select(IncomingEmail)
            .where(
                IncomingEmail.purged_at.is_not(None),
                IncomingEmail.purged_at < cutoff,
            )
        )
        .scalars()
        .all()
    )

    if not old_emails:
        return 0

    upload_dir = Path(settings.upload_dir)
    count = 0

    for email in old_emails:
        attachments = (
            db.execute(
                select(EmailAttachment).where(EmailAttachment.email_id == email.id)
            )
            .scalars()
            .all()
        )
        for att in attachments:
            filepath = upload_dir / att.storage_path
            if filepath.exists():
                filepath.unlink()
            db.delete(att)

        db.delete(email)
        count += 1

    db.commit()
    log.info("Purge: %d email véglegesen törölve (retention: %d nap)", count, RETENTION_DAYS)
    return count
