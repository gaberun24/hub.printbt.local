"""Public ID generálás a Munkák modulhoz.

Karakterkészlet: `ABCDEFGHJKMNPQRSTVWXYZ23456789` (kihagyva a vizuálisan
összetéveszthető `0/O`, `1/I/L`, `U` és néhány zavaró). 30 karakter,
6 hosszal `30^6 ≈ 729 millió` kombináció.

Generálás: `secrets.choice` per karakter. Ütközés esetén retry max 5×,
utána +1 karakterre hosszabbít (eldolt esemény, de a kód kezeli).

Megjelenítés: kötőjellel tagolva (`K7M-2X9`), backend kötőjel nélkül
tárolja. A kereső mindkettőt elfogadja (a `normalize` a kötőjelet kiveszi).
"""

from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"
DEFAULT_LENGTH = 6
MAX_RETRY_AT_LENGTH = 5
MAX_LENGTH = 8


def generate_random(length: int = DEFAULT_LENGTH) -> str:
    """Egy random ID, kötőjel nélkül."""
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def normalize(raw: str) -> str:
    """Bemeneti ID normalizálás: nagybetűsít, kötőjelet és space-t eltávolít.

    A kereső / detail-route ezt használja, hogy mind `K7M-2X9`, mind
    `k7m2x9`, mind `K7M 2X9` ugyanarra a Job-ra vezessen.
    """
    return "".join(c for c in raw.upper() if c in ALPHABET)


def format_display(public_id: str) -> str:
    """Megjelenítés: 6 karakter → `XXX-XXX`, 7+ karakter esetén
    `XXX-XXXX...` (3+rest) szerkezetet ad.

    Ha nem 6 karakter, akkor a kötőjel az első 3 után van, a többi
    egyben marad.
    """
    s = normalize(public_id)
    if len(s) <= 3:
        return s
    return f"{s[:3]}-{s[3:]}"


def generate_unique(db: Session, length: int = DEFAULT_LENGTH) -> str:
    """Egyedi public ID-t generál, ütközés-retry-jal.

    Ha az adott `length`-en `MAX_RETRY_AT_LENGTH` próbálkozás után sem
    talál szabadot, +1 karakterre hosszabbít és újra próbál.

    Felső korlát `MAX_LENGTH` — afölött RuntimeError, mert ekkora ID-térben
    soha nem szabad ütközéses helyzetbe kerülni.
    """
    from app.modules.jobs.models import Job

    while length <= MAX_LENGTH:
        for _ in range(MAX_RETRY_AT_LENGTH):
            candidate = generate_random(length)
            existing = db.execute(
                select(Job.id).where(Job.public_id == candidate)
            ).scalar_one_or_none()
            if existing is None:
                return candidate
        # Az adott length-en ütközés volt — bővítjük a teret +1 karakterrel
        length += 1
    raise RuntimeError(f"Public ID generálás sikertelen: {MAX_LENGTH} karakteren is ütközés volt.")
