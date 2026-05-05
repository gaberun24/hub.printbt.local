"""4-lépcsős email osztályozó pipeline.

Sorrend (az első match nyer, a többi kimarad):
  1. Ismert ügyfél — from_address illeszkedik customers.email → WORK
  2. Ismert szállító domain — system_settings 'email.supplier_domains' → SUPPLIER
  3. Spam minták — unsubscribe, marketing, newsletter, stb. → SPAM
  4. Gemini flash — ami maradt, AI dönti el → WORK / QUOTE_REQUEST / OTHER / SPAM

A pipeline ~70-80%-ot Python-nel elintéz, Gemini API hívás
csak a maradék ~20-30%-ra megy.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.jobs.email_models import ClassifiedBy, EmailCategory, IncomingEmail
from app.shared.models import Customer, get_setting

log = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    """Egy email osztályozásának eredménye."""

    category: EmailCategory
    classified_by: ClassifiedBy
    confidence: float  # 0.0–1.0
    summary: str | None = None  # Gemini által generált összefoglaló
    matched_customer_id: int | None = None


# ── Spam minták ──────────────────────────────────────────────
# Headerben vagy body-ban keresünk. Kisbetűsítve vizsgáljuk.
_SPAM_SUBJECT_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"unsubscribe", re.IGNORECASE),
    re.compile(r"leiratkoz[áa]s", re.IGNORECASE),
    re.compile(r"newsletter", re.IGNORECASE),
    re.compile(r"h[íi]rlev[ée]l", re.IGNORECASE),
    re.compile(r"marketing", re.IGNORECASE),
    re.compile(r"promo(tion|ci[óo])", re.IGNORECASE),
    re.compile(r"limited.?time.?offer", re.IGNORECASE),
    re.compile(r"act\s+now", re.IGNORECASE),
    re.compile(r"free\s+gift", re.IGNORECASE),
    re.compile(r"click\s+here", re.IGNORECASE),
]

# Feladó-cím spam minták. A noreply jellegű címekről érkező mail
# 99%-ban automatizált, marketing vagy értesítés — nem munka.
_SPAM_SENDER_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^no[\-_]?reply@", re.IGNORECASE),
    re.compile(r"^donot[\-_]?reply@", re.IGNORECASE),
    re.compile(r"^newsletter@", re.IGNORECASE),
    re.compile(r"^marketing@", re.IGNORECASE),
]

_SPAM_BODY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"you\s+are\s+receiving\s+this", re.IGNORECASE),
    re.compile(r"email\s+preferences", re.IGNORECASE),
    re.compile(r"view\s+in\s+browser", re.IGNORECASE),
    re.compile(r"email\s+c[íi]m.*(t[öo]rl|leiratkoz)", re.IGNORECASE),
]

# Erős spam minták — egyetlen találat is elég (a tárgyban VAGY a body-ban).
# A user feedback alapján: ha a "spam" vagy "leiratkozás"/"unsubscribe" szó
# bárhol szerepel az emailben, gyakorlatilag mindig marketing / hírlevél.
_HARD_SPAM_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bspam\b", re.IGNORECASE),
    re.compile(r"unsubscribe", re.IGNORECASE),
    re.compile(r"leiratkoz[áaoó]", re.IGNORECASE),  # leiratkozás, leiratkozó, leiratkozni
]

# Spam feladó domain-ek — ezek szinte mindig spam
_SPAM_SENDER_DOMAINS: set[str] = {
    "mailchimp.com",
    "sendgrid.net",
    "mailgun.org",
    "constantcontact.com",
    "hubspot.com",
    "sendinblue.com",
    "brevo.com",
    "drip.com",
    "klaviyo.com",
}


def _extract_domain(email_addr: str) -> str:
    """'valaki@example.com' → 'example.com' (kisbetűs)."""
    at = email_addr.rfind("@")
    return email_addr[at + 1 :].strip().lower() if at > 0 else ""


def _check_known_customer(
    db: Session, from_address: str
) -> tuple[int, None] | tuple[None, None]:
    """1. lépcső: ismert ügyfél email?"""
    addr = from_address.strip().lower()
    customer = db.execute(
        select(Customer).where(func.lower(Customer.email) == addr)
    ).scalar_one_or_none()
    if customer:
        return customer.id, None
    return None, None


def _check_supplier_domain(db: Session, from_address: str) -> bool:
    """2. lépcső: ismert szállító domain?"""
    domain = _extract_domain(from_address)
    if not domain:
        return False
    raw = get_setting(db, "email.supplier_domains", "")
    if not raw:
        return False
    supplier_domains = {d.strip().lower() for d in raw.split(",") if d.strip()}
    return domain in supplier_domains


def _check_spam(subject: str | None, body_text: str | None, from_address: str) -> bool:
    """3. lépcső: spam minták keresése."""
    # Spam feladó domain
    domain = _extract_domain(from_address)
    if domain in _SPAM_SENDER_DOMAINS:
        return True

    # Spam feladó local-part (noreply@, donotreply@, newsletter@, marketing@)
    addr = (from_address or "").strip()
    for pat in _SPAM_SENDER_PATTERNS:
        if pat.search(addr):
            return True

    subj = subject or ""
    body = (body_text or "")[:2000]
    combined = f"{subj}\n{body}"

    # Erős spam minták — egyetlen találat is elég (subject vagy body)
    for pat in _HARD_SPAM_PATTERNS:
        if pat.search(combined):
            return True

    # Subject minták (gyenge — csak a tárgyban)
    for pat in _SPAM_SUBJECT_PATTERNS:
        if pat.search(subj):
            return True

    # Body minták — legalább 2 különböző találat kell hozzá
    spam_hits = sum(1 for pat in _SPAM_BODY_PATTERNS if pat.search(body))
    return spam_hits >= 2  # noqa: PLR2004


def _classify_with_ai(db: Session, email: IncomingEmail) -> ClassificationResult | None:
    """A 4. lépcső — provider-aware AI hívás.

    A runtime config (system_settings tábla, fallback .env) alapján:
      - "gemini"    → Google Gemini Flash API
      - "ollama"    → Helyi Ollama szerver
      - "lm_studio" → Helyi LM Studio (OpenAI-kompatibilis)
      - "none"      → AI kihagyva, fallback OTHER

    Visszaad egy ClassificationResult-ot, vagy None-t ha hiba van /
    a provider nincs konfigurálva.
    """
    from app.modules.jobs.ai_settings import get_ai_config

    provider = get_ai_config(db).provider

    if provider == "gemini":
        from app.modules.jobs.gemini_client import classify_with_gemini

        return classify_with_gemini(db, email)

    if provider == "ollama":
        from app.modules.jobs.ollama_client import classify_with_ollama

        return classify_with_ollama(db, email)

    if provider == "lm_studio":
        from app.modules.jobs.lm_studio_client import classify_with_lm_studio

        return classify_with_lm_studio(db, email)

    # provider == "none" vagy ismeretlen
    return None


def classify_email(
    db: Session,
    email: IncomingEmail,
    *,
    use_gemini: bool = True,  # backward-compat — most use_ai-ként értelmezzük
) -> ClassificationResult:
    """Egy emailt végigfuttat a 4-lépcsős pipeline-on.

    Az eredményt visszaadja, de NEM menti a DB-be — a hívó felelőssége.
    """
    from_addr = email.from_address or ""

    # ── 1. Ismert ügyfél ──
    customer_id, _ = _check_known_customer(db, from_addr)
    if customer_id:
        log.info("Email #%s → WORK (ismert ügyfél #%d)", email.id, customer_id)
        return ClassificationResult(
            category=EmailCategory.WORK,
            classified_by=ClassifiedBy.RULE_CUSTOMER,
            confidence=1.0,
            matched_customer_id=customer_id,
        )

    # ── 2. Szállító domain ──
    if _check_supplier_domain(db, from_addr):
        log.info("Email #%s → SUPPLIER (domain: %s)", email.id, _extract_domain(from_addr))
        return ClassificationResult(
            category=EmailCategory.SUPPLIER,
            classified_by=ClassifiedBy.RULE_SUPPLIER,
            confidence=1.0,
        )

    # ── 3. Spam mintázat ──
    if _check_spam(email.subject, email.body_text, from_addr):
        log.info("Email #%s → SPAM (minta-illeszkedés)", email.id)
        return ClassificationResult(
            category=EmailCategory.SPAM,
            classified_by=ClassifiedBy.RULE_SPAM,
            confidence=0.9,
        )

    # ── 4. AI (Gemini / Ollama / LM Studio — runtime config alapján) ──
    if use_gemini:
        result = _classify_with_ai(db, email)
        if result:
            log.info(
                "Email #%s → %s (%s, %.0f%%)",
                email.id,
                result.category,
                result.classified_by,
                result.confidence * 100,
            )
            return result

    # Ha az AI nincs konfigurálva vagy hibázott → OTHER
    log.info("Email #%s → OTHER (fallback, nincs AI)", email.id)
    return ClassificationResult(
        category=EmailCategory.OTHER,
        classified_by=ClassifiedBy.RULE_FALLBACK,
        confidence=0.3,
    )


def apply_classification(email: IncomingEmail, result: ClassificationResult) -> None:
    """A ClassificationResult mezőit ráírja az IncomingEmail-re.

    NEM commitol — a hívó felelőssége.
    """
    email.category = result.category
    email.classified_by = result.classified_by
    email.confidence = result.confidence
    email.gemini_summary = result.summary
    email.matched_customer_id = result.matched_customer_id
