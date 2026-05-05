"""Ollama email osztályozó — native /api/chat hívás JSON-mode-dal.

A user gépén (vagy bármely céges gépen) futó Ollama szerverre hív.
Nem OpenAI-kompatibilis — Ollama saját API-ját használja, mert a
`format: "json"` opciója megbízhatóbb JSON-választ ad mint a generic
OpenAI-protocol json_object mode.

Beállítás a klienst futtató gépen:
1. `ollama serve` (alapból csak 127.0.0.1:11434-re hallgat)
2. Hogy a Hub VM elérje, az OLLAMA_HOST env var-t 0.0.0.0:11434-re kell
   állítani (Windows: rendszerváltozóban; Linux: systemd override)
3. Tűzfal: bejövő port 11434 engedélyezve
4. `ollama pull qwen2.5:7b` (vagy más modell)
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
    """Ollama /api/chat hívás. None hibára (timeout / connection refused)."""
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
        log.warning("Ollama nem elérhető (%s): %s", url, exc)
    except (json.JSONDecodeError, OSError):
        log.exception("Ollama válasz parse hiba")
    return None


def classify_with_ollama(db: Session, email: IncomingEmail):
    """Email osztályozása Ollama-val.

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
    if not cfg.ollama_url:
        return None

    user_prompt = build_email_prompt(email)

    chat_body = {
        "model": cfg.ollama_model,
        "messages": [
            {"role": "system", "content": EMAIL_CLASSIFIER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        # Az Ollama JSON-mode garantálja a valid JSON outputot — nem kell
        # markdown code-fence stripping mint a generic OpenAI-protocolnál.
        "format": "json",
        # Reasoning modellek (Gemma4, DeepSeek-R1, stb.) a `thinking` mezőbe
        # hosszú belső gondolkodást írnak, ami elfogyasztaná a num_predict
        # tokeneket még a JSON-content előtt → üres content. Ollama 0.4+
        # támogatja a `think: false` flag-et, az ismeretlen verziók ignorálják.
        "think": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 2000,  # max output token — hagyjon helyet a JSON-nak
        },
    }

    url = cfg.ollama_url.rstrip("/") + "/api/chat"
    data = _post_chat(url, chat_body, cfg.ollama_timeout_sec)
    if data is None:
        return None

    try:
        raw = data["message"]["content"]
    except (KeyError, TypeError):
        log.warning("Ollama válasz váratlan szerkezet: %.300s", str(data))
        return None

    if not raw or not raw.strip():
        # Reasoning modell (think) elfogyasztotta a num_predict-et — nincs content.
        # Diagnosztikai log a thinking-ből, hogy lássuk mit "gondolkodott".
        thinking = (data.get("message") or {}).get("thinking") or ""
        log.warning(
            "Ollama üres content-et adott (model=%s). Thinking: %.500s",
            cfg.ollama_model,
            thinking,
        )
        return None

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        log.warning("Ollama JSON-mode mégis nem-JSON-t adott: %.500s", raw)
        return None

    category_str = parsed.get("category", "other")
    if category_str not in {"work", "quote_request", "other", "spam"}:
        category_str = "other"

    confidence = float(parsed.get("confidence", 0.5))
    confidence = max(0.0, min(1.0, confidence))

    summary = (parsed.get("summary") or "").strip() or None

    return ClassificationResult(
        category=EmailCategory(category_str),
        classified_by=ClassifiedBy.OLLAMA,
        confidence=confidence,
        summary=summary,
    )
