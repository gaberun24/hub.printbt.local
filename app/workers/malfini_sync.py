"""Malfini stock-szinkron worker-integráció.

A hub-worker.service main loop-jából minden 60 mp-es ciklusban hívódik.
Nem fut feleslegesen: ellenőrzi az időt (hétköznap 7:30-17:30 helyi idő)
és az utolsó futás óta eltelt időt (30 perc). Ha mindkettő OK, futtatja
a `refresh_all_stocks`-ot.

A last-run timestamp a `system_settings.malfini.last_refresh_at` mezőben
él — ezt egyébként is írja a `refresh_all_stocks` minden hívásnál,
így a kézi /admin/integrations/malfini/refresh és a worker-timer
ugyanazt az állapotot használja.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.shared.models import utcnow

log = logging.getLogger(__name__)

# Munkaidő (helyi idő, Europe/Budapest)
LOCAL_TZ = ZoneInfo("Europe/Budapest")
WORK_HOUR_START = 7  # 07:30 → első futás kb. 7:30
WORK_HOUR_END = 18   # < 18:00 → utolsó futás kb. 17:30
INTERVAL_MIN = 30    # fél óránként


def _is_work_time() -> bool:
    """Hétköznap 7:00-18:00 helyi idő (Europe/Budapest)."""
    now_local = datetime.now(LOCAL_TZ)
    # 0=hétfő, 4=péntek, 5=szombat, 6=vasárnap
    if now_local.weekday() >= 5:
        return False
    if now_local.hour < WORK_HOUR_START or now_local.hour >= WORK_HOUR_END:
        return False
    return True


def maybe_refresh_malfini_stock(db: Session) -> None:
    """Ha a feltételek igazak, futtatja a Malfini stock-szinkronizálást.

    Feltételek:
    - A Malfini B2B credential konfigurálva (admin UI-n vagy korábban)
    - Munkaidő: hétköznap 7:00-17:59 helyi idő
    - Az utolsó futás óta legalább `INTERVAL_MIN` perc eltelt

    Hibakezelés: a `refresh_all_stocks` magában elnyeli a B2B API-hibákat,
    csak a state-mezőket írja át. Itt csak loggolunk.
    """
    from app.modules.rendelo import malfini_settings as cfg
    from app.modules.rendelo.malfini_settings import MalfiniKeys
    from app.modules.rendelo.malfini_stock import is_configured, refresh_all_stocks

    if not is_configured(db):
        return
    if not _is_work_time():
        return

    # Utolsó futás időpontja
    last_str = cfg.get(db, MalfiniKeys.LAST_REFRESH_AT, default="") or ""
    last_dt: datetime | None = None
    if last_str:
        try:
            last_dt = datetime.fromisoformat(last_str)
        except ValueError:
            last_dt = None

    if last_dt is not None:
        elapsed = utcnow() - last_dt
        if elapsed < timedelta(minutes=INTERVAL_MIN):
            return  # még túl frissen futott

    log.info("Malfini stock-szinkron indul (worker timer)")
    try:
        result = refresh_all_stocks(db)
    except Exception:
        log.exception("Malfini stock-szinkron exception")
        return

    if result.ok:
        log.info("Malfini stock-szinkron kész — %s", result.message)
    else:
        log.warning("Malfini stock-szinkron sikertelen — %s", result.message)
