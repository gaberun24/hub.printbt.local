"""Malfini B2B integrációs beállítások a `system_settings` táblán keresztül.

A Malfini-credentialek (username, password, base URL) és a sync-state
(utolsó login időpontja, utolsó hibája, utolsó refresh státusza) mind a
`SystemSetting` táblában élnek, hogy admin UI-ról szerkeszthetők legyenek
.env helyett.

A jelszó titkosítva tárolódik — a `email_crypto.encrypt_password` Fernet
implementációját újrahasznosítjuk (SECRET_KEY → SHA256 → Fernet 32-byte
kulcs). Más KDF mint a régi `nyomda_rendelo` repó (PBKDF2), de a Hub-ba
nem hozunk át adatot — a user új credentialt fog beírni a Hub UI-ról.

Konvenció a key-ekre:
    `malfini.b2b.<field>` snake_case-ben.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.modules.jobs.email_crypto import decrypt_password, encrypt_password
from app.shared.models import SystemSetting, get_setting

log = logging.getLogger(__name__)


# Default base URL — a Malfini publikus B2B endpointja. Akkor írunk
# ettől eltérőt a SystemSetting-be, ha az admin manuálisan átírja.
DEFAULT_MALFINI_BASE_URL = "https://api.malfini.com/api/v4"


# A jelszó-mező titkosítva van tárolva. Más Malfini-key plain text.
ENCRYPTED_KEYS: frozenset[str] = frozenset({
    "malfini.b2b.password",
})


class MalfiniKeys:
    """Központi konstans-sor a Malfini B2B kulcsokhoz, hogy a hívók ne
    hardcode-olják stringben."""

    USERNAME = "malfini.b2b.username"
    PASSWORD = "malfini.b2b.password"  # encrypted
    BASE_URL = "malfini.b2b.base_url"
    LAST_LOGIN_OK_AT = "malfini.b2b.last_login_ok_at"
    LAST_LOGIN_ERROR = "malfini.b2b.last_login_error"
    LAST_REFRESH_AT = "malfini.b2b.last_refresh_at"
    LAST_REFRESH_STATUS = "malfini.b2b.last_refresh_status"


def _decrypt_if_secret(key: str, value: str) -> str:
    """Ha a kulcs titkosítva van tárolva, visszafejtjük. Egyébként visszaadjuk."""
    if not value or key not in ENCRYPTED_KEYS:
        return value
    try:
        return decrypt_password(value)
    except ValueError:
        log.warning("Malfini setting visszafejtés sikertelen: %s", key)
        return ""


def get(db: Session, key: str, default: str = "") -> str:
    """Plain string érték olvasása. (Encrypted kulcsra is működik —
    visszafejtve adja vissza, hogy a hívó egyszerűen használhassa.)"""
    raw = get_setting(db, key, "") or ""
    if not raw:
        return default
    return _decrypt_if_secret(key, raw) or default


def set_(db: Session, key: str, value: str, *, user_id: int | None = None) -> None:
    """Setting írása. Az `ENCRYPTED_KEYS`-be tartozó kulcsoknál titkosít."""
    stored = encrypt_password(value) if (key in ENCRYPTED_KEYS and value) else value
    existing = db.get(SystemSetting, key)
    if existing is None:
        db.add(SystemSetting(key=key, value=stored, updated_by_id=user_id))
    else:
        existing.value = stored
        existing.updated_by_id = user_id


def has_value(db: Session, key: str) -> bool:
    """True ha létezik record + nem üres value. UI-state ellenőrzéshez."""
    raw = get_setting(db, key, "") or ""
    return bool(raw)


def delete(db: Session, key: str) -> None:
    row = db.get(SystemSetting, key)
    if row is not None:
        db.delete(row)
