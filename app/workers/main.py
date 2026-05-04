"""Worker fő belépési pont — IMAP poller loop + jövőbeli watcher-ek.

Futtatás:
    python -m app.workers.main

Ciklikusan pollozza az IMAP fiókokat, a konfiguráció szerinti
intervallumban (alapértelmezett: 60 másodperc).
"""

from __future__ import annotations

import logging
import signal
import time

from app.shared.config import settings
from app.shared.db import SessionLocal, init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("hub.worker")

# Graceful shutdown
_running = True


def _shutdown(signum, _frame):
    global _running  # noqa: PLW0603
    log.info("Leállítás kérve (signal %s)...", signum)
    _running = False


signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)


def main() -> None:
    """Fő worker loop."""
    log.info("Hub worker indítása — poll intervallum: %ds", settings.imap_poll_interval_sec)

    init_db()

    while _running:
        try:
            db = SessionLocal()
            try:
                from app.workers.imap_poller import poll_all_accounts

                count = poll_all_accounts(db)
                if count:
                    log.info("Összesen %d új email feldolgozva.", count)

                from app.workers.purge import purge_old_deleted_emails

                purged = purge_old_deleted_emails(db)
                if purged:
                    log.info("%d régi törölt email véglegesen eltávolítva.", purged)
            finally:
                db.close()
        except Exception:
            log.exception("Worker ciklus hiba")

        # Várakozás a következő ciklusig — 1 másodperces lépésekben,
        # hogy a SIGINT/SIGTERM gyorsan hasson
        for _ in range(settings.imap_poll_interval_sec):
            if not _running:
                break
            time.sleep(1)

    log.info("Worker leállt.")


if __name__ == "__main__":
    main()
