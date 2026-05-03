"""IMAP jelszavak titkosítása/visszafejtése Fernet-tel.

A kulcs a SECRET_KEY SHA256 hash-éből képződik (Fernet 32 byte
base64-kódolt kulcsot vár). Így a .env-ben lévő SECRET_KEY védi
az adatbázisban tárolt IMAP jelszavakat.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.shared.config import settings


def _derive_key() -> bytes:
    """SECRET_KEY → Fernet-kompatibilis 32-byte base64 kulcs."""
    raw = hashlib.sha256(settings.secret_key.encode()).digest()
    return base64.urlsafe_b64encode(raw)


def encrypt_password(plaintext: str) -> str:
    """Jelszó titkosítása — az eredmény a DB-be kerül."""
    f = Fernet(_derive_key())
    return f.encrypt(plaintext.encode()).decode()


def decrypt_password(ciphertext: str) -> str:
    """Jelszó visszafejtése a DB-ből."""
    f = Fernet(_derive_key())
    try:
        return f.decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        msg = "Nem sikerült visszafejteni az IMAP jelszót. Lehet, hogy a SECRET_KEY változott?"
        raise ValueError(msg) from exc
