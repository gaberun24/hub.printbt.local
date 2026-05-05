"""LM Studio email osztályozó — OpenAI-kompatibilis HTTP API.

A user gépén futó LM Studio Local Server-en megy keresztül. Privát,
ingyenes, lassabb mint a Gemini felhő.

A modul stdlib `urllib.request`-et használ (nincs új dependency). Ha az
LM Studio nem elérhető (timeout / connection refused), None-t ad vissza
és a classifier fallback-ben OTHER-be sorol.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from sqlalchemy.orm import Session

from app.modules.jobs.email_models import IncomingEmail

log = logging.getLogger(__name__)

# A system prompt, a prompt-builder és a kategória-lista is közös az AI
# kliensek között — lásd `app.modules.jobs.ai_settings`.


def _post_chat(url: str, body: dict, timeout: int) -> dict | None:
    """OpenAI-kompatibilis /chat/completions hívás. None hibára."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw)
    except urllib.error.URLError as exc:
        log.warning("LM Studio nem elérhető (%s): %s", url, exc)
    except (json.JSONDecodeError, OSError):
        log.exception("LM Studio válasz parse hiba")
    return None


def _strip_code_fence(text: str) -> str:
    """Egyes modellek markdown-ba pakolják a JSON-t — szedjük ki."""
    s = text.strip()
    if s.startswith("```"):
        # ```json\n{...}\n``` vagy ```\n{...}\n```
        s = s.split("\n", 1)[1] if "\n" in s else s[3:]
        if s.endswith("```"):
            s = s[:-3]
    return s.strip()


def classify_with_lm_studio(db: Session, email: IncomingEmail):
    """Email osztályozása LM Studio-val.

    Visszaad egy ClassificationResult-ot, vagy None-t ha hiba van
    (a classifier ekkor RULE_FALLBACK / OTHER-re esik).
    """
    from app.modules.jobs.ai_settings import (
        EMAIL_CLASSIFIER_SYSTEM_PROMPT,
        build_email_prompt,
        get_ai_config,
    )
    from app.modules.jobs.email_classifier import ClassificationResult
    from app.modules.jobs.email_models import ClassifiedBy, EmailCategory

    cfg = get_ai_config(db)
    if not cfg.lm_studio_url:
        return None

    user_prompt = build_email_prompt(email)

    chat_body = {
        "model": cfg.lm_studio_model,
        "messages": [
            {"role": "system", "content": EMAIL_CLASSIFIER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 300,
        # OpenAI kompatibilis JSON-mode opció — az LM Studio újabb verzióiban
        # támogatott, és ha nem, a strip_code_fence akkor is megfogja.
        "response_format": {"type": "json_object"},
    }

    url = cfg.lm_studio_url.rstrip("/") + "/chat/completions"
    data = _post_chat(url, chat_body, cfg.lm_studio_timeout_sec)
    if data is None:
        return None

    try:
        raw = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        log.warning("LM Studio válasz váratlan szerkezet: %.300s", str(data))
        return None

    raw = _strip_code_fence(raw)

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("LM Studio válasz nem valid JSON: %.300s", raw)
        return None

    category_str = parsed.get("category", "other")
    if category_str not in {"work", "quote_request", "other", "spam"}:
        category_str = "other"

    confidence = float(parsed.get("confidence", 0.5))
    confidence = max(0.0, min(1.0, confidence))

    summary = (parsed.get("summary") or "").strip() or None

    return ClassificationResult(
        category=EmailCategory(category_str),
        classified_by=ClassifiedBy.LM_STUDIO,
        confidence=confidence,
        summary=summary,
    )
