"""AI provider runtime config + email prompt builder.

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


# ── Közös prompt-builder az email kliensekhez ─────────────────


# Közös system prompt — minden AI kliens (Gemini, Ollama, LM Studio) ezt
# használja, hogy a kategória-listák és az osztályozási logika konzisztens
# legyen a provider-ek között.
EMAIL_CLASSIFIER_SYSTEM_PROMPT = """\
Te egy nyomdai cég (PrintBT / Gyorsnyomda) belső rendszerének email-osztályozója vagy.

Az emaileket az alábbi kategóriák egyikébe kell sorolnod:

- work: Új munkamegrendelés, gyártási megbízás, grafikai anyag küldése, \
konkrét nyomtatási/gravírozási/UV feladat kérése. Ha az ügyfél fájlt küld \
vagy konkrét darabszámot/méretet említ, az szinte biztos work. \
**Ha az emailben csak csatolmány van (nincs vagy nagyon rövid a szöveg), \
az általában work — valaki ki akarja nyomtatni / le akarja gyártani azt amit küld.**
- quote_request: Árajánlat-kérés — az ügyfél árat kérdez, mennyibe kerülne, \
tudnátok-e csinálni, stb. Nincs konkrét megrendelés, csak érdeklődés.
- other: Nem illik a fentiekbe — kérdés, visszajelzés, köszönet, általános \
levelezés. Ha bizonytalan vagy, inkább ide sorold.
- spam: Reklám, hírlevél, automatikus értesítés, marketing kampány, csaló email.

FONTOS: A „supplier" kategóriát NE használd — a szállítói emaileket már \
korábban kiszűrtük, ide nem jutnak el.

A válaszod KIZÁRÓLAG egy JSON objektum legyen, az alábbi mezőkkel:
{
  "category": "work" | "quote_request" | "other" | "spam",
  "confidence": 0.0-1.0 közötti szám,
  "summary": "1-2 mondatos magyar összefoglaló az email tartalmáról"
}
"""


def _strip_html(html: str, max_len: int = 3000) -> str:
    """Egyszerű HTML→text konverzió. Stdlib HTMLParser, nincs új dep."""
    from html.parser import HTMLParser

    class _Stripper(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.parts: list[str] = []

        def handle_data(self, data: str) -> None:
            self.parts.append(data)

    s = _Stripper()
    try:
        s.feed(html)
    except Exception:
        return html[:max_len]
    text = " ".join(p.strip() for p in s.parts if p.strip())
    return text[:max_len]


def build_email_prompt(email) -> str:  # noqa: ANN001 — IncomingEmail körkörös import
    """Email tartalom strukturált prompt-építése — feladó + tárgy + csatolmány-
    fájlnevek + body (HTML fallback-kel ha a plain üres). Egységes minden
    AI kliens számára.

    A csatolmány-fájlnevek átadása fontos: a magyar nyomdai workflow-ban
    sokszor csak egy fájlt küld az ügyfél ('nyomdakesz.pdf') szöveg nélkül,
    ami egyértelmű work — a fájlnév alapján a modell ezt tudja értelmezni.
    """
    subject = email.subject or "(nincs tárgy)"
    from_info = f"{email.from_name or ''} <{email.from_address}>".strip()

    # Body: plain text, fallback HTML→text
    body = (email.body_text or "").strip()
    if not body and getattr(email, "body_html", None):
        body = _strip_html(email.body_html)
    body = body[:3000]

    # Csatolmány-fájlnevek
    attachments = getattr(email, "attachments", None) or []
    att_names = [a.filename for a in attachments if getattr(a, "filename", None)]

    parts = [f"Feladó: {from_info}", f"Tárgy: {subject}"]
    if att_names:
        parts.append(f"Csatolmányok ({len(att_names)} db): " + ", ".join(att_names))
    if body:
        parts.append("")
        parts.append(body)
    else:
        parts.append("")
        parts.append("(nincs szöveges tartalom)")

    return "\n".join(parts)


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
