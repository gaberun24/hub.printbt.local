"""Közös (shared) táblák a Hub-ban: users, customers, audit_log, notifications.

A modul-specifikus táblák (jobs, requests, stock_items, ...) az adott
modul saját `models.py`-jában élnek és ide importálják a Base-t.

A három modul egy SQLite DB-ben él, az audit_log `entity_type` mezője
különbözteti meg az egyes modulok rekordjait.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.shared.db import Base


def utcnow() -> datetime:
    """Naive datetime, ami UTC-t reprezentál.

    SQLite tárolja a datetime-okat szövegként és nem tartja meg a
    timezone infót olvasáskor, így aware DT-ot bekerítve naive-ot
    olvasunk vissza, és a kettő összehasonlítása `TypeError`-t dob.
    Egyszerűbb: naive UTC mindenhol, konvenció szerint.
    """
    return datetime.now(UTC).replace(tzinfo=None)


# A role-flag mezők a User táblán. Egy ember egyszerre több role-t viselhet.
# A sidebar / menü ezek alapján rajzolódik ki.
ROLE_FLAGS: tuple[str, ...] = (
    "is_intake",  # új munka felvétel (Munkák)
    "is_designer",  # grafikus pipeline (Munkák)
    "is_workshop",  # műhely task-ok (Munkák) + igény feladás (Rendelő)
    "is_quote_handler",  # árajánlat shared inbox (Munkák)
    "is_orderer",  # rendelések felvétele/lezárása (Rendelő)
    "is_admin",  # mindent + user/ügyfél/email-fiók kezelés
)


class CustomerType(StrEnum):
    """Vásárló (regular) vagy viszonteladó (kedvezménnyel rendel)."""

    RETAIL = "retail"  # vásárló
    RESELLER = "reseller"  # viszonteladó


class LegalType(StrEnum):
    """Magánszemély vagy cég. Cégeknek adószám is kell."""

    INDIVIDUAL = "individual"  # magánszemély
    COMPANY = "company"  # cég


class AuditEntityType(StrEnum):
    JOB = "job"
    TASK = "task"
    EMAIL = "email"
    REQUEST = "request"
    STOCK = "stock"
    USER = "user"


class User(Base):
    """Multi-role user.

    A klasszikus enum-alapú role helyett boolean flag-ek vannak: egy ember
    lehet egyszerre `is_designer` és `is_intake`, vagy `is_quote_handler`
    és `is_orderer`. A sidebar/menü ezek alapján jelenik meg dinamikusan.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str] = mapped_column(String(190), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    # Role flagek — több is lehet egyszerre
    is_intake: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_designer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_workshop: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_quote_handler: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_orderer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    force_password_change: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    sessions: Mapped[list[UserSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    @property
    def role_flags(self) -> set[str]:
        """A bekapcsolt role-flagek halmaza, pl. {"is_designer", "is_intake"}."""
        return {flag for flag in ROLE_FLAGS if getattr(self, flag)}

    @property
    def role_label(self) -> str:
        """Rövid magyar leírás a role-okhoz a UI-on (avatar mellett)."""
        labels = {
            "is_admin": "admin",
            "is_intake": "felvevő",
            "is_designer": "grafikus",
            "is_workshop": "műhely",
            "is_quote_handler": "árajánlat",
            "is_orderer": "rendelő",
        }
        if self.is_admin:
            return "admin"
        active = [labels[f] for f in ROLE_FLAGS if getattr(self, f) and f != "is_admin"]
        return ", ".join(active) if active else "—"


class Invite(Base):
    """Meghívásos regisztráció: admin generál tokent + role flag-eket,
    a meghívott a tokennel beállítja a saját jelszavát."""

    __tablename__ = "invites"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email_hint: Mapped[str | None] = mapped_column(String(190), nullable=True)

    # Role flagek a meghívottnak — ugyanaz a hat oszlop mint a user-en
    is_intake: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_designer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_workshop: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_quote_handler: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_orderer: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    used_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")


class Customer(Base):
    """Közös ügyféltábla — a Munkák modul tölti tartalommal, de a séma
    közös, mert a későbbi printbt.hu redesign is innen olvasna.

    Két ortogonális dimenzió:
    - `legal_type`: magánszemély vs cég (cégeknek `tax_number` kötelező a UI-on)
    - `customer_type`: vásárló vs viszonteladó (utóbbi kap kedvezményt)
    """

    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(190), index=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    legal_type: Mapped[LegalType] = mapped_column(
        String(20), nullable=False, default=LegalType.INDIVIDUAL
    )
    # Adószám (HU `12345678-1-23` formátum). Magánszemélynél NULL,
    # cégnél a form-szinten kötelező — DB-szinten nullable, hogy a
    # migráció ne törjön el meglévő rekordokat.
    tax_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    customer_type: Mapped[CustomerType] = mapped_column(
        String(20), nullable=False, default=CustomerType.RETAIL
    )
    discount_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Cím — minden mező opcionális, az ország kivételével. Magyar default,
    # struktúrált (nem szabad-szöveges), hogy a későbbi számlázás-integráció
    # tudjon belőle dolgozni.
    country: Mapped[str] = mapped_column(String(80), nullable=False, default="Magyarország")
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Utca + házszám egy sorban (pl. "Petőfi utca 12/B")
    address_line1: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Emelet, ajtó, egyéb (pl. "3. em. 12. ajtó" vagy "Hátsó épület")
    address_line2: Mapped[str | None] = mapped_column(String(200), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class AuditLog(Base):
    """Központi audit log — minden modul ide ír státusz-átléptetést és
    fontos változtatást. Az `entity_type` mező különbözteti meg, melyik
    modulé az adott rekord."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_type: Mapped[AuditEntityType] = mapped_column(String(20), nullable=False, index=True)
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class Notification(Base):
    """Toast-szintű értesítés egy adott usernek. A frontend percenként
    polling-olja és akkor pop-up-ol amikor új."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    link_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
