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
    """Egyedi Job public_id, ütközés-retry-jal.

    Ha az adott `length`-en `MAX_RETRY_AT_LENGTH` próbálkozás után sem
    talál szabadot, +1 karakterre hosszabbít és újra próbál.

    Felső korlát `MAX_LENGTH` — afölött RuntimeError, mert ekkora ID-térben
    soha nem szabad ütközéses helyzetbe kerülni.
    """
    from app.modules.jobs.models import Job

    return _generate_unique_for(db, Job, "public_id", length)


def generate_unique_for(
    db: Session, model_class, column_name: str = "public_id", length: int = DEFAULT_LENGTH
) -> str:
    """Generic egyedi public ID. Tetszőleges modell-osztálynak +
    oszlop-névnek (default `public_id`).

    Pl. Customer:
        from app.shared.models import Customer
        cid = generate_unique_for(db, Customer)
    """
    return _generate_unique_for(db, model_class, column_name, length)


def _generate_unique_for(db: Session, model_class, column_name: str, length: int) -> str:
    column = getattr(model_class, column_name)
    while length <= MAX_LENGTH:
        for _ in range(MAX_RETRY_AT_LENGTH):
            candidate = generate_random(length)
            existing = db.execute(
                select(model_class.id).where(column == candidate)
            ).scalar_one_or_none()
            if existing is None:
                return candidate
        length += 1
    raise RuntimeError(
        f"{model_class.__name__}.{column_name} generálás sikertelen: "
        f"{MAX_LENGTH} karakteren is ütközés volt."
    )
