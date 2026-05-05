"""Malfini stock-szinkronizáció — összefogja a B2B API klienst és a DB-t.

Egy `refresh_all_stocks(db)` hívás:
  1. Beolvassa a credential-eket a `system_settings`-ből (Malfini-key-ek)
  2. Loginol a B2B API-ra → bearer token
  3. Lehúzza az összes aktív Malfini Item code-jának stock-ját
  4. Item.stock_qty + stock_fetched_at update batch-ben
  5. Logol a `system_settings.malfini.b2b.last_refresh_*` mezőkbe

A hívók (CLI, admin manual-trigger gomb, systemd timer) ezt használják.
A művelet nem blokkolja a fő FastAPI processt — kívülről hívják CLI-vel.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.rendelo import malfini_settings as cfg
from app.modules.rendelo.malfini_b2b import (
    MalfiniB2BError,
    fetch_availabilities,
    login,
)
from app.modules.rendelo.malfini_settings import DEFAULT_MALFINI_BASE_URL, MalfiniKeys
from app.modules.rendelo.models import Item
from app.shared.models import utcnow


@dataclass
class RefreshResult:
    ok: bool
    message: str
    items_total: int = 0
    items_updated: int = 0
    items_zeroed: int = 0  # API-tól nem érkezett adat → 0-ra állítjuk
    api_returned: int = 0  # API-tól érkezett kód-szám


def get_credentials(db: Session) -> tuple[str, str, str]:
    """Visszaadja (username, password, base_url). Üres-ek ha nincs configolva."""
    username = cfg.get(db, MalfiniKeys.USERNAME, default="")
    password = cfg.get(db, MalfiniKeys.PASSWORD, default="")
    base_url = cfg.get(db, MalfiniKeys.BASE_URL, default="") or DEFAULT_MALFINI_BASE_URL
    return username, password, base_url


def is_configured(db: Session) -> bool:
    """True ha mind username, mind password be van állítva."""
    u, p, _ = get_credentials(db)
    return bool(u and p)


def test_login(db: Session) -> tuple[bool, str]:
    """Tesztel egy login-t a tárolt credential-ekkel. UI-on `Test connection`-höz.

    Returns:
        (success, message). A message magyar nyelvű, UI-on megjeleníthető.
    """
    username, password, base_url = get_credentials(db)
    if not username or not password:
        return False, "Hiányzik a felhasználónév vagy jelszó."

    try:
        result = login(username, password, base_url=base_url)
    except MalfiniB2BError as e:
        cfg.set_(db, MalfiniKeys.LAST_LOGIN_ERROR, str(e))
        db.commit()
        return False, f"Sikertelen: {e}"

    cfg.set_(db, MalfiniKeys.LAST_LOGIN_OK_AT, utcnow().isoformat())
    cfg.set_(db, MalfiniKeys.LAST_LOGIN_ERROR, "")
    db.commit()
    token_hint = result.token[:8] + "…" if len(result.token) > 8 else "(rövid)"
    return True, f"Sikeres login. Token kezdete: {token_hint}"


def refresh_all_stocks(db: Session) -> RefreshResult:
    """Az összes aktív Malfini Item stock-ját frissíti a B2B API-ról."""
    username, password, base_url = get_credentials(db)
    if not username or not password:
        msg = "Nincs Malfini B2B credential configurálva — admin UI-n állítható be."
        cfg.set_(db, MalfiniKeys.LAST_REFRESH_STATUS, msg)
        cfg.set_(db, MalfiniKeys.LAST_REFRESH_AT, utcnow().isoformat())
        db.commit()
        return RefreshResult(ok=False, message=msg)

    # Aktív Malfini Item-ek code-jai
    items = (
        db.execute(
            select(Item).where(
                Item.active.is_(True),
                func.lower(Item.brand) == "malfini",
                Item.code.is_not(None),
            )
        )
        .scalars()
        .all()
    )
    items_by_code: dict[str, Item] = {it.code: it for it in items if it.code}

    try:
        login_result = login(username, password, base_url=base_url)
        cfg.set_(db, MalfiniKeys.LAST_LOGIN_OK_AT, utcnow().isoformat())
        cfg.set_(db, MalfiniKeys.LAST_LOGIN_ERROR, "")

        entries = fetch_availabilities(
            login_result.token,
            base_url=base_url,
            codes=list(items_by_code.keys()) or None,
        )
    except MalfiniB2BError as e:
        msg = f"API hiba: {e}"
        cfg.set_(db, MalfiniKeys.LAST_REFRESH_STATUS, msg)
        cfg.set_(db, MalfiniKeys.LAST_REFRESH_AT, utcnow().isoformat())
        cfg.set_(db, MalfiniKeys.LAST_LOGIN_ERROR, str(e))
        db.commit()
        return RefreshResult(ok=False, message=msg)

    # Aggregálás kódonként (több raktár → összegezzük)
    totals: dict[str, int] = {}
    for entry in entries:
        totals[entry.code] = totals.get(entry.code, 0) + entry.quantity

    now = utcnow()
    updated = 0
    for code, item in items_by_code.items():
        # API nem ismeri ezt a kódot → 0-nak vesszük (out-of-stock vagy
        # discontinued). Ne maradjon stale érték.
        item.stock_qty = totals.get(code, 0)
        item.stock_fetched_at = now
        updated += 1

    zeroed = sum(1 for code in items_by_code if code not in totals)

    msg = f"OK — {updated} tétel frissítve ({len(totals)} az API-ból, {zeroed} 0-ra állítva)."
    cfg.set_(db, MalfiniKeys.LAST_REFRESH_STATUS, msg)
    cfg.set_(db, MalfiniKeys.LAST_REFRESH_AT, now.isoformat())
    db.commit()

    return RefreshResult(
        ok=True,
        message=msg,
        items_total=len(items_by_code),
        items_updated=updated,
        items_zeroed=zeroed,
        api_returned=len(totals),
    )
