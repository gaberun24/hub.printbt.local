"""AI provider runtime config.

A runtime-ban változtatható AI beállítások a `system_settings` táblában
élnek (admin UI-ról szerkeszthetők). A `.env` továbbra is fallback —
ha a DB-ben üres egy érték, a `.env`-ből vesszük, ha az is üres,
default érték.

Az API-kulcsok titkosítva vannak tárolva (`email_crypto.encrypt_password`),
visszafejtve csak az olvasáskor.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.modules.jobs.email_crypto import decrypt_password, encrypt_password
from app.shared.config import settings
from app.shared.models import SystemSetting, get_setting, get_setting_int

log = logging.getLogger(__name__)


# A `system_settings` tábla `value` Text mezőjében tárolt setting-ek,
# amelyeket titkosítunk: API kulcsok és jelszavak.
ENCRYPTED_KEYS: frozenset[str] = frozenset({
    "ai.gemini_api_key",
})


def _decrypt_if_secret(key: str, value: str) -> str:
    """Ha a kulcs titkosítva van tárolva, visszafejtjük. Egyébként visszaadjuk."""
    if not value or key not in ENCRYPTED_KEYS:
        return value
    try:
        return decrypt_password(value)
    except ValueError:
        log.warning("Setting visszafejtés sikertelen: %s", key)
        return ""


def get_db_or_env(db: Session, db_key: str, env_value: str, default: str = "") -> str:
    """Setting olvasás priorítás-sorrenddel:
    DB nem-üres érték → .env nem-üres érték → default.
    A titkosított kulcsok visszafejtve jönnek vissza.
    """
    raw = get_setting(db, db_key, "") or ""
    decrypted = _decrypt_if_secret(db_key, raw)
    if decrypted:
        return decrypted
    if env_value:
        return env_value
    return default


def set_setting(db: Session, key: str, value: str, *, user_id: int | None = None) -> None:
    """Setting írása. Titkosítja az `ENCRYPTED_KEYS` kulcsokat."""
    stored_value = encrypt_password(value) if (key in ENCRYPTED_KEYS and value) else value
    existing = db.get(SystemSetting, key)
    if existing is None:
        db.add(SystemSetting(key=key, value=stored_value, updated_by_id=user_id))
    else:
        existing.value = stored_value
        existing.updated_by_id = user_id


# ── AI provider config olvasása ────────────────────────────────


@dataclass
class AIConfig:
    """Az aktuális AI provider futási konfigurációja."""

    provider: str  # none | gemini | ollama | lm_studio

    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    ollama_url: str = ""
    ollama_model: str = "qwen2.5:7b"
    ollama_timeout_sec: int = 60

    lm_studio_url: str = ""
    lm_studio_model: str = "gemma-4-e4b"
    lm_studio_timeout_sec: int = 60


def get_ai_config(db: Session) -> AIConfig:
    """Aktuális AI config a DB + .env priorítás-sorrendben."""

    provider = get_db_or_env(
        db, "ai.provider", settings.ai_provider, "none"
    ).lower().strip() or "none"

    return AIConfig(
        provider=provider,
        gemini_api_key=get_db_or_env(db, "ai.gemini_api_key", settings.gemini_api_key),
        gemini_model=get_db_or_env(db, "ai.gemini_model", settings.gemini_model, "gemini-2.5-flash"),
        ollama_url=get_db_or_env(db, "ai.ollama_url", settings.ollama_url),
        ollama_model=get_db_or_env(db, "ai.ollama_model", settings.ollama_model, "qwen2.5:7b"),
        ollama_timeout_sec=(
            get_setting_int(db, "ai.ollama_timeout_sec", 0)
            or settings.ollama_timeout_sec
            or 60
        ),
        lm_studio_url=get_db_or_env(db, "ai.lm_studio_url", settings.lm_studio_url),
        lm_studio_model=get_db_or_env(
            db, "ai.lm_studio_model", settings.lm_studio_model, "gemma-4-e4b"
        ),
        lm_studio_timeout_sec=(
            get_setting_int(db, "ai.lm_studio_timeout_sec", 0)
            or settings.lm_studio_timeout_sec
            or 60
        ),
    )
