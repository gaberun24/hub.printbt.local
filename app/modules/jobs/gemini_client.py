"""Gemini flash email osztályozó — a pipeline 4. lépcsője.

Egy rövid prompt-ot küld a Gemini API-nak:
  - Email tárgy + body (max 3000 karakter)
  - Strukturált JSON válasz: category, confidence, summary

A modul lazy-init-et használ: ha nincs GEMINI_API_KEY,
nem importálja a google.genai SDK-t, és None-t ad vissza.
"""

from __future__ import annotations

import json
import logging

from app.modules.jobs.email_models import IncomingEmail
from app.shared.config import settings

log = logging.getLogger(__name__)

# Lazy-init: egyszer hozzuk létre a klienst
_client = None
_init_attempted = False

# A prompt megmondja a Gemini-nek hogy nyomdai cég emailjeit kell osztályozni
_SYSTEM_PROMPT = """\
Te egy nyomdai cég (PrintBT / Gyorsnyomda) belső rendszerének email-osztályozója vagy.

Az emaileket az alábbi kategóriák egyikébe kell sorolnod:

- work: Új munkamegrendelés, gyártási megbízás, grafikai anyag küldése, \
konkrét nyomtatási/gravírozási/UV feladat kérése. Ha az ügyfél fájlt küld \
vagy konkrét darabszámot/méretet említ, az szinte biztos work.
- quote_request: Árajánlat-kérés — az ügyfél árat kérdez, mennyibe kerülne, \
tudnátok-e csinálni, stb. Nincs konkrét megrendelés, csak érdeklődés.
- other: Nem illik a fentiekbe — kérdés, visszajelzés, köszönet, általános \
levelezés. Ha bizonytalan vagy, inkább ide sorold.
- spam: Reklám, hírlevél, automatikus értesítés, marketing kampány.

FONTOS: A „supplier" kategóriát NE használd — a szállítói emaileket már \
korábban kiszűrtük, ide nem jutnak el.

Válaszolj KIZÁRÓLAG az alábbi JSON formátumban (semmi más szöveg):
{
  "category": "work|quote_request|other|spam",
  "confidence": 0.0-1.0,
  "summary": "1-2 mondatos magyar összefoglaló az email tartalmáról"
}
"""


def _get_client():
    """Lazy Gemini kliens inicializálás."""
    global _client, _init_attempted  # noqa: PLW0603
    if _init_attempted:
        return _client
    _init_attempted = True

    api_key = settings.gemini_api_key
    if not api_key:
        log.warning("GEMINI_API_KEY nincs beállítva — email-osztályozás Gemini nélkül fut.")
        return None

    try:
        from google import genai

        _client = genai.Client(api_key=api_key)
        log.info("Gemini kliens inicializálva (model: %s)", settings.gemini_model)
    except Exception:
        log.exception("Gemini kliens inicializálás sikertelen")
        _client = None

    return _client


def classify_with_gemini(email: IncomingEmail):
    """Email osztályozása Gemini flash-sel.

    Visszaad egy ClassificationResult-ot, vagy None-t ha hiba van.
    """
    from app.modules.jobs.email_classifier import ClassificationResult
    from app.modules.jobs.email_models import ClassifiedBy, EmailCategory

    client = _get_client()
    if client is None:
        return None

    # Email tartalom összeállítása a prompt-hoz
    subject = email.subject or "(nincs tárgy)"
    body = (email.body_text or "")[:3000]  # Max 3000 karakter
    from_info = f"{email.from_name or ''} <{email.from_address}>".strip()

    user_prompt = f"""\
Feladó: {from_info}
Tárgy: {subject}

{body}
"""

    try:
        response = client.models.generate_content(
            model=settings.gemini_model,
            contents=user_prompt,
            config={
                "system_instruction": _SYSTEM_PROMPT,
                "temperature": 0.1,  # Alacsony — determinisztikus osztályozás
                "max_output_tokens": 300,
            },
        )

        raw = response.text.strip()
        # Gemini néha markdown code block-ba teszi
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

        data = json.loads(raw)

        category_str = data.get("category", "other")
        # Validáció — csak megengedett értékek
        valid_categories = {"work", "quote_request", "other", "spam"}
        if category_str not in valid_categories:
            category_str = "other"

        confidence = float(data.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))

        summary = data.get("summary", "")

        return ClassificationResult(
            category=EmailCategory(category_str),
            classified_by=ClassifiedBy.GEMINI,
            confidence=confidence,
            summary=summary or None,
        )

    except json.JSONDecodeError:
        log.warning("Gemini válasz nem valid JSON: %.200s", raw if "raw" in dir() else "?")
        return None
    except Exception:
        log.exception("Gemini API hívás sikertelen (email #%s)", email.id)
        return None
